"""Public Qt lifecycle and local IPC flow in isolated homes.

Tests use original media through temporary character manifests. A deterministic
app-server peer is used for question races because forcing model questions and
server failures would send real tasks and is not reliable or safe for E2E.
"""
import json
import os
from pathlib import Path
import sys

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMenu


def _texts(menu):
    result = []
    for action in menu.actions():
        if action.menu():
            result.extend(_texts(action.menu()))
        elif not action.isSeparator():
            result.append(action.text())
    return result


@pytest.fixture
def companion_shell(qapp, tmp_path, monkeypatch):
    from pet import catalog
    from pet.app import AppShell
    from pet.config import Config
    from pet import autostart
    from pathlib import Path

    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: tmp_path))
    monkeypatch.setenv('CODEX_HOME', str(tmp_path / 'codex'))
    monkeypatch.setenv('DSH_HOME', str(tmp_path / 'dsh'))
    monkeypatch.setattr(autostart, 'is_enabled', lambda: False)
    source = Path(__file__).resolve().parents[1] / 'assets/characters/shenshen/videos/idle/待机呼吸休闲.webm'
    if not source.is_file():
        pytest.skip('original media unavailable')
    root = tmp_path / 'characters'
    for name in ('fixture-a', 'fixture-b'):
        videos = root / name / 'videos' / 'idle'
        videos.mkdir(parents=True)
        (videos / source.name).symlink_to(source)
        (videos.parent / 'manifest.json').write_text(json.dumps({'name': name}))
    monkeypatch.setattr(catalog, 'external_character_dirs', lambda: [root])
    cfg = Config(tmp_path / 'config')
    cfg.data.update({'character': 'fixture-a', 'no_move': True, 'media_prewarm': 'minimal',
                     'click_sound_enabled': False, 'collision_sound_enabled': False,
                     'music_sing_enabled': True, 'music_lyric_enabled': True,
                     'todo_reminder_enabled': True, 'voice_chime_enabled': True,
                     'festival_reminder_enabled': True, 'harness_autostart': True,
                     'proactive_screen': {'enabled': True}, 'agent_link': {'dsh': True},
                     'codex_link_enabled': True, 'experimental_single_process_spawn': True})
    cfg.save()
    cfg.reload()
    original = {key: cfg.get(key) for key in ('music_sing_enabled', 'music_lyric_enabled',
                'todo_reminder_enabled', 'voice_chime_enabled', 'festival_reminder_enabled',
                'proactive_screen', 'agent_link')}
    shell = AppShell(qapp, cfg, enable_chat=False, companion_mode=True)
    shell.start()
    yield shell, cfg, original
    shell._on_about_to_quit()


def test_companion_public_start_reload_hide_and_switch_do_not_revive_retired_services(companion_shell, qtbot):
    shell, cfg, original = companion_shell
    owner = shell.codex_companion
    assert owner.snapshot()['enabled']
    for turn in range(2):
        win = shell.win
        assert win._companion_mode
        assert not shell._dsh_state_tracker._online_timer.isActive()
        assert shell.todo_service is shell.voice_chime_service is shell.festival_service is None
        assert win.agent_link_manager is win.proactive_watcher is None
        assert not win._music_sing_timer.isActive()
        assert win._music_lyric is None
        win.hide(); win.show(); shell._apply_external_config_change()
        assert not win._music_sing_timer.isActive()
        assert win._music_lyric is None
        if turn == 0:
            shell.instance.switch_character('fixture-b')
            assert shell.codex_companion is owner
            assert owner.snapshot()['enabled']
    cfg.reload()
    assert {key: cfg.get(key) for key in original} == original


