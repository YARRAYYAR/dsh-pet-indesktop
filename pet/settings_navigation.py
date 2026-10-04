"""Qt adaptation of Codenotch's SidebarRow states (see THIRD_PARTY_NOTICES)."""
from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QPushButton, QStyledItemDelegate

from .ui_motion import StateTransition


class NavigationDelegate(QStyledItemDelegate):
    """The index widget draws the complete row, including its icon."""
    def paint(self, painter, option, index):
        pass

    def updateEditorGeometry(self, editor, option, index):
        editor.setGeometry(option.rect)


class SidebarNavigationButton(QPushButton):
    def __init__(self, text, parent=None, *, selected=False, secondary=False):
        super().__init__(text, parent)
        self._selected = selected
        self._secondary = secondary
        self._hover = 0.0
        self._selection = float(selected)
        self._press = 0.0
        self._fade = StateTransition(self, 120, self._advance)
        self._selection_fade = StateTransition(self, 140, self._advance_selection, self._selection)
        self._press_fade = StateTransition(self, 80, self._advance_press)
        self.toggled.connect(lambda _checked: self._selection_fade.move_to(float(self._is_selected())))
        self.pressed.connect(lambda: self._press_fade.move_to(1.0))
        self.released.connect(lambda: self._press_fade.move_to(0.0))
        self.setAutoDefault(False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(28)

    def _advance(self, value):
        self._hover = float(value)
        self.update()

    def _hover_to(self, value):
        self._fade.move_to(value)

    def _is_selected(self):
        return self._selected or (self._secondary and self.isChecked())

    def setSelected(self, selected):
        self._selected = bool(selected)
        self._selection_fade.move_to(float(self._is_selected()))

    def _advance_selection(self, value):
        self._selection = value
        self.update()

    def _advance_press(self, value):
        self._press = value
        self.update()

    def hideEvent(self, event):
        self._fade.snap(0.0)
        self._press_fade.snap(0.0)
        self._selection_fade.snap(float(self._is_selected()))
        super().hideEvent(event)

    def enterEvent(self, event):
        super().enterEvent(event)
        self._hover_to(1.0)

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self._hover_to(0.0)

    def sizeHint(self):
        return QSize(self.fontMetrics().horizontalAdvance(self.text()) + 36, 30)

    def keyPressEvent(self, event):
        if self.isCheckable() and not self._secondary:
            if event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right):
                self.setChecked(event.key() == Qt.Key.Key_Right)
                event.accept()
                return
        super().keyPressEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        selected = self._is_selected()
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        # Codenotch uses white at .10 for selection and .05 for hover,
        # plus a .10→.02 hairline gradient to catch the light.
        if self._selection or self._hover or self._press:
            painter.setPen(Qt.PenStyle.NoPen)
            opacity = 0.10 * self._selection + 0.05 * self._hover * (1 - self._selection) + 0.025 * self._press
            painter.setBrush(QColor(255, 255, 255, round(255 * opacity)))
            painter.drawRoundedRect(rect, 7, 7)
        if self._selection:
            edge = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            edge.setColorAt(0, QColor(255, 255, 255, round(26 * self._selection)))
            edge.setColorAt(1, QColor(255, 255, 255, round(5 * self._selection)))
            painter.setPen(QPen(edge, 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect, 7, 7)
        painter.translate(0, 0.7 * self._press)
        icon = self.icon().pixmap(QSize(18, 18), self.devicePixelRatioF())
        if not icon.isNull():
            tint = QPainter(icon)
            tint.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
            tint.fillRect(icon.rect(), Qt.GlobalColor.white)
            tint.end()
            painter.setOpacity(0.62 + 0.33 * self._selection + 0.20 * self._hover * (1 - self._selection))
            painter.drawPixmap(4, (self.height() - 18) // 2, icon)
            painter.setOpacity(1)
        font = QFont(self.font())
        # Honor font enlargement; the dialog establishes the base system font.
        if self._secondary and font.pixelSize() > 0:
            font.setPixelSize(max(12, font.pixelSize() - 1))
        font.setWeight(QFont.Weight.Medium if selected else QFont.Weight.Normal)
        painter.setFont(font)
        opacity = 0.78 + 0.17 * self._selection + 0.14 * self._hover * (1 - self._selection)
        painter.setPen(QColor(255, 255, 255, round(255 * opacity)))
        text_rect = self.rect().adjusted(30, 0, -4, 0)
        if self._secondary:
            text_rect = self.rect().adjusted(10, 0, -4, 0)
        text = painter.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideRight, text_rect.width())
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
        if self.hasFocus():
            painter.setPen(QPen(QColor('#b9b9c2'), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect, 7, 7)
