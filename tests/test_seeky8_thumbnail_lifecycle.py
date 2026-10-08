"""Decoder/owner failures cannot be induced deterministically in native E2E."""
from types import SimpleNamespace
import threading

import pytest
from PySide6.QtGui import QImage

from pet import animation_thumbnail as thumbnail


class _Reader:
    def __init__(self, meta, frames, *, fail_at=None, close_error=False):
        self._items = iter([meta, *frames])
        self._frames = frames
        self._index = 0
        self._fail_at = fail_at
        self._close_error = close_error
        self.closed = False

    def __iter__(self):
        return self

    def __next__(self):
        index = self._index
        self._index += 1
        if index == self._fail_at:
            raise OSError("decoder failed")
        return next(self._items)

    def close(self):
        self.closed = True
        for frame in self._frames:
            frame[:] = bytes(len(frame))
        if self._close_error:
            raise OSError("decoder close failed")


def _install_reader(monkeypatch, reader):
    monkeypatch.setattr(
        thumbnail, "imageio_ffmpeg",
        SimpleNamespace(read_frames=lambda *args, **kwargs: reader),
    )


@pytest.mark.parametrize("size", [(640, 390), (64, 32)])
@pytest.mark.parametrize("close_error", [False, True])
def test_representative_thumbnail_owns_pixels_after_reader_close(
    monkeypatch, tmp_path, size, close_error,
):
    width, height = size
    intro = bytearray(bytes((10, 20, 30, 40)) * (width * height))
    rgba = bytearray()
    for index in range(width * height):
        rgba.extend((index % 256, 37, 181, (index * 7) % 256))
    expected = thumbnail._as_thumbnail(
        QImage(rgba, width, height, width * 4, QImage.Format.Format_RGBA8888).copy(),
    )
    expected_bytes = bytes(expected.constBits())
    reader = _Reader(
        {"fps": 3, "duration": 1, "size": size},
        [intro, rgba], close_error=close_error,
    )
    _install_reader(monkeypatch, reader)

    image = thumbnail._decode_webm(tmp_path / "clip.webm")

    assert reader.closed
    assert not any(rgba)
    assert not image.isNull()
    assert image.size() == expected.size()
    assert bytes(image.constBits()) == expected_bytes
    assert image.hasAlphaChannel()


@pytest.mark.parametrize("frame", [bytearray(15), bytearray(17)])
def test_malformed_frame_is_empty_and_reader_is_closed(monkeypatch, tmp_path, frame):
    reader = _Reader({"fps": 1, "duration": 1, "size": (2, 2)}, [frame])
    _install_reader(monkeypatch, reader)

    assert thumbnail._decode_webm(tmp_path / "bad.webm").isNull()
    assert reader.closed


@pytest.mark.parametrize("fail_at", [0, 1])
def test_decoder_exception_is_empty_and_reader_is_closed(monkeypatch, tmp_path, fail_at):
    reader = _Reader(
        {"fps": 1, "duration": 1, "size": (2, 2)},
        [bytearray(16)], fail_at=fail_at,
    )
    _install_reader(monkeypatch, reader)

    assert thumbnail._decode_webm(tmp_path / "bad.webm").isNull()
    assert reader.closed


@pytest.mark.parametrize("failure", ["decode", "cache"])
def test_owner_failure_releases_waiter_and_allows_retry(monkeypatch, tmp_path, failure):
    monkeypatch.setattr(thumbnail, "_DISK_CACHE_DIR", tmp_path / "thumbs")
    thumbnail._image_cache.clear()
    thumbnail._inflight.clear()
    path = tmp_path / "clip.webm"
    path.write_bytes(b"clip")
    owner_entered = threading.Event()
    release_owner = threading.Event()
    waiter_entered = threading.Event()
    owner_errors = []
    waiter_images = []
    image = QImage(4, 4, QImage.Format.Format_RGBA8888)
    image.fill(0x7F112233)

    class ObservedEvent(threading.Event):
        def wait(self, timeout=None):
            waiter_entered.set()
            return super().wait(timeout)

    monkeypatch.setattr(
        thumbnail, "threading",
        SimpleNamespace(Event=ObservedEvent, get_ident=threading.get_ident),
    )

    def decode(_path):
        owner_entered.set()
        if not release_owner.wait(10):
            raise TimeoutError("test did not release owner")
        if failure == "decode":
            raise OSError("owner decoder failed")
        return image

    original_put = thumbnail._image_cache.put

    def fail_put(*args, **kwargs):
        raise RuntimeError("cache insertion failed")

    monkeypatch.setattr(thumbnail, "_decode_representative_frame", decode)
    if failure == "cache":
        monkeypatch.setattr(thumbnail._image_cache, "put", fail_put)

    def own():
        try:
            thumbnail.decode_representative_frame(path)
        except Exception as error:
            owner_errors.append(error)

    owner = threading.Thread(target=own, daemon=True)
    waiter = threading.Thread(
        target=lambda: waiter_images.append(thumbnail.decode_representative_frame(path)),
        daemon=True,
    )
    try:
        owner.start()
        assert owner_entered.wait(10)
        waiter.start()
        assert waiter_entered.wait(10)
    finally:
        release_owner.set()
        owner.join(10)
        if waiter.ident is not None:
            waiter.join(10)

    assert not owner.is_alive()
    assert not waiter.is_alive()
    assert len(owner_errors) == 1
    assert isinstance(owner_errors[0], OSError if failure == "decode" else RuntimeError)
    assert len(waiter_images) == 1
    assert waiter_images[0].isNull()
    assert not thumbnail._inflight
    assert not list(thumbnail._image_cache)

    monkeypatch.setattr(thumbnail._image_cache, "put", original_put)
    monkeypatch.setattr(thumbnail, "_decode_representative_frame", lambda _path: image)
    retry = thumbnail.decode_representative_frame(path)
    assert bytes(retry.constBits()) == bytes(image.constBits())
    assert not thumbnail._inflight
