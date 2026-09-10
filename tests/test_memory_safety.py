"""Pixel and lifecycle regressions for the memory-only optimization."""

import os
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from pet.frames import DecodedFrame, clear_alpha_floor
from pet.library import MovieLibrary


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize('width', [1, 2, 3, 4, 6, 462, 922, 1280])
def test_alpha_cleanup_handles_stride_without_changing_other_pixels(width):
    image = QImage(width, 256, QImage.Format.Format_RGBA8888)
    for alpha in range(256):
        for x in range(width):
            image.setPixelColor(x, alpha, QColor(73, 149, 231, alpha))
    before = bytes(image.constBits())
    expected = image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    actual = clear_alpha_floor(image)
    assert bytes(image.constBits()) == before
    for alpha in range(256):
        for x in range(width):
            assert actual.pixel(x, alpha) == (0 if alpha == 1 else expected.pixel(x, alpha))


def test_action_switch_releases_last_frame_and_preserves_preload(app, tmp_path):
    for name in ('a', 'b'):
        (tmp_path / f'{name}.webm').touch()
    library = MovieLibrary(asset_dir=tmp_path, cache_limit=2)
    try:
        first = library.activate('a')
        image = QImage(6, 4, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(QColor('red'))
        preload = DecodedFrame(image, 0, 0, 6, 4)
        first._first_frame = preload
        first._current_frame = DecodedFrame(image.copy(), 0, 0, 6, 4)
        first._queue.put(('frame', b'pending'))
        second = library.activate('b')
        assert first._current_frame is None
        assert first._first_frame is preload
        assert first._queue.empty()
        assert first._stop_evt.is_set()
        assert library.activate('a') is first
        assert first.jumpToFrame(0)
        assert first.currentFrame() is preload
        library.close()
        assert first._first_frame is None
        assert first._current_frame is None
        assert second._current_frame is None
    finally:
        library.close()


def test_gif_frame_can_be_rebuilt_after_inactive_release(app, tmp_path):
    image = QImage(4, 4, QImage.Format.Format_RGB32)
    image.fill(QColor('red'))
    from PIL import Image
    for name in ('a', 'b'):
        Image.new('RGB', (4, 4), 'red').save(tmp_path / f'{name}.gif')
    library = MovieLibrary(asset_dir=tmp_path)
    try:
        first = library.activate('a')
        expected = first.currentFrame().image.copy()
        library.activate('b')
        assert first._current_frame is None
        library.activate('a')
        assert first.currentFrame().image == expected
    finally:
        library.close()
