# -*- coding: utf-8 -*-
"""帧呈现层：把解码帧变成最终画面与窗口命中区域。

职责边界
--------
- 输入：一个 `DecodedFrame`、朝向、窗口几何、显示器 DPR。
- 输出：Retina 就绪的 `QPixmap`、逻辑画布矩形、窗口 `QRegion` 命中遮罩。
- **不读取窗口状态**：所有几何与朝向都由调用方通过 `PresenterLayout` 传入，
  因此本模块可以脱离 `QWidget` 单独测试。

行为约束（与重构前逐字节一致）
------------------------------
- 裁边帧只在需要时补回画布（`frame_canvas_image`），整帧时直接复用。
- `facing == 'right'` 时水平镜像。
- 仅当解码尺寸与目标像素尺寸不同才做 `SmoothTransformation`，避免重复重采样。
- 命中遮罩取自当前帧 Alpha，并向外扩 2 个逻辑像素；它只决定鼠标命中范围，
  不参与画面合成，所以降低同步频率不会让可见边缘变粗。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QRect, QRectF, Qt
from PySide6.QtGui import QBitmap, QImage, QPainter, QPixmap, QRegion

from .frames import DecodedFrame, frame_canvas_image
from .window_effects import begin_rotation, end_rotation

# 遮罩向外扩张的偏移量：4 个边 + 4 个角，保证 Retina 半透明轮廓不被切掉。
MASK_PADDING_OFFSETS = (
    (-2, 0), (2, 0), (0, -2), (0, 2),
    (-1, -1), (-1, 1), (1, -1), (1, 1),
)


@dataclass(frozen=True)
class PresenterLayout:
    """一次呈现所需的窗口几何；由窗口在每次调用时构造。"""

    window_w: int
    window_h: int
    bubble_h: int
    scale: float
    dpr: float
    canvas_w: int
    canvas_h: int
    pad: int
    dpr_cap: float

    def pet_top(self) -> int:
        """人物画布在窗口内的上边距（气泡高度 + 落地偏移）。"""
        return self.bubble_h + int(round(self.pad * self.scale))

    def pixel_size(self) -> tuple[int, int]:
        """最终像素目标尺寸（逻辑画布 × 有效 DPR）。"""
        dpr = min(self.dpr_cap, max(1.0, float(self.dpr)))
        width = max(1, int(round(self.canvas_w * self.scale * dpr)))
        height = max(1, int(round(self.canvas_h * self.scale * dpr)))
        return width, height


class FramePresenter:
    """持有当前帧的呈现状态；无 QObject、无信号、无计时器。"""

    def __init__(self, *, canvas_w: int, canvas_h: int, pad: int,
                 dpr_cap: float) -> None:
        self._canvas_w = int(canvas_w)
        self._canvas_h = int(canvas_h)
        self._pad = int(pad)
        self._dpr_cap = float(dpr_cap)

        self.frame_pixmap: QPixmap | None = None
        self.logical_size: tuple[int, int] = (0, 0)
        self.logical_rect: tuple[int, int, int, int] = (0, 0, 0, 0)
        self.mask_region: QRegion | None = None
        self.mask_key: object | None = None
        self.mask_frame_counter = 0

    # ------------------------------------------------------------ 帧 → 画面
    def render(
        self,
        frame: DecodedFrame | None,
        *,
        facing: str,
        layout: PresenterLayout,
        force_mask: bool = False,
        mask_interval: int = 1,
    ) -> bool:
        """按当前帧重建画面；返回是否真的更新了画面。"""
        if frame is None or frame.image.isNull():
            return False

        image = self._canvas_image(frame)
        if facing == 'right':
            image = image.mirrored(True, False)

        logical_w = max(1, int(round(self._canvas_w * layout.scale)))
        logical_h = max(1, int(round(self._canvas_h * layout.scale)))
        pixel_w, pixel_h = layout.pixel_size()
        # 解码器通常已经按当前显示尺寸输出；同尺寸再做一次 SmoothTransformation
        # 只会产生一份重复拷贝，24fps 下会稳定占掉一段 CPU。
        if image.width() != pixel_w or image.height() != pixel_h:
            image = image.scaled(
                pixel_w, pixel_h,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )

        pixmap = QPixmap.fromImage(image)
        pixmap.setDevicePixelRatio(min(self._dpr_cap, max(1.0, float(layout.dpr))))
        self.frame_pixmap = pixmap
        # 显示始终还原到稳定画布，避免每帧透明边界变化带来尺寸/位置抖动。
        self.logical_size = (logical_w, logical_h)
        self.logical_rect = (0, 0, logical_w, logical_h)

        self.mask_frame_counter += 1
        if force_mask or self.mask_frame_counter >= max(1, int(mask_interval)):
            self.mask_frame_counter = 0
            return True
        return False

    def _canvas_image(self, frame: DecodedFrame) -> QImage:
        """整帧直接复用；裁边帧才补回画布。"""
        if (frame.x == 0 and frame.y == 0
                and frame.image.width() == frame.canvas_width
                and frame.image.height() == frame.canvas_height):
            return frame.image
        return frame_canvas_image(frame)

    def reset_mask_counter(self) -> None:
        self.mask_frame_counter = 0

    def invalidate(self) -> None:
        """尺寸/朝向变化后强制下一次遮罩重建。"""
        self.mask_key = None

    # ------------------------------------------------------------ 命中遮罩
    def pet_region(self, layout: PresenterLayout, *, rotation_deg: float = 0.0) -> QRegion:
        """当前帧的 Alpha 命中区域（已按需缓存，未做 2px 外扩）。"""
        key = (
            self.frame_pixmap.cacheKey() if self.frame_pixmap is not None else None,
            layout.window_w, layout.window_h, layout.bubble_h,
            layout.scale, self.logical_rect, round(float(rotation_deg), 4),
        )
        if key == self.mask_key and self.mask_region is not None:
            return self.mask_region

        canvas = QImage(layout.window_w, layout.window_h, QImage.Format.Format_ARGB32)
        canvas.fill(Qt.GlobalColor.transparent)
        painter = QPainter(canvas)
        painter.translate(0, layout.pet_top())
        if self.frame_pixmap is not None:
            x, y, _, _ = self.logical_rect
            pivot = QRect(x, y, self.logical_size[0], self.logical_size[1])
            begin_rotation(painter, pivot, rotation_deg)
            painter.drawPixmap(x, y, self.frame_pixmap)
            end_rotation(painter, rotation_deg)
        painter.end()
        self.mask_region = QRegion(QBitmap.fromImage(canvas.createAlphaMask()))
        self.mask_key = key
        return self.mask_region

    @staticmethod
    def padded_region(region: QRegion) -> QRegion:
        """向外扩 2 个逻辑像素，避免切掉 Retina 半透明轮廓。"""
        padded = region
        for dx, dy in MASK_PADDING_OFFSETS:
            padded = padded.united(region.translated(dx, dy))
        return padded

    def compose_region(
        self,
        layout: PresenterLayout,
        *,
        bubble_region: QRegion | None = None,
        rotation_deg: float = 0.0,
    ) -> QRegion:
        """最终窗口遮罩 = （人物命中区域 ∪ 气泡命中区域）再整体外扩 2px。

        外扩必须作用在并集之后：先并集再膨胀与逐块膨胀虽然点集相同，但
        QRegion 的矩形分解可能不同，会破坏既有的矩形级等价校验。
        """
        region = self.pet_region(layout, rotation_deg=rotation_deg)
        if bubble_region is not None and not bubble_region.isEmpty():
            region = region.united(bubble_region)
        return self.padded_region(region)

    # ------------------------------------------------------------ 绘制
    def paint(
        self,
        painter: QPainter,
        *,
        layout: PresenterLayout,
        squash_progress: float | None = None,
        rotation_deg: float = 0.0,
    ) -> None:
        """把当前帧画到窗口坐标；squash_progress 非空时应用点击 Q 弹形变。"""
        if self.frame_pixmap is None:
            return
        painter.save()
        if squash_progress is None:
            painter.translate(0, layout.pet_top())
            x, y, _, _ = self.logical_rect
            pivot = QRect(x, y, self.logical_size[0], self.logical_size[1])
            begin_rotation(painter, pivot, rotation_deg)
            painter.drawPixmap(x, y, self.frame_pixmap)
            end_rotation(painter, rotation_deg)
        else:
            # Q 弹：垂直变矮 + 水平微微变宽，脚底保持不动
            phase = math.sin(math.pi * squash_progress)
            scale_y = 1.0 - 0.15 * phase
            scale_x = 1.0 + 0.10 * phase
            canvas_w, canvas_h = self.logical_size
            crop_x, crop_y, crop_w, crop_h = self.logical_rect
            base_x = (layout.window_w - canvas_w * scale_x) / 2.0
            base_y = layout.pet_top() + canvas_h - canvas_h * scale_y
            draw_rect = QRect(
                int(round(base_x + crop_x * scale_x)),
                int(round(base_y + crop_y * scale_y)),
                max(1, int(round(crop_w * scale_x))),
                max(1, int(round(crop_h * scale_y))),
            )
            begin_rotation(painter, draw_rect, rotation_deg)
            painter.drawPixmap(draw_rect, self.frame_pixmap)
            end_rotation(painter, rotation_deg)
        painter.restore()

    # ------------------------------------------------------------ 图标
    def icon_image(
        self,
        *,
        fallback_frame_provider: Callable[[], DecodedFrame | None] | None = None,
    ) -> QImage:
        """托盘/设置页图标源图：优先当前帧，退化到待机首帧。"""
        if self.frame_pixmap is not None:
            canvas_w, canvas_h = self.logical_size
            image = QImage(canvas_w, canvas_h, QImage.Format.Format_ARGB32)
            image.fill(Qt.GlobalColor.transparent)
            painter = QPainter(image)
            x, y, _, _ = self.logical_rect
            painter.drawPixmap(x, y, self.frame_pixmap)
            painter.end()
            return image

        frame = fallback_frame_provider() if fallback_frame_provider else None
        if frame is None or frame.image.isNull():
            return QImage()
        image = QImage(frame.canvas_width, frame.canvas_height,
                       QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.drawImage(frame.x, frame.y, frame.image)
        painter.end()
        return image

    @staticmethod
    def scaled_icon(image: QImage, size: int) -> QPixmap:
        if image.isNull():
            return QPixmap()
        return QPixmap.fromImage(image.scaled(
            size, size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        ))
