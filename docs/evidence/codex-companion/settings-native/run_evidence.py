#!/usr/bin/env python3
"""Native settings screenshots and serial process measurements, isolated from user data."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import tempfile
import time
import traceback

ROOT = Path(__file__).resolve().parents[4]


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def child(mode, destination, duration):
    started = time.perf_counter()
    result = {'mode': mode, 'command': [sys.executable, *sys.argv], 'exit_status': 1}
    try:
        with tempfile.TemporaryDirectory(prefix='seeky-settings-metric-') as sandbox:
            sandbox = Path(sandbox)
            Path.home = classmethod(lambda cls: sandbox / 'home')
            Path.home().mkdir()
            os.environ['DSH_HOME'] = str(sandbox / '.dsh')
            sys.path.insert(0, str(ROOT))
            from PySide6 import __version__
            from PySide6.QtCore import QStandardPaths, QTimer, qVersion
            from PySide6.QtWidgets import QApplication, QWidget
            from pet import autostart
            from pet.config import Config
            from pet.modern_settings_dialog import ModernSettingsDialog
            QStandardPaths.setTestModeEnabled(True)
            app = QApplication([])
            assert app.platformName() == 'cocoa', app.platformName()
            autostart.is_enabled = lambda: False
            config = Config(sandbox)
            config.data.update({'codex_link_enabled': False, 'harness_autostart': False,
                                'self_talk_enabled': False, 'click_sound_enabled': False})
            constructing = time.perf_counter()
            dialog = ModernSettingsDialog(config, include_ai=mode == 'original',
                                          companion_mode=mode == 'companion', standalone=True)
            constructed = time.perf_counter()
            dialog.resize(1100, 760)
            dialog.show()
            result.update({'qt_platform': app.platformName(), 'qt_version': qVersion(),
                           'pyside_version': __version__, 'python': platform.python_version(),
                           'constructor_ms': (constructed - constructing) * 1000,
                           'imports_and_setup_ms': (constructing - started) * 1000,
                           'sidebar': [dialog.sidebar.item(i).text() for i in range(dialog.sidebar.count())],
                           'qwidget_count': len(dialog.findChildren(QWidget)),
                           'logical_size': [dialog.width(), dialog.height()], 'dpr': dialog.devicePixelRatioF()})

            def shown():
                handle = dialog.windowHandle()
                if handle is not None and handle.isExposed():
                    result['child_start_to_exposed_ms'] = (time.perf_counter() - started) * 1000
                    result['constructor_to_exposed_ms'] = (time.perf_counter() - constructing) * 1000
                    write(destination.with_suffix('.ready.json'), result)
                    QTimer.singleShot(round(duration * 1000), finish)
                elif time.perf_counter() - started < 15:
                    QTimer.singleShot(10, shown)
                else:
                    result['error'] = 'native window was never exposed'
                    app.quit()

            def finish():
                result['exit_status'] = 0
                dialog.command_client.close()
                dialog.close()
                app.quit()

            QTimer.singleShot(0, shown)
            app.exec()
    except Exception:
        result['error'] = traceback.format_exc()
    write(destination, result)
    return result['exit_status']


def measure(args):
    import psutil
    args.output.mkdir(parents=True, exist_ok=True)
    probe = args.output / 'proc-memory-probe'
    compile_command = ['clang', '-O2', str(ROOT / 'scripts/dsr_proc_memory.c'), '-o', str(probe)]
    compiled = subprocess.run(compile_command, capture_output=True, text=True)
    write(args.output / 'probe-build.json', {'command': compile_command, 'cwd': str(ROOT),
                                           'stdout': compiled.stdout, 'stderr': compiled.stderr,
                                           'exit_status': compiled.returncode})
    if compiled.returncode:
        return compiled.returncode
    env = dict(os.environ, QT_QPA_PLATFORM='cocoa', PYTHON_KEYRING_BACKEND='keyring.backends.null.Keyring',
               DSH_PET_INSTANCE='', PYTHONDONTWRITEBYTECODE='1')
    summary = {'command': [sys.executable, *sys.argv], 'cwd': str(ROOT), 'platform': platform.platform(),
               'python': sys.version, 'cpu_count': os.cpu_count(), 'load_average_before': os.getloadavg(),
               'setup': 'Each fresh Cocoa subprocess has temporary Config, Python home, DSH_HOME, Qt test paths and null keyring. No task/session/credential reads. Serial alternating original/companion; same source revision, dimensions, default general page; no Codex server or pet process.',
               'accounting': 'RSS and physical footprint sum the settings child and descendants. External observer/probe excluded. Steady samples start 1 second after native window exposure. Startup includes imports and native font/style setup; constructor separately timed. CPU uses psutil user+system counters; thread count sampled. This compares presentation modes, not pre-change commits.',
               'duration_seconds': args.duration, 'runs': [], 'exit_status': 1}
    for round_number in range(1, 4):
        for mode in ('original', 'companion'):
            name = f'{round_number:02d}-{mode}'
            target = args.output / f'{name}.json'
            command = [sys.executable, str(Path(__file__).resolve()), '--child', mode,
                       '--output', str(target), '--duration', str(args.duration)]
            log = (args.output / f'{name}.log').open('w')
            started = time.monotonic()
            process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            observed = psutil.Process(process.pid)
            samples, ready_at = [], None
            while process.poll() is None and time.monotonic() - started < args.duration + 25:
                now = time.monotonic()
                if ready_at is None and target.with_suffix('.ready.json').exists():
                    ready_at = now
                try:
                    procs = [observed, *observed.children(recursive=True)]
                    rows = subprocess.run([str(probe), *[str(p.pid) for p in procs]],
                                          capture_output=True, text=True, check=True).stdout.splitlines()
                    counters = [list(map(int, row.split())) for row in rows]
                    samples.append({'seconds': now - started, 'steady': ready_at is not None and now - ready_at >= 1,
                                    'pids': [r[0] for r in counters], 'footprint_bytes': sum(r[1] for r in counters),
                                    'rss_bytes': sum(r[2] for r in counters),
                                    'threads': sum(p.num_threads() for p in procs),
                                    'cpu_seconds': sum(sum(p.cpu_times()[:2]) for p in procs)})
                except (psutil.NoSuchProcess, psutil.ZombieProcess):
                    pass
                time.sleep(.2)
            if process.poll() is None:
                process.terminate()
            exit_status = process.wait(timeout=10)
            log.close()
            details = json.loads(target.read_text()) if target.exists() else {'error': 'child result missing'}
            steady = [s for s in samples if s['steady']]
            entry = {'mode': mode, 'round': round_number, 'command': command,
                     'exit_status': exit_status, 'child_result': details, 'samples': samples}
            if steady:
                entry['steady'] = {key: statistics.median(s[key] for s in steady)
                                   for key in ('footprint_bytes', 'rss_bytes', 'threads')}
                entry['steady']['cpu_percent'] = 100 * (steady[-1]['cpu_seconds'] - steady[0]['cpu_seconds']) / (steady[-1]['seconds'] - steady[0]['seconds'])
            summary['runs'].append(entry)
            write(args.output / 'measurements.json', summary)
            print(name, 'exit', exit_status, 'constructor_ms', round(details.get('constructor_ms', -1), 2),
                  'rss_mib', round(entry.get('steady', {}).get('rss_bytes', 0) / 2**20, 2), flush=True)
    summary['load_average_after'] = os.getloadavg()
    summary['exit_status'] = int(any(r['exit_status'] or not r.get('steady') for r in summary['runs']))
    for mode in ('original', 'companion'):
        runs = [r for r in summary['runs'] if r['mode'] == mode and 'steady' in r]
        if runs:
            summary[mode] = {key: {'median': statistics.median(values), 'minimum': min(values), 'maximum': max(values)}
                             for key, values in {
                                 'constructor_ms': [r['child_result']['constructor_ms'] for r in runs],
                                 'exposed_ms': [r['child_result']['child_start_to_exposed_ms'] for r in runs],
                                 **{key: [r['steady'][key] for r in runs]
                                    for key in ('rss_bytes', 'footprint_bytes', 'threads', 'cpu_percent')},
                             }.items()}
    write(args.output / 'measurements.json', summary)
    probe.unlink()
    return summary['exit_status']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--child', choices=('original', 'companion'))
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--duration', type=float, default=5)
    options = parser.parse_args()
    raise SystemExit(child(options.child, options.output, options.duration) if options.child else measure(options))
