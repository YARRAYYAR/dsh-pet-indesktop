"""Keep soft display alpha independent of the binary native window mask."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QBitmap, QImage, QRegion, qRgba


def coverage_region(canvas: QImage) -> QRegion:
    """Cover visible alpha samples, with one logical pixel of padding.

    Exact black A=1 background samples in the HD assets are excluded from
    coverage only; the display image and colored semi-transparent edges remain.

    The image remains untouched. A dithered alpha mask would otherwise clip
    low-opacity hair/shadows before the window compositor can blend them.
    Qt's native masks avoid full RGBA/Pillow plane copies in the GUI hot path.
    """
    # Alpha8 converted back to ARGB has black RGB. Only A=0 matches zero,
    # including transparent colored samples in an unpremultiplied input.
    alpha = canvas if canvas.format() == QImage.Format.Format_ARGB32_Premultiplied else canvas.convertToFormat(QImage.Format.Format_Alpha8).convertToFormat(QImage.Format.Format_ARGB32)
    visible = alpha.createMaskFromColor(0, Qt.MaskMode.MaskOutColor)
    rgba = canvas if canvas.format() == QImage.Format.Format_ARGB32_Premultiplied else canvas.convertToFormat(QImage.Format.Format_ARGB32)
    floor = rgba.createMaskFromColor(qRgba(0, 0, 0, 1), Qt.MaskMode.MaskInColor)
    # createMaskFromColor uses black/white, while QBitmap treats black as the
    # covered bit. Match createAlphaMask's white/black palette without changing
    # any bits (otherwise fromImage silently inverts the coverage).
    for mask in (visible, floor):
        mask.setColor(0, 0xffffffff)
        mask.setColor(1, 0xff000000)
    region = QRegion(QBitmap.fromImage(visible)) - QRegion(QBitmap.fromImage(floor))
    horizontal = region | region.translated(-1, 0) | region.translated(1, 0)
    padded = horizontal | horizontal.translated(0, -1) | horizontal.translated(0, 1)
    return padded.intersected(QRegion(canvas.rect()))
