"""Compare original/candidate decoded pixels and media hashes without rewriting assets."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import imageio_ffmpeg
from PySide6.QtGui import QImage
from pet import webm_clip as candidate


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('baseline', type=Path)
    parser.add_argument('--frames', type=int, default=6)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location('pet._baseline_media', args.baseline / 'pet/webm_clip.py')
    baseline = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = baseline
    spec.loader.exec_module(baseline)
    results = []
    videos = sorted((ROOT / 'assets/characters').rglob('*.webm'))
    for video in videos:
        relative = video.relative_to(ROOT)
        original = args.baseline / relative
        digest = hashlib.sha256(video.read_bytes()).hexdigest()
        assert digest == hashlib.sha256(original.read_bytes()).hexdigest(), relative
        generators = []
        try:
            for module, path, threads in ((baseline, original, []), (candidate, video, ['-filter_threads', '2'])):
                generator = imageio_ffmpeg.read_frames(
                    str(path), pix_fmt='rgba', bits_per_pixel=32,
                    input_params=['-c:v', 'libvpx-vp9', *threads],
                    output_params=['-vf', module._decode_filter(922, 520)],
                )
                generators.append(generator)
            old_meta, new_meta = [next(generator) for generator in generators]
            assert old_meta['size'] == new_meta['size']
            width, height = old_meta['size']
            checked = 0
            for _ in range(args.frames):
                old = next(generators[0], None)
                new = next(generators[1], None)
                assert (old is None) == (new is None)
                if old is None:
                    break
                assert len(old) == len(new) == width * height * 4
                assert old == new, f'decoder mismatch: {relative}, frame {checked}'
                images = [QImage(frame, width, height, width * 4, QImage.Format.Format_RGBA8888) for frame in (old, new)]
                clean_old = baseline.clear_alpha_floor(images[0])
                clean_new = candidate.clear_alpha_floor(images[1])
                assert bytes(clean_old.constBits()) == bytes(clean_new.constBits()), f'alpha mismatch: {relative}, frame {checked}'
                checked += 1
            results.append({'path': str(relative), 'sha256': digest, 'size': [width, height], 'frames_equal': checked})
        finally:
            for generator in generators:
                generator.close()
    args.output.write_text(json.dumps({'videos': len(results), 'frames_equal': sum(x['frames_equal'] for x in results), 'results': results}, ensure_ascii=False, indent=2) + '\n')
    print(f'{len(results)} videos; {sum(x["frames_equal"] for x in results)} identical frames; all asset hashes match')


if __name__ == '__main__':
    main()
