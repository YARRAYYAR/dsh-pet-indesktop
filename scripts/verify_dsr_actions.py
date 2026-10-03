"""Native settings/action flow across real main and settings processes."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QPushButton

from pet.config import Config

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / 'docs/evidence/dsr-pet'


def settings_flow(app, config):
    from pet.modern_settings_dialog import ModernSettingsDialog
    from pet.settings_actions import ActionLibrary

    dialog = ModernSettingsDialog(config, include_ai=False, standalone=True)
    dialog.setWindowFlag(Qt.WindowType.WindowTransparentForInput, True)
    dialog.show()
    library = dialog.findChild(ActionLibrary)
    checks, errors = {}, []
    finished = False
    encoder = subprocess.Popen([
        '/opt/homebrew/bin/ffmpeg', '-y', '-loglevel', 'error', '-f', 'rawvideo',
        '-pixel_format', 'rgba', '-video_size', '1000x680', '-framerate', '24',
        '-i', '-', '-an', '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '18',
        '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(OUTPUT / 'native-ui.mp4'),
    ], stdin=subprocess.PIPE)
    recorder = QTimer(app)

    def finish():
        nonlocal finished
        if finished:
            return
        finished = True
        recorder.stop()
        encoder.stdin.close()
        result = encoder.wait(15)
        if result:
            errors.append(f'Recording encoder exited {result}')
        (OUTPUT / 'native-ui.json').write_text(json.dumps({
            'command': 'QT_QPA_PLATFORM=cocoa PYTHONPATH=. .venv/bin/python scripts/verify_dsr_actions.py',
            'setup': 'Temporary Config, real main and separate settings process; 106 HD actions',
            'reset': 'Fresh temporary Config per run; input passes through verification windows',
            'platform': app.platformName(), 'dpr': dialog.devicePixelRatioF(),
            'checks': checks, 'errors': errors, 'exit_status': 1 if errors else 0,
        }, ensure_ascii=False, indent=2))
        dialog.close()
        app.exit(1 if errors else 0)

    def guarded(callback):
        def run():
            try:
                callback()
            except Exception as exc:
                import traceback
                traceback.print_exc()
                errors.append(str(exc) or type(exc).__name__)
                finish()
        return run

    def wait_for(predicate, callback, deadline, description):
        if predicate():
            callback()
        elif time.monotonic() >= deadline:
            raise AssertionError(description)
        else:
            QTimer.singleShot(20, guarded(lambda: wait_for(predicate, callback, deadline, description)))

    def record():
        image = dialog.grab().toImage().scaled(1000, 680).convertToFormat(QImage.Format.Format_RGBA8888)
        encoder.stdin.write(bytes(image.constBits()))

    recorder.timeout.connect(guarded(record))
    recorder.start(42)

    def pet():
        dialog.sidebar.setCurrentRow(next(i for i in range(dialog.sidebar.count())
                                          if dialog.sidebar.item(i).text() == '桌宠'))

    def actions():
        dialog.grab().save(str(OUTPUT / 'settings-pet.png'))
        next(button for button in dialog.findChildren(QPushButton, 'sidebarSubtask')
             if button.text() == '动作库').click()
        wait_for(lambda: len(library._actions) == 106, play, time.monotonic() + 15,
                 f'Action directory did not load: {library.status.text()}')

    def play():
        checks['actions'] = len(library._actions)
        dialog.grab().save(str(OUTPUT / 'settings-actions.png'))
        library.category.setCurrentData('click')
        library.search.setText('挥手')
        assert library.list.count() == 1
        checks['selected'] = library.list.item(0).data(Qt.ItemDataRole.UserRole)
        library.play.click()
        wait_for(lambda: library._current == checks['selected'], played,
                 time.monotonic() + 15, 'Requested action was never observed as current')

    def played():
        checks['status'] = library.status.text()
        checks['current'] = library._current
        dialog.grab().save(str(OUTPUT / 'settings-actions-playing.png'))
        QTimer.singleShot(2000, guarded(minimum))

    def minimum():
        dialog.resize(720, 500)
        QTimer.singleShot(500, guarded(capture_minimum))

    def capture_minimum():
        checks['minimum_footer_visible'] = dialog.quit_button.isVisible()
        checks['island_entry_absent'] = all(dialog.sidebar.item(i).text() != '桌面组件'
                                             for i in range(dialog.sidebar.count()))
        assert checks['minimum_footer_visible'] and checks['island_entry_absent']
        dialog.grab().save(str(OUTPUT / 'settings-actions-minimum.png'))
        QTimer.singleShot(1500, finish)

    QTimer.singleShot(500, guarded(lambda: dialog.grab().save(str(OUTPUT / 'settings-general.png'))))
    QTimer.singleShot(1000, guarded(pet))
    QTimer.singleShot(2000, guarded(actions))
    return app.exec()


def main():
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    assert app.platformName() == 'cocoa'
    OUTPUT.mkdir(parents=True, exist_ok=True)
    child_mode = '--child' in sys.argv
    base = Path(sys.argv[2]) if child_mode else Path(tempfile.mkdtemp(prefix='dsr-native-'))
    config = Config(base)
    if child_mode:
        return settings_flow(app, config)

    from pet.app import AppShell
    config.data.update({'no_move': True, 'idle_low_fps_enabled': False, 'self_talk_enabled': False,
                        'harness_autostart': False, 'click_sound_enabled': False,
                        'collision_sound_enabled': False, 'dynamic_island': {'enabled': True}})
    config.save()
    shell = AppShell(app, config, enable_chat=False)
    shell.start()
    shell.win.setWindowFlag(Qt.WindowType.WindowTransparentForInput, True)
    shell.win.show()

    def launch():
        child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--child', str(base)])

        def poll():
            if child.poll() is not None:
                print('settings child exit', child.returncode, flush=True)
                app.exit(child.returncode)
            else:
                QTimer.singleShot(200, poll)
        poll()

    QTimer.singleShot(2000, launch)
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
