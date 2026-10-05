# -*- coding: utf-8 -*-
"""纯鼠标空间判定，供桌宠窗口交互复用。"""

from __future__ import annotations

import math


def cursor_facing(
    center: tuple[float, float],
    cursor: tuple[float, float],
    radius: float,
    dead_zone: float = 16.0,
    *,
    rotation_deg: float = 0.0,
) -> str | None:
    """按屏幕水平差判朝向；倒转时补偿绘制镜像，死区或半径外保持。"""
    dx = cursor[0] - center[0]
    dy = cursor[1] - center[1]
    if math.hypot(dx, dy) > radius or abs(dx) < dead_zone:
        return None
    if math.cos(math.radians(rotation_deg)) < 0:
        dx = -dx
    return "right" if dx > 0 else "left"
