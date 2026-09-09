# -*- coding: utf-8 -*-
"""桌宠输入手势与空间反馈的纯函数。"""

from __future__ import annotations

import math


def classify_tap_burst(count: int) -> str:
    """把一次快速点击序列分成单击、双击或连续点击。"""
    if count <= 1:
        return "single"
    if count == 2:
        return "double"
    return "rapid"


def cursor_facing(
    center: tuple[float, float],
    cursor: tuple[float, float],
    radius: float,
    dead_zone: float = 16.0,
) -> str | None:
    """鼠标进入反应半径后返回朝向；在中心死区或半径外不改变朝向。"""
    dx = cursor[0] - center[0]
    dy = cursor[1] - center[1]
    if math.hypot(dx, dy) > radius or abs(dx) < dead_zone:
        return None
    return "right" if dx > 0 else "left"


def edge_contacts(
    rect: tuple[float, float, float, float],
    screen: tuple[float, float, float, float],
    margin: float,
) -> frozenset[str]:
    """返回窗口是否贴近屏幕四边；参数均为 x, y, width, height。"""
    x, y, width, height = rect
    sx, sy, sw, sh = screen
    contacts: set[str] = set()
    if x <= sx + margin:
        contacts.add("left")
    if y <= sy + margin:
        contacts.add("top")
    if x + width >= sx + sw - margin:
        contacts.add("right")
    if y + height >= sy + sh - margin:
        contacts.add("bottom")
    return frozenset(contacts)
