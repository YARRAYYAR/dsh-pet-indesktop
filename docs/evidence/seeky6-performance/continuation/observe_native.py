"""Correlate real native playback with concurrent system pressure samples."""
import json
import subprocess
import sys
import time
from pathlib import Path

import psutil

root = Path.cwd()
out = Path(__file__).resolve().parent
command = [sys.executable, str(root / 'scripts/verify_seeky_multi.py'),
           '--output', str(out / 'observed-native.json'), '--probe', str(root / '.scratch/seeky-proc-memory'),
           '--duration', '100', '--steady-after', '35', '--prewarm', 'balanced', '--scale', '1.3',
           '--spawn-api', '--expect-warm-limit', '2', '--expect-shared-first-frames']
samples = []
psutil.cpu_percent()
start = time.monotonic()
with (out / 'observed-native.log').open('w') as log:
    process = subprocess.Popen(command, cwd=root, stdout=log, stderr=subprocess.STDOUT)
    while process.poll() is None:
        memory, swap = psutil.virtual_memory(), psutil.swap_memory()
        samples.append({'time': time.monotonic() - start, 'cpu_percent': psutil.cpu_percent(),
                        'available': memory.available, 'swap_used': swap.used,
                        'swap_in_bytes': swap.sin, 'swap_out_bytes': swap.sout})
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            continue
record = {'command': [sys.executable, str(Path(__file__).resolve())], 'child_command': command,
          'cwd': str(root), 'setup': 'Only one isolated real Cocoa playback run; observer samples read-only system counters every5s',
          'inputs': 'Three HQ pets at1.3, balanced prewarm, natural action boundaries',
          'assertions': 'Native >=22fps/no source gaps; capture simultaneous pressure rather than infer from after-only snapshot',
          'samples': samples, 'exit_status': process.returncode,
          'reset': 'Native script closes windows/readers; observer joins exact child; no other apps modified'}
(out / 'observed-system.json').write_text(json.dumps(record, indent=2) + '\n')
sys.exit(process.returncode)
