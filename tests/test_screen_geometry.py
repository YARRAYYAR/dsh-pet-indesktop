# -*- coding: utf-8 -*-
"""多屏联合工作区的纯几何测试。"""

from PySide6.QtCore import QRect

from pet.screen_geometry import union_available_geometry


class _Screen:
    def __init__(self, rect: QRect) -> None:
        self._rect = rect

    def availableGeometry(self) -> QRect:
        return QRect(self._rect)


def test_union_keeps_negative_coordinates_and_different_screen_sizes():
    workspace = union_available_geometry([
        _Screen(QRect(0, 0, 1920, 1080)),
        _Screen(QRect(-1440, 120, 1440, 900)),
    ])
    assert workspace == QRect(-1440, 0, 3360, 1080)


def test_union_ignores_invalid_screen_rectangles():
    workspace = union_available_geometry([
        _Screen(QRect()),
        _Screen(QRect(10, 20, 300, 200)),
    ])
    assert workspace == QRect(10, 20, 300, 200)


def test_union_without_screens_is_none():
    assert union_available_geometry([]) is None