@pytest.mark.parametrize('template', ['modern', 'legacy'])
def test_companion_menu_and_tray_use_one_capability_without_changing_layout(companion_shell, template):
    from pet.context_menu import populate_context_menu
    from pet.context_menus.registry import COMPANION_ACTION_IDS, MENU_ACTIONS

    shell, cfg, _ = companion_shell
    cfg.set('context_menu_template', template)
    layout = cfg.get('context_menu_layout')
    menu = QMenu()
    populate_context_menu(menu, shell.win)
    texts = _texts(menu)
    assert 'Codex 任务与用量' in texts
    assert any('设置' in text for text in texts)
    assert any('退出' in text for text in texts)
    assert not any(any(term in text for term in ('DeepSeek', '音乐', '报时', '待办', '节日', 'Agent', '识屏', '生小肥鱼')) for text in texts)
    assert MENU_ACTIONS.available_ids(shell.win) <= COMPANION_ACTION_IDS
    assert cfg.get('context_menu_layout') == layout
    assert not any('DeepSeek' in text for text in _texts(shell.tray.contextMenu()))
    menu.close()


def test_companion_local_ipc_roundtrip_rejects_desktop_actions(qtbot, tmp_path):
    from pet.codex_companion import CodexCompanion
    from pet.codex_link import CodexMonitor
    from pet.config import Config
    from pet.settings_commands import SettingsCommandClient, SettingsCommandServer

    path = tmp_path / 'rollout-desktop.jsonl'
    records = [ {'type': 'session_meta', 'payload': {'id': 'desktop-id', 'cwd': '/project/demo'}},
                {'type': 'event_msg', 'payload': {'type': 'task_started'}}]
    path.write_text(''.join(json.dumps(r) + '\n' for r in records))
    cfg = Config(tmp_path / 'config'); cfg.set('codex_link_enabled', True)
    owner = CodexCompanion(cfg, monitor=CodexMonitor(tmp_path, date_dirs=[tmp_path]))
    owner.set_enabled(True)
    server = SettingsCommandServer(cfg, owner.dispatch)
    client = SettingsCommandClient(cfg)
    try:
        replies = []
        client.request('codex_status', {}, replies.append)
        qtbot.waitUntil(lambda: bool(replies))
        status = replies[-1]['data']
        assert status['source'] == 'desktop_readonly'
        assert status['session_id'] == 'desktop-id'
        assert not status['can_send'] and not status['can_reply']
        replies.clear()
        client.request('codex_send', {'session_id': 'desktop-id', 'turn_id': '', 'text': '不得发送'}, replies.append)
        qtbot.waitUntil(lambda: bool(replies))
        assert replies[-1]['ok'] is False
        assert '只读' in replies[-1]['error']
    finally:
        client.close(); server.close(); owner.stop()


def test_pet_session_does_not_borrow_desktop_usage_or_limits(qapp, tmp_path):
    from pet.codex_companion import CodexCompanion
    from pet.config import Config
    from PySide6.QtCore import QObject, Signal

    class SnapshotMonitor(QObject):
        updated = Signal()
        event = Signal(dict)

        def snapshot(self):
            return {
                'sessions': [{'id': 'desktop', 'project': 'demo'}],
                'selected_session_id': 'desktop', 'usage': desktop_usage, 'limits': desktop_limits,
            }

        def stop(self):
            pass

    class SnapshotClient(QObject):
        changed = Signal(dict)

        def snapshot(self):
            return {
                'session_id': 'pet-session', 'project': 'demo', 'connection': 'ready',
                'generation': 1, 'pending': [], 'can_send': True,
            }

        def stop(self):
            pass

    desktop_limits = {'source': 'rollout', 'windows': [{'used_percent': 88}]}
    desktop_usage = {'source': 'rollout', 'total': {'total_tokens': 9900}}
    monitor, client = SnapshotMonitor(), SnapshotClient()
    owner = CodexCompanion(Config(tmp_path / 'config'), monitor=monitor, client=client)
    owner._enabled = True
    owner.dispatch('codex_select', {'session_id': 'pet-session'})

    state = owner.snapshot()
    assert state['source'] == 'pet_session'
    assert state['usage']['source'] == 'app_server'
    assert state['usage']['total'] is None
    assert state['limits']['source'] == 'app_server'
    assert state['limits']['windows'] == []
    owner.stop()


