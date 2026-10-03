"""seeky· pet identity; upstream compatibility version stays in pet.__init__."""
from pathlib import Path
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QIcon, QImage, QPainter, QPainterPath

NAME = 'seeky· pet'
DISPLAY_VERSION = '4.2.1 · seeky.5'


def brand_icon() -> QIcon:
    return QIcon(str(Path(__file__).parent / 'resources' / 'app-icon-mac.png'))


def mac_icon_image(source: QImage) -> QImage:
    """Apply a vector icon plate; the user's original artwork stays intact."""
    image = QImage(1024, 1024, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    plate = QRectF(64, 64, 896, 896)
    path = QPainterPath()
    path.addRoundedRect(plate, 200, 200)
    painter = QPainter(image)
    painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
    painter.setClipPath(path)
    painter.drawImage(plate, source)
    painter.end()
    return image
