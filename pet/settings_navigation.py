"""Finite painted sidebar feedback; shared selection belongs to the dialog."""
from PySide6.QtCore import QEvent, QPoint, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QPushButton, QSizePolicy, QStyledItemDelegate, QWidget

from . import ui_motion
from .ui_motion import RectTransition, StateTransition


class NavigationDelegate(QStyledItemDelegate):
    """The index widget draws the complete row, including its icon."""
    def paint(self, painter, option, index):
        pass

    def updateEditorGeometry(self, editor, option, index):
        editor.setGeometry(option.rect)


class NavigationSelectionPill(QWidget):
    """One painted surface moves between root rows without altering hit areas."""
    def __init__(self, sidebar):
        super().__init__(sidebar.viewport())
        self.sidebar = sidebar
        self._rect = QRectF()
        self._motion = RectTransition(self, 160, self._advance)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setObjectName('sidebarSelectionPill')
        sidebar.viewport().installEventFilter(self)
        sidebar.verticalScrollBar().valueChanged.connect(lambda _value: self.reposition(animate=False))
        self.show()
        self.lower()

    def _advance(self, rect):
        self._rect = QRectF(rect)
        self.update()

    def reposition(self, *, animate=True):
        self.setGeometry(self.sidebar.viewport().rect())
        item = self.sidebar.currentItem()
        if item is None:
            self._motion.snap(QRectF())
            return
        pane = self.sidebar.itemWidget(item)
        if pane is None:
            return
        item_rect = self.sidebar.visualItemRect(item)
        heading_top = pane.heading.mapTo(self.sidebar.viewport(), QPoint(0, 0)).y()
        target = QRectF(item_rect.x(), heading_top, item_rect.width(), pane.heading.height())
        self._motion.move_to(target) if animate and not self._rect.isEmpty() else self._motion.snap(target)
        self.lower()

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            self.reposition(animate=False)
        elif event.type() == QEvent.Type.LayoutRequest:
            self.reposition()
        return super().eventFilter(watched, event)

    def hideEvent(self, event):
        self._motion.snap()
        super().hideEvent(event)

    def paintEvent(self, event):
        if self._rect.isEmpty():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self._rect.adjusted(.5, .5, -.5, -.5)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 26))
        painter.drawRoundedRect(rect, 7, 7)
        edge = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        edge.setColorAt(0, QColor(255, 255, 255, 26))
        edge.setColorAt(1, QColor(255, 255, 255, 5))
        painter.setPen(QPen(edge, 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect, 7, 7)


class SidebarNavigationButton(QPushButton):
    metricsChanged = Signal()

    def __init__(self, text, parent=None, *, selected=False, secondary=False, disclosure=False, quit_action=False):
        super().__init__(text, parent)
        self._selected = selected
        self._secondary = secondary
        self._disclosure = disclosure
        self._quit_action = quit_action
        self._hover = 0.0
        self._selection = float(selected)
        self._press = 0.0
        self._paint_scale = 1.0
        self._icon_scale = 1.0
        self._keyboard_handler = None
        self._fade = StateTransition(self, 120, self._advance)
        self._selection_fade = StateTransition(self, 140, self._advance_selection, self._selection)
        self._press_fade = StateTransition(self, 80, self._advance_press)
        self._icon_bounce = StateTransition(self, 80, self._advance_icon, 1.0)
        self._icon_bounce.finished.connect(self._settle_icon)
        self.toggled.connect(lambda _checked: self._selection_changed())
        self.pressed.connect(lambda: self._press_fade.move_to(1.0))
        self.released.connect(lambda: self._press_fade.move_to(0.0))
        self.setAutoDefault(False)
        self.setDefault(False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setProperty('keyboardFocus', False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._update_metrics()

    def _text_font(self):
        font = QFont(self.font())
        if self._secondary and font.pixelSize() > 0:
            font.setPixelSize(max(12, round(font.pixelSize() * 12 / 13)))
        return font

    def _update_metrics(self):
        self.setMinimumHeight(max(28 if self._secondary else 32, self.fontMetrics().height() + 8))
        self.updateGeometry()
        self.metricsChanged.emit()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self._update_metrics()

    def _advance(self, value):
        self._hover = float(value)
        self.update()

    def _hover_to(self, value):
        self._fade.move_to(value)

    def _is_selected(self):
        return self._selected or (self._secondary and self.isChecked())

    def setSelected(self, selected):
        previous = self._is_selected()
        self._selected = bool(selected)
        self._selection_changed(previous)

    def _selection_changed(self, previous=None):
        selected = self._is_selected()
        was_selected = bool(self._selection_fade._target) if previous is None else previous
        self._selection_fade.move_to(float(selected))
        if selected and not was_selected and not self._disclosure:
            if not self.isVisible() or ui_motion.reduced_motion_requested():
                self._icon_bounce.snap(1.0)
            else:
                self._icon_bounce.setDuration(80)
                self._icon_bounce.move_to(1.10)
        elif not selected:
            self._icon_bounce.setDuration(160)
            self._icon_bounce.move_to(1.0)

    def _settle_icon(self):
        if self._icon_bounce._target != 1.0:
            self._icon_bounce.setDuration(160)
            self._icon_bounce.move_to(1.0)

    def _advance_selection(self, value):
        self._selection = value
        self.update()

    def _advance_press(self, value):
        self._press = value
        self._paint_scale = 1 - .03 * value
        self.update()

    def _advance_icon(self, value):
        self._icon_scale = value
        self.update()

    def hideEvent(self, event):
        self._fade.snap(0.0)
        self._press_fade.snap(0.0)
        self._selection_fade.snap(float(self._is_selected()))
        self._icon_bounce.snap(1.0)
        super().hideEvent(event)

    def enterEvent(self, event):
        super().enterEvent(event)
        self._hover_to(1.0)

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self._hover_to(0.0)

    def focusInEvent(self, event):
        self.setProperty('keyboardFocus', event.reason() in (Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason))
        super().focusInEvent(event)
        self.update()

    def mousePressEvent(self, event):
        self.setProperty('keyboardFocus', False)
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        super().mousePressEvent(event)

    def sizeHint(self):
        return QSize(self.fontMetrics().horizontalAdvance(self.text()) + 36, self.minimumHeight())

    def nextCheckState(self):
        # Root labels select their domain; only the independent arrow discloses.
        if self._secondary:
            self.setChecked(True)
        elif self._disclosure:
            super().nextCheckState()

    def keyPressEvent(self, event):
        self.setProperty('keyboardFocus', True)
        self.update()
        if self._keyboard_handler is not None and self._keyboard_handler(self, event.key()):
            event.accept()
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.click()
            event.accept()
            return
        super().keyPressEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(.5, .5, -.5, -.5)
        painter.save()
        center = rect.center()
        painter.translate(center)
        painter.scale(self._paint_scale, self._paint_scale)
        painter.translate(-center)
        feedback_color = QColor(255, 255, 255)
        if self._quit_action:
            feedback_color = QColor(255, 100, 100) if self._hover or (self.hasFocus() and self.property('keyboardFocus')) else QColor(160, 160, 166)
        if self._hover or self._press or (self._secondary and self._selection):
            opacity = (.10 * self._selection if self._secondary else 0) + .05 * self._hover * (1 - self._selection) + .025 * self._press
            painter.setPen(Qt.PenStyle.NoPen)
            surface = QColor(feedback_color)
            surface.setAlpha(round(255 * opacity))
            painter.setBrush(surface)
            painter.drawRoundedRect(rect, 7, 7)
        icon = self.icon().pixmap(QSize(18, 18), self.devicePixelRatioF())
        if not icon.isNull():
            tint = QPainter(icon)
            tint.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
            tint.fillRect(icon.rect(), feedback_color)
            tint.end()
            painter.save()
            icon_center = QRectF(4, (self.height() - 18) / 2, 18, 18).center()
            painter.translate(icon_center.x() + 1.5 * self._hover * (1 - self._selection), icon_center.y())
            painter.scale(self._icon_scale, self._icon_scale)
            painter.setOpacity(.62 + .33 * self._selection + .20 * self._hover * (1 - self._selection))
            painter.drawPixmap(-9, -9, icon)
            painter.restore()
        font = self._text_font()
        font.setWeight(QFont.Weight.Medium if self._is_selected() else QFont.Weight.Normal)
        painter.setFont(font)
        opacity = .78 + .17 * self._selection + .14 * self._hover * (1 - self._selection)
        text_color = QColor(feedback_color)
        text_color.setAlpha(round(255 * opacity))
        painter.setPen(text_color)
        if self._disclosure:
            painter.setPen(QPen(QColor(255, 255, 255, round(255 * opacity)), 1.35, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            x, y = rect.center().x(), rect.center().y()
            if self.isChecked():
                painter.drawLine(x - 3, y - 1.5, x, y + 1.5)
                painter.drawLine(x, y + 1.5, x + 3, y - 1.5)
            else:
                painter.drawLine(x - 1.5, y - 3, x + 1.5, y)
                painter.drawLine(x + 1.5, y, x - 1.5, y + 3)
        else:
            text_rect = self.rect().adjusted(10 if self._secondary else 30, 0, -4, 0)
            text = painter.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideRight, text_rect.width())
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
        painter.restore()
        if self.hasFocus() and self.property('keyboardFocus'):
            painter.setPen(QPen(feedback_color if self._quit_action else QColor('#b9b9c2'), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect, 7, 7)
