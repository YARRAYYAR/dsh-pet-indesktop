"""Preserve image ownership; inject only the OS thread-creation failure.

Native AppShell flows cover successful decoding and window caches. Exhausting
the machine's thread allowance is unsafe, so that boundary is isolated here:
cached prediction must not need a thread; cold prediction failures must log
and remain retryable. Real QImages check sharing without removing draw copies.
"""
import logging
from pathlib import Path

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication


def test_shared_first_frame_keeps_private_display_and_survives_owner_close(tmp_path):
    from pet.webm_clip import WebMClip

    app = QApplication.instance() or QApplication([])
    path = tmp_path / 'sample.webm'
    path.write_bytes(b'asset identity only; decoded pixels arrive from reader')
    data = bytes(range(16))
    clips = [WebMClip(path) for _ in range(3)]
    try:
        for clip in clips[:2]:
            clip._w, clip._h = 2, 2
            clip._process_frame((data, 0))
        cached_key = clips[1]._first_image.cacheKey()
        assert clips[0]._first_image.cacheKey() == cached_key
        clips[0].currentImage().fill(0xFF00FF00)
        assert bytes(clips[1]._first_image.constBits()) == data
        assert bytes(clips[1].currentImage().constBits()) == data
        clips[0].cleanup()
        clips[2]._w, clips[2]._h = 2, 2
        clips[2]._process_frame((data, 0))
        assert clips[2]._first_image.cacheKey() == cached_key
        clips[1].currentImage().fill(0xFF0000FF)
        assert bytes(clips[2]._first_image.constBits()) == data
        assert bytes(clips[2].currentImage().constBits()) == data
    finally:
        for clip in clips:
            clip.cleanup()
        app.processEvents()


def test_cached_prediction_is_usable_when_os_cannot_create_threads(tmp_path, monkeypatch, caplog):
    from pet import library

    app = QApplication.instance() or QApplication([])
    path = tmp_path / 'sample.webm'
    path.write_bytes(b'asset')
    lib = library.MovieLibrary(asset_dir=tmp_path)
    clip = lib.movie('sample')
    clip._w, clip._h = 2, 2
    clip._process_frame((bytes(range(16)), 0))

    def unavailable_thread(*args, **kwargs):
        raise RuntimeError('OS thread creation unavailable')

    monkeypatch.setattr(library.threading, 'Thread', unavailable_thread)
    try:
        with caplog.at_level(logging.ERROR):
            lib.warm_predicted('sample')
        assert not caplog.records, 'An already usable first frame must not require a new thread'
        assert bytes(clip._first_image.constBits()) == bytes(range(16))
    finally:
        lib.shutdown()
        app.processEvents()
