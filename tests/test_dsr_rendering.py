import queue
import threading
import random
import pytest

from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor, QImage


def test_decode_queue_keeps_two_full_quality_frames(qapp, tmp_path):
    from pet.webm_clip import WebMClip

    clip = WebMClip(tmp_path / 'not-opened.webm')
    assert clip._queue.maxsize == 2
    clip.cleanup()


def test_backpressure_preserves_frame_order_and_is_interruptible():
    from pet.webm_clip import WebMClip

    frames = [bytes([i]) for i in range(6)]
    target = queue.Queue(maxsize=2)
    stop = threading.Event()
    worker = threading.Thread(target=WebMClip._stamp_source_indices,
                              args=(frames, target, stop.is_set),
                              kwargs={'timeout': 0.01, 'throttled': lambda: True})
    worker.start()
    received = [target.get(timeout=5) for _ in frames]
    worker.join(timeout=5)
    assert received == list(zip(frames, range(6)))
    assert not worker.is_alive()

    target.put((b'x', 0))
    target.put((b'y', 1))
    worker = threading.Thread(target=WebMClip._stamp_source_indices,
                              args=(frames, target, stop.is_set),
                              kwargs={'timeout': 0.01, 'throttled': lambda: True})
    worker.start()
    stop.set()
    worker.join(timeout=5)
    assert not worker.is_alive()


def test_soft_alpha_coverage_preserves_faint_edges_and_holes():
    from pet.frame_edges import coverage_region

    # Odd width exercises Qt's padded Alpha8 scanlines.
    image = QImage(17, 11, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)
    image.setPixelColor(8, 5, QColor(40, 120, 255, 1))
    before = bytes(image.constBits())
    region = coverage_region(image)
    assert region.contains(QPoint(8, 5))
    assert region.contains(QPoint(7, 4))
    assert not region.contains(QPoint(0, 0))
    assert bytes(image.constBits()) == before


def test_empty_alpha_coverage_is_empty():
    from pet.frame_edges import coverage_region

    image = QImage(9, 7, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)
    assert coverage_region(image).isEmpty()


def test_hd_black_alpha_floor_does_not_capture_the_entire_desktop():
    from pet.frame_edges import coverage_region

    image = QImage(17, 11, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(0, 0, 0, 1))
    image.setPixelColor(8, 5, QColor(255, 120, 40, 120))
    region = coverage_region(image)
    assert region.contains(QPoint(8, 5))
    assert not region.contains(QPoint(0, 0))


@pytest.mark.parametrize('format', [QImage.Format.Format_RGBA8888, QImage.Format.Format_ARGB32_Premultiplied])
def test_coverage_matches_every_alpha_and_color_without_mutating_display(format):
    """Independent pixel oracle: alpha0/floor1, colored1, holes, padding/clipping.

    Native E2E covers rotations/real media; this deterministic oracle covers
    uncommon alpha values that cannot all be selected from those source clips.
    """
    from PySide6.QtGui import QRegion
    from PySide6.QtCore import QRect
    from pet.frame_edges import coverage_region

    image = QImage(37, 25, format)
    image.fill(0)
    rng = random.Random(42)
    for y in range(image.height()):
        for x in range(image.width()):
            alpha = rng.randrange(256)
            if x % 3:
                image.setPixelColor(x, y, QColor(0, 0, 0, alpha))
            else:
                image.setPixelColor(x, y, QColor(rng.randrange(256), 80, 255, alpha))
    expected = QRegion()
    for y in range(image.height()):
        for x in range(image.width()):
            color = image.pixelColor(x, y)
            if color.alpha() and color != QColor(0, 0, 0, 1):
                expected |= QRegion(QRect(x-1, y-1, 3, 3))
    expected &= QRegion(image.rect())
    before = bytes(image.constBits())
    assert coverage_region(image) == expected
    assert bytes(image.constBits()) == before


@pytest.mark.parametrize('size', [(1, 1), (1, 9), (8, 1), (31, 9), (32, 9), (33, 9)])
@pytest.mark.parametrize('format', [QImage.Format.Format_RGBA8888,
                                   QImage.Format.Format_ARGB32_Premultiplied])
def test_sparse_coverage_clips_corners_and_preserves_scanline_padding(size, format):
    """Rare alpha/border combinations need a deterministic pixel oracle."""
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QRegion
    from pet.frame_edges import coverage_region

    width, height = size
    image = QImage(width, height, format)
    image.fill(0)
    for x, y, color in (
        (0, 0, QColor(255, 120, 40, 1)),
        (width-1, height-1, QColor(40, 120, 255, 3)),
        (width//2, height//2, QColor(0, 0, 0, 1)),
    ):
        image.setPixelColor(x, y, color)
    expected = QRegion()
    for y in range(height):
        for x in range(width):
            color = image.pixelColor(x, y)
            if color.alpha() and color != QColor(0, 0, 0, 1):
                expected |= QRegion(QRect(x-1, y-1, 3, 3))
    expected &= QRegion(image.rect())
    before = bytes(image.constBits())
    assert (coverage_region(image) ^ expected).isEmpty()
    assert bytes(image.constBits()) == before


def test_null_coverage_stays_empty():
    from pet.frame_edges import coverage_region

    assert coverage_region(QImage()).isEmpty()


def test_premultiplied_coverage_avoids_full_image_conversion():
    from pet.frame_edges import coverage_region

    class ConversionObservedImage(QImage):
        def __init__(self):
            super().__init__(33, 9, QImage.Format.Format_ARGB32_Premultiplied)
            self.conversions = []

        def convertToFormat(self, *args, **kwargs):  # noqa: N802 (Qt API)
            self.conversions.append(args[0])
            return super().convertToFormat(*args, **kwargs)

    image = ConversionObservedImage()
    image.fill(0)
    image.setPixelColor(16, 4, QColor(80, 120, 255, 1))
    assert coverage_region(image).contains(QPoint(16, 4))
    assert image.conversions == []
