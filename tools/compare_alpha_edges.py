#!/usr/bin/env python3
"""比较原始与 RGB 外扩实验 WebM，并生成显示尺寸对照图。"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy.ndimage import distance_transform_edt

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.build_hq_webm import _read_exact  # noqa: E402

DISPLAY_SIZE = (462, 260)


def _probe_video(path: Path, ffmpeg: str) -> tuple[int, int]:
    ffprobe = str(Path(ffmpeg).with_name('ffprobe'))
    result = subprocess.run(
        [
            ffprobe, '-v', 'error', '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height', '-of', 'json', str(path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    stream = json.loads(result.stdout)['streams'][0]
    return int(stream['width']), int(stream['height'])


def _open_reader(path: Path, ffmpeg: str, frames: int) -> subprocess.Popen:
    return subprocess.Popen(
        [
            ffmpeg,
            '-hide_banner', '-loglevel', 'error', '-threads', '1',
            '-c:v', 'libvpx-vp9', '-i', str(path),
            '-frames:v', str(frames),
            '-f', 'rawvideo', '-pix_fmt', 'rgba', '-',
        ],
        stdout=subprocess.PIPE,
    )


def _green_spill(rgb: np.ndarray) -> np.ndarray:
    channels = rgb.astype(np.int16)
    return np.maximum(
        0,
        channels[..., 1] - np.maximum(channels[..., 0], channels[..., 2]),
    )


def _checkerboard(width: int, height: int, tile: int = 12) -> np.ndarray:
    y, x = np.indices((height, width))
    cells = ((x // tile) + (y // tile)) % 2
    values = np.where(cells[..., None] == 0, 218, 168)
    return np.repeat(values.astype(np.uint8), 3, axis=2)


def _display_composite(
    rgba: np.ndarray,
    alpha_floor: int,
    background: str = 'checker',
) -> np.ndarray:
    working = rgba.copy()
    clear = working[..., 3] <= alpha_floor
    working[clear] = 0
    image = Image.fromarray(working, 'RGBA').resize(
        DISPLAY_SIZE,
        Image.Resampling.LANCZOS,
    )
    scaled = np.asarray(image, dtype=np.uint8)
    alpha = scaled[..., 3:4].astype(np.float32) / 255.0
    if background == 'white':
        backdrop = np.full((DISPLAY_SIZE[1], DISPLAY_SIZE[0], 3), 255, np.uint8)
    elif background == 'black':
        backdrop = np.zeros((DISPLAY_SIZE[1], DISPLAY_SIZE[0], 3), np.uint8)
    else:
        backdrop = _checkerboard(*DISPLAY_SIZE)
    return np.clip(
        scaled[..., :3].astype(np.float32) * alpha
        + backdrop.astype(np.float32) * (1.0 - alpha),
        0,
        255,
    ).astype(np.uint8)


def _flat_composite(rgba: np.ndarray, alpha_floor: int, value: int = 192) -> np.ndarray:
    alpha = rgba[..., 3].copy()
    alpha[alpha <= alpha_floor] = 0
    weight = alpha[..., None].astype(np.float32) / 255.0
    return np.clip(
        rgba[..., :3].astype(np.float32) * weight + value * (1.0 - weight),
        0,
        255,
    ).astype(np.uint8)


def _save_contact_sheet(
    samples: list[tuple[int, np.ndarray, np.ndarray]],
    path: Path,
    alpha_floor: int,
    background: str = 'checker',
) -> None:
    width, height = DISPLAY_SIZE
    label_height = 24
    canvas = Image.new('RGB', (width * 3, (height + label_height) * len(samples)), 'white')
    draw = ImageDraw.Draw(canvas)
    for row, (frame_index, original, variant) in enumerate(samples):
        y = row * (height + label_height)
        before = _display_composite(original, alpha_floor, background)
        after = _display_composite(variant, alpha_floor, background)
        difference = np.clip(
            np.abs(after.astype(np.int16) - before.astype(np.int16)) * 8,
            0,
            255,
        ).astype(np.uint8)
        draw.text((6, y + 5), f'frame {frame_index}  original / RGB bleed / diff x8', fill='black')
        canvas.paste(Image.fromarray(before), (0, y + label_height))
        canvas.paste(Image.fromarray(after), (width, y + label_height))
        canvas.paste(Image.fromarray(difference), (width * 2, y + label_height))
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(path)


def _save_floor_contact_sheet(
    samples: list[tuple[int, np.ndarray, np.ndarray]],
    path: Path,
) -> None:
    width, height = DISPLAY_SIZE
    label_height = 24
    canvas = Image.new('RGB', (width * 3, (height + label_height) * len(samples)), 'white')
    draw = ImageDraw.Draw(canvas)
    for row, (frame_index, original, _variant) in enumerate(samples):
        y = row * (height + label_height)
        floor1 = _display_composite(original, 1)
        floor4 = _display_composite(original, 4)
        difference = np.clip(
            np.abs(floor4.astype(np.int16) - floor1.astype(np.int16)) * 32,
            0,
            255,
        ).astype(np.uint8)
        draw.text((6, y + 5), f'frame {frame_index}  floor 1 / floor 4 / diff x32', fill='black')
        canvas.paste(Image.fromarray(floor1), (0, y + label_height))
        canvas.paste(Image.fromarray(floor4), (width, y + label_height))
        canvas.paste(Image.fromarray(difference), (width * 2, y + label_height))
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('original', type=Path)
    parser.add_argument('variant', type=Path)
    parser.add_argument('--ffmpeg', default='ffmpeg')
    parser.add_argument('--frames', type=int, default=72)
    parser.add_argument('--samples', default='0,24,48,71')
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--contact-prefix', type=Path, required=True)
    args = parser.parse_args()

    sample_indices = {
        int(value) for value in args.samples.split(',') if value.strip()
    }
    width, height = _probe_video(args.original, args.ffmpeg)
    variant_size = _probe_video(args.variant, args.ffmpeg)
    if variant_size != (width, height):
        raise SystemExit(
            f'视频尺寸不一致: original={(width, height)}, variant={variant_size}'
        )
    original_reader = _open_reader(args.original, args.ffmpeg, args.frames)
    variant_reader = _open_reader(args.variant, args.ffmpeg, args.frames)
    frame_bytes = width * height * 4

    alpha_difference = 0
    alpha_changed = 0
    original_floor_2_4 = 0
    variant_floor_2_4 = 0
    near_low_count = 0
    original_near_low_rgb = np.zeros(3, dtype=np.float64)
    variant_near_low_rgb = np.zeros(3, dtype=np.float64)
    transition_count = 0
    original_transition_spill = 0.0
    variant_transition_spill = 0.0
    floor1_floor4_difference = 0
    samples: list[tuple[int, np.ndarray, np.ndarray]] = []
    frames = 0

    while frames < args.frames:
        original_payload = _read_exact(original_reader.stdout, frame_bytes)
        variant_payload = _read_exact(variant_reader.stdout, frame_bytes)
        if len(original_payload) < frame_bytes or len(variant_payload) < frame_bytes:
            break
        original = np.frombuffer(original_payload, np.uint8).reshape(height, width, 4)
        variant = np.frombuffer(variant_payload, np.uint8).reshape(height, width, 4)
        original_alpha = original[..., 3]
        variant_alpha = variant[..., 3]

        difference = np.abs(
            original_alpha.astype(np.int16) - variant_alpha.astype(np.int16)
        )
        alpha_difference += int(difference.sum())
        alpha_changed += int((difference > 0).sum())
        original_floor_2_4 += int(
            ((original_alpha >= 2) & (original_alpha <= 4)).sum()
        )
        variant_floor_2_4 += int(
            ((variant_alpha >= 2) & (variant_alpha <= 4)).sum()
        )

        core = original_alpha >= 48
        distance = distance_transform_edt(~core)
        near_low = (original_alpha <= 4) & (distance <= 10)
        transition = (
            (original_alpha >= 5)
            & (original_alpha < 48)
            & (distance <= 10)
        )
        near_low_count += int(near_low.sum())
        original_near_low_rgb += original[..., :3][near_low].sum(axis=0)
        variant_near_low_rgb += variant[..., :3][near_low].sum(axis=0)
        transition_count += int(transition.sum())
        original_transition_spill += float(_green_spill(original[..., :3])[transition].sum())
        variant_transition_spill += float(_green_spill(variant[..., :3])[transition].sum())
        floor1_floor4_difference += int(np.abs(
            _flat_composite(original, 1).astype(np.int16)
            - _flat_composite(original, 4).astype(np.int16)
        ).sum())

        if frames in sample_indices:
            samples.append((frames, original.copy(), variant.copy()))
        frames += 1

    if original_reader.stdout is not None:
        original_reader.stdout.close()
    if variant_reader.stdout is not None:
        variant_reader.stdout.close()
    returncodes = (original_reader.wait(), variant_reader.wait())
    if returncodes != (0, 0) or frames == 0:
        raise RuntimeError(f'比较解码失败: frames={frames}, returncodes={returncodes}')

    report = {
        'frames': frames,
        'width': width,
        'height': height,
        'alpha_changed_pixels': alpha_changed,
        'alpha_mean_absolute_difference': alpha_difference / (frames * width * height),
        'original_alpha_2_4': original_floor_2_4,
        'variant_alpha_2_4': variant_floor_2_4,
        'near_low_alpha_pixels': near_low_count,
        'original_near_low_rgb_mean': (
            original_near_low_rgb / max(1, near_low_count)
        ).round(3).tolist(),
        'variant_near_low_rgb_mean': (
            variant_near_low_rgb / max(1, near_low_count)
        ).round(3).tolist(),
        'transition_pixels': transition_count,
        'original_transition_green_spill_mean': (
            original_transition_spill / max(1, transition_count)
        ),
        'variant_transition_green_spill_mean': (
            variant_transition_spill / max(1, transition_count)
        ),
        'floor1_vs_floor4_composite_mae': (
            floor1_floor4_difference / (frames * width * height * 3)
        ),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8',
    )
    _save_contact_sheet(samples, args.contact_prefix.with_name(
        f'{args.contact_prefix.name}-floor1.png'
    ), 1)
    _save_contact_sheet(samples, args.contact_prefix.with_name(
        f'{args.contact_prefix.name}-floor4.png'
    ), 4)
    _save_contact_sheet(samples, args.contact_prefix.with_name(
        f'{args.contact_prefix.name}-floor1-white.png'
    ), 1, 'white')
    _save_contact_sheet(samples, args.contact_prefix.with_name(
        f'{args.contact_prefix.name}-floor1-black.png'
    ), 1, 'black')
    _save_floor_contact_sheet(samples, args.contact_prefix.with_name(
        f'{args.contact_prefix.name}-floor1-vs-floor4.png'
    ))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
