"""Real Qt surface flows with an isolated IPC peer.

Live models cannot deterministically produce questions, approval failures or stale
requests without affecting user tasks. A tiny IPC boundary peer supplies those
states; all settings, widgets, selection and submission actions are real Qt.
"""
from copy import deepcopy

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QLineEdit, QPushButton

from pet.config import Config
from pet.settings_codex import CodexConnectionPage


class Peer:
    def __init__(self, data):
        self.data = deepcopy(data)
        self.commands = []
        self.failure = ''
        self.hold = False
        self.pending = None

    def request(self, command, args, callback):
        self.commands.append((command, deepcopy(args)))
        if command == 'codex_status':
            callback({'ok': True, 'data': deepcopy(self.data)})
        elif self.hold:
            self.pending = callback
        elif self.failure:
            callback({'ok': False, 'error': self.failure})
        else:
            callback({'ok': True, 'data': {'accepted': True}})


@pytest.fixture
def snapshot():
    return {'enabled': True, 'state': 'working', 'session_id': 'owned', 'turn_id': 'turn-2',
            'project': 'demo', 'text': '<b>任务内容</b>', 'source': 'pet_session',
            'selected_session_id': 'owned', 'connection': 'ready', 'generation': 4,
            'can_reply': True, 'can_send': True, 'can_interrupt': True,
            'sessions': [{'id': 'desktop', 'project': 'old', 'source': 'desktop_readonly'},
                         {'id': 'owned', 'project': 'demo', 'source': 'pet_session'}],
            'usage': {'source': 'app_server', 'observed_at': '2026-10-21T12:00:00Z',
                      'total': {'total_tokens': 1200, 'input_tokens': 900, 'cached_input_tokens': 200,
                                'output_tokens': 300, 'reasoning_output_tokens': 100},
                      'last': {'total_tokens': 320}},
            'limits': {'source': 'app_server', 'observed_at': '2026-10-21T12:00:00Z',
                       'windows': [{'window_minutes': 15, 'used_percent': 42, 'reset_at': 1792584000}]},
            'questions': [], 'error': ''}


def page(qtbot, tmp_path, data):
    peer = Peer(data)
    widget = CodexConnectionPage(Config(tmp_path), peer)
    qtbot.addWidget(widget)
    widget.resize(600, 740)
    widget.show()
    return widget, peer


def test_usage_source_unknown_values_and_desktop_capabilities(qtbot, tmp_path, snapshot):
    widget, peer = page(qtbot, tmp_path, snapshot)
    assert '1,200' in widget.usage_text.text()
    assert '320' in widget.usage_text.text()
    assert '15 分钟' in widget.quota_text.text()
    assert '42%' in widget.quota_text.text()
    assert '2026-10-21' in widget.quota_text.text()
    assert widget.message.textFormat() == Qt.TextFormat.PlainText
    assert widget.message.text() == 'demo\n<b>任务内容</b>'
    peer.data.update(source='desktop_readonly', can_reply=False, can_send=False,
                     can_interrupt=False, usage=None, limits=None)
    widget.refresh()
    assert '只读' in widget.source_note.text()
    assert not widget.send_button.isEnabled() and not widget.stop_button.isEnabled()
    assert '暂无' in widget.usage_text.text() and '暂无' in widget.quota_text.text()
    assert not any('0%' in label.text() for label in (widget.usage_text, widget.quota_text))


def test_session_selection_and_task_commands_bind_snapshot(qtbot, tmp_path, snapshot):
    widget, peer = page(qtbot, tmp_path, snapshot)
    widget.sessions.setCurrentData('desktop')
    assert ('codex_select', {'session_id': 'desktop'}) in peer.commands
    widget.sessions.setCurrentData('')
    assert ('codex_select', {'session_id': ''}) in peer.commands
    peer.data['connection'] = 'disconnected'
    widget.refresh()
    widget.connect_button.click()
    assert ('codex_connect', {}) in peer.commands
    peer.data['connection'] = 'ready'
    widget.refresh()
    widget.workspace.setText(str(tmp_path))
    widget.composer.setPlainText('继续整理')
    widget.send_button.click()
    assert ('codex_send', {'session_id': 'owned', 'turn_id': 'turn-2', 'text': '继续整理'}) in peer.commands
    widget.stop_button.click()
    assert ('codex_interrupt', {'session_id': 'owned', 'turn_id': 'turn-2'}) in peer.commands
    peer.data.update(state='complete', can_interrupt=False)
    widget.refresh()
    widget.composer.setPlainText('新任务')
    widget.new_button.click()
    assert ('codex_new_task', {'text': '新任务', 'cwd': str(tmp_path)}) in peer.commands


