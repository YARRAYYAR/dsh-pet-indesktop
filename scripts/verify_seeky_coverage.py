"""Native coverage parity and hot-path cost using real transparent assets."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time

from PIL import Image, ImageChops
from PySide6.QtCore import Qt
from PySide6.QtGui import QBitmap, QImage, QPainter, QRegion
from PySide6.QtWidgets import QApplication

from compare_seeky_quality import first_frame


def reference(canvas):
    rgba = canvas.convertToFormat(QImage.Format.Format_RGBA8888)
    pixels = Image.frombytes('RGBA', (rgba.width(), rgba.height()),
                             bytes(rgba.constBits()), 'raw', 'RGBA', rgba.bytesPerLine())
    red, green, blue, plane = pixels.split()
    rgb = ImageChops.lighter(ImageChops.lighter(red, green), blue)
    black = rgb.point([255] + [0]*255)
    floor = ImageChops.multiply(black, plane.point([0, 255] + [0]*254))
    plane = ImageChops.subtract(plane, floor.point([0] + [1]*255))
    binary = plane.point([0] + [255]*255).tobytes()
    coverage = QImage(binary, rgba.width(), rgba.height(), rgba.width(),
                      QImage.Format.Format_Alpha8).convertToFormat(QImage.Format.Format_ARGB32)
    region = QRegion(QBitmap.fromImage(coverage.createAlphaMask(Qt.ImageConversionFlag.ThresholdDither)))
    padded = QRegion(region)
    for dx, dy in ((-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (0, 1), (1, 1)):
        padded |= region.translated(dx, dy)
    return padded.intersected(QRegion(canvas.rect()))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--max-ms', type=float)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from pet.frame_edges import coverage_region
    app = QApplication([])
    assert app.platformName() == 'cocoa'
    results, errors = [], []
    source = first_frame(root/'assets/characters_hq/shenshen/videos/idle/待机呼吸休闲.webm')
    for scale in (.5203125, 1.3, 1.8):
        width, height = round(640*scale), round(360*scale)
        for angle in (0, 35, -90):
            canvas = QImage(width+80, height+80, QImage.Format.Format_ARGB32_Premultiplied)
            canvas.fill(Qt.GlobalColor.transparent)
            painter = QPainter(canvas)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.translate(canvas.width()/2, canvas.height()/2)
            painter.rotate(angle)
            painter.drawImage(-width//2, -height//2, source.scaled(
                width, height, Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
            painter.end()
            before = hashlib.sha256(bytes(canvas.constBits())).hexdigest()
            expected = reference(canvas)
            timings = []
            for _ in range(8):
                start = time.perf_counter()
                actual = coverage_region(canvas)
                timings.append((time.perf_counter()-start)*1000)
            # QRegion equality compares rectangle decomposition; XOR compares coverage.
            parity = (actual ^ expected).isEmpty()
            unchanged = before == hashlib.sha256(bytes(canvas.constBits())).hexdigest()
            row = {'scale': scale, 'angle': angle, 'median_ms': statistics.median(timings),
                   'coverage_rectangles': actual.rectCount(), 'exact_region_parity': parity,
                   'display_pixels_unchanged': unchanged}
            results.append(row)
            if not parity or not unchanged:
                errors.append(f'Coverage or display parity failed: {row}')
            if args.max_ms is not None and row['median_ms'] > args.max_ms:
                errors.append(f'Coverage hot path exceeds {args.max_ms} ms: {row}')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({'command': [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]],
        'cwd': str(root), 'setup': 'Cocoa, real transparent HQ idle frame; original region union as reference',
        'inputs': 'Three sizes, three rotations, eight repeats per case',
        'assertions': 'Exact native coverage region; unchanged display bytes; optional cost budget',
        'checks': results, 'errors': errors, 'reset': 'Decode generator closed; source assets unchanged',
        'exit_status': int(bool(errors))}, indent=2))
    print(results, errors)
    return int(bool(errors))


if __name__ == '__main__':
    sys.exit(main())
