"""Extract a delivered ZIP and verify signatures, preflight and original videos."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('archive', type=Path)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    stage = Path(tempfile.mkdtemp(prefix='pet-delivery-check-'))
    subprocess.run(['ditto', '-x', '-k', str(args.archive), str(stage)], check=True)
    bundle = stage / 'DSH-Pet Smooth.app'
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(bundle)], check=True)
    env = os.environ.copy()
    env['DSH_PET_CONFIG_BASE'] = str(stage / 'config')
    executable = bundle / 'Contents/MacOS/DSH-Pet Smooth'
    result = subprocess.run([str(executable), '--selftest'], env=env, capture_output=True, text=True, timeout=60, check=True)
    assert result.stdout.strip() == 'preflight: OK', result
    assets = ROOT / 'assets/characters'
    videos = list(assets.rglob('*.webm'))
    for video in videos:
        packaged = bundle / 'Contents/Resources/assets/characters' / video.relative_to(assets)
        assert digest(video) == digest(packaged), video
    report = {
        'bundle': str(bundle),
        'signature': 'codesign --verify --deep --strict: passed (ad-hoc)',
        'selftest': result.stdout.strip(),
        'identical_videos': len(videos),
        'archive_bytes': args.archive.stat().st_size,
        'sha256': digest(args.archive),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
