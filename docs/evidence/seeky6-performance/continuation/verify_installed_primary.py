"""Read the already-open installed app through its real local command API."""
import json
from pathlib import Path
import sys

import psutil
from PySide6.QtCore import QCoreApplication, QTimer

root = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(root))
from pet.config import Config
from pet.settings_commands import SettingsCommandClient

bundle = Path('/Users/ray/Applications/seeky· pet.app')
processes = [p for p in psutil.process_iter(['cmdline'])
             if (p.info['cmdline'] or [None])[0] == str(bundle / 'Contents/MacOS/seeky· pet')
             and '--settings' not in (p.info['cmdline'] or [])]
assert len(processes) == 1
app = QCoreApplication([])
client = SettingsCommandClient(Config())
responses = []


def received(response):
    responses.append(response)
    app.quit()


client.request('list_actions', {}, received)
QTimer.singleShot(10000, app.quit)
app.exec()
assert responses and responses[0]['ok']
assert len(responses[0]['data']['actions']) == 106
result = {'command': [sys.executable, str(Path(__file__).resolve())], 'cwd': str(root),
          'setup': 'CUA getApp exact installed path; already running actual primary instance',
          'inputs': 'Read-only list_actions',
          'assertions': 'Installed process exists; real directory contains 106 actions',
          'checks': {'installed_path': str(bundle), 'pid': processes[0].pid,
                     'action_count': 106, 'current': responses[0]['data']['current']},
          'reset': 'No settings written; leave application running', 'exit_status': 0}
(root / 'docs/evidence/seeky6-performance/continuation/installed-primary.json').write_text(
    json.dumps(result, ensure_ascii=False, indent=2) + '\n')
print('PASS')
