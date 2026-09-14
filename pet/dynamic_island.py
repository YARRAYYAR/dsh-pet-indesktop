# -*- coding: utf-8 -*-
"""轻量级灵动岛胶囊窗口。

这个模块只负责一个透明 Qt 小窗和一个低频时钟：不创建线程、不解码视频，
也不复制桌宠帧。桌宠隐藏后胶囊仍可见，单击胶囊可以恢复桌宠。
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QApplication, QWidget

from . import catalog


_CAPSULE_HEIGHT = 44
_EDGE_MARGIN = 16
_SNAP_TOP_THRESHOLD = 24


def _cfg_dict(config) -> dict:
    value = config.get('dynamic_island', {})
    return dict(value) if isinstance(value, dict) else {}


class DynamicIsland(QWidget):
    """可拖动、可吸附顶部的独立灵动岛胶囊。"""

    clicked = Signal()

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self._cfg = _cfg_dict(config)
        self.setObjectName('dynamic-island')
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        if hasattr(Qt.WidgetAttribute, 'WA_MacAlwaysShowToolWindow'):
            self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow, True)

        self._drag_offset: QPoint | None = None
        self._press_global: QPoint | None = None
        self._dragging = False
        self._pet_visible = True

        # 胶囊只显示时间/短文本，30 秒刷新一次，避免常驻高频任务。
        self._info_timer = QTimer(self)
        self._info_timer.setInterval(30_000)
        self._info_timer.timeout.connect(self._refresh)
        self._info_timer.start()
        self._apply_position()

    def set_pet_visible(self, visible: bool) -> None:
        self._pet_visible = bool(visible)
        self.update()

    def refresh_from_config(self) -> None:
        self._cfg = _cfg_dict(self.config)
        self._refresh()

    def _refresh(self) -> None:
        self._update_size()
        self._clamp_to_screen()
        self.update()

    def _visible_parts(self) -> tuple[bool, bool, bool, bool]:
        icon = bool(self._cfg.get('show_icon', True))
        name = bool(self._cfg.get('show_name', True))
        info = bool(self._cfg.get('show_info', True))
        status = bool(self._cfg.get('show_status', True))
        if not (icon or name or info or status):
            info = True
        return icon, name, info, status

    def _info_text(self) -> str:
        if str(self._cfg.get('info_mode') or 'time') == 'custom':
            return str(self._cfg.get('custom_text') or '').strip()[:80] or '准备中'
        from PySide6.QtCore import QTime

        return QTime.currentTime().toString('HH:mm')

    def _character_name(self) -> str:
        return str(self.config.get('character', catalog.DEFAULT_CHARACTER))

    def _icon_text(self) -> str:
        return str(self._cfg.get('icon') or '🐳').strip()[:8] or '🐳'

    def _update_size(self) -> None:
        icon, name, info, status = self._visible_parts()
        fm = self.fontMetrics()
        width = 32
        if icon:
            width += 26 + 8
        if name:
            width += fm.horizontalAdvance(self._character_name()) + 8
        if info:
            width += fm.horizontalAdvance(self._info_text()) + 8
        if status:
            width += 10
        self.setFixedSize(max(120, width), _CAPSULE_HEIGHT)

    def _apply_position(self) -> None:
        self._update_size()
        screen = QGuiApplication.primaryScreen()
        available = screen.availableGeometry() if screen is not None else None
        x = self._cfg.get('x')
        y = self._cfg.get('y')
        if isinstance(x, (int, float)) and isinstance(y, (int, float)):
            pos = QPoint(int(x), int(y))
        elif available is not None:
            pos = QPoint(
                available.right() - self.width() - _EDGE_MARGIN,
                available.top() + _EDGE_MARGIN,
            )
        else:
            pos = QPoint(100, 100)
        self.move(pos)
        self._clamp_to_screen()

    def _clamp_to_screen(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        x = max(available.left(), min(self.x(), available.right() - self.width() + 1))
        y = max(available.top(), min(self.y(), available.bottom() - self.height() + 1))
        if (x, y) != (self.x(), self.y()):
            self.move(x, y)

    def _save_position(self) -> None:
        island = dict(self._cfg)
        island.update(x=self.x(), y=self.y())
        self._cfg = island
        self.config.set('dynamic_island', island)
        self.config.save()

    def _style_palette(self):
        style = str(self._cfg.get('style') or 'dark')
        if style == 'light':
            return QColor(255, 255, 255, 242), QColor(31, 35, 40), QColor(107, 114, 128)
        if style == 'glass':
            gradient = QLinearGradient(0, 0, 0, self.height())
            gradient.setColorAt(0.0, QColor(255, 255, 255, 196))
            gradient.setColorAt(0.5, QColor(230, 242, 255, 150))
            gradient.setColorAt(1.0, QColor(255, 255, 255, 210))
            return gradient, QColor(35, 45, 60), QColor(90, 105, 125)
        return QColor(28, 30, 38, 235), QColor(235, 238, 245), QColor(160, 170, 190)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(0, 0, self.width(), self.height())
        radius = rect.height() / 2.0

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 46))
        painter.drawRoundedRect(rect.translated(0, 2), radius, radius)

        background, primary, secondary = self._style_palette()
        painter.setBrush(background)
        painter.drawRoundedRect(rect, radius, radius)
        if str(self._cfg.get('style') or 'dark') == 'glass':
            painter.setPen(QPen(QColor(255, 255, 255, 130), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), radius - 0.5, radius - 0.5)

        icon, name, info, status = self._visible_parts()
        x = 16.0
        painter.setPen(Qt.PenStyle.NoPen)
        if icon:
            painter.setBrush(QColor(64, 184, 255, 255))
            painter.drawEllipse(QRectF(x, (self.height() - 26) / 2, 26, 26))
            painter.setPen(QColor(255, 255, 255))
            fm = self.fontMetrics()
            painter.drawText(
                QRectF(x, (self.height() - fm.height()) / 2 - 1, 26, fm.height()),
                Qt.AlignmentFlag.AlignCenter,
                self._icon_text(),
            )
            painter.setPen(Qt.PenStyle.NoPen)
            x += 34

        fm = self.fontMetrics()
        if name:
            text = self._character_name()
            painter.setPen(primary)
            painter.drawText(
                QRectF(x, 0, fm.horizontalAdvance(text), self.height()),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                text,
            )
            x += fm.horizontalAdvance(text) + 8

        if info:
            text = self._info_text()
            painter.setPen(secondary)
            painter.drawText(
                QRectF(x, 0, fm.horizontalAdvance(text), self.height()),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                text,
            )
            x += fm.horizontalAdvance(text) + 8

        if status:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(80, 220, 120) if self._pet_visible else QColor(130, 140, 155))
            painter.drawEllipse(QRectF(x, (self.height() - 10) / 2, 10, 10))
        painter.end()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_global = event.globalPosition().toPoint()
            self._drag_offset = self._press_global - self.pos()
            self._dragging = False
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._press_global is None or not event.buttons() & Qt.MouseButton.LeftButton:
            return
        global_pos = event.globalPosition().toPoint()
        if not self._dragging and (
            global_pos - self._press_global
        ).manhattanLength() >= QApplication.startDragDistance():
            self._dragging = True
        if self._dragging and self._drag_offset is not None:
            self.move(global_pos - self._drag_offset)
            self._clamp_to_screen()
            event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if not self._dragging:
            self.clicked.emit()
        else:
            self._clamp_to_screen()
            screen = QGuiApplication.primaryScreen()
            if screen is not None and self.y() <= screen.availableGeometry().top() + _SNAP_TOP_THRESHOLD:
                self.move(self.x(), screen.availableGeometry().top())
            self._save_position()
        self._press_global = None
        self._drag_offset = None
        self._dragging = False
        event.accept()
