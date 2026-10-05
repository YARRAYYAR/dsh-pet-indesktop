"""seeky.7 real Qt/Cocoa acceptance; exclusively uses temporary configuration."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('PYTHON_KEYRING_BACKEND', 'keyring.backends.null.Keyring')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--suite', choices=('navigation', 'save', 'all'), default='all')
    parser.add_argument('--allow-offscreen', action='store_true')
    parser.add_argument('--idle-seconds', type=float, default=30)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    from PySide6 import __version__
    from PySide6.QtCore import QAbstractAnimation, QEvent, QEventLoop, QPoint, Qt, QTimer, QVariantAnimation
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton
    from pet import autostart
    from pet.config import Config
    from pet.modern_settings_dialog import ModernSettingsDialog
    import psutil

    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    report = {'command': [sys.executable, *sys.argv], 'cwd': str(Path.cwd()), 'python': sys.version,
              'pyside': __version__, 'platform': app.platformName(),
              'setup': 'temporary Config; no installed app/config writes; autostart disabled',
              'inputs': 'actual Qt mouse/key events, repeated label/disclosure, real disk replacement failure, missing IPC endpoint, 30s idle',
              'checks': [], 'captures': [], 'errors': [], 'exit_status': 1}

    def pump(ms):
        loop = QEventLoop()
        QTimer.singleShot(max(1, round(ms)), loop.quit)
        loop.exec()

    def wait(predicate, timeout=8000):
        deadline = time.monotonic() + timeout / 1000
        while not predicate() and time.monotonic() < deadline:
            pump(20)
        assert predicate(), 'Qt event condition timeout'

    def capture(dialog, name):
        path = args.output / f'{name}.png'
        assert dialog.grab().save(str(path))
        report['captures'].append({'path': str(path), 'logical_size': [dialog.width(), dialog.height()],
                                   'dpr': dialog.devicePixelRatioF()})

    def check(name, run):
        try:
            run()
            report['checks'].append({'name': name, 'passed': True})
        except Exception:
            report['checks'].append({'name': name, 'passed': False})
            report['errors'].append(traceback.format_exc())

    try:
        assert args.allow_offscreen or app.platformName() == 'cocoa'
        with tempfile.TemporaryDirectory(prefix='seeky7-settings-') as data:
            config = Config(Path(data))
            config.data.update({'no_move': True, 'show_dock_icon': False, 'harness_autostart': False,
                                'click_sound_enabled': False, 'collision_sound_enabled': False,
                                'self_talk_enabled': False, 'codex_link_enabled': False})
            config.save()
            autostart.is_enabled = lambda: False
            dialog = ModernSettingsDialog(config, include_ai=False, standalone=True)
            dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
            dialog.show()
            dialog.activateWindow()
            pump(250)
            def pane(label):
                return next(dialog.sidebar.itemWidget(dialog.sidebar.item(i)) for i in range(dialog.sidebar.count())
                            if dialog.sidebar.item(i).text() == label)
            pet = pane('桌宠')
            if args.suite in ('navigation', 'all'):
                def compact():
                    sidebar = dialog.sidebar.parentWidget()
                    assert sidebar.width() == 200
                    assert sidebar.layout().contentsMargins().top() == 12
                    assert sidebar.layout().spacing() == 6
                    assert dialog.findChild(type(dialog.search_status), 'brandLogo').width() == 28
                    QTest.mouseClick(pet.heading, Qt.MouseButton.LeftButton)
                    pump(200)
                    assert pet.heading.height() == 32
                    assert all(button.height() == 28 for button in pet.children.findChildren(QPushButton))
                    assert dialog.search_edit.height() == 32
                    capture(dialog, 'compact-geometry')
                check('compact logical tokens 200/28/12/6/32/28/32', compact)
                def disclosure():
                    QTest.mouseClick(pet.heading, Qt.MouseButton.LeftButton)
                    QTest.mouseClick(pet.heading, Qt.MouseButton.LeftButton)
                    assert pet.children.isVisible()
                    QTest.mouseClick(pet.disclosure, Qt.MouseButton.LeftButton)
                    assert not pet.children.isVisible()
                    QTest.mouseClick(pet.heading, Qt.MouseButton.LeftButton)
                    assert not pet.children.isVisible()
                    pane('菜单').heading.click()
                    pet.heading.click()
                    assert not pet.children.isVisible()
                    QTest.keyClick(pet.heading, Qt.Key.Key_Right)
                    assert pet.children.isVisible()
                    capture(dialog, 'independent-disclosure')
                check('label retains independent arrow expansion', disclosure)
                def keyboard():
                    QTest.mouseClick(pet.heading, Qt.MouseButton.LeftButton)
                    assert pet.heading.hasFocus() and not pet.heading.property('keyboardFocus')
                    QTest.keyClick(pet.heading, Qt.Key.Key_Down)
                    assert QApplication.focusWidget() is pet.disclosure
                    QTest.keyClick(pet.disclosure, Qt.Key.Key_Tab)
                    child = pet.children.findChildren(QPushButton)[0]
                    assert QApplication.focusWidget() is child
                    assert child.property('keyboardFocus')
                    QTest.keyClick(child, Qt.Key.Key_Down)
                    active = QApplication.focusWidget()
                    QTest.keyClick(active, Qt.Key.Key_Return)
                    assert active.isChecked()
                    QTest.keyClick(active, Qt.Key.Key_Return)
                    assert active.isChecked()
                    dialog.resize(720, 500)
                    pump(100)
                    pane('常规').heading.setFocus(Qt.FocusReason.TabFocusReason)
                    last = pane('语音').heading
                    for _ in range(64):
                        focused = QApplication.focusWidget()
                        if focused is last:
                            break
                        QTest.keyClick(focused, Qt.Key.Key_Down)
                    assert QApplication.focusWidget() is last
                    top = last.mapTo(dialog.sidebar.viewport(), QPoint(0, 0)).y()
                    assert 0 <= top and top + last.height() <= dialog.sidebar.viewport().height()
                    capture(dialog, 'keyboard-scroll-last-row')
                    dialog.resize(1000, 680)
                    capture(dialog, 'keyboard-focus')
                check('mouse focus retained; keyboard arrows Tab Enter activation', keyboard)
                def motion():
                    from pet.ui_motion import reduced_motion_requested
                    report['reduced_motion'] = reduced_motion_requested()
                    pane('常规').heading.click()
                    pump(260)
                    QTest.mousePress(pet.heading, Qt.MouseButton.LeftButton)
                    pump(35)
                    assert pet.heading._paint_scale < 1
                    QTest.mouseRelease(pet.heading, Qt.MouseButton.LeftButton)
                    pump(40)
                    if not report['reduced_motion']:
                        assert pet.heading._icon_scale > 1
                    assert dialog._navigation_pill._motion.duration() == 160
                    assert dialog._page_transition.duration() == 120
                    pump(300)
                    assert pet.heading._icon_scale == 1
                    pet.heading.click()
                    assert pet.heading._icon_bounce.state() == QAbstractAnimation.State.Stopped
                    QApplication.sendEvent(pet.heading, QEvent(QEvent.Type.Enter))
                    dialog.hide()
                    assert all(a.state() == QAbstractAnimation.State.Stopped for a in dialog.findChildren(QVariantAnimation))
                    dialog.show()
                    capture(dialog, 'motion-settled')
                check('finite painted feedback; true selection bounce; hide stops', motion)
                def idle():
                    QTest.mouseMove(dialog, QPoint(dialog.width() - 15, 15))
                    pump(300)
                    animations = dialog.findChildren(QVariantAnimation)
                    wait(lambda: all(a.state() == QAbstractAnimation.State.Stopped for a in animations))
                    process = psutil.Process()
                    cpu = sum(process.cpu_times()[:2])
                    rss = process.memory_info().rss
                    start = time.monotonic()
                    pump(args.idle_seconds * 1000)
                    running = sum(a.state() == QAbstractAnimation.State.Running for a in animations)
                    report['idle'] = {'seconds': round(time.monotonic() - start, 3),
                                      'cpu_seconds': round(sum(process.cpu_times()[:2]) - cpu, 4),
                                      'rss_before': rss, 'rss_after': process.memory_info().rss, 'running_animations': running,
                                      'active': [{'parent': type(a.parent()).__name__, 'object': a.parent().objectName(), 'duration': a.duration(), 'time': a.currentTime(), 'value': str(a.currentValue())} for a in animations if a.state() == QAbstractAnimation.State.Running]}
                    assert running == 0
                check('idle has no running animations', idle)
            if args.suite in ('save', 'all'):
                def failed_disk():
                    original = config.path
                    blocked = config.dir / 'save-is-directory.json'
                    blocked.mkdir()
                    config.path = blocked
                    boxes = []
                    timer = QTimer()
                    timer.setInterval(10)
                    def dismiss():
                        modal = QApplication.activeModalWidget()
                        if isinstance(modal, QMessageBox):
                            boxes.append(modal.text())
                            modal.grab().save(str(args.output / f'save-error-{len(boxes)}.png'))
                            modal.accept()
                    timer.timeout.connect(dismiss)
                    timer.start()
                    try:
                        QTest.keyClick(dialog, Qt.Key.Key_Escape)
                        assert dialog.isVisible()
                        dialog.close()
                        assert dialog.isVisible()
                        QTest.mouseClick(dialog.quit_button, Qt.MouseButton.LeftButton)
                        assert dialog.isVisible() and dialog.quit_button.isEnabled()
                        assert len(boxes) == 3
                        assert dialog.footer_status.isVisible() and '保存' in dialog.footer_status.text()
                        capture(dialog, 'all-save-paths-retain-window')
                    finally:
                        timer.stop()
                        config.path = original
                check('real disk failure X/Esc/quit retains window', failed_disk)
                def quit_retry():
                    assert dialog.quit_button.text() == '退出软件'
                    assert dialog.save_exit_button is dialog.quit_button
                    external = json.loads(config.path.read_text())
                    external['screen_name'] = 'retain'
                    config.path.write_text(json.dumps(external))
                    QTest.mouseClick(dialog.quit_button, Qt.MouseButton.LeftButton)
                    wait(lambda: dialog.quit_button.isEnabled())
                    assert dialog.isVisible() and dialog.footer_status.isVisible()
                    assert '连接' in dialog.footer_status.text()
                    assert json.loads(config.path.read_text())['screen_name'] == 'retain'
                    capture(dialog, 'quit-connection-retry')
                check('one quit button saves/rereads; missing actual IPC endpoint retry', quit_retry)
                def escape_success():
                    QTest.keyClick(dialog, Qt.Key.Key_Escape)
                    assert not dialog.isVisible()
                check('successful Esc saves and closes', escape_success)
            dialog.command_client.close()
            dialog.deleteLater()
            pump(20)
        report['exit_status'] = 0 if all(check['passed'] for check in report['checks']) else 1
    except Exception:
        report['errors'].append(traceback.format_exc())
    finally:
        (args.output / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    return report['exit_status']


if __name__ == '__main__':
    raise SystemExit(main())
