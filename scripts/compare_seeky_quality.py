"""Same-frame Qt premultiplied Retina rendering on three backgrounds."""
import argparse
import json
from pathlib import Path
import sys

import imageio_ffmpeg
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtWidgets import QApplication


def first_frame(path):
    frames = imageio_ffmpeg.read_frames(str(path), pix_fmt='rgba', bits_per_pixel=32,
                                       input_params=['-c:v', 'libvpx-vp9'])
    try:
        meta = next(frames)
        width, height = meta['size']
        raw = next(frames)
        return QImage(raw, width, height, width*4, QImage.Format.Format_RGBA8888).copy()
    finally:
        frames.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--clip', default='idle/待机呼吸休闲.webm')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    app = QApplication([])
    assert app.platformName() == 'cocoa'
    before = first_frame(root/'assets/characters/shenshen/videos'/args.clip)
    after = first_frame(root/'assets/characters_hq/shenshen/videos'/args.clip)
    rendered = [image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied).scaled(
        1664, 936, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
        for image in (before, after)]
    crop = QRect(481, 104, 702, 507)
    output = QImage(1440, 1701, QImage.Format.Format_ARGB32_Premultiplied)
    output.fill(QColor('#141416'))
    painter = QPainter(output)
    painter.setFont(QFont(app.font().family(), 16))
    backgrounds = ['#ffffff', '#707070', '#c05a44']
    for row, color in enumerate(backgrounds):
        y = 567*row
        painter.setPen(QColor('#f5f5f7'))
        painter.drawText(20, y+30, '原素材放大 · 720p')
        painter.drawText(730, y+30, '高清素材 · 1440p')
        for column, frame in enumerate(rendered):
            x = 20+710*column
            painter.fillRect(QRect(x, y+48, 702, 507), QColor(color))
            painter.drawImage(QRect(x, y+48, 702, 507), frame, crop)
    painter.end()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    assert output.save(str(args.output))
    args.output.with_suffix('.json').write_text(json.dumps({'command': [sys.executable,
        str(Path(__file__).resolve()), *sys.argv[1:]], 'cwd': str(root),
        'setup': 'Real Cocoa Qt renderer, same source frame zero, .72 -> 1.3 scale at Retina DPR2',
        'inputs': {'clip': args.clip, 'backgrounds': backgrounds, 'display_physical_size': [1664, 936]},
        'assertions': '1280x720 versus 2560x1440; both premultiplied and Qt SmoothTransformation, same crop',
        'checks': {'source_dimensions': [[before.width(), before.height()], [after.width(), after.height()]]},
        'reset': 'Decode generators closed; source unchanged; comparison PNG only', 'exit_status': 0}, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
