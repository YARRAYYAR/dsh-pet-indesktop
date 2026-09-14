# -*- coding: utf-8 -*-
"""透明帧的像素处理与画布坐标；不依赖播放器、窗口状态或解码线程。"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QBitmap, QImage, QPainter, QRegion

TRANSPARENT_CROP_PADDING = 8
# bytes.translate 查表：仅 Alpha==1 映射为 255，其余为 0。
# 该表与 translate 都是 C 级实现，是这条链路能跑满 24fps 的关键。
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
    """清除 VP9 Alpha 常见的精确 1 阶底噪，不改变真实半透明边缘。

    实现取舍（已实测，勿改成逐像素 Python 循环）：
    这条链路必须在 24fps 下每帧跑完，因此每一步都必须是 C 级操作。
    曾尝试改为"按行扫描 Alpha 字节、原地把 Alpha==1 的像素写 0"，
    单帧从 0.388ms 退化到 51.3ms（慢 130 倍）——因为透明底噪分散在大量
    行里，逐行 Python 内循环横扫整幅图。当前实现依赖：
      · `bytes.translate`（C）生成"仅 Alpha=1 可见"的清除遮罩；
      · `QPainter.DestinationOut`（C）用该 Alpha8 遮罩整帧清零。
    两点等价性说明：
      - 预乘 ARGB32 中 Alpha=1 时各颜色分量必然 ≤1，所以 DestinationOut
        把整像素清零，与逐通道归零结果一致；
      - Alpha8 的 bytesPerLine 可能大于 width，因此沿用 Qt 分配的缓冲与
        步长做切片赋值，不能假设每行字节数等于像素宽度。
    只清除 Alpha==1；Alpha≥2 的真实抗锯齿边缘完全原样保留。
    """
    result = image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    if result.isNull():
        return result

    alpha = result.convertToFormat(QImage.Format.Format_Alpha8)
    alpha_bytes = bytes(alpha.constBits())
    if b'\x01' not in alpha_bytes:
        return result
    # 直接用 Alpha8 作 DestinationOut 遮罩，省掉独立 ARGB32 遮罩及其复制。
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
