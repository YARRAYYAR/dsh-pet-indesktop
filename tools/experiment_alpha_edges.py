#!/usr/bin/env python3
"""对一段透明 WebM 做限距 RGB 外扩实验，不覆盖原素材。"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from scipy.ndimage import distance_transform_edt

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.build_hq_webm import (
    _read_exact,
)


def bleed_low_alpha_rgb(
    rgb: np.ndarray,
    alpha: np.ndarray,
    *,
    foreground_threshold: int = 48,
    alpha_floor: int = 4,
    radius: int = 10,
) -> np.ndarray:
    """实验性地把可信前景颜色外扩到邻近低 Alpha 像素。"""
    result = rgb.copy()
    foreground_threshold = max(1, min(255, int(foreground_threshold)))
    alpha_floor = max(0, min(foreground_threshold - 1, int(alpha_floor)))
    radius = max(0, int(radius))
    seeds = alpha >= foreground_threshold
    targets = alpha <= alpha_floor
    if radius == 0 or not seeds.any() or not targets.any():
        return result

    distance, indices = distance_transform_edt(~seeds, return_indices=True)
    fill = targets & (distance <= radius)
    nearest_y, nearest_x = indices
    result[fill] = rgb[nearest_y[fill], nearest_x[fill]]
    return result


def _probe_video(path: Path, ffmpeg: str) -> tuple[int, int, str]:
    ffprobe = str(Path(ffmpeg).with_name('ffprobe'))
    result = subprocess.run(
        [
            ffprobe, '-v', 'error', '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height,r_frame_rate',
            '-of', 'json', str(path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    stream = json.loads(result.stdout)['streams'][0]
    return int(stream['width']), int(stream['height']), str(stream['r_frame_rate'])


def _rgb_to_yuv(frame: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    height, width = frame.shape[:2]
    if height % 2 or width % 2:
        raise ValueError('yuva420p 要求宽高为偶数')
    r = frame[..., 0].astype(np.float32)
    g = frame[..., 1].astype(np.float32)
    b = frame[..., 2].astype(np.float32)
    y = np.clip(16 + 0.257 * r + 0.504 * g + 0.098 * b, 16, 235).astype(np.uint8)
    u = np.clip(128 - 0.148 * r - 0.291 * g + 0.439 * b, 16, 240)
    v = np.clip(128 + 0.439 * r - 0.368 * g - 0.071 * b, 16, 240)
    u = u.reshape(height // 2, 2, width // 2, 2).mean(axis=(1, 3)).astype(np.uint8)
    v = v.reshape(height // 2, 2, width // 2, 2).mean(axis=(1, 3)).astype(np.uint8)
    return y, u, v


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--ffmpeg', default='ffmpeg')
    parser.add_argument('--max-frames', type=int, default=72)
    parser.add_argument('--foreground-threshold', type=int, default=48)
    parser.add_argument('--alpha-floor', type=int, default=4)
    parser.add_argument('--radius', type=int, default=10)
    args = parser.parse_args()

    if args.source.resolve() == args.output.resolve():
        raise SystemExit('实验输出不能覆盖源素材')
    args.output.parent.mkdir(parents=True, exist_ok=True)

    width, height, frame_rate = _probe_video(args.source, args.ffmpeg)
    frame_bytes = width * height * 4
    reader_command = [
        args.ffmpeg,
        '-hide_banner', '-loglevel', 'error', '-threads', '1',
        '-c:v', 'libvpx-vp9', '-i', str(args.source),
    ]
    if args.max_frames > 0:
        reader_command.extend(('-frames:v', str(args.max_frames)))
    reader_command.extend(('-f', 'rawvideo', '-pix_fmt', 'rgba', '-'))
    reader = subprocess.Popen(reader_command, stdout=subprocess.PIPE)
    writer = subprocess.Popen(
        [
            args.ffmpeg,
            '-y', '-hide_banner', '-loglevel', 'error',
            '-f', 'rawvideo', '-pix_fmt', 'yuva420p',
            '-s', f'{width}x{height}', '-r', frame_rate, '-i', '-',
            '-c:v', 'libvpx-vp9', '-pix_fmt', 'yuva420p',
            '-crf', '24', '-b:v', '0', '-auto-alt-ref', '0',
            '-row-mt', '1', '-deadline', 'good', '-cpu-used', '4',
            '-an', str(args.output),
        ],
        stdin=subprocess.PIPE,
    )

    frames = 0
    changed_pixels = 0
    low_alpha_pixels = 0
    elapsed_start = time.monotonic()
    try:
        while args.max_frames <= 0 or frames < args.max_frames:
            payload = _read_exact(reader.stdout, frame_bytes)
            if len(payload) < frame_bytes:
                break
            rgba = np.frombuffer(payload, np.uint8).reshape(height, width, 4)
            rgb = rgba[..., :3]
            alpha = rgba[..., 3]
            processed = bleed_low_alpha_rgb(
                rgb,
                alpha,
                foreground_threshold=args.foreground_threshold,
                alpha_floor=args.alpha_floor,
                radius=args.radius,
            )
            changed_pixels += int(np.any(processed != rgb, axis=2).sum())
            low_alpha_pixels += int((alpha <= args.alpha_floor).sum())
            y, u, v = _rgb_to_yuv(processed)
            writer.stdin.write(
                y.tobytes() + u.tobytes() + v.tobytes() + alpha.tobytes()
            )
            frames += 1
    finally:
        if reader.stdout is not None:
            reader.stdout.close()
        if writer.stdin is not None:
            writer.stdin.close()
        reader_returncode = reader.wait()
        writer_returncode = writer.wait()

    if reader_returncode != 0 or writer_returncode != 0:
        raise RuntimeError(
            f'实验转码失败: reader={reader_returncode}, writer={writer_returncode}'
        )
    if frames == 0:
        raise RuntimeError('实验没有读取到有效帧')

    report = {
        'source': str(args.source),
        'output': str(args.output),
        'frames': frames,
        'width': width,
        'height': height,
        'frame_rate': frame_rate,
        'foreground_threshold': args.foreground_threshold,
        'alpha_floor': args.alpha_floor,
        'radius': args.radius,
        'changed_pixels': changed_pixels,
        'low_alpha_pixels': low_alpha_pixels,
        'changed_ratio_of_low_alpha': changed_pixels / max(1, low_alpha_pixels),
        'elapsed_seconds': round(time.monotonic() - elapsed_start, 3),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
