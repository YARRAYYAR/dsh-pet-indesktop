"""Cocoa E2E: task appearance from settings through persisted config to Codex alerts."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import statistics
import sys
import tempfile
import time

import psutil
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QPushButton, QScrollArea, QSpinBox

from pet.app import AppShell
from pet.config import Config
from pet.modern_settings_dialog import ModernSettingsDialog


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--label', default='task-frame')
    args = parser.parse_args()
    output = Path('docs/evidence/dsr-pet')
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    checks, errors = {}, []
    shell = dialog = None
    fixture = Path(tempfile.mkdtemp(prefix='seeky-task-e2e-'))
    os.environ['CODEX_HOME'] = str(fixture / 'codex')
    day = fixture / 'codex' / 'sessions' / datetime.now(timezone.utc).strftime('%Y/%m/%d')
    day.mkdir(parents=True)
    events = day / 'rollout-task-frame.jsonl'
    events.write_text(json.dumps({'type': 'session_meta', 'payload': {'id': 'verification', 'cwd': '/work/Seeky'}}) + '\n')
    cfg = Config(fixture / 'config')

    def append(payload):
        with events.open('a') as stream:
            stream.write(json.dumps({'type': 'event_msg', 'payload': payload}) + '\n')

    def fail(kind, error, trace):
        import traceback
        traceback.print_exception(kind, error, trace)
        errors.append(f'{kind.__name__}: {error}')
        app.quit()

    sys.excepthook = fail

    def enter(field, text):
        field.setFocus()
        field.selectAll()
        QTest.keyClicks(field, text)
        QTest.keyClick(field, Qt.Key.Key_Tab)
        app.processEvents()

    def setup():
        nonlocal shell, dialog
        assert app.platformName() == 'cocoa'
        assert cfg.get('codex_task_appearance') == {'background': '#1c1c1e', 'accent': '#707078', 'scale': 100}, 'Missing task appearance defaults'
        cfg.data.update({'codex_link_enabled': True, 'no_move': True, 'self_talk_enabled': False,
                         'harness_autostart': False, 'click_sound_enabled': False})
        assert cfg.save()
        shell = AppShell(app, cfg, enable_chat=False)
        shell.start()
        dialog = ModernSettingsDialog(Config(cfg.dir.parent), include_ai=False, standalone=True)
        dialog.show()
        dialog.sidebar.setCurrentRow(next(i for i in range(dialog.sidebar.count()) if dialog.sidebar.item(i).text() == '连接'))
        QTimer.singleShot(500, edit)

    def edit():
        page = dialog.codex_page
        background = page.findChild(QLineEdit, 'taskBackground')
        accent = page.findChild(QLineEdit, 'taskAccent')
        size = page.findChild(QSpinBox, 'taskScale')
        assert background and accent and size, 'Task controls are unavailable'
        enter(background, '#f3e7d0')
        enter(accent, '#805c40')
        enter(size.lineEdit(), '140')
        stored = Config(cfg.dir.parent).get('codex_task_appearance')
        assert stored == {'background': '#f3e7d0', 'accent': '#805c40', 'scale': 140}, stored
        checks['saved_style'] = stored
        before = psutil.Process().memory_info().rss
        timings = []
        for index in range(100):
            started = time.perf_counter()
            size.setValue(80 if index % 2 else 160)
            app.processEvents()
            timings.append((time.perf_counter() - started) * 1000)
        checks['preview_100_median_ms'] = statistics.median(timings)
        checks['preview_100_max_ms'] = max(timings)
        checks['preview_100_rss_delta_bytes'] = psutil.Process().memory_info().rss - before
        checks['preview_decoder_children'] = len([p for p in psutil.Process().children() if 'ffmpeg' in p.name().lower()])
        enter(size.lineEdit(), '140')
        # Reachable filesystem failure: write under a regular file; no mocked save.
        original_path = page.config.path
        blocker = fixture / 'not-a-directory'
        blocker.write_text('filesystem failure fixture')
        page.config.path = blocker / 'config.json'
        enter(background, '#000000')
        assert '保存失败' in page.appearance_editor.error.text()
        assert page.config.get('codex_task_appearance') == stored
        checks['save_failure_reverted'] = True
        page.config.path = original_path
        dialog.grab().save(str(output / 'task-frame-save-error.png'))
        page.findChild(QPushButton, 'taskReset').click()
        assert Config(cfg.dir.parent).get('codex_task_appearance')['scale'] == 100
        enter(background, '#f3e7d0')
        enter(accent, '#805c40')
        enter(size.lineEdit(), '140')
        dialog.grab().save(str(output / 'task-frame-settings.png'))
        control = background.parentWidget()
        control.grab().save(str(output / 'task-color-control.png'))
        checks['color_control_height'] = control.height()
        checks['color_child_rects'] = [child.geometry().getRect() for child in [*control.findChildren(QLineEdit), *control.findChildren(QPushButton)]]
        assert control.height() >= 30 and all(control.rect().contains(child.geometry()) for child in [*control.findChildren(QLineEdit), *control.findChildren(QPushButton)]), 'Color controls clipped by their container'
        visible_buttons = [button for button in page.appearance_editor.preview.bubble.findChildren(QPushButton) if button.isVisible()]
        assert len(visible_buttons) == 1, f'Stale preview buttons remain visible: {len(visible_buttons)}'
        scroll = next(area for area in dialog.findChildren(QScrollArea, 'settingsScroll') if area.isVisible())
        scroll.ensureWidgetVisible(page.appearance_editor.preview)
        app.processEvents()
        dialog.grab().save(str(output / 'task-frame-settings-preview.png'))
        dialog.resize(720, 500)
        app.processEvents()
        dialog.grab().save(str(output / 'task-frame-settings-minimum.png'))
        dialog.close()
        append({'type': 'task_started'})
        QTimer.singleShot(1500, question)

    def question():
        # Config watcher must apply appearance without changing a real Codex event.
        long_text = '请确认任务框的颜色和大小。' * 18
        with events.open('a') as stream:
            stream.write(json.dumps({'type': 'response_item', 'payload': {'type': 'function_call',
                        'name': 'request_user_input_async', 'call_id': 'question',
                        'arguments': json.dumps({'questions': [{'title': long_text}]})}}) + '\n')
        QTimer.singleShot(1500, capture)

    def capture():
        bubble = shell.win._speech_bubble
        assert bubble.isVisible()
        assert shell.win._sticky_bubble_active
        assert bubble.label.text().replace('\n', '') == '请确认任务框的颜色和大小。' * 18, 'Question text was clipped or elided'
        checks['question_color_actual'] = bubble._preset['background']
        checks['disk_style_before_question'] = Config(cfg.dir.parent).get('codex_task_appearance')
        checks['main_style_before_question'] = cfg.get('codex_task_appearance')
        assert bubble._preset['background'] == '#f3e7d0', checks
        assert bubble._interactive_buttons[0].text() == '打开 Codex'
        assert not bubble._hide_timer.isActive()
        checks['question_size'] = [bubble.width(), bubble.height()]
        checks['question_color'] = bubble._preset['background']
        bubble.grab().save(str(output / 'task-frame-question.png'))
        append({'type': 'user_message', 'message': '确认'})
        append({'type': 'task_complete', 'last_agent_message': '任务完成，设置已保留。'})
        QTimer.singleShot(1500, completion)

    def completion():
        bubble = shell.win._speech_bubble
        assert not shell.win._sticky_bubble_active
        assert bubble._hide_timer.isActive(), 'Completion with an Open button never expires'
        bubble.grab().save(str(output / 'task-frame-completion.png'))
        checks['completion_timeout_ms'] = bubble._hide_timer.remainingTime()
        QTimer.singleShot(bubble._hide_timer.remainingTime() + 300, finish)

    def finish():
        checks['completion_hidden'] = not shell.win._speech_bubble.isVisible()
        assert checks['completion_hidden']
        cfg.reload()
        assert cfg.get('codex_task_appearance')['scale'] == 140
        checks['reopened_style'] = cfg.get('codex_task_appearance')
        cfg.set('codex_task_appearance', {'background': 'invalid', 'accent': '#gggggg', 'scale': float('nan')})
        assert cfg.save()
        assert Config(cfg.dir.parent).get('codex_task_appearance') == {'background': '#1c1c1e', 'accent': '#707078', 'scale': 100}
        checks['invalid_config_recovered'] = True
        app.quit()

    QTimer.singleShot(0, setup)
    QTimer.singleShot(30000, lambda: (errors.append('E2E timeout'), app.quit()))
    app.exec()
    # QApplication.aboutToQuit is the real application shutdown entry point.
    result = {'command': 'QT_QPA_PLATFORM=cocoa PYTHONPATH=. .venv/bin/python scripts/verify_seeky_task_frame.py --label ' + args.label,
              'cwd': str(Path.cwd()), 'setup': 'Fresh temporary config and Codex JSONL fixture; real Cocoa app, standalone settings, file watcher and local IPC',
              'reset': 'Fresh temporary directory per run; main app shut down after run',
              'inputs': 'Warm colors, 140%; 100 previews across 80/160%; unwritable config path; reset; long question; completion; invalid stored colors/NaN',
              'assertions': 'Controls persist; failure rolls back and displays error; defaults recover; full question and Open button remain; completion expires',
              'platform': app.platformName(), 'checks': checks, 'errors': errors, 'exit_status': 1 if errors else 0}
    (output / (args.label + '.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False))
    return result['exit_status']


if __name__ == '__main__':
    raise SystemExit(main())
