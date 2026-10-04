"""Cocoa settings captures and the real AppShell action command flow.

Use --phase baseline before changing product code. --live starts an isolated
AppShell with temporary configuration; it never touches the installed app.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('PYTHON_KEYRING_BACKEND', 'keyring.backends.null.Keyring')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--phase', choices=('baseline', 'after'), default='after')
    parser.add_argument('--live', action='store_true')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    from PySide6 import __version__ as qt_version
    from PySide6.QtCore import QAbstractAnimation, QEvent, QEventLoop, QPoint, Qt, QTimer, QVariantAnimation
    from PySide6.QtGui import QPalette
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton, QScrollArea, QWidget
    from pet import autostart
    from pet.config import Config
    from pet.modern_settings_dialog import ModernSettingsDialog
    from pet.settings_widgets import SettingsTabContainer
    from pet.settings_actions import ActionLibrary
    import psutil

    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    report = {'command': [sys.executable, *sys.argv], 'cwd': str(Path.cwd()),
              'python': sys.version, 'pyside': qt_version, 'platform': app.platformName(),
              'phase': args.phase, 'live': args.live, 'setup': 'temporary isolated Config, pure build, sound/link/autostart disabled',
              'inputs': 'domain navigation; all subtask pages; 720x500/1000x680/1100x760; 125% fonts; actual action request when --live',
              'assertions': [], 'captures': [], 'errors': [], 'exit_status': 1}
    shell = None
    dialog = None

    def pump(milliseconds):
        loop = QEventLoop()
        timer = QTimer()
        timer.setTimerType(Qt.TimerType.PreciseTimer)
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        timer.start(milliseconds)
        loop.exec()

    def wait(predicate, timeout=8000):
        if predicate():
            return
        # exec() lets Python decoder threads run while Qt pumps native events.
        loop = QEventLoop()
        check = QTimer()
        check.setTimerType(Qt.TimerType.PreciseTimer)
        check.setInterval(15)
        check.timeout.connect(lambda: loop.quit() if predicate() else None)
        deadline = QTimer()
        deadline.setTimerType(Qt.TimerType.PreciseTimer)
        deadline.setSingleShot(True)
        deadline.timeout.connect(loop.quit)
        check.start()
        deadline.start(timeout)
        loop.exec()
        check.stop()
        deadline.stop()
        if not predicate():
            if shell is not None and shell.win is not None:
                win = shell.win
                movie = win.movie
                library = dialog.findChild(ActionLibrary)
                report['timeout_state'] = {'actual_current': win.anim, 'displayed_current': library._current,
                                           'actual_pending': win._pending_link_anim, 'queued': library._queued,
                                           'frame': movie.currentFrameNumber(), 'frame_count': movie.frameCount(),
                                           'duration': movie.duration(), 'timer_active': movie._timer.isActive(),
                                           'hidden_paused': win._hidden_paused, 'pet_visible': win.isVisible(),
                                           'library_visible': library.isVisible(), 'requests': list(library._requests),
                                           'sidebar_row': dialog.sidebar.currentRow()}
            raise AssertionError('event-loop condition timed out')

    def capture(name):
        pump(170)
        target = args.output / f'{name}.png'
        assert dialog.grab().save(str(target))
        sidebar = dialog.sidebar.parentWidget()
        report['captures'].append({'path': str(target), 'logical_size': [dialog.width(), dialog.height()],
                                   'dpr': dialog.devicePixelRatioF(), 'sidebar': list(sidebar.geometry().getRect()),
                                   'search': list(dialog.search_edit.geometry().getRect()),
                                   'save': list(dialog.save_exit_button.geometry().getRect()),
                                   'quit': list(dialog.quit_button.geometry().getRect()),
                                   'current_row': dialog.sidebar.currentRow(),
                                   'row_heights': [dialog.sidebar.item(i).sizeHint().height() for i in range(dialog.sidebar.count())]})

    def select_action(library, name):
        for index in range(library.list.count()):
            if library.list.item(index).data(Qt.ItemDataRole.UserRole) == name:
                library.list.setCurrentRow(index)
                library.list.scrollToItem(library.list.currentItem())
                return
        raise AssertionError(f'action not found: {name}')

    def contrast(foreground, background):
        def luminance(rgb):
            channels = [value / 255 for value in rgb[:3]]
            linear = [value / 12.92 if value <= .04045 else ((value + .055) / 1.055) ** 2.4
                      for value in channels]
            return sum(value * weight for value, weight in zip(linear, (.2126, .7152, .0722)))

        alpha = foreground[3] / 255 if len(foreground) == 4 else 1
        composed = [fg * alpha + bg * (1 - alpha) for fg, bg in zip(foreground[:3], background[:3])]
        light, dark = sorted((luminance(composed), luminance(background)), reverse=True)
        return {'foreground_rgba': list(foreground), 'background_rgb': list(background[:3]),
                'composited_rgb': composed, 'ratio': round((light + .05) / (dark + .05), 3)}

    def verify_contrast():
        library = dialog.findChild(ActionLibrary)
        values = {}
        report['contrast'] = {'method': 'WCAG sRGB relative luminance; alpha composited over actual surface before linearization',
                              'palette_samples': 'live QWidget palettes after native show/QSS polish', 'values': values}
        for name, widget in (('settings_search', dialog.search_edit), ('action_search', library.search)):
            palette = widget.palette()
            background = palette.color(QPalette.ColorRole.Base).getRgb()
            for role in (QPalette.ColorRole.Text, QPalette.ColorRole.PlaceholderText):
                values[f'{name}_{role.name}'] = contrast(palette.color(role).getRgb(), background)
                assert values[f'{name}_{role.name}']['ratio'] >= 4.5
        # Source colours at full-coverage stroke interiors; antialias edge pixels
        # blend with the surface and are not separate foreground colours.
        samples = {
            'sidebar_idle_text': ([255, 255, 255, round(255 * .78)], [20, 20, 22], 4.5),
            'brand_version': ([137, 137, 143], [20, 20, 22], 4.5),
            'setting_hint': ([160, 160, 167], [23, 23, 25], 4.5),
            'sidebar_idle_icon': ([255, 255, 255, round(255 * .62)], [20, 20, 22], 3),
            'sidebar_selected_icon': ([255, 255, 255, round(255 * .95)], [49, 49, 51], 3),
            'action_play_icon': ([214, 214, 214], [44, 44, 46], 3),
            'sidebar_focus': ([185, 185, 194], [49, 49, 51], 3),
            'action_focus_hover': ([185, 185, 194], [81, 81, 85], 3),
            'search_focus': ([10, 132, 255], [41, 41, 43], 3),
        }
        for name, (foreground, background, threshold) in samples.items():
            values[name] = contrast(foreground, background)
            values[name]['threshold'] = threshold
            assert values[name]['ratio'] >= threshold
        report['assertions'].append('readable text and native placeholder >=4.5:1; focus and required icon source strokes >=3:1')

    try:
        assert app.platformName() == 'cocoa', 'native Cocoa required'
        with tempfile.TemporaryDirectory(prefix='seeky-settings-ui-') as data:
            config = Config(Path(data))
            config.data.update({'no_move': True, 'mouse_through': True, 'cursor_hidden_passthrough': False,
                                'self_talk_enabled': False, 'codex_link_enabled': False,
                                'harness_autostart': False, 'top_flip_enabled': False,
                                'click_sound_enabled': False, 'collision_sound_enabled': False,
                                'show_dock_icon': False, 'scale': .3})
            config.save()
            autostart.is_enabled = lambda: False
            if args.live:
                from pet.app import AppShell
                shell = AppShell(app, config, enable_chat=False, slot_id=0)
                shell.start()
            dialog = ModernSettingsDialog(config, include_ai=False, standalone=True)
            dialog.show()
            dialog.activateWindow()
            pump(250)
            if args.phase == 'after':
                verify_contrast()
            domains = [dialog.sidebar.item(i).text() for i in range(dialog.sidebar.count())]
            assert domains == ['常规', '桌宠', '互动', '菜单', '连接', '自动化与联动', '语音']
            report['assertions'].append('seven domain labels/order unchanged; sidebar width 200')
            assert dialog.sidebar.parentWidget().width() == 200
            headings = dialog.findChildren(QPushButton, 'sidebarDomainHeading')
            target = next(button for button in headings if button.text().startswith('桌宠'))
            target.setFocus(Qt.FocusReason.OtherFocusReason)
            target.click()
            reused = dialog.findChildren(QPushButton, 'sidebarDomainHeading') == headings
            focused = QApplication.focusWidget() is target
            report['navigation_reused'] = reused
            report['navigation_focus_preserved'] = focused
            if args.phase == 'after':
                assert reused and focused
                report['assertions'].append('domain buttons reused and keyboard focus preserved')
                QTest.keyClick(target, Qt.Key.Key_Left)
                assert not target.isChecked()
                QTest.keyClick(target, Qt.Key.Key_Right)
                assert target.isChecked()
                subtask = next(button for button in dialog.findChildren(QPushButton, 'sidebarSubtask')
                               if button.text() == '动作库')
                subtask.setFocus()
                QTest.keyClick(subtask, Qt.Key.Key_Space)
                assert dialog.pet_tabs.currentKey() == 'actions'
                capture('keyboard-action-tab-focus')
                QTest.keyClick(subtask, Qt.Key.Key_Tab)
                assert QApplication.focusWidget() is not subtask
                report['assertions'].append('keyboard Left/Right disclosure, Space task selection and Tab navigation')
            for width, height, scale in ((720, 500, 1), (1000, 680, 1), (1100, 760, 1), (720, 500, 1.25)):
                dialog.resize(width, height)
                if scale != 1:
                    for widget in (dialog, *dialog.findChildren(QWidget)):
                        font = widget.font()
                        if font.pixelSize() > 0:
                            font.setPixelSize(round(font.pixelSize() * scale))
                            widget.setFont(font)
                for index, label in enumerate(domains):
                    heading = next(button for button in headings if button.text().startswith(label))
                    heading.setFocus()
                    dialog.sidebar.setCurrentRow(index)
                    if heading.isCheckable():
                        heading.setChecked(True)
                    page = dialog.pages.currentWidget()
                    for scroll in page.findChildren(QScrollArea):
                        scroll.verticalScrollBar().setValue(0)
                        assert scroll.horizontalScrollBar().maximum() == 0
                    capture(f'{width}x{height}-font{round(scale*100)}-{index+1}-{label}')
                    tabs = page.findChildren(SettingsTabContainer)
                    if tabs:
                        for key, title in zip(tabs[0].keys(), tabs[0].labels()):
                            tabs[0].setCurrentKey(key)
                            capture(f'{width}x{height}-font{round(scale*100)}-{index+1}-{title}')
                            if args.phase == 'after' and title == '动作库':
                                assert dialog.sidebar.currentRow() == index and page.isVisible()
                                library = dialog.findChild(ActionLibrary)
                                scroll = page.findChild(QScrollArea)
                                scroll.ensureWidgetVisible(library.play)
                                pump(30)
                                play_top = library.play.mapTo(scroll.viewport(), QPoint()).y()
                                assert 0 <= play_top and play_top + library.play.height() <= scroll.viewport().height()
                                assert scroll.horizontalScrollBar().maximum() == 0
                                if height >= 680:
                                    assert scroll.verticalScrollBar().maximum() == 0
                                report.setdefault('action_layout', []).append({
                                    'window': [width, height], 'font_percent': round(scale*100),
                                    'content_height': library.height(), 'play_top': play_top,
                                    'play_height': library.play.height(), 'viewport_height': scroll.viewport().height(),
                                    'page_scroll': scroll.verticalScrollBar().value()})
                                capture(f'{width}x{height}-font{round(scale*100)}-action-footer')
                        tabs[0].setCurrentIndex(0)
                assert dialog.quit_button.mapTo(dialog, QPoint()).y() + dialog.quit_button.height() <= dialog.height()
            if args.live:
                dialog.resize(1000, 680)
                target.setFocus()
                dialog.sidebar.setCurrentRow(domains.index('桌宠'))
                page = dialog.pages.currentWidget()
                tabs = page.findChild(SettingsTabContainer)
                tabs.setCurrentKey(next(key for key, label in zip(tabs.keys(), tabs.labels()) if label == '动作库'))
                library = dialog.findChild(ActionLibrary)
                wait(lambda: library.list.count() > 0)
                assert library.list.count() == len(shell.win.lib.names())
                first, chosen = '点击回应-元气挥手', '点击回应-傲娇生气'
                quality_path = Path(__file__).resolve().parents[1] / 'assets/characters_hq/shenshen/videos/quality-index.json'
                quality = json.loads(quality_path.read_text())['clips']
                report['action_sources'] = {name: {key: quality[f'click/{name}.webm'][key]
                                                  for key in ('frames', 'duration', 'fps')}
                                            for name in (first, chosen)}
                assert first != chosen
                library.search.setText(first)
                assert library.list.count() >= 1
                assert all(first.casefold() in library.list.item(i).data(Qt.ItemDataRole.UserRole).casefold()
                           for i in range(library.list.count()))
                library.search.clear()
                select_action(library, first)
                library.play.click()
                assert '请求中' in library.status.text() and not library.play.isEnabled()
                wait(lambda: shell.win.anim == first and library._current == first, timeout=30000)
                wait(lambda: library.play.isEnabled())
                replay_serial = getattr(library, '_watch_serial', None)
                library.play.click()
                wait(lambda: library.play.isEnabled())
                report['same_action_replay_queued'] = {'actual_current': shell.win.anim,
                                                       'actual_pending': shell.win._pending_link_anim,
                                                       'displayed_current': library._current,
                                                       'queued': library._queued,
                                                       'watch_serial_before': replay_serial,
                                                       'watch_serial_after': getattr(library, '_watch_serial', None)}
                capture('live-current-replay-queued')
                assert shell.win.anim == first and shell.win._pending_link_anim == first
                assert library._queued == first
                assert '正在播放' in library.list.currentItem().text() and '已排队' in library.list.currentItem().text()
                wait(lambda: library._watch_serial > replay_serial and library._current == first and not library._queued,
                     timeout=30000)
                assert shell.win.anim == first and shell.win._pending_link_anim is None
                report['same_action_replay_started'] = {'actual_current': shell.win.anim,
                                                        'actual_pending': shell.win._pending_link_anim,
                                                        'displayed_current': library._current,
                                                        'queued': library._queued,
                                                        'watch_serial': library._watch_serial}
                capture('live-current-replay-started')
                report['assertions'].append('replaying current one-shot shows playing and queued together; next same-name watch event clears queue')
                select_action(library, chosen)
                before_scroll = library.list.verticalScrollBar().value()
                library.play.click()
                assert '请求中' in library.status.text() and not library.play.isEnabled()
                wait(lambda: library.play.isEnabled())
                assert library._queued == chosen
                assert shell.win._pending_link_anim == chosen and shell.win.anim == first
                report['queue_observation'] = {'selected': chosen, 'queued': library._queued,
                                               'actual_pending': shell.win._pending_link_anim,
                                               'displayed_current': library._current, 'actual_current': shell.win.anim}
                capture('live-action-queued')
                dialog.resize(720, 500)
                scroll = page.findChild(QScrollArea)
                scroll.ensureWidgetVisible(library.play)
                pump(30)
                play_top = library.play.mapTo(scroll.viewport(), QPoint()).y()
                assert 0 <= play_top and play_top + library.play.height() <= scroll.viewport().height()
                assert scroll.horizontalScrollBar().maximum() == 0
                report['narrow_real_queue_layout'] = {'window': [dialog.width(), dialog.height()], 'font_percent': 125,
                                                      'play_top': play_top, 'play_height': library.play.height(),
                                                      'viewport_height': scroll.viewport().height(),
                                                      'page_scroll': scroll.verticalScrollBar().value()}
                capture('live-720-font125-action-queued-footer')
                dialog.resize(1000, 680)
                pump(30)
                assert library.list.currentItem().data(Qt.ItemDataRole.UserRole) == chosen
                assert library.list.verticalScrollBar().value() == before_scroll
                wait(lambda: shell.win.anim == chosen and library._current == chosen, timeout=30000)
                assert library._queued == ''
                assert '正在播放' in library.list.currentItem().text()
                capture('live-action-request')
                library.refresh.click()
                wait(lambda: library.refresh.isEnabled())
                assert library.list.currentItem().data(Qt.ItemDataRole.UserRole) == chosen
                assert library.list.verticalScrollBar().value() == before_scroll
                report['assertions'].append('real AppShell list/search/play/queue/watch IPC; selection/scroll retained; displayed queue and current match pet')
                old_server = shell.instance.settings_commands
                old_server.close()
                library.refresh.click()
                wait(lambda: library.refresh.isEnabled() and '无法连接' in library.status.text())
                wait(lambda: library._current == '')
                assert library.play.isEnabled()
                capture('live-disconnected-retry')
                report['assertions'].append('actual command server disconnect clears current, shows connection error and keeps retry available')
                from pet.settings_commands import SettingsCommandServer
                old_server.deleteLater()
                controller = shell.instance
                controller.settings_commands = SettingsCommandServer(config, controller._dispatch_settings_command, app)
                shell.win.action_changed.connect(controller.settings_commands.publish_action)
                library.refresh.click()
                wait(lambda: library.refresh.isEnabled() and library._watch_seen)
                retry = first if library._current != first else chosen
                select_action(library, retry)
                library.play.click()
                wait(lambda: shell.win.anim == retry and library._current == retry, timeout=30000)
                assert '正在播放' in library.list.currentItem().text()
                capture('live-reconnected-playback-watch')
                report['assertions'].append('restored actual server; Refresh reattaches watch and a new real playback push updates current')
            if args.phase == 'after':
                from pet.ui_motion import reduced_motion_requested
                report['native_reduced_motion'] = reduced_motion_requested()
                dialog.sidebar.setCurrentRow(domains.index('桌宠'))
                target.setFocus()
                QApplication.sendEvent(target, QEvent(QEvent.Type.Leave))
                pump(160)
                QApplication.sendEvent(target, QEvent(QEvent.Type.Enter))
                pump(35)
                midpoint = target._hover
                QApplication.sendEvent(target, QEvent(QEvent.Type.Leave))
                if not report['native_reduced_motion']:
                    assert 0 < midpoint < 1 and target._fade.startValue() == midpoint
                pump(160)
                assert target._hover == 0
                QTest.mousePress(target, Qt.MouseButton.LeftButton)
                pump(35)
                pressed = target._press
                QTest.mouseRelease(target, Qt.MouseButton.LeftButton)
                pump(180)
                assert target._press == 0
                report['motion'] = {'hover_midpoint': midpoint, 'press_midpoint': pressed,
                                    'durations_ms': [target._fade.duration(), target._selection_fade.duration(), target._press_fade.duration()]}
                capture('motion-selected-focus')
                QApplication.sendEvent(target, QEvent(QEvent.Type.Enter))
                dialog.hide()
                assert all(animation.state() == QAbstractAnimation.State.Stopped
                           for animation in dialog.findChildren(QVariantAnimation))
                dialog.show()
                report['assertions'].append('rapid hover reversal starts at rendered value; press settles; hidden window stops every state animation')
            animations = dialog.findChildren(QVariantAnimation)
            wait(lambda: all(animation.state() == QAbstractAnimation.State.Stopped for animation in animations))
            process = psutil.Process()
            cpu_before = sum(process.cpu_times()[:2])
            rss_before = process.memory_info().rss
            begin = time.monotonic()
            pump(2000)
            report['idle'] = {'seconds': round(time.monotonic()-begin, 3),
                              'cpu_seconds': round(sum(process.cpu_times()[:2])-cpu_before, 4),
                              'rss_before': rss_before, 'rss_after': process.memory_info().rss,
                              'running_animations': sum(animation.state() == QAbstractAnimation.State.Running for animation in animations)}
            assert report['idle']['running_animations'] == 0
            if args.phase == 'after':
                original_path = config.path
                blocked_path = config.dir / 'blocked-save.json'
                blocked_path.mkdir()
                config.path = blocked_path
                observed = []
                watcher = QTimer(dialog)
                watcher.setInterval(15)

                def dismiss_save_error():
                    modal = QApplication.activeModalWidget()
                    if isinstance(modal, QMessageBox):
                        observed.append({'title': modal.windowTitle(), 'text': modal.text()})
                        assert modal.grab().save(str(args.output / 'save-failure-dialog.png'))
                        watcher.stop()
                        modal.accept()

                watcher.timeout.connect(dismiss_save_error)
                watcher.start()
                dialog.save_exit_button.click()
                watcher.stop()
                config.path = original_path
                report['save_failure'] = observed
                assert len(observed) == 1 and '配置未能写入磁盘' in observed[0]['text']
                assert dialog.isVisible() and not getattr(dialog, '_saved_via_button', False)
                report['save_failure'] = observed[0]
                capture('save-failure-settings-stays-open')
                dialog.save_exit_button.click()
                assert not dialog.isVisible() and dialog._saved_via_button
                assert json.loads(original_path.read_text())['no_move'] is True
                report['assertions'].append('real disk replacement failure shows native save dialog and retains settings; restored destination saves and closes')
            else:
                dialog.close()
            app.processEvents()
            if shell is not None:
                children = psutil.Process().children(recursive=True)
                QTimer.singleShot(0, app.quit)
                app.exec()
                exited, alive = psutil.wait_procs(children, timeout=3)
                report['child_process_exit'] = {'observed_pids': [child.pid for child in children],
                                               'exited_pids': [child.pid for child in exited],
                                               'alive_pids': [child.pid for child in alive]}
                assert not alive
            report['exit_status'] = 0
    except Exception as exc:
        import traceback
        report['errors'].append(traceback.format_exc())
        print(type(exc).__name__, str(exc), flush=True)
        if dialog is not None:
            dialog.close()
        if shell is not None:
            QTimer.singleShot(0, app.quit)
            app.exec()
    finally:
        (args.output / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(json.dumps({key: report[key] for key in ('phase', 'live', 'assertions', 'idle', 'exit_status') if key in report}, ensure_ascii=False), flush=True)
    return report['exit_status']


if __name__ == '__main__':
    raise SystemExit(main())
