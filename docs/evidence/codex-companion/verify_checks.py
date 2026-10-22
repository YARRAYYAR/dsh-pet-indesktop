#!/usr/bin/env python3
"""Repeatable final checks with retained outputs and CPU-load cleanup."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
OUTPUT = Path(__file__).resolve().parent / 'final-checks'
ENV = dict(os.environ, QT_QPA_PLATFORM='offscreen',
           PYTHON_KEYRING_BACKEND='keyring.backends.null.Keyring',
           PYTHONDONTWRITEBYTECODE='1')
PYTEST = [str(ROOT / '.venv/bin/python'), '-m', 'pytest', '-q']


def check(name, command, *, load=False):
    OUTPUT.mkdir(parents=True, exist_ok=True)
    record = {'command': command, 'cwd': str(ROOT), 'platform': platform.platform(),
              'environment': {k: ENV[k] for k in ('QT_QPA_PLATFORM', 'PYTHON_KEYRING_BACKEND', 'PYTHONDONTWRITEBYTECODE')},
              'setup': 'Existing isolated test fixtures; temporary sessions/configuration and deterministic protocol peer. Original media unchanged.',
              'inputs': 'Complete suite or listed related public Qt/IPC/lifecycle paths.',
              'assertions': 'All collected assertions pass and process exits zero.',
              'started_unix': time.time(), 'exit_status': 1}
    burners = []
    try:
        if load:
            for _ in range(os.cpu_count() or 1):
                burners.append(subprocess.Popen([sys.executable, '-c', 'while True: pass'],
                                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        with (OUTPUT / f'{name}.log').open('w') as log:
            process = subprocess.run(command, cwd=ROOT, env=ENV, stdout=log, stderr=subprocess.STDOUT)
        record['exit_status'] = process.returncode
    except BaseException as exc:
        record['error'] = repr(exc)
    finally:
        for burner in burners:
            burner.terminate()
        for burner in burners:
            try:
                burner.wait(timeout=10)
            except subprocess.TimeoutExpired:
                burner.kill()
                burner.wait()
        record['elapsed_seconds'] = time.time() - record['started_unix']
        if load:
            record['load'] = {'cpu_burners': len(burners), 'command': [sys.executable, '-c', 'while True: pass'],
                              'stopped_all': all(p.poll() is not None for p in burners)}
        record['result_tail'] = (OUTPUT / f'{name}.log').read_text(errors='replace')[-6000:] if (OUTPUT / f'{name}.log').exists() else ''
        (OUTPUT / f'{name}.json').write_text(json.dumps(record, ensure_ascii=False, indent=2))
        print(name, 'exit', record['exit_status'], record['result_tail'][-1500:], flush=True)
    return record['exit_status']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', choices=('focused', 'full', 'loaded', 'static'), required=True)
    phase = parser.parse_args().phase
    codex = ['tests/test_codex_client.py', 'tests/test_codex_companion_flow.py',
             'tests/test_codex_companion_ui.py', 'tests/test_codex_discovery.py',
             'tests/test_codex_usage.py', 'tests/test_settings_process_isolation.py',
             'tests/test_companion_menu_editor.py', 'tests/test_dsr_codex_and_ceiling.py']
    decoder = ['tests/test_webm_reader_lifecycle.py', 'tests/test_webm_clip_lifecycle.py',
               'tests/test_webm_first_frame_lock.py']
    interaction = ['tests/test_low_priority_warm_interaction_yield.py']
    if phase == 'focused':
        return check('focused', PYTEST + codex + ['tests/test_architecture.py'])
    if phase == 'static':
        return check('ruff', [str(ROOT / '.venv/bin/ruff'), 'check', 'pet/', 'tests/', 'scripts/',
                              'docs/evidence/codex-companion/']) or check('diff-check', ['git', 'diff', '--check'])
    if phase == 'full':
        for name, args in [('pytest-main', [f'--ignore={p}' for p in decoder + interaction]),
                           ('pytest-decoder-lifecycle', decoder), ('pytest-interaction-isolated', interaction)]:
            result = check(name, PYTEST + args)
            if result:
                return result
        return 0
    family = codex + decoder + interaction + ['tests/test_prewarm_scheduler.py', 'tests/test_dsh_state.py',
             'tests/test_character_switch_lifecycle.py', 'tests/test_predictive_prewarm.py',
             'tests/test_library_priority_warm.py', 'tests/test_library_warm_priority.py',
             'tests/test_session_end_ffmpeg_guard.py']
    for round_number in range(1, 4):
        result = check(f'loaded-{round_number}', PYTEST + family, load=True)
        if result:
            return result
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
