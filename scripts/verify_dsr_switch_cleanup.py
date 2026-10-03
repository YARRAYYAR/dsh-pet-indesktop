"""Real native action request must release the interrupted decoder."""
import json
from pathlib import Path
import tempfile
import time
import weakref

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from pet.app import AppShell
from pet.config import Config
from pet.settings_commands import SettingsCommandClient


def main():
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    assert app.platformName() == 'cocoa'
    config = Config(Path(tempfile.mkdtemp(prefix='dsr-switch-')))
    config.data.update({'no_move': True, 'mouse_through': True, 'harness_autostart': False,
                        'self_talk_enabled': False, 'click_sound_enabled': False})
    config.save()
    shell = AppShell(app, config, enable_chat=False)
    shell.start()
    client = SettingsCommandClient(config)
    checks, errors = {}, []
    previous = shell.win.movie
    previous_queue = weakref.ref(previous._queue)
    release_started = 0.0

    def finish():
        Path('docs/evidence/dsr-pet/switch-cleanup.json').write_text(json.dumps({
            'command': 'QT_QPA_PLATFORM=cocoa PYTHONPATH=. .venv/bin/python scripts/verify_dsr_switch_cleanup.py',
            'setup': 'Temporary Config; native main window; actual 106 HD assets; real QLocalServer request',
            'reset': 'Fresh temporary configuration; QApplication shutdown releases services',
            'assertions': 'Successful play stops the interrupted clip/timer and releases its queued buffers; new clip runs',
            'checks': checks, 'errors': errors, 'exit_status': 1 if errors else 0,
        }, ensure_ascii=False, indent=2))
        app.exit(1 if errors else 0)

    def played(response):
        nonlocal release_started
        release_started = time.monotonic()
        checks['response'] = response
        QTimer.singleShot(300, check_release)

    def check_release():
        checks['previous_running'] = previous._running
        checks['previous_timer_active'] = previous._timer.isActive()
        checks['current_running'] = shell.win.movie._running
        checks['current_action'] = shell.win.anim
        with previous._queue.mutex:
            checks['previous_queued_bytes'] = sum(len(item[0]) for item in previous._queue.queue
                                                 if isinstance(item, tuple) and isinstance(item[0], bytes))
        checks['original_queue_released'] = previous_queue() is None
        original = previous_queue()
        if original is not None:
            with original.mutex:
                checks['original_queued_bytes'] = sum(len(item[0]) for item in original.queue
                                                     if isinstance(item, tuple) and isinstance(item[0], bytes))
        else:
            checks['original_queued_bytes'] = 0
        checks['retired_reader_alive'] = [reader.thread.is_alive() for reader in previous._retired]
        checks['release_ms'] = (time.monotonic() - release_started) * 1000
        if checks['original_queued_bytes'] and any(checks['retired_reader_alive']) and checks['release_ms'] < 3000:
            QTimer.singleShot(100, check_release)
            return  # The reader owns its abandoned queue until bounded process cleanup finishes.
        if not checks['response']['ok'] or checks['previous_running'] or checks['previous_timer_active']:
            errors.append('Interrupted previous decoder or timer remained active')
        if checks['previous_queued_bytes'] or checks['original_queued_bytes']:
            errors.append('Interrupted decoder retained its queued frame buffers')
        if not checks['current_running']:
            errors.append('New action did not remain running')
        finish()

    QTimer.singleShot(3000, lambda: client.request('play_action', {'name': '点击回应-元气挥手'}, played))
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
