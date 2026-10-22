#!/usr/bin/env python3
"""Probe installed app-server handshake without real account or task access."""
from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import traceback

ROOT = Path(__file__).resolve().parents[3]
OUTPUT = Path(__file__).resolve().parent / 'native-cli.json'


def main():
    record = {'command': [sys.executable, *sys.argv], 'cwd': str(ROOT),
              'platform': platform.platform(), 'exit_status': 1,
              'setup': 'Fresh HOME/CODEX_HOME/DSH_HOME, whitelist environment, null keyring; no real sessions, credentials or model requests.',
              'inputs': 'Installed codex binary; initialize + initialized + account reads only. No thread/start, resume or turn/start.',
              'assertions': 'Installed CLI handshakes, exposes unauthenticated account error, stops and reaps owned process.'}
    try:
        program = shutil.which('codex')
        assert program, 'Codex CLI not found'
        record['program'] = program
        with tempfile.TemporaryDirectory(prefix='seeky-cli-verification-') as directory:
            sandbox = Path(directory)
            (sandbox / 'codex').mkdir()
            env = {key: os.environ[key] for key in ('PATH', 'LANG', 'LC_ALL', 'SYSTEMROOT') if key in os.environ}
            env.update(HOME=str(sandbox), CODEX_HOME=str(sandbox / 'codex'), DSH_HOME=str(sandbox / 'dsh'),
                       TMPDIR=str(sandbox), QT_QPA_PLATFORM='offscreen',
                       PYTHON_KEYRING_BACKEND='keyring.backends.null.Keyring')
            os.environ.clear()
            os.environ.update(env)
            version = subprocess.run([program, '--version'], env=env, capture_output=True, text=True, timeout=10)
            record['version'] = version.stdout.strip()
            record['version_exit_status'] = version.returncode
            sys.path.insert(0, str(ROOT))
            from PySide6 import __version__
            from PySide6.QtCore import QCoreApplication, QProcess, QTimer
            from pet.codex_client import CodexClient
            app = QCoreApplication([])
            client = CodexClient(program=program, home=sandbox / 'codex')
            record['pyside_version'] = __version__
            record['states'] = []
            ready = []
            deadline = time.monotonic() + 20

            def changed(state):
                if state['connection'] == 'ready':
                    ready.append(True)
                record['states'].append({key: state[key] for key in ('connection', 'state', 'error')})

            def poll():
                state = client.snapshot()
                if state['connection'] == 'error' or (ready and state['error']) or time.monotonic() > deadline:
                    record['ready'] = bool(ready)
                    record['account_error'] = state['error']
                    client.stop()
                    record['process_stopped'] = client.process.state() == QProcess.ProcessState.NotRunning
                    record['exit_status'] = int(not (record['ready'] and record['account_error'] and record['process_stopped']))
                    timer.stop()
                    app.quit()

            client.changed.connect(changed)
            timer = QTimer()
            timer.setInterval(25)
            timer.timeout.connect(poll)
            timer.start()
            client.connect_server()
            app.exec()
            client.stop()
    except BaseException:
        record['error'] = traceback.format_exc()
    OUTPUT.write_text(json.dumps(record, ensure_ascii=False, indent=2))
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return record['exit_status']


if __name__ == '__main__':
    raise SystemExit(main())
