#!/usr/bin/env python3
"""Probe direct transport reap through real Qt lifecycle paths, no real account."""
import json
import os
from pathlib import Path
import platform
import sys
import tempfile
import time

import psutil
from PySide6 import __version__
from PySide6.QtCore import QCoreApplication, QEvent, QObject, QTimer

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
from pet.codex_client import CodexClient  # noqa: E402


def main():
    app = QCoreApplication([])
    results = []
    record = {
        'command': [sys.executable, str(Path(__file__).resolve())],
        'cwd': str(Path.cwd()),
        'environment': {'QT_QPA_PLATFORM': os.environ.get('QT_QPA_PLATFORM'),
                        'python': sys.version, 'PySide6': __version__, 'platform': platform.platform()},
        'setup': 'Temporary CODEX_HOME, actual QProcess peer and active turn. No private sessions, credentials or model.',
        'inputs': ['explicit stop', 'parent QObject destruction', 'application aboutToQuit'],
        'assertions': ['child starts with active turn', 'same child PID/create-time identity is absent after close'],
        'limits': 'Direct transport process only; real model command descendants and SIGKILL/crash shutdown are unverified.',
        'exit_status': 1,
    }

    def wait_for(check):
        deadline = time.monotonic() + 10
        while not check() and time.monotonic() < deadline:
            app.processEvents()
        assert check()

    try:
        with tempfile.TemporaryDirectory(prefix='seeky-codex-exit-') as directory:
            root = Path(directory)
            for mode in ('explicit-stop', 'parent-destruction', 'application-quit'):
                parent = QObject()
                client = CodexClient(parent, program=sys.executable, arguments=[
                    str(ROOT / 'tests/fixtures/codex_peer.py'), 'active', str(root / f'{mode}.jsonl'),
                ], home=root / 'codex')
                client.connect_server()
                wait_for(lambda: client.snapshot()['connection'] == 'ready')
                client.new_task('isolated active task', str(root))
                wait_for(lambda: bool(client.snapshot()['turn_id']))
                pid = client.process.processId()
                identity = psutil.Process(pid).create_time()
                started = time.monotonic()
                if mode == 'explicit-stop':
                    client.stop()
                elif mode == 'parent-destruction':
                    parent.deleteLater()
                    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                else:
                    QTimer.singleShot(0, app.quit)
                    app.exec()
                try:
                    alive = psutil.Process(pid).create_time() == identity
                except psutil.NoSuchProcess:
                    alive = False
                results.append({'mode': mode, 'pid': pid, 'same_identity_alive': alive,
                                'close_ms': (time.monotonic() - started) * 1000})
                assert not alive, (mode, pid)
                if mode != 'parent-destruction':
                    parent.deleteLater()
                    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        record['exit_status'] = 0
    finally:
        record['results'] = results
        Path(__file__).with_name('exit-paths.json').write_text(json.dumps(record, ensure_ascii=False, indent=2))
        print(json.dumps(record, ensure_ascii=False, indent=2))
    return record['exit_status']


if __name__ == '__main__':
    raise SystemExit(main())
