# -*- coding: utf-8 -*-
"""透明帧的像素处理与画布坐标；不依赖播放器、窗口状态或解码线程。"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QBitmap, QImage, QPainter, QRegion

TRANSPARENT_CROP_PADDING = 8
ALPHA_FLOOR_MASK = bytes(255 if value == 1 else 0 for value in range(256))


@dataclass(frozen=True, slots=True)
class DecodedFrame:
    """裁掉透明边缘后的图像，以及它在原解码画布中的位置。"""

    image: QImage
    x: int
    y: int
    canvas_width: int
    canvas_height: int

    @property
    def offset(self) -> tuple[int, int]:
        return self.x, self.y

    @property
    def canvas_size(self) -> tuple[int, int]:
        return self.canvas_width, self.canvas_height


def clear_alpha_floor(image: QImage) -> QImage:
    """清除 VP9 Alpha 常见的精确 1 阶底噪，不改变真实半透明边缘。"""
    result = image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    if result.isNull():
        return result

    # 用 C 实现的 bytes.translate 生成“仅 Alpha=1 可见”的清除遮罩，
    # 再用 DestinationOut 清掉这些像素。这样 Alpha=2 及以上（真实抗锯齿
    # 边缘）完全原样保留，且会同步清掉透明像素里残留的 RGB。
    alpha = result.convertToFormat(QImage.Format.Format_Alpha8)
    alpha_bytes = bytes(alpha.constBits())
    if b'\x01' not in alpha_bytes:
        return result
    # Alpha8 的 bytesPerLine 可能大于 width；沿用 Qt 分配的缓冲与步长。
    # 直接用 Alpha8 作 DestinationOut 遮罩，省去整帧 ARGB32 遮罩及其复制。
    alpha.bits()[:] = alpha_bytes.translate(ALPHA_FLOOR_MASK)
    painter = QPainter(result)
    painter.setCompositionMode(
        QPainter.CompositionMode.CompositionMode_DestinationOut
    )
    painter.drawImage(0, 0, alpha)
    painter.end()
    return result


def trim_transparent_frame(
    image: QImage,
    *,
    padding: int = TRANSPARENT_CROP_PADDING,
    soften_edges: bool = False,
) -> DecodedFrame:
    """裁掉透明压缩噪声，并保留安全边与原画布坐标。"""
    canvas_width, canvas_height = image.width(), image.height()
    if image.isNull():
        return DecodedFrame(QImage(), 0, 0, canvas_width, canvas_height)

    # Alpha=1 必须在计算边界前清掉；否则它虽然不会进入最终画面，仍会把
    # 每一帧的裁剪范围撑大，造成动画边缘/尺寸在播放时抖动。
    working = clear_alpha_floor(image) if soften_edges else image
    bounds = QRegion(QBitmap.fromImage(working.createAlphaMask())).boundingRect()
    if bounds.isEmpty():
        transparent = QImage(
            1,
            1,
            QImage.Format.Format_ARGB32_Premultiplied,
        )
        transparent.fill(0)
        return DecodedFrame(transparent, 0, 0, canvas_width, canvas_height)

    padding = max(0, int(padding))
    if padding:
        bounds = bounds.adjusted(-padding, -padding, padding, padding).intersected(
            image.rect()
        )

    cropped = working.copy(bounds).convertToFormat(
        QImage.Format.Format_ARGB32_Premultiplied
    )

    return DecodedFrame(
        cropped,
        bounds.x(),
        bounds.y(),
        canvas_width,
        canvas_height,
    )


def frame_canvas_image(frame: DecodedFrame) -> QImage:
    """兼容接口需要完整画布时才还原；动画热路径不调用。"""
    if frame.canvas_width <= 0 or frame.canvas_height <= 0:
        return QImage()
    canvas = QImage(
        frame.canvas_width,
        frame.canvas_height,
        QImage.Format.Format_ARGB32,
    )
    canvas.fill(0)
    painter = QPainter(canvas)
    painter.drawImage(frame.x, frame.y, frame.image)
    painter.end()
    return canvas
