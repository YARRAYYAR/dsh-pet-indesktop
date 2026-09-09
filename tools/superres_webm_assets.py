#!/usr/bin/env python3
"""AI-super-resolve transparent WebM pet assets with Real-ESRGAN NCNN."""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from fractions import Fraction
from pathlib import Path


def run(command: list[str], *, cwd: Path | None = None) -> None:
    completed = subprocess.run(
        command,
        cwd=cwd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or '').strip().splitlines()[-12:]
        raise RuntimeError(
            f"command failed ({completed.returncode}): {' '.join(command[:4])}\n"
            + '\n'.join(detail)
        )


def probe_video(path: Path, ffprobe: Path) -> dict:
    completed = subprocess.run(
        [
            str(ffprobe), "-v", "error", "-select_streams", "v:0",
            "-show_entries",
            "stream=width,height,avg_frame_rate:stream_tags=alpha_mode:format=duration",
            "-of", "json", str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)
    stream = payload["streams"][0]
    tags = {str(k).lower(): str(v) for k, v in stream.get("tags", {}).items()}
    fps_text = stream.get("avg_frame_rate", "0/1")
    return {
        "width": int(stream["width"]),
        "height": int(stream["height"]),
        "fps": float(Fraction(fps_text)) if fps_text != "0/0" else 0.0,
        "fps_text": fps_text,
        "duration": float(payload.get("format", {}).get("duration") or 0.0),
        "alpha_mode": tags.get("alpha_mode"),
    }


def alpha_range(path: Path, ffmpeg: Path) -> tuple[int, int] | None:
    completed = subprocess.run(
        [
            str(ffmpeg), "-v", "error", "-c:v", "libvpx-vp9", "-i", str(path),
            "-vf", "alphaextract,select='not(mod(n,10))'", "-frames:v", "5",
            "-vsync", "0", "-pix_fmt", "gray",
            "-f", "rawvideo", "-",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0 or not completed.stdout:
        return None
    return min(completed.stdout), max(completed.stdout)


def valid_output(
    source: Path,
    destination: Path,
    *,
    scale: int,
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

    expected_size = (source_meta["width"] * scale, source_meta["height"] * scale)
    actual_size = (output_meta["width"], output_meta["height"])
    if actual_size != expected_size:
        return False, f"size {actual_size} != {expected_size}"
    if abs(output_meta["fps"] - source_meta["fps"]) > 0.01:
        return False, f"fps {output_meta['fps']} != {source_meta['fps']}"
    duration_tolerance = max(0.2, 2.0 / max(1.0, source_meta["fps"]))
    if abs(output_meta["duration"] - source_meta["duration"]) > duration_tolerance:
        return False, "duration mismatch"
    if output_meta["alpha_mode"] != "1":
        return False, "alpha_mode missing"
    alpha = alpha_range(destination, ffmpeg)
    if alpha is None or alpha[0] >= 32 or alpha[1] <= 223:
        return False, f"invalid alpha range {alpha}"
    return True, "ok"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument(
        "--engine-root",
        type=Path,
        default=Path(__file__).resolve().parent / "realesrgan-20220424",
    )
    parser.add_argument("--ffmpeg", type=Path, default=Path("/opt/homebrew/bin/ffmpeg"))
    parser.add_argument("--ffprobe", type=Path, default=Path("/opt/homebrew/bin/ffprobe"))
    parser.add_argument("--model-name", default="realesr-animevideov3")
    parser.add_argument("--scale", type=int, choices=(2, 3, 4), default=2)
    parser.add_argument("--workers", default="1:4:2")
    parser.add_argument("--crf", type=int, default=18)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()

    input_root = args.input_root.resolve()
    output_root = args.output_root.resolve()
    engine_root = args.engine_root.resolve()
    ffmpeg = args.ffmpeg.resolve()
    ffprobe = args.ffprobe.resolve()
    engine = engine_root / "realesrgan-ncnn-vulkan"
    if not input_root.is_dir():
        raise SystemExit(f"input root does not exist: {input_root}")
    if not args.verify_only and not engine.is_file():
        raise SystemExit(f"Real-ESRGAN executable does not exist: {engine}")

    inputs = sorted(input_root.rglob("*.webm"))
    if args.limit:
        inputs = inputs[: args.limit]
    output_root.mkdir(parents=True, exist_ok=True)

    failures: list[str] = []

    for index, source in enumerate(inputs, 1):
        relative = source.relative_to(input_root)
        destination = output_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        valid, reason = valid_output(
            source,
            destination,
            scale=args.scale,
            ffmpeg=ffmpeg,
            ffprobe=ffprobe,
        )
        if valid:
            print(f"[{index}/{len(inputs)}] skip {relative}", flush=True)
            continue
        if args.verify_only:
            failures.append(f"{relative}: {reason}")
            print(f"[{index}/{len(inputs)}] invalid {relative}: {reason}", flush=True)
            continue

        partial = destination.with_name(f"{destination.stem}.partial.webm")
        partial.unlink(missing_ok=True)
        source_meta = probe_video(source, ffprobe)

        with tempfile.TemporaryDirectory(prefix="dsh-superres-") as temporary:
            work = Path(temporary)
            source_frames = work / "source"
            output_frames = work / "output"
            source_frames.mkdir()
            output_frames.mkdir()
            run([
                str(ffmpeg), "-y", "-hide_banner", "-loglevel", "error",
                "-c:v", "libvpx-vp9", "-i", str(source), "-vsync", "0",
                str(source_frames / "frame%05d.png"),
            ])
            run([
                str(engine), "-i", str(source_frames), "-o", str(output_frames),
                "-n", args.model_name, "-s", str(args.scale), "-f", "png",
                "-t", "256", "-j", args.workers,
            ], cwd=engine_root)
            run([
                str(ffmpeg), "-y", "-hide_banner", "-loglevel", "error",
                "-framerate", source_meta["fps_text"],
                "-i", str(output_frames / "frame%05d.png"),
                "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-auto-alt-ref", "0",
                "-crf", str(args.crf), "-b:v", "0", "-row-mt", "1", "-cpu-used", "4",
                "-metadata:s:v:0", "alpha_mode=1", "-an", str(partial),
            ])
        valid, reason = valid_output(
            source,
            partial,
            scale=args.scale,
            ffmpeg=ffmpeg,
            ffprobe=ffprobe,
        )
        if not valid:
            partial.unlink(missing_ok=True)
            raise RuntimeError(f"invalid output {relative}: {reason}")
        partial.replace(destination)
        print(f"[{index}/{len(inputs)}] done {relative}", flush=True)

    if failures:
        raise SystemExit(f"verification failed for {len(failures)} assets")
    print(f"completed {len(inputs)} assets -> {output_root}")


if __name__ == "__main__":
    main()
