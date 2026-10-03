"""Launch the installed native bundle and exercise its real local command API."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import psutil
from PySide6.QtCore import QCoreApplication, QTimer

from pet.config import Config
from pet.settings_commands import SettingsCommandClient


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--app', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    output = args.output or root / 'docs/evidence/dsr-pet/packaged-ipc.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    bundle = args.app.resolve()
    config_dir = Config().dir
    slot = next(index for index in range(127, 99, -1)
                if not (config_dir / f'config-slot-{index}.json').exists()
                and not (config_dir / 'slots' / f'slot-{index}.lock').exists())
    instance = f'slot-{slot}'
    config = Config(instance_id=instance)
    config.data.update({'no_move': True, 'mouse_through': True,
                        'harness_autostart': False, 'self_talk_enabled': False,
                        'codex_link_enabled': False, 'click_sound_enabled': False,
                        'user_customized': True})
    assert config.save()
    app = QCoreApplication([])
    client = SettingsCommandClient(config)
    checks, errors, descendants = {}, [], set()
    command = [str(bundle / 'Contents/MacOS/seeky· pet'), '--slot', str(slot)]
    started = time.monotonic()
    with output.with_suffix('.log').open('w') as stream:
        process = subprocess.Popen(command, cwd=root, env={**os.environ, 'DSH_PET_INSTANCE': instance},
                                   stdout=stream, stderr=subprocess.STDOUT)

        def fail(kind, error, trace):
            errors.append(f'{kind.__name__}: {error}')
            app.quit()

        sys.excepthook = fail

        def remember_children():
            try:
                descendants.update(item.pid for item in psutil.Process(process.pid).children(recursive=True))
            except psutil.NoSuchProcess:
                pass  # A successful quit can finish before this sampling tick.

        def listed(response):
            if not response['ok'] and time.monotonic() - started < 15 and process.poll() is None:
                QTimer.singleShot(300, connect)
                return
            assert response['ok'], response
            checks['action_count'] = len(response['data']['actions'])
            assert checks['action_count'] == 106
            remember_children()
            client.request('play_action', {'name': '点击回应-元气挥手'}, played)

        def played(response):
            checks['play'] = response
            assert response['ok'], response
            assert response['data']['current'] == '点击回应-元气挥手'
            client.request('play_action', {'name': 'not-an-action'}, invalid)

        def invalid(response):
            checks['invalid_error'] = response
            assert not response['ok'], response
            remember_children()
            client.request('quit', {}, quit_done)

        def quit_done(response):
            checks['quit'] = response
            assert response['ok'], response
            app.quit()

        def connect():
            client.request('list_actions', {}, listed)

        def timeout():
            errors.append('Packaged command flow exceeded 25 seconds')
            app.quit()

        QTimer.singleShot(300, connect)
        QTimer.singleShot(25000, timeout)
        child_timer = QTimer(app)
        child_timer.timeout.connect(remember_children)
        child_timer.start(500)
        app.exec()
        child_timer.stop()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            errors.append('Bundle did not exit after quit')
            process.terminate()
            process.wait(timeout=10)
        if process.returncode:
            errors.append(f'Bundle exited {process.returncode}')
    alive = [pid for pid in descendants if psutil.pid_exists(pid)]
    checks['remaining_child_pids'] = alive
    if alive:
        errors.append('Bundle child processes remain after quit')
    config.path.unlink(missing_ok=True)
    (config_dir / 'slots' / f'slot-{slot}.lock').unlink(missing_ok=True)
    output.write_text(json.dumps({'command': [sys.executable, str(Path(__file__).resolve()),
                                 *sys.argv[1:]], 'bundle_command': command, 'cwd': str(root),
                                 'setup': 'Previously unused slot with temporary Config; actual installed bundle, 106 HD assets',
                                 'assertions': 'Directory/play/error/quit through real QLocalServer; child processes exit',
                                 'reset': 'Test instance config removed; packaged process and its children stopped',
                                 'checks': checks, 'errors': errors, 'exit_status': int(bool(errors))},
                                ensure_ascii=False, indent=2))
    print('PASS' if not errors else errors)
    return int(bool(errors))


if __name__ == '__main__':
    sys.exit(main())
