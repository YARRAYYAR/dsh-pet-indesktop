# -*- coding: utf-8 -*-
"""气泡布局和形状计算；绘制、命中测试和遮罩共享同一轮廓。"""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap

HEADER_HEIGHT = 330


def geometry(width: int, scale: float, x: int, y: int) -> QRectF:
    body_width = min(width - 28 * scale, 360 * scale)
    return QRectF((width - body_width) / 2 + (x - 35) * scale,
                  (112 + y) * scale, max(1.0, body_width), body_width * 0.63)


def body_path(rect: QRectF) -> QPainterPath:
    """参考轮廓：饱满椭圆，底部连着圆润的小凸泡。"""
    def point(x: float, y: float) -> QPointF:
        return QPointF(rect.left() + x * rect.width(),
                       rect.top() + y * rect.height())

    path = QPainterPath(point(0.5, 0.0))
    path.cubicTo(point(0.776, 0.0), point(1.0, 0.224), point(1.0, 0.52))
    path.cubicTo(point(1.0, 0.817), point(0.776, 1.0), point(0.5, 1.0))
    path.cubicTo(point(0.475, 1.0), point(0.456, 0.998), point(0.445, 0.997))
    path.cubicTo(point(0.430, 0.997), point(0.447, 1.040), point(0.390, 1.040))
    path.cubicTo(point(0.350, 1.040), point(0.312, 1.019), point(0.310, 0.975))
    path.cubicTo(point(0.307, 0.959), point(0.305, 0.960), point(0.287, 0.953))
    path.cubicTo(point(0.115, 0.893), point(0.0, 0.735), point(0.0, 0.52))
    path.cubicTo(point(0.0, 0.224), point(0.224, 0.0), point(0.5, 0.0))
    path.closeSubpath()
    return path


def tail_rects(rect: QRectF) -> tuple[QRectF, QRectF]:
    unit = rect.width()
    return (
        QRectF(rect.left() + unit * 0.33, rect.bottom() + unit * 0.060,
               unit * 0.098, unit * 0.062),
        QRectF(rect.left() + unit * 0.45, rect.bottom() + unit * 0.129,
               unit * 0.070, unit * 0.048),
    )


def scaled_rect(rect: QRectF, progress: float) -> QRectF:
    progress = max(0.0, min(1.0, progress))
    factor = 0.10 + 0.90 * (1 - (1 - progress) ** 3)
    w, h = rect.width() * factor, rect.height() * factor
    return QRectF(rect.center().x() - w / 2, rect.center().y() - h / 2, w, h)


def shape(rect: QRectF, progress: float) -> QPainterPath:
    path = QPainterPath()
    path.setFillRule(Qt.FillRule.WindingFill)
    if progress <= 0:
        return path
    phases = (min(1.0, progress / 0.28),
              min(1.0, max(0.0, (progress - 0.08) / 0.42)))
    for tail, phase in zip(tail_rects(rect), phases):
        if phase > 0:
            path.addEllipse(scaled_rect(tail, phase))
    main = max(0.0, min(1.0, (progress - 0.16) / 0.84))
    if main > 0:
        path.addPath(body_path(scaled_rect(rect, main)))
    return path


def stroke_width(rect: QRectF) -> float:
    return max(2.0, rect.width() * 0.024)


def _content_rect(rect: QRectF, progress: float) -> QRectF | None:
    """返回表情图在气泡主体内的内容区域。"""
    main = max(0.0, min(1.0, (progress - 0.16) / 0.84))
    if main <= 0.0:
        return None
    body = scaled_rect(rect, main)
    padding = max(8.0, body.width() * 0.085)
    content = body.adjusted(padding, padding, -padding, -padding)
    return content if content.width() > 2 and content.height() > 2 else None


def paint(painter: QPainter, rect: QRectF, progress: float,
          image: QPixmap | None = None) -> None:
    """绘制气泡；image 只在调用方已按需加载时显示。"""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    outline = QPen(QColor('#1e286c'), stroke_width(rect))
    painter.setBrush(QColor('#ffffff'))
    bubble_shape = shape(rect, progress)
    painter.setPen(outline)
    painter.drawPath(bubble_shape)
    content = _content_rect(rect, progress)
    if image is not None and content is not None and not image.isNull():
        body = scaled_rect(rect, max(0.0, min(1.0, (progress - 0.16) / 0.84)))
        painter.save()
        painter.setClipPath(body_path(body))
        source_ratio = image.width() / max(1, image.height())
        target_ratio = content.width() / max(1.0, content.height())
        if source_ratio >= target_ratio:
            draw_h = content.height()
            draw_w = draw_h * source_ratio
        else:
            draw_w = content.width()
            draw_h = draw_w / max(0.001, source_ratio)
        draw_rect = QRectF(
            content.center().x() - draw_w / 2,
            content.center().y() - draw_h / 2,
            draw_w,
            draw_h,
        )
        painter.drawPixmap(draw_rect, image)
        painter.restore()
        # 图片绘制后再描边，避免图片覆盖气泡轮廓。
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(outline)
        painter.drawPath(bubble_shape)
    painter.restore()
