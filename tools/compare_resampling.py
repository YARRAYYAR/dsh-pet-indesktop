"""Compare alpha-aware resampling on an unchanged source clip."""
import argparse
import json
import subprocess
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
import imageio_ffmpeg


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    filters = {
        'current-lanczos': 'scale=462:260:flags=lanczos',
        'area': 'scale=462:260:flags=area',
        'alpha-area': 'format=gbrap16le,premultiply=inplace=1,scale=462:260:flags=area,unpremultiply=inplace=1,format=rgba',
        'alpha-lanczos': 'format=gbrap16le,premultiply=inplace=1,scale=462:260:flags=lanczos,unpremultiply=inplace=1,format=rgba',
    }
    results = {}
    frames = {}
    for name, vf in filters.items():
        start = time.perf_counter()
        result = subprocess.run([
            imageio_ffmpeg.get_ffmpeg_exe(), '-v', 'error', '-threads', '1',
            '-c:v', 'libvpx-vp9', '-i', str(args.source), '-frames:v', '48',
            '-vf', vf, '-pix_fmt', 'rgba', '-f', 'rawvideo', '-',
        ], capture_output=True, check=True)
        elapsed = time.perf_counter() - start
        data = np.frombuffer(result.stdout, dtype=np.uint8).reshape(-1, 260, 462, 4)
        results[name] = {'seconds': elapsed, 'frames': len(data)}
        frames[name] = data
    sheet = Image.new('RGB', (462 * 4, 284 * 4), 'white')
    draw = ImageDraw.Draw(sheet)
    for col, (name, data) in enumerate(frames.items()):
        for row, (idx, bg) in enumerate(((0, 0), (24, 0), (0, 255), (24, 255))):
            rgba = data[idx].astype(np.float32)
            alpha = rgba[:, :, 3:] / 255
            rgb = np.clip(rgba[:, :, :3] * alpha + bg * (1-alpha), 0, 255).astype(np.uint8)
            sheet.paste(Image.fromarray(rgb), (col * 462, row * 284 + 24))
            draw.text((col * 462 + 6, row * 284 + 5), f'{name} frame {idx}', fill='black')
    sheet.save(args.output / 'comparison.png')
    detail = Image.new('RGB', (480 * 2, 480), 'black')
    for column, index in enumerate((0, 2)):
        crop = sheet.crop((index * 462 + 160, 54, index * 462 + 280, 174))
        detail.paste(crop.resize((480, 480), Image.Resampling.NEAREST), (column * 480, 0))
    detail.save(args.output / 'edge-detail-before-after.png')
    (args.output / 'report.json').write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
