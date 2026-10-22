#!/usr/bin/env python3
"""Isolated serial Cocoa captures of both current profiles and original source."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[4]
OUTPUT = Path(__file__).resolve().parent / 'visuals'


def run_capture(name, source, width, scale, companion=False, details=False):
    target = OUTPUT / name
    target.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, '-c',
               'import os,runpy,sys; from pathlib import Path; '
               'Path.home=classmethod(lambda cls:Path(os.environ["SEEKY_TEST_HOME"])); '
               'from PySide6.QtCore import QStandardPaths; QStandardPaths.setTestModeEnabled(True); '
               'script=sys.argv.pop(1); runpy.run_path(script,run_name="__main__")',
               str(source / 'scripts/capture_settings_pages.py'), str(target),
               '--width', str(width), '--height', '760', '--font-scale', str(scale), '--dark']
    if companion:
        command.append('--companion')
    if details:
        command.extend(['--interaction-details', '--menu-details'])
    with tempfile.TemporaryDirectory(prefix='seeky-native-capture-') as sandbox:
        home = Path(sandbox) / 'home'
        home.mkdir()
        env = dict(os.environ, QT_QPA_PLATFORM='cocoa',
                   PYTHON_KEYRING_BACKEND='keyring.backends.null.Keyring',
                   SEEKY_TEST_HOME=str(home), DSH_HOME=str(Path(sandbox) / '.dsh'),
                   CODEX_HOME=str(Path(sandbox) / '.codex'),
                   PYTHONDONTWRITEBYTECODE='1', DSH_PET_INSTANCE='')
        started = time.monotonic()
        result = subprocess.run(command, cwd=source, env=env, capture_output=True, text=True, timeout=90)
    (target / 'run.log').write_text(result.stdout + result.stderr)
    layout_path = target / 'layout.json'
    layout = json.loads(layout_path.read_text()) if layout_path.exists() else None
    maxima = [m for screen in layout['screens'] for m in screen['horizontal_scroll_maxima']] if layout else []
    assertions = {'process_exit_zero': result.returncode == 0,
                  'native_cocoa': bool(layout and layout['qt_platform'] == 'cocoa'),
                  'screens_saved': bool(list(target.glob('*.png'))),
                  'no_horizontal_page_scroll': bool(layout) and all(m == 0 for m in maxima)}
    record = {'command': command, 'cwd': str(source), 'environment': {k: env[k] for k in (
        'QT_QPA_PLATFORM', 'PYTHON_KEYRING_BACKEND', 'PYTHONDONTWRITEBYTECODE')},
        'setup': 'Temporary Python home, DSH_HOME, CODEX_HOME, Config and Qt test paths; no real sessions or credentials.',
        'inputs': {'source': name.split('-')[0], 'width': width, 'height': 760,
                   'font_scale': scale, 'companion': companion, 'details': details},
        'assertions': assertions, 'duration_seconds': time.monotonic() - started,
        'exit_status': result.returncode, 'platform': platform.platform()}
    (target / 'run.json').write_text(json.dumps(record, ensure_ascii=False, indent=2))
    print(name, result.returncode, assertions, flush=True)
    return record


def main():
    global OUTPUT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-only', action='store_true')
    parser.add_argument('--output', type=Path, default=OUTPUT)
    options = parser.parse_args()
    global_output = options.output.resolve()
    OUTPUT = global_output
    OUTPUT.mkdir(parents=True, exist_ok=True)
    source_files = ['pet/settings_theme_qss.py', 'pet/settings_widgets.py', 'pet/settings_navigation.py']
    diff = subprocess.run(['git', 'diff', '7a5fed77', '--', *source_files], cwd=ROOT, capture_output=True, text=True)
    (OUTPUT / 'source-layout-baseline.json').write_text(json.dumps({
        'command': diff.args, 'cwd': str(ROOT), 'files': source_files, 'diff': diff.stdout,
        'exit_status': diff.returncode, 'unchanged': not diff.stdout,
        'baseline': '7a5fed77', 'note': 'Current original mode is not original commit; original commit captured separately.'
    }, ensure_ascii=False, indent=2))
    runs = []
    if not options.baseline_only:
        for width, scale in ((1100, 1.0), (720, 1.0), (720, 1.35)):
            for companion in (False, True):
                name = f'{"companion" if companion else "original"}-{width}-font-{scale}'
                runs.append(run_capture(name, ROOT, width, scale, companion, details=True))
    with tempfile.TemporaryDirectory(prefix='seeky-original-ui-source-') as temporary:
        source = Path(temporary)
        shutil.copytree(ROOT / 'pet', source / 'pet', ignore=shutil.ignore_patterns('__pycache__'))
        names = subprocess.run(['git', 'ls-files', 'pet'], cwd=ROOT, capture_output=True,
                               text=True, check=True, timeout=10).stdout.splitlines()
        baseline_manifest = []
        for name in names:
            target = source / name
            if not target.is_file():
                continue
            baseline = subprocess.run(['git', 'show', f'7a5fed77:{name}'], cwd=ROOT,
                                      capture_output=True, timeout=10)
            if baseline.returncode == 0:
                target.write_bytes(baseline.stdout)
                baseline_manifest.append(name)
        (OUTPUT / 'baseline-source-manifest.json').write_text(json.dumps(baseline_manifest, indent=2))
        (source / 'assets').symlink_to(ROOT / 'assets', target_is_directory=True)
        (source / 'scripts').mkdir()
        script = (ROOT / 'scripts/capture_settings_pages.py').read_text()
        script = script.replace('            companion_mode=args.companion,\n', '')
        script = script.replace('        dialog.command_client.close()\n', '')
        (source / 'scripts/capture_settings_pages.py').write_text(script)
        runs.append(run_capture('baseline-7a5fed77-1100-font-1.0', source, 1100, 1.0))
    (OUTPUT / 'summary.json').write_text(json.dumps(runs, ensure_ascii=False, indent=2))
    return int(any(not all(r['assertions'].values()) for r in runs))


if __name__ == '__main__':
    raise SystemExit(main())