def questions():
    return [{'request_id': 9, 'session_id': 'owned', 'turn_id': 'turn-2', 'generation': 4,
             'kind': 'question', 'questions': [
                 {'id': 'color', 'header': '颜色', 'question': '选哪个？', 'isOther': True,
                  'options': [{'label': '蓝色', 'description': '保留当前风格'}, {'label': '灰色', 'description': ''}]},
                 {'id': 'secret', 'header': '名称', 'question': '输入名称', 'isSecret': True, 'options': None}]}]


def test_question_submission_exact_identity_failure_and_resolution(qtbot, tmp_path, snapshot):
    snapshot['questions'] = questions()
    snapshot['state'] = 'question'
    widget, peer = page(qtbot, tmp_path, snapshot)
    option = widget.findChild(QPushButton, 'codexOption_color_0')
    assert option is not None
    # showEvent creates the request card; wait for its real layout before clicking.
    qtbot.waitUntil(lambda: option.visibleRegion().contains(option.rect().center()), timeout=10000)
    qtbot.mouseClick(option, Qt.MouseButton.LeftButton)
    assert option.isChecked(), {
        'option_geometry': option.geometry().getRect(),
        'option_visible': option.isVisible(),
        'option_enabled': option.isEnabled(),
        'option_visible_region': option.visibleRegion().boundingRect().getRect(),
        'page_geometry': widget.geometry().getRect(),
    }
    answer = widget.findChild(QLineEdit, 'codexAnswer_secret')
    assert answer.echoMode() == QLineEdit.EchoMode.Password
    answer.setText('fixture-name')
    submit = widget.findChild(QPushButton, 'codexSubmit_9')
    peer.failure = '问题已过期'
    submit.click()
    command, args = [item for item in peer.commands if item[0] == 'codex_answer'][-1]
    assert args == {'session_id': 'owned', 'turn_id': 'turn-2', 'request_id': 9,
                    'generation': 4, 'answers': {'color': {'answers': ['蓝色']}, 'secret': {'answers': ['fixture-name']}}}
    assert '问题已过期' in widget.command_status.text()
    assert answer.text() == 'fixture-name'
    widget.refresh()
    assert widget.findChild(QLineEdit, 'codexAnswer_secret') is answer
    peer.failure = ''
    peer.hold = True
    submit.click()
    assert not submit.isEnabled()
    count = len([item for item in peer.commands if item[0] == 'codex_answer'])
    submit.click()
    assert len([item for item in peer.commands if item[0] == 'codex_answer']) == count
    peer.hold = False
    peer.pending({'ok': True, 'data': {'accepted': True}})
    peer.data['questions'] = []
    widget.refresh()
    assert widget.findChild(QPushButton, 'codexSubmit_9') is None


@pytest.mark.parametrize('decision,label', [('accept', '允许'), ('decline', '拒绝')])
def test_approval_is_explicit_and_not_plain_answer(qtbot, tmp_path, snapshot, decision, label):
    snapshot['questions'] = [{'request_id': 'approval-1', 'session_id': 'owned', 'turn_id': 'turn-2',
                              'generation': 4, 'kind': 'file_approval', 'summary': '<script>变更文件</script>',
                              'sending': False}]
    widget, peer = page(qtbot, tmp_path, snapshot)
    button = widget.findChild(QPushButton, f'codexApproval_{decision}_approval-1')
    assert button is not None
    assert button.text() == label
    button.click()
    assert ('codex_approve', {'session_id': 'owned', 'turn_id': 'turn-2', 'request_id': 'approval-1',
                             'generation': 4, 'decision': decision}) in peer.commands
    for line in widget.findChildren(QLabel, 'codexQuestionText'):
        assert line.textFormat() == Qt.TextFormat.PlainText


def test_readonly_questions_have_no_answer_control_and_hidden_timer_stops(qtbot, tmp_path, snapshot):
    snapshot.update(source='desktop_readonly', can_reply=False, questions=questions())
    widget, peer = page(qtbot, tmp_path, snapshot)
    assert widget.findChild(QPushButton, 'codexSubmit_9') is None
    assert not widget.findChildren(QLineEdit, 'codexAnswer_secret')
    assert widget.timer.isActive()
    widget.hide()
    assert not widget.timer.isActive()


