# -*- coding: utf-8 -*-
"""所有显示器工作区的轻量几何工具。"""

from __future__ import annotations

from typing import Iterable

from PySide6.QtCore import QPoint, QRect


def union_available_geometry(screens: Iterable[object]) -> QRect | None:
    """返回所有屏幕 availableGeometry 的联合区域，保留负坐标和跨屏布局。"""
    result: QRect | None = None
    for screen in screens:
        geometry = getattr(screen, 'availableGeometry', None)
        rect = geometry() if callable(geometry) else None
        if rect is None or not rect.isValid():
            continue
        result = QRect(rect) if result is None else result.united(rect)
    return result


def screen_containing_point(screens: Iterable[object], point: QPoint):
    """返回包含点的屏幕；点在屏幕间隙时返回 None。"""
    for screen in screens:
        geometry = getattr(screen, 'availableGeometry', None)
        rect = geometry() if callable(geometry) else None
        if rect is not None and rect.contains(point):
            return screen
    return None
