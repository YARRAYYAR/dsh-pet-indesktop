"""Qt adaptation of Codenotch's SidebarRow states (see THIRD_PARTY_NOTICES)."""
from PySide6.QtCore import QEasingCurve, QRectF, QSize, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QPushButton, QStyledItemDelegate


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
        self._fade = QVariantAnimation(self)
        self._fade.setDuration(140)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade.valueChanged.connect(self._advance)
        self.setAutoDefault(False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(28)

    def _advance(self, value):
        self._hover = float(value)
        self.update()

    def _hover_to(self, value):
        self._fade.stop()
        self._fade.setStartValue(self._hover)
        self._fade.setEndValue(value)
        self._fade.start()

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
        selected = self._selected or self.isChecked()
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        # Codenotch uses white at .10 for selection and .05 for hover,
        # plus a .10→.02 hairline gradient to catch the light.
        if selected or self._hover:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 255, 255, round(255 * (0.10 if selected else 0.05 * self._hover))))
            painter.drawRoundedRect(rect, 7, 7)
        if selected:
            edge = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            edge.setColorAt(0, QColor(255, 255, 255, 26))
            edge.setColorAt(1, QColor(255, 255, 255, 5))
            painter.setPen(QPen(edge, 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect, 7, 7)
        if self.isDown():
            painter.translate(0, 0.7)
        icon = self.icon().pixmap(18, 18)
        if not icon.isNull():
            tint = QPainter(icon)
            tint.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
            tint.fillRect(icon.rect(), Qt.GlobalColor.white)
            tint.end()
            painter.setOpacity(0.95 if selected else 0.60 + 0.25 * self._hover)
            painter.drawPixmap(4, (self.height() - 18) // 2, icon)
            painter.setOpacity(1)
        font = QFont(self.font())
        font.setPixelSize(12 if self._secondary else 13)
        font.setWeight(QFont.Weight.Medium if selected else QFont.Weight.Normal)
        painter.setFont(font)
        opacity = 0.95 if selected else 0.78 + 0.14 * self._hover
        painter.setPen(QColor(255, 255, 255, round(255 * opacity)))
        text_rect = self.rect().adjusted(30, 0, -4, 0)
        if self._secondary:
            text_rect = self.rect().adjusted(10, 0, -4, 0)
        text = painter.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideRight, text_rect.width())
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
        if self.hasFocus():
            painter.setPen(QPen(QColor('#64b5ff'), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect, 7, 7)