def test_send_failure_preserves_draft_and_old_snapshot_stays_compatible(qtbot, tmp_path, snapshot):
    widget, peer = page(qtbot, tmp_path, snapshot)
    peer.failure = '通道不可用'
    widget.composer.setPlainText('请保留我的输入')
    widget.send_button.click()
    assert widget.composer.toPlainText() == '请保留我的输入'
    assert '通道不可用' in widget.command_status.text()
    peer.data = {'enabled': False, 'state': 'disconnected', 'session_id': '', 'project': '', 'text': ''}
    widget.refresh()
    assert not widget.send_button.isEnabled()


def test_late_command_reply_preserves_current_snapshot_capabilities(qtbot, tmp_path, snapshot):
    widget, peer = page(qtbot, tmp_path, snapshot)
    peer.hold = True
    widget.sessions.setCurrentData('desktop')
    peer.data.update(source='desktop_readonly', can_reply=False, can_send=False, can_interrupt=False)
    widget.refresh()
    peer.pending({'ok': True, 'data': {'accepted': True}})
    assert not widget.send_button.isEnabled()
    assert not widget.stop_button.isEnabled()
    peer.data.update(enabled=False, connection='disconnected')
    widget.refresh()
    widget.sessions.setCurrentData('owned')
    peer.pending({'ok': False, 'error': '连接已关闭'})
    assert not widget.new_button.isEnabled()
    assert not widget.connect_button.isEnabled()


def test_request_cards_keep_typed_ids_separate(qtbot, tmp_path, snapshot):
    first = questions()[0]
    second = deepcopy(first)
    second['request_id'] = '9'
    snapshot['questions'] = [first, second]
    widget, _peer = page(qtbot, tmp_path, snapshot)
    assert len(widget.findChildren(QPushButton, 'codexSubmit_9')) == 2


def test_reused_request_id_rebuilds_card_for_new_task_identity(qtbot, tmp_path, snapshot):
    snapshot['questions'] = questions()
    widget, peer = page(qtbot, tmp_path, snapshot)
    widget.findChild(QLineEdit, 'codexAnswer_secret').setText('old-answer')
    replacement = deepcopy(questions()[0])
    replacement.update(session_id='owned-new', turn_id='turn-new', generation=5)
    replacement['questions'] = [{'id': 'replacement', 'question': '新的问题', 'isSecret': False}]
    peer.data.update(session_id='owned-new', turn_id='turn-new', generation=5, questions=[replacement])
    widget.refresh()
    answer = widget.findChild(QLineEdit, 'codexAnswer_replacement')
    assert answer is not None and answer.text() == ''
    assert widget.findChild(QLineEdit, 'codexAnswer_secret') is None
    answer.setText('new-answer')
    widget.findChild(QPushButton, 'codexSubmit_9').click()
    assert ('codex_answer', {'session_id': 'owned-new', 'turn_id': 'turn-new', 'request_id': 9,
                             'generation': 5, 'answers': {'replacement': {'answers': ['new-answer']}}}) in peer.commands


def test_sending_request_stays_disabled_after_another_command_reply(qtbot, tmp_path, snapshot):
    snapshot['questions'] = questions()
    snapshot['questions'][0]['sending'] = True
    widget, _peer = page(qtbot, tmp_path, snapshot)
    submit = widget.findChild(QPushButton, 'codexSubmit_9')
    assert not submit.isEnabled()
    widget.sessions.setCurrentData('desktop')
    assert not submit.isEnabled()


def test_desktop_monitor_question_shape_remains_visible_readonly(qtbot, tmp_path, snapshot):
    question = questions()[0]
    question.pop('kind')
    snapshot.update(source='desktop_readonly', can_reply=False, questions=[question])
    widget, _peer = page(qtbot, tmp_path, snapshot)
    prompts = [label.text() for label in widget.findChildren(QLabel, 'codexQuestionText')]
    assert '选哪个？' in prompts
    assert widget.findChild(QPushButton, 'codexSubmit_9') is None


@pytest.mark.parametrize('reset_at', [2**63 - 1, 253402300800])
def test_unrenderable_quota_reset_keeps_window_usage_visible(qtbot, tmp_path, snapshot, reset_at):
    from pet.codex_usage import normalize_limits

    widget, peer = page(qtbot, tmp_path, snapshot)
    peer.data['limits'] = normalize_limits(
        {'primary': {'windowDurationMins': 15, 'usedPercent': 42, 'resetsAt': reset_at}},
        source='app_server',
    )
    widget.refresh()
    assert '15 分钟' in widget.quota_text.text()
    assert '42%' in widget.quota_text.text()
    assert '重置时间不可用' in widget.quota_text.text()


