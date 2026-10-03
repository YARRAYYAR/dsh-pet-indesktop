"""Validate immutable sources and timing/alpha parity of offline HQ variants."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import imageio_ffmpeg


def probe(path):
    result = subprocess.run(['/opt/homebrew/bin/ffprobe', '-v', 'error', '-count_frames',
        '-select_streams', 'v:0', '-show_entries',
        'stream=width,height,avg_frame_rate,nb_read_frames:stream_tags=alpha_mode:format=duration',
        '-of', 'json', str(path)], capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)
    stream = data['streams'][0]
    return {'width': stream['width'], 'height': stream['height'],
            'frames': int(stream['nb_read_frames']), 'fps': stream['avg_frame_rate'],
            'duration': float(data['format']['duration']),
            'alpha': {str(k).lower(): v for k, v in stream.get('tags', {}).items()}.get('alpha_mode')}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--allow-incomplete', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    base = root / 'assets/characters/shenshen/videos'
    hq = root / 'assets/characters_hq/shenshen/videos'
    errors, entries, absent = [], {}, []

    def validate(source):
        relative = source.relative_to(base).as_posix()
        target = hq / relative
        if not target.is_file():
            return relative, None
        before, after = probe(source), probe(target)
        assert (after['width'], after['height']) == (before['width']*2, before['height']*2), f'size: {before} -> {after}'
        assert before['frames'] == after['frames'] and before['fps'] == after['fps'], f'timeline: {before} -> {after}'
        assert abs(before['duration']-after['duration']) < .005, f'duration: {before} -> {after}'
        assert after['alpha'] == '1', f'alpha: {after}'
        frames, duration = imageio_ffmpeg.count_frames_and_secs(str(source))
        assert frames == before['frames'], relative
        return relative, {'base_width': before['width'], 'width': after['width'],
            'height': after['height'], 'frames': frames, 'duration': duration,
            'fps': frames/duration, 'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
            'hq_sha256': hashlib.sha256(target.read_bytes()).hexdigest()}

    files = sorted(base.rglob('*.webm'))
    with ThreadPoolExecutor(max_workers=4) as workers:
        futures = [workers.submit(validate, source) for source in files]
        for source, future in zip(files, futures):
            try:
                relative, entry = future.result()
                if entry is None:
                    absent.append(relative)
                else:
                    entries[relative] = entry
            except Exception as exc:
                errors.append(f'{source.relative_to(base)}: {exc}')
    if absent and not args.allow_incomplete:
        errors.append(f'{len(absent)} high-resolution variants missing')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result = {'command': [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]],
        'cwd': str(root), 'setup': 'Original 106 720p VP9 alpha clips paired with offline 1440p variants',
        'inputs': 'Every source/variant; four read-only probes in parallel',
        'assertions': '2x dimensions; exact frame count/rate; duration within 5 ms; AlphaMode=1; SHA256 recorded',
        'reset': 'Probe processes complete; no source or variant changes',
        'count': len(files), 'verified': len(entries), 'missing': absent,
        'clips': entries, 'errors': errors, 'exit_status': int(bool(errors))}
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    if not errors:
        (hq / 'quality-index.json').write_text(json.dumps({'clips': entries}, ensure_ascii=False, indent=2))
    print({'verified': len(entries), 'missing': len(absent), 'errors': errors})
    return int(bool(errors))


if __name__ == '__main__':
    sys.exit(main())
