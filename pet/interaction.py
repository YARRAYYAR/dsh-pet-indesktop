# -*- coding: utf-8 -*-
"""纯鼠标空间判定，供桌宠窗口交互复用。"""

from __future__ import annotations

import math


def cursor_facing(
    center: tuple[float, float],
    cursor: tuple[float, float],
    radius: float,
    dead_zone: float = 16.0,
) -> str | None:
    """返回鼠标在角色窗口坐标中的朝向；中心死区或半径外不改变朝向。"""
    dx = cursor[0] - center[0]
    dy = cursor[1] - center[1]
    if math.hypot(dx, dy) > radius or abs(dx) < dead_zone:
        return None
    return "right" if dx > 0 else "left"
