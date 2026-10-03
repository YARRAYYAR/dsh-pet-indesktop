import json

from PySide6.QtCore import QRect
from PySide6.QtWidgets import QPushButton


def test_ceiling_settings_round_trip_and_navigation(qtbot, tmp_path, monkeypatch):
    from pet import autostart
    from pet.config import Config
    from pet.modern_settings_dialog import ModernSettingsDialog

    monkeypatch.setattr(autostart, 'is_enabled', lambda: False)
    config = Config(tmp_path)
    dialog = ModernSettingsDialog(config, include_ai=False, standalone=True)
    qtbot.addWidget(dialog)
    assert dialog.top_flip_check.isChecked()
    dialog.top_flip_exposure_spin.setValue(35)
    assert dialog._write_config()
    saved = Config(tmp_path)
    assert saved.get('top_flip_exposure') == 0.35
    assert '连接' in [dialog.sidebar.item(i).text() for i in range(dialog.sidebar.count())]
    pet_index = next(i for i in range(dialog.sidebar.count()) if dialog.sidebar.item(i).text() == '桌宠')
    dialog.sidebar.setCurrentRow(pet_index)
    children = dialog.findChildren(QPushButton, 'sidebarSubtask')
    assert children and all(button.icon().isNull() for button in children)


def test_ceiling_move_preserves_horizontal_position_and_can_leave(qapp, tmp_path):
    from pet.config import Config
    from pet.window import PetWindow
    from pet.window_placement import stable_body_local_rect
    from tests.test_pet_interaction_locks import FakeLibrary

    window = PetWindow(FakeLibrary(), Config(tmp_path))
    try:
        screen = window._screen_available()
        body = stable_body_local_rect(window)
        x = screen.availableGeometry().center().x() - body.center().x()
        top = screen.geometry().top() - body.top()
        window._move_window_towards(x, top)
        assert window._effects_current_angle() == 180
        assert window._virtual_pos().x() == x
        assert window._top_flip._timer.isActive() is False
        window._move_window_towards(x, top + 200)
        assert window._effects_current_angle() == 0
    finally:
        window.close()


def test_codex_incremental_events_partial_lines_and_no_history_replay(qtbot, tmp_path):
    from pet.codex_link import CodexMonitor

    sessions = tmp_path / 'sessions' / '2026' / '10' / '03'
    sessions.mkdir(parents=True)
    path = sessions / 'rollout-test.jsonl'
    meta = {'type': 'session_meta', 'payload': {'id': 'test-session', 'cwd': '/work/demo'}}
    start = {'type': 'event_msg', 'payload': {'type': 'task_started'}}
    path.write_text(json.dumps(meta) + '\n' + json.dumps(start) + '\n')
    monitor = CodexMonitor(tmp_path, date_dirs=[sessions])
    events = []
    monitor.event.connect(events.append)
    monitor.start()
    assert events == []
    assert monitor.snapshot()['state'] == 'working'
    question = {'type': 'response_item', 'payload': {'type': 'function_call', 'name': 'request_user_input_async',
                'call_id': 'q1', 'arguments': json.dumps({'questions': [{'title': '选择哪个颜色？'}]})}}
    encoded = (json.dumps(question) + '\n').encode()
    with path.open('ab') as stream:
        stream.write(encoded[:25])
    monitor.poll()
    assert not events
    with path.open('ab') as stream:
        stream.write(encoded[25:])
    monitor.poll()
    assert events[-1]['state'] == 'question'
    assert events[-1]['text'] == '选择哪个颜色？'
    done = {'type': 'event_msg', 'payload': {'type': 'task_complete', 'last_agent_message': '修改完成'}}
    answer = {'type': 'event_msg', 'payload': {'type': 'user_message', 'message': '灰色'}}
    with path.open('a') as stream:
        stream.write(json.dumps(answer) + '\n' + json.dumps(done) + '\n')
    monitor.poll()
    assert events[-1]['state'] == 'complete'
    assert events[-1]['text'] == '修改完成'
    monitor.stop()
    assert not monitor.timer.isActive()


def test_ceiling_flip_target_geometry():
    from pet.top_flip import flip_target

    assert flip_target(-100, -100) == 1
    assert flip_target(10, -100) == 0
    assert QRect(0, 0, 10, 10).top() == 0


def test_codex_connection_reports_save_failure(qtbot, tmp_path, monkeypatch):
    from pet.config import Config
    from pet.settings_codex import CodexConnectionPage
    from pet.settings_commands import SettingsCommandClient

    config = Config(tmp_path)
    page = CodexConnectionPage(config, SettingsCommandClient(config))
    qtbot.addWidget(page)
    monkeypatch.setattr(config, 'save', lambda: False)
    page.enabled.setChecked(True)
    assert not page.enabled.isChecked()
    assert '保存失败' in page.status.text()


def test_codex_question_acknowledgement_and_file_rotation(qtbot, tmp_path):
    from pet.codex_link import CodexMonitor

    path = tmp_path / 'rollout-test.jsonl'
    meta = {'type': 'session_meta', 'payload': {'id': 'test-session'}}
    path.write_text(json.dumps(meta) + '\n')
    monitor = CodexMonitor(tmp_path, date_dirs=[tmp_path])
    events = []
    monitor.event.connect(events.append)
    monitor.start()
    question = {'type': 'response_item', 'payload': {'type': 'function_call',
                'name': 'request_user_input_async', 'call_id': 'q1',
                'arguments': json.dumps({'questions': [{'title': '请选颜色'}]})}}
    ack = {'type': 'response_item', 'payload': {'type': 'function_call_output', 'call_id': 'q1', 'output': 'Question displayed'}}
    done = {'type': 'event_msg', 'payload': {'type': 'task_complete'}}
    with path.open('a') as stream:
        for record in (question, ack, done):
            stream.write(json.dumps(record) + '\n')
    monitor.poll()
    assert monitor.snapshot()['state'] == 'question'
    assert len(events) == 1
    replacement = tmp_path / 'new.jsonl'
    replacement.write_text(json.dumps(meta) + '\n' + json.dumps(done) + '\n')
    replacement.replace(path)
    monitor.poll()
    assert monitor.snapshot()['state'] == 'complete'
    assert len(events) == 1
    monitor.stop()
