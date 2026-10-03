"""Codex presentation using the existing alert window, placement and lifecycle."""
import logging
import weakref

from PySide6.QtCore import QRect, QRectF, Qt
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen

from .speech_bubble import PetSpeechBubble
from .task_bubble_style import clean_task_appearance, task_foreground


def create_speech_bubble(window, config):
    owner = weakref.ref(window)

    def appearance():
        host = owner()
        if host is not None and (host._alert_current or {}).get('id') == 'dsr-codex':
            return host.cfg.get('codex_task_appearance')
        return None

    return TaskSpeechBubble(style_id=str(config.get('self_talk_bubble_style', 'classic_top')),
                            appearance_provider=appearance)


class TaskSpeechBubble(PetSpeechBubble):
    def __init__(self, *args, appearance_provider, embedded=False, **kwargs):
        self._task_active = False
        self._appearance_provider = appearance_provider
        self._task_content = None
        self._embedded = embedded
        super().__init__(*args, **kwargs)
        self._regular_spacing = self._layout.spacing()
        if embedded:
            self.setWindowFlags(Qt.WindowType.Widget)

    def _available_geometry(self, anchor_rect):
        if self._embedded:
            return QRect(0, 0, self.parentWidget().width() - 12, 10000)
        return super()._available_geometry(anchor_rect)

    def _place(self, anchor_rect, *, animate=True):
        if self._embedded:
            self._anchor_rect = QRect(anchor_rect)
            self.move(10, 10)
            return
        return super()._place(anchor_rect, animate=animate)

    def show_text(self, text, anchor_rect, duration_ms=3200, **kwargs):
        # Ordinary self-talk cannot replace an outstanding interactive question.
        if self._interactive_active and not kwargs.get('buttons') and not self._embedded:
            return
        appearance = self._appearance_provider()
        if appearance is None:
            if self._task_active:
                self._task_active = False
                self._task_content = None
                self.setMinimumSize(0, 0)
                self.setMaximumSize(16777215, 16777215)
                self._subtitle_label.setMaximumWidth(248)
                self.label.setWordWrap(False)
                self.label.setTextFormat(Qt.TextFormat.AutoText)
                self._layout.setSpacing(self._regular_spacing)
                self.set_style(self._style_id)
            return super().show_text(text, anchor_rect, duration_ms, **kwargs)
        self._task_active = True
        self._task_content = (str(text), dict(kwargs))
        self._raw_text = str(text)
        self._content_kind = 'task'
        self._pet_scale = kwargs.get('pet_scale')
        self._reset_paging()
        appearance = clean_task_appearance(appearance)
        scale = appearance['scale'] / 100
        foreground = task_foreground(appearance['background'])
        self._preset = dict(self._preset, background=appearance['background'],
                            border=appearance['accent'], foreground=foreground,
                            shape='rounded', radius=12, placement='top')
        pad = round(16 * scale)
        self._layout.setContentsMargins(pad, pad, pad, pad)
        self._layout.setSpacing(round(10 * scale))
        available = self._available_geometry(anchor_rect)
        width = round(320 * scale)
        if available is not None:
            width = min(width, available.width() - 8)
        self.setFixedWidth(width)
        self.setMinimumHeight(0)
        self.setMaximumHeight(16777215)
        column = max(1, width - pad * 2)
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.label.setWordWrap(True)
        self.label.setStyleSheet(f'background:transparent; border:none; padding:0; color:{foreground}; font-size:{round(13 * scale)}px;')
        self.label.ensurePolished()
        self.label.setText(str(text))
        metrics = QFontMetrics(self.label.font())
        height = metrics.boundingRect(QRect(0, 0, column, 100000), Qt.TextFlag.TextWordWrap, str(text)).height() + 6
        self.label.setFixedSize(column, height)
        self.label.show()
        subtitle = str(kwargs.get('subtitle', ''))
        self._subtitle_label.setTextFormat(Qt.TextFormat.PlainText)
        self._subtitle_label.setText(subtitle)
        self._subtitle_label.setStyleSheet(f'background:transparent; border:none; padding:0; color:{foreground}; font-size:{round(11 * scale)}px; font-weight:600;')
        self._subtitle_label.setMaximumWidth(column)
        self._subtitle_label.setVisible(bool(subtitle))
        self._layout.removeWidget(self._subtitle_label)
        self._layout.insertWidget(0, self._subtitle_label)
        buttons = kwargs.get('buttons')
        self._teardown_interactive()
        if buttons:
            self._setup_buttons(buttons)
            self._interactive_active = True
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
            button_bg = QColor(appearance['background'])
            button_bg = button_bg.lighter(130) if foreground == '#ffffff' else button_bg.darker(105)
            for button in self._interactive_buttons:
                button.setAccessibleName(button.toolTip())
                button.setMaximumWidth(column)
                button.setStyleSheet(f'QPushButton {{background:{button_bg.name()}; color:{foreground}; border:1px solid {appearance["accent"]}; border-radius:8px; padding:{round(6 * scale)}px {round(12 * scale)}px; font-size:{round(12 * scale)}px;}} QPushButton:hover {{border:1px solid {foreground};}} QPushButton:pressed {{background:{appearance["background"]};}} QPushButton:focus {{border:2px solid {foreground};}}')
                button.ensurePolished()
            self._button_layout.invalidate()
        self._layout.invalidate()
        self.adjustSize()
        self._place(anchor_rect, animate=False)
        self.show()
        if kwargs.get('sticky'):
            self._hide_timer.stop()
        else:
            # An Open button must not make a timed completion alert permanent.
            self._hide_timer.start(max(500, int(duration_ms)))

    def refresh_task_appearance(self):
        if not self._task_active or not self.isVisible() or self._task_content is None:
            return
        remaining = self._hide_timer.remainingTime()
        text, kwargs = self._task_content
        self.show_text(text, self._anchor_rect, max(1, remaining), **kwargs)

    def _teardown_interactive(self):
        # deleteLater waits for the event loop; hide old preview controls now.
        for index in range(self._button_layout.count()):
            widget = self._button_layout.itemAt(index).widget()
            if widget is not None:
                widget.hide()
        super()._teardown_interactive()

    def _on_interactive_click(self, callback):
        if not self._task_active:
            return super()._on_interactive_click(callback)
        try:
            callback()
        except Exception:
            logging.getLogger('dsh-pet-standalone').exception('Codex 任务框操作失败')

    def paintEvent(self, event):
        if not self._task_active:
            return super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(self._preset['background']))
        painter.setPen(QPen(QColor(self._preset['border']), 1))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 12, 12)
