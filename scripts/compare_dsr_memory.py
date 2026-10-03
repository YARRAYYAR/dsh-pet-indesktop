"""Run the requested three alternating native baseline/candidate measurements."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--probe', type=Path, required=True)
    args = parser.parse_args()
    baseline = args.baseline.resolve()
    probe = args.probe.resolve()
    if not baseline.is_dir() or not probe.is_file():
        raise FileNotFoundError('Prepare the baseline source and compiled macOS memory helper first')
    root = Path(__file__).resolve().parent.parent
    output = root / 'docs/evidence/dsr-pet'
    output.mkdir(parents=True, exist_ok=True)
    for repetition in range(1, 4):
        for label, source in (('baseline', baseline), ('optimized', root)):
            print(label, repetition, flush=True)
            command = [sys.executable, str(root / 'scripts/verify_dsr_runtime.py'),
                       '--root', str(source), '--output', str(output / f'{label}-{repetition}.json'),
                       '--probe', str(probe)]
            started = time.monotonic()
            timestamp = datetime.now(timezone.utc).isoformat()
            with (output / f'{label}-{repetition}.log').open('w') as stream:
                result = subprocess.run(command, cwd=root, stdout=stream, stderr=subprocess.STDOUT,
                                        env={**os.environ, 'QT_QPA_PLATFORM': 'cocoa'})
            (output / f'{label}-{repetition}.run.json').write_text(json.dumps({
                'command': command, 'cwd': str(root), 'started_utc': timestamp,
                'elapsed_seconds': time.monotonic() - started,
                'setup': 'Same Python/Qt runtime and HD assets; isolated temporary Config, seed 42',
                'inputs': 'Single/three pets, continuous switching, eight sequential settings opens, return to single',
                'assertions': 'Complete samples and frames; all settings children exit 0; no callback errors',
                'reset': 'New temporary Config each run; application shutdown releases readers and Qt services',
                'exit_status': result.returncode,
            }, ensure_ascii=False, indent=2))
            if result.returncode:
                return result.returncode
    return 0


if __name__ == '__main__':
    sys.exit(main())