def test_companion_qprocess_task_question_answer_and_shutdown_over_local_ipc(qtbot, tmp_path):
    from pet.codex_companion import CodexCompanion
    from pet.codex_client import CodexClient
    from pet.codex_link import CodexMonitor
    from pet.config import Config
    from pet.settings_commands import SettingsCommandClient, SettingsCommandServer

    cfg = Config(tmp_path / 'config'); cfg.set('codex_link_enabled', True)
    peer = Path(__file__).parent / 'fixtures/codex_peer.py'
    transport = CodexClient(program=sys.executable, arguments=[str(peer)], home=tmp_path / 'codex')
    owner = CodexCompanion(cfg, monitor=CodexMonitor(tmp_path, date_dirs=[]), client=transport)
    owner.set_enabled(True)
    server = SettingsCommandServer(cfg, owner.dispatch)
    client = SettingsCommandClient(cfg)
    def call(command, args):
        replies = []
        client.request(command, args, replies.append)
        qtbot.waitUntil(lambda: bool(replies), timeout=10000)
        assert replies[-1]['ok'], replies[-1]
        return replies[-1]['data']
    try:
        call('codex_connect', {})
        qtbot.waitUntil(lambda: owner.snapshot()['connection'] == 'ready', timeout=10000)
        call('codex_new_task', {'text': 'fixture question', 'cwd': str(tmp_path)})
        qtbot.waitUntil(lambda: bool(owner.snapshot()['questions']), timeout=10000)
        state = owner.snapshot(); question = state['questions'][0]
        assert state['source'] == 'pet_session' and state['can_reply']
        args = {key: question[key] for key in ('session_id','turn_id','request_id','generation')}
        args['answers'] = {q['id']: {'answers': [(q.get('options') or [{'label':'ok'}])[0]['label']]}
                           for q in question['questions']}
        call('codex_answer', args)
        qtbot.waitUntil(lambda: not owner.snapshot()['questions'], timeout=10000)
        assert owner.snapshot()['session_id'] == state['session_id']
    finally:
        client.close(); server.close(); owner.stop()
    assert transport.snapshot()['connection'] == 'disconnected'


@pytest.mark.parametrize('scenario,expected', [
    ('question', '选择颜色？'),
    ('command', 'echo hello'),
    ('file', '需要批准'),
])
def test_owned_request_event_has_visible_body(qtbot, tmp_path, scenario, expected):
    from pet.codex_companion import CodexCompanion
    from pet.codex_client import CodexClient
    from pet.codex_link import CodexMonitor
    from pet.config import Config

    peer = Path(__file__).parent / 'fixtures/codex_peer.py'
    transport = CodexClient(program=sys.executable, arguments=[
        str(peer), scenario, str(tmp_path / 'wire.jsonl'),
    ], home=tmp_path / 'codex')
    owner = CodexCompanion(Config(tmp_path / 'config'),
                           monitor=CodexMonitor(tmp_path, date_dirs=[]), client=transport)
    events = []
    owner.event.connect(events.append)
    owner.set_enabled(True)
    try:
        owner.dispatch('codex_connect', {})
        qtbot.waitUntil(lambda: owner.snapshot()['connection'] == 'ready', timeout=10000)
        owner.dispatch('codex_new_task', {'text': 'isolated fixture', 'cwd': str(tmp_path)})
        qtbot.waitUntil(lambda: any(e['state'] == 'question' for e in events), timeout=10000)
        event = next(e for e in events if e['state'] == 'question')
        assert expected in event['text']
        pending = event['questions'][0]
        args = {key: pending[key] for key in ('session_id', 'turn_id', 'request_id', 'generation')}
        if scenario == 'question':
            assert len(pending['questions']) == 2
            args['answers'] = {q['id']: {'answers': ['fixture answer']} for q in pending['questions']}
            owner.dispatch('codex_answer', args)
        else:
            args['decision'] = 'decline'
            owner.dispatch('codex_approve', args)
        qtbot.waitUntil(lambda: owner.snapshot()['state'] == 'complete', timeout=10000)
        assert owner.snapshot()['text'] == '完成 <b>原文</b>'
    finally:
        owner.stop()
