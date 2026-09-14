# -*- coding: utf-8 -*-
"""轻量绘制变换工具，供边缘探头的画面与命中遮罩共用。"""

from __future__ import annotations

import math

from PySide6.QtCore import QEasingCurve, QPointF, QRect, QRectF


def begin_rotation(painter, rect: QRect, angle_deg: float) -> None:
    """围绕 rect 中心旋转 painter；调用方必须配对 end_rotation。"""
    if abs(float(angle_deg)) < 1e-6:
        return
    center = QPointF(rect.center())
    painter.save()
    painter.translate(center)
    painter.rotate(float(angle_deg))
    painter.translate(-center)


def end_rotation(painter, angle_deg: float) -> None:
    if abs(float(angle_deg)) >= 1e-6:
        painter.restore()


def rotated_region_bounds(region: QRect, pivot_rect: QRect, angle_deg: float) -> QRect:
    """返回 region 绕 pivot_rect 中心旋转后的轴对齐外接矩形。"""
    angle = float(angle_deg)
    if abs(angle) < 1e-6:
        return QRect(region)
    center = QPointF(pivot_rect.center())
    rad = math.radians(angle)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    corners = (
        QPointF(region.left(), region.top()),
        QPointF(region.left() + region.width(), region.top()),
        QPointF(region.left(), region.top() + region.height()),
        QPointF(region.left() + region.width(), region.top() + region.height()),
    )
    points = []
    for point in corners:
        dx, dy = point.x() - center.x(), point.y() - center.y()
        points.append(QPointF(
            center.x() + dx * cos_a - dy * sin_a,
            center.y() + dx * sin_a + dy * cos_a,
        ))
    min_x = min(point.x() for point in points)
    min_y = min(point.y() for point in points)
    max_x = max(point.x() for point in points)
    max_y = max(point.y() for point in points)
    return QRectF(min_x, min_y, max_x - min_x, max_y - min_y).toAlignedRect()


def eased_progress(elapsed_ms: float, duration_ms: int) -> float:
    """将过渡时间压到 [0, 1]，使用 Qt OutCubic 缓动。"""
    if duration_ms <= 0:
        return 1.0
    raw = max(0.0, min(1.0, float(elapsed_ms) / float(duration_ms)))
    return QEasingCurve(QEasingCurve.Type.OutCubic).valueForProgress(raw)
