"""Keep soft display alpha independent of the binary native window mask."""
from PIL import Image, ImageChops
from PySide6.QtCore import Qt
from PySide6.QtGui import QBitmap, QImage, QRegion


def coverage_region(canvas: QImage) -> QRegion:
    """Cover visible alpha samples, with one logical pixel of padding.

    Exact black A=1 background samples in the HD assets are excluded from
    coverage only; the display image and colored semi-transparent edges remain.

    The image remains untouched. A dithered alpha mask would otherwise clip
    low-opacity hair/shadows before the window compositor can blend them.
    Pillow's compiled LUT avoids scanning pixels in the GUI's Python loop.
    """
    rgba = canvas.convertToFormat(QImage.Format.Format_RGBA8888)
    pixels = Image.frombytes('RGBA', (rgba.width(), rgba.height()),
                             bytes(rgba.constBits()), 'raw', 'RGBA', rgba.bytesPerLine())
    red, green, blue, plane = pixels.split()
    # The imported HD VP9 clips encode their empty black background at A=1.
    # Exclude exactly that tuple from native coverage (not from display data).
    # Colored faint edges and every other alpha value retain their coverage.
    rgb = ImageChops.lighter(ImageChops.lighter(red, green), blue)
    black = rgb.point([255] + [0] * 255)
    floor = ImageChops.multiply(black, plane.point([0, 255] + [0] * 254))
    plane = ImageChops.subtract(plane, floor.point([0] + [1] * 255))
    binary = plane.point([0] + [255] * 255).tobytes()
    coverage = QImage(binary, rgba.width(), rgba.height(), rgba.width(),
                      QImage.Format.Format_Alpha8).convertToFormat(QImage.Format.Format_ARGB32)
    mask = QBitmap.fromImage(coverage.createAlphaMask(Qt.ImageConversionFlag.ThresholdDither))
    region = QRegion(mask)
    padded = QRegion(region)
    for dx, dy in ((-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (0, 1), (1, 1)):
        padded |= region.translated(dx, dy)
    return padded.intersected(QRegion(canvas.rect()))