def test_codex_task_controls_follow_native_settings_layout(qtbot, tmp_path, snapshot):
    from PySide6.QtWidgets import QFrame

    from pet.settings_widgets import SettingRow, SettingsSection

    widget, _peer = page(qtbot, tmp_path, snapshot)
    row_names = {row.objectName() for row in widget.findChildren(SettingRow)}
    assert {
        'settingRow_codex_workspace',
        'settingRow_codex_task_message',
        'settingRow_codex_task_actions',
    } <= row_names

    task_section = next(
        section for section in widget.findChildren(SettingsSection)
        if any(row.objectName() == 'settingRow_codex_workspace' for row in section.rows)
    )
    assert len(task_section.findChildren(QFrame, 'settingsCard')) == 1
    assert not hasattr(widget, 'appearance_editor')


def test_companion_default_constructor_does_not_create_retired_ai_page(qtbot, tmp_path, monkeypatch):
    from pet import autostart
    from pet.modern_settings_dialog import ModernSettingsDialog

    monkeypatch.setattr(autostart, 'is_enabled', lambda: False)
    dialog = ModernSettingsDialog(Config(tmp_path), standalone=True, companion_mode=True)
    qtbot.addWidget(dialog)
    assert dialog.ai_page is None


@pytest.mark.parametrize('external_update', [False, True])
def test_companion_settings_slim_search_and_preserve_retired_configuration(qtbot, tmp_path, monkeypatch, external_update):
    from pet import autostart
    from pet.modern_settings_dialog import ModernSettingsDialog
    monkeypatch.setattr(autostart, 'is_enabled', lambda: False)
    config = Config(tmp_path)
    config.data.update({'music_sing_enabled': True, 'music_lyric_enabled': True,
                        'music_player_paths': {'netease': '/before/player', 'custom': '/keep/unknown'},
                        'agent_link': {**config.get('agent_link'), 'dsh': True, 'unknown': {'keep': [1]}},
                        'voice_chime_enabled': True, 'todo_reminder_enabled': True,
                        'harness_autostart': True, 'self_talk_texts': ['旧台词'],
                        'spawn_inherit_size': False, 'spawn_scale': .7})
    assert config.save()
    before = deepcopy(Config(tmp_path).data)
    dialog = ModernSettingsDialog(
        config,
        include_ai=False,
        standalone=True,
        companion_mode=True,
    )
    qtbot.addWidget(dialog)
    assert [dialog.sidebar.item(i).text() for i in range(dialog.sidebar.count())] == [
        '常规', '桌宠', '互动', '菜单', '连接',
    ]
    assert dialog.pet_tabs.labels() == ('常用控制', '动作库')
    for retired_term in ('音乐', '唱歌', '歌词', '报时', '节日', '待办', '识屏', 'Agent 联动'):
        dialog.search_edit.setText(retired_term)
        assert dialog._search_matches == [], retired_term
    assert 'music_open_netease' not in dialog.menu_available_actions
    assert dialog.codex_page is not None
    from pet.settings_widgets import SettingsTabContainer
    menu_index = next(i for i in range(dialog.sidebar.count()) if dialog.sidebar.item(i).text() == '菜单')
    menu_tabs = dialog.pages.widget(menu_index).findChild(SettingsTabContainer)
    assert menu_tabs.labels() == ('菜单编排', '外观')
    if external_update:
        external = Config(tmp_path)
        external.set('music_player_paths', {'custom': '/external/player'})
        external.set('music_sing_enabled', False)
        external.set('agent_link', {**external.get('agent_link'), 'unknown': {'external': [2]}})
        external.set('voice_chime_enabled', False)
        external.set('harness_autostart', False)
        external.set('spawn_inherit_size', True)
        external.set('spawn_scale', .4)
        assert external.save()
        before = deepcopy(Config(tmp_path).data)
    dialog.top_flip_exposure_spin.setValue(42)
    assert dialog._write_config()
    after = Config(tmp_path).data
    for key in ('music_sing_enabled', 'music_lyric_enabled', 'music_player_paths', 'agent_link',
                'voice_chime_enabled', 'todo_reminder_enabled', 'harness_autostart', 'self_talk_texts',
                'spawn_inherit_size', 'spawn_scale'):
        assert after[key] == before[key], key
    assert after['top_flip_exposure'] == .42
