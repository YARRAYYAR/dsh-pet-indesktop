#!/usr/bin/env python3
"""Build lightweight transparent WebM playback assets from high-resolution masters."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from superres_webm_assets import alpha_range, probe_video, run


def target_size(source_meta: dict, max_width: int, max_height: int) -> tuple[int, int]:
    scale = min(max_width / source_meta["width"], max_height / source_meta["height"], 1.0)
    width = max(2, int(source_meta["width"] * scale) // 2 * 2)
    height = max(2, int(source_meta["height"] * scale) // 2 * 2)
    return width, height


def valid_output(
    source: Path,
    destination: Path,
    *,
    max_width: int,
    max_height: int,
    ffmpeg: Path,
    ffprobe: Path,
) -> tuple[bool, str]:
    if not destination.is_file() or destination.stat().st_size <= 0:
        return False, "missing"
    try:
        source_meta = probe_video(source, ffprobe)
        output_meta = probe_video(destination, ffprobe)
    except Exception as exc:
        return False, f"probe failed: {exc}"
    expected = target_size(source_meta, max_width, max_height)
    actual = output_meta["width"], output_meta["height"]
    if actual != expected:
        return False, f"size {actual} != {expected}"
    if abs(output_meta["fps"] - source_meta["fps"]) > 0.01:
        return False, f"fps {output_meta['fps']} != {source_meta['fps']}"
    tolerance = max(0.2, 2.0 / max(1.0, source_meta["fps"]))
    if abs(output_meta["duration"] - source_meta["duration"]) > tolerance:
        return False, "duration mismatch"
    if output_meta["alpha_mode"] != "1":
        return False, "alpha_mode missing"
    alpha = alpha_range(destination, ffmpeg)
    if alpha is None or alpha[0] >= 32 or alpha[1] <= 223:
        return False, f"invalid alpha range {alpha}"
    return True, "ok"


def build_one(
    source: Path,
    destination: Path,
    *,
    max_width: int,
    max_height: int,
    crf: int,
    ffmpeg: Path,
    ffprobe: Path,
) -> str:
    valid, _ = valid_output(
        source,
        destination,
        max_width=max_width,
        max_height=max_height,
        ffmpeg=ffmpeg,
        ffprobe=ffprobe,
    )
    if valid:
        return "skip"
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(f"{destination.stem}.partial.webm")
    partial.unlink(missing_ok=True)
    source_meta = probe_video(source, ffprobe)
    width, height = target_size(source_meta, max_width, max_height)
    run([
        str(ffmpeg), "-y", "-hide_banner", "-loglevel", "error",
        "-c:v", "libvpx-vp9", "-i", str(source),
        "-vf", f"scale={width}:{height}:flags=lanczos",
        "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-auto-alt-ref", "0",
        "-crf", str(crf), "-b:v", "0", "-row-mt", "1", "-cpu-used", "4",
        "-metadata:s:v:0", "alpha_mode=1", "-an", str(partial),
    ])
    valid, reason = valid_output(
        source,
        partial,
        max_width=max_width,
        max_height=max_height,
        ffmpeg=ffmpeg,
        ffprobe=ffprobe,
    )
    if not valid:
        partial.unlink(missing_ok=True)
        raise RuntimeError(f"invalid output {source.name}: {reason}")
    partial.replace(destination)
    return "done"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--ffmpeg", type=Path, default=Path("/opt/homebrew/bin/ffmpeg"))
    parser.add_argument("--ffprobe", type=Path, default=Path("/opt/homebrew/bin/ffprobe"))
    parser.add_argument("--max-width", type=int, default=1280)
    parser.add_argument("--max-height", type=int, default=720)
    parser.add_argument("--crf", type=int, default=18)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()

    input_root = args.input_root.resolve()
    output_root = args.output_root.resolve()
    ffmpeg = args.ffmpeg.resolve()
    ffprobe = args.ffprobe.resolve()
    inputs = sorted(input_root.rglob("*.webm"))
    if not inputs:
        raise SystemExit(f"no WebM assets found: {input_root}")
    output_root.mkdir(parents=True, exist_ok=True)

    if args.verify_only:
        failures = []
        for index, source in enumerate(inputs, 1):
            relative = source.relative_to(input_root)
            valid, reason = valid_output(
                source,
                output_root / relative,
                max_width=args.max_width,
                max_height=args.max_height,
                ffmpeg=ffmpeg,
                ffprobe=ffprobe,
            )
            print(f"[{index}/{len(inputs)}] {'ok' if valid else 'invalid'} {relative}", flush=True)
            if not valid:
                failures.append(f"{relative}: {reason}")
        if failures:
            raise SystemExit(f"verification failed for {len(failures)} assets")
        print(f"verified {len(inputs)} runtime assets -> {output_root}")
        return

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = {}
        for source in inputs:
            relative = source.relative_to(input_root)
            future = executor.submit(
                build_one,
                source,
                output_root / relative,
                max_width=args.max_width,
                max_height=args.max_height,
                crf=args.crf,
                ffmpeg=ffmpeg,
                ffprobe=ffprobe,
            )
            futures[future] = relative
        completed = 0
        for future in as_completed(futures):
            completed += 1
            result = future.result()
            print(f"[{completed}/{len(inputs)}] {result} {futures[future]}", flush=True)
    print(f"completed {len(inputs)} runtime assets -> {output_root}")


if __name__ == "__main__":
    main()
