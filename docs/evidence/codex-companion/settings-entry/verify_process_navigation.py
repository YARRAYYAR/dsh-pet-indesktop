"""Repeatable, isolated native Qt settings process/navigation check.

Run from repository root with .venv/bin/python <this file>. The real settings
dialog runs in a child process. Only Config(base=<temporary directory>) is used;
Codex connection stays disabled and no user session or credential is read.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time

import PySide6
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

CHILD = r'''
import json
from pathlib import Path
import sys
from PySide6.QtCore import QTimer
from pet.config import Config
import pet.__main__ as entry
import pet.modern_settings_dialog as settings

base, report = Path(sys.argv[1]), Path(sys.argv[2])
state = {}
Original = settings.ModernSettingsDialog

class ObservedSettings(Original):
    def __init__(self, *args, **kwargs):
        self.raised = self.activated = 0
        self.ready = False
        super().__init__(*args, **kwargs)
        self.sidebar.currentRowChanged.connect(self.changed)

    def raise_(self):
        self.raised += 1
        return super().raise_()

    def activateWindow(self):
        self.activated += 1
        return super().activateWindow()

    def selected(self):
        page = self.pages.currentWidget()
        return page is self.codex_page or page.isAncestorOf(self.codex_page)

    def snapshot(self):
        return {'companion_mode': self.companion_mode,
                'codex_selected': self.selected(), 'visible': self.isVisible(),
                'raised': self.raised, 'activated': self.activated,
                'sidebar': [self.sidebar.item(i).text() for i in range(self.sidebar.count())]}

    def show(self):
        super().show()
        QTimer.singleShot(0, self.announce)

    def announce(self):
        state['initial'] = self.snapshot()
        self.sidebar.setCurrentRow(0)
        self.ready = True
        state['ready'] = True
        report.write_text(json.dumps(state))

    def changed(self, _row):
        if self.ready and self.selected():
            QTimer.singleShot(0, self.finish)

    def finish(self):
        state['after_ipc'] = self.snapshot()
        report.write_text(json.dumps(state))
        self.accept()

settings.ModernSettingsDialog = ObservedSettings
sys.argv = ['pet', '--settings', '--companion', '--settings-page', 'codex']
raise SystemExit(entry._run_settings(Config(base=base)))
'''


def wait_for(app, condition, *, seconds=20):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        if condition():
            return
        time.sleep(0.01)
    raise TimeoutError('native settings flow exceeded its state-based budget')


def read_state(path):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def main():
    from pet.config import Config
    from pet.settings_process_navigation import SettingsProcessNavigationClient

    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    output = Path(__file__).with_name('native-process.json')
    record = {
        'command': [sys.executable, str(Path(__file__).resolve())],
        'child_command': [sys.executable, '-c', '<CHILD source in runner>', '<temporary config base>', '<state file>'],
        'cwd': str(ROOT),
        'environment': {'QT_QPA_PLATFORM': os.environ.get('QT_QPA_PLATFORM', ''),
                        'python': sys.version, 'PySide6': PySide6.__version__,
                        'platform': platform.platform()},
        'setup': 'Three serial child processes with actual ModernSettingsDialog and temporary Config; Codex disabled.',
        'inputs': '--settings --companion --settings-page codex, then real QLocalSocket navigation from another process after resetting to the first page.',
        'assertions': 'Mode reaches actual dialog; startup selects Codex; IPC selects Codex and requests raise/activation; child exits zero; settings.lock released.',
        'rounds': [],
        'exit_status': 1,
    }
    try:
        for index in range(3):
            with tempfile.TemporaryDirectory(prefix='dsrp-nav-') as directory:
                base = Path(directory)
                state_file = base / 'state.json'
                child = subprocess.Popen([sys.executable, '-c', CHILD, str(base), str(state_file)],
                                         cwd=ROOT, env=os.environ.copy(), stdout=subprocess.PIPE,
                                         stderr=subprocess.PIPE, text=True)
                client = SettingsProcessNavigationClient(Config(base=base))
                round_record = {'round': index + 1}
                record['rounds'].append(round_record)
                try:
                    wait_for(app, lambda: bool(read_state(state_file).get('ready')) or child.poll() is not None)
                    initial = read_state(state_file).get('initial', {})
                    assert initial.get('companion_mode') is True, initial
                    assert initial.get('codex_selected') is True, initial
                    assert initial.get('visible') is True, initial
                    started = time.monotonic()
                    client.navigate('codex')
                    wait_for(app, lambda: 'after_ipc' in read_state(state_file) or child.poll() is not None)
                    round_record['navigation_ms'] = (time.monotonic() - started) * 1000
                    state = read_state(state_file)
                    after = state.get('after_ipc', {})
                    assert after.get('codex_selected') is True, state
                    assert after.get('raised', 0) > initial['raised'], state
                    assert after.get('activated', 0) > initial['activated'], state
                    wait_for(app, lambda: child.poll() is not None)
                    assert child.returncode == 0, child.returncode
                    assert not (Config(base=base).dir / 'settings.lock').exists()
                    round_record['state'] = state
                finally:
                    client.close()
                    if child.poll() is None:
                        child.terminate()
                    stdout, stderr = child.communicate(timeout=5)
                    round_record.update(child_exit_status=child.returncode, stdout=stdout, stderr=stderr)
        record['exit_status'] = 0
    except Exception as exc:
        record['error'] = f'{type(exc).__name__}: {exc}'
    finally:
        output.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'exit_status': record['exit_status'], 'rounds': len(record['rounds']),
                      'navigation_ms': [r.get('navigation_ms') for r in record['rounds']],
                      'error': record.get('error'), 'artifact': str(output)}, ensure_ascii=False))
    return record['exit_status']


if __name__ == '__main__':
    raise SystemExit(main())
