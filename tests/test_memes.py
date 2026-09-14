# -*- coding: utf-8 -*-
"""v0.2.9 表情包资源与按需解码测试。"""

import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication

from pet import memes


def test_official_meme_manifest_matches_27_png_assets():
    names = memes.available_names()
    assert len(names) == 27
    assert all((memes.memes_dir() / f'{name}.png').is_file() for name in names)


def test_random_meme_loads_only_the_requested_pixmap():
    app = QApplication.instance() or QApplication([])
    name, pixmap = memes.random_pixmap(rng=__import__('random').Random(7))
    assert name in memes.available_names()
    assert pixmap is not None and not pixmap.isNull()
    assert pixmap.width() == 384
    assert 1 <= pixmap.height() <= 384
    app.processEvents()
