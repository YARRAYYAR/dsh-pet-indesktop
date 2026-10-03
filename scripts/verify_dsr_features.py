"""Native Cocoa ceiling, Codex event adapter and connection-page evidence."""
import json
from datetime import datetime, timezone
import os
from pathlib import Path
import statistics
import tempfile
import time

from PySide6.QtCore import QRect, QTimer, Qt
from PySide6.QtWidgets import QApplication

from pet.app import AppShell
from pet.codex_link import CodexMonitor
from pet.config import Config
from pet.modern_settings_dialog import ModernSettingsDialog


def main():
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    assert app.platformName() == 'cocoa'
    output = Path('docs/evidence/dsr-pet')
    output.mkdir(parents=True, exist_ok=True)
    fixture = Path(tempfile.mkdtemp(prefix='dsr-codex-events-'))
    day = fixture / 'sessions' / datetime.now(timezone.utc).strftime('%Y/%m/%d')
    day.mkdir(parents=True)
    events_path = day / 'rollout-verification.jsonl'
    events_path.write_text(json.dumps({'type': 'session_meta', 'payload': {'id': 'verification', 'cwd': '/work/Native verification'}}) + '\n')
    real_monitor = CodexMonitor()
    scan_started = time.perf_counter()
    real_monitor.start()
    scan_ms = (time.perf_counter() - scan_started) * 1000
    real_state = real_monitor.snapshot()
    costs = []
    for _ in range(100):
        started = time.perf_counter()
        real_monitor.poll()
        costs.append((time.perf_counter() - started) * 1000)
    real_monitor.stop()
    os.environ['CODEX_HOME'] = str(fixture)
    config = Config(Path(tempfile.mkdtemp(prefix='dsr-features-')))
    config.data.update({'codex_link_enabled': True, 'no_move': True, 'harness_autostart': False,
                        'self_talk_enabled': False, 'click_sound_enabled': False})
    config.save()
    shell = AppShell(app, config, enable_chat=False)
    shell.start()
    window = shell.win
    window.setWindowFlag(Qt.WindowType.WindowTransparentForInput, True)
    window.show()
    captured = []
    window._codex_link.event.connect(lambda event: captured.append({k: event[k] for k in ('state', 'text')}))
    checks = {}
    errors = []
    dialog = None
    finish_attempts = 0

    def guarded(callback):
        def run():
            try:
                callback()
            except Exception as exc:
                import traceback
                traceback.print_exc()
                errors.append(str(exc))
                app.quit()
        return run

    def append(record):
        with events_path.open('a') as stream:
            stream.write(json.dumps(record) + '\n')

    def ceiling():
        body = window._stable_body_local_rect()
        screen = window._screen_available()
        x = screen.availableGeometry().center().x() - body.center().x()
        window._move_window_towards(x, screen.geometry().top() - body.top())
        checks['ceiling_angle'] = window._effects_current_angle()
        checks['ceiling_x_preserved'] = window._virtual_pos().x() == x
        checks['ceiling_timer_stopped'] = not window._top_flip._timer.isActive()
        assert checks['ceiling_angle'] == 180
        assert checks['ceiling_x_preserved']
        visible = window.geometry().intersected(screen.geometry()).translated(-window.pos())
        dpr = window.devicePixelRatioF()
        physical = QRect(round(visible.x() * dpr), round(visible.y() * dpr),
                         round(visible.width() * dpr), round(visible.height() * dpr))
        window.grab().copy(physical).save(str(output / 'ceiling-inverted.png'))
        checks['visible_ceiling_window_height'] = visible.height()
        window._move_window_towards(x, screen.geometry().top() - body.top() + 220)
        checks['drag_down_angle'] = window._effects_current_angle()
        assert checks['drag_down_angle'] == 0
        window.grab().save(str(output / 'ceiling-restored.png'))

    def question():
        checks['custom_tool_working'] = window.codex_status()['state'] == 'working'
        assert checks['custom_tool_working'], 'Codex custom_tool_call did not show active work'
        append({'type': 'response_item', 'payload': {'type': 'function_call', 'name': 'request_user_input_async',
                'call_id': 'verification-question', 'arguments': json.dumps({'questions': [{'title': '联动验收：选择灰色还是蓝色？'}]})}})

    def capture_question():
        checks['question_sticky'] = window._sticky_bubble_active
        checks['question_button'] = window._alert_current['buttons'][0][0]
        assert checks['question_sticky']
        assert checks['question_button'] == '打开 Codex'
        window._speech_bubble.grab().save(str(output / 'codex-question-bubble.png'))
        config.data['codex_link_enabled'] = False
        window.sync_codex_link()
        checks['disabled_question_cleared'] = not window._sticky_bubble_active
        checks['disabled_polling_stopped'] = not window._codex_link.timer.isActive()
        assert checks['disabled_question_cleared'], 'Disabling Codex left its question bubble visible'
        assert checks['disabled_polling_stopped']
        config.data['codex_link_enabled'] = True
        window.sync_codex_link()

    def complete():
        append({'type': 'event_msg', 'payload': {'type': 'user_message', 'message': '灰色'}})
        append({'type': 'event_msg', 'payload': {'type': 'task_complete', 'last_agent_message': '联动验收：本轮工作完成。'}})

    def connection():
        nonlocal dialog
        checks['completion_not_sticky'] = not window._sticky_bubble_active
        assert checks['completion_not_sticky']
        window._speech_bubble.grab().save(str(output / 'codex-complete-bubble.png'))
        dialog = ModernSettingsDialog(config, include_ai=False, standalone=True)
        dialog.setWindowFlag(Qt.WindowType.WindowTransparentForInput, True)
        dialog.show()
        dialog.sidebar.setCurrentRow(next(i for i in range(dialog.sidebar.count()) if dialog.sidebar.item(i).text() == '连接'))

    def finish():
        nonlocal finish_attempts
        if '本轮已完成' not in dialog.codex_page.status.text():
            finish_attempts += 1
            if finish_attempts > 60:
                raise AssertionError(f'Codex status did not arrive: {dialog.codex_page.status.text()}')
            QTimer.singleShot(200, guarded(finish))
            return
        dialog.grab().save(str(output / 'settings-codex.png'))
        dialog.resize(720, 500)
        app.processEvents()
        dialog.grab().save(str(output / 'settings-codex-minimum.png'))
        dialog.close()
        app.quit()

    for delay, callback in ((3000, ceiling), (4000, lambda: append({'type': 'response_item', 'payload': {
                                'type': 'custom_tool_call', 'name': 'functions.exec', 'input': 'local verification fixture'}})),
                            (5500, question), (7200, capture_question), (8000, complete), (10000, connection), (12500, finish)):
        QTimer.singleShot(delay, guarded(callback))
    app.exec()
    checks['codex_events'] = captured
    checks['real_local_codex_state'] = {key: real_state[key] for key in ('state', 'session_id', 'project')}
    checks['poll_100_calls_median_ms'] = statistics.median(costs)
    checks['poll_100_calls_max_ms'] = max(costs)
    checks['initial_local_discovery_ms'] = scan_ms
    (output / 'native-features.json').write_text(json.dumps({
        'command': 'QT_QPA_PLATFORM=cocoa PYTHONPATH=. .venv/bin/python scripts/verify_dsr_features.py',
        'setup': 'Temporary Config and CODEX_HOME; real main window and QLocalServer; no user configuration writes',
        'reset': 'Fresh temporary directories on each run; QApplication shutdown closes services',
        'platform': app.platformName(), 'dpr': window.devicePixelRatioF(),
        'codex_events_are_local_fixture': True, 'checks': checks, 'errors': errors,
        'exit_status': 1 if errors else 0}, ensure_ascii=False, indent=2))
    if errors:
        raise RuntimeError(errors)


if __name__ == '__main__':
    main()
