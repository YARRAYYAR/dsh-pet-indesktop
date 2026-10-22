"""One application owner for Desktop observation and interactive pet tasks."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

from PySide6.QtCore import QObject, Signal

from .codex_client import CodexClient
from .codex_link import CodexMonitor
from .codex_usage import normalize_limits, normalize_usage


def _now():
    return datetime.now(timezone.utc).isoformat()


class CodexCompanion(QObject):
    changed = Signal(dict)
    event = Signal(dict)

    def __init__(self, config, parent=None, *, monitor=None, client=None):
        super().__init__(parent)
        self.config = config
        self.monitor = monitor if monitor is not None else CodexMonitor(parent=self)
        self.client = client if client is not None else CodexClient(parent=self)
        self._enabled = False
        self._pet_selected = False
        self._select_new = False
        self._usage = normalize_usage(None, source='app_server', session_id='')
        self._limits = normalize_limits(None, source='app_server')
        self._raw_usage = None
        self._raw_limits = None
        self._last_event = None
        self.monitor.updated.connect(self._updated)
        self.monitor.event.connect(self._desktop_event)
        self.client.changed.connect(self._client_changed)

    def set_enabled(self, enabled):
        enabled = bool(enabled)
        if enabled == self._enabled:
            return
        self._enabled = enabled
        if enabled:
            self.monitor.start()
        else:
            self.monitor.stop()
            self.client.stop()
            self._select_new = self._pet_selected = False
            self._raw_usage = self._raw_limits = None
            self._usage = normalize_usage(None, source='app_server', session_id='')
            self._limits = normalize_limits(None, source='app_server')
        self._updated()

    def stop(self):
        self.set_enabled(False)
        # Also handles a never-enabled client supplied by an embedding caller.
        self.client.stop()

    def snapshot(self):
        desktop, pet = self.monitor.snapshot(), self.client.snapshot()
        sessions = [{**item, 'source': 'desktop_readonly'} for item in desktop.get('sessions', [])
                    if item['id'] != pet.get('session_id')]
        if pet.get('session_id'):
            sessions.insert(0, {'id': pet['session_id'], 'project': pet.get('project', ''), 'source': 'pet_session'})
        selected = self._pet_selected and bool(pet.get('session_id'))
        source = pet if selected else desktop
        result = {key: source.get(key, '') for key in ('state', 'session_id', 'turn_id', 'project', 'text')}
        result.update(enabled=self._enabled, source='pet_session' if selected else 'desktop_readonly',
                      sessions=sessions, selected_session_id=pet.get('session_id', '') if selected else desktop.get('selected_session_id', ''),
                      connection=pet.get('connection', 'disconnected'), generation=pet.get('generation', 0),
                      usage=self._usage if selected else desktop.get('usage'),
                      limits=self._limits if selected else desktop.get('limits'),
                      account_usage=pet.get('account_usage'),
                      questions=pet.get('pending', []) if selected else desktop.get('questions', []),
                      can_reply=bool(selected and self._enabled and pet.get('pending')),
                      can_send=bool(selected and self._enabled and pet.get('can_send')),
                      can_interrupt=bool(selected and self._enabled and pet.get('can_interrupt')),
                      error=pet.get('error') or desktop.get('error', ''))
        return deepcopy(result)

    def _updated(self, *_args):
        self.changed.emit(self.snapshot())

    def _desktop_event(self, _event):
        if not self._pet_selected:
            self._emit_event()

    def _emit_event(self):
        state = self.snapshot()
        identity = (state['source'], state['session_id'], state['state'], state['text'])
        if identity != self._last_event:
            self._last_event = identity
            self.event.emit(state)

    def _client_changed(self, pet):
        usage = pet.get('token_usage')
        if usage != self._raw_usage or self._usage.get('session_id') != pet.get('session_id'):
            self._raw_usage = deepcopy(usage)
            self._usage = normalize_usage(usage, source='app_server', session_id=pet.get('session_id', ''), observed_at=_now() if usage else None)
        limits = pet.get('rate_limits')
        if limits != self._raw_limits:
            self._raw_limits = deepcopy(limits)
            self._limits = normalize_limits(limits, source='app_server', observed_at=_now() if limits else None)
        if self._select_new and pet.get('session_id'):
            self._pet_selected, self._select_new = True, False
        self._updated()
        if self._pet_selected:
            self._emit_event()

    def dispatch(self, command, args):
        if not isinstance(args, dict):
            raise ValueError('无效的 Codex 命令参数')
        if command == 'codex_status':
            return self.snapshot()
        if not self._enabled:
            raise ValueError('请先开启 Codex 连接')
        if command == 'codex_select':
            session = args.get('session_id', '')
            if not isinstance(session, str):
                raise ValueError('会话标识无效')
            if session and session == self.client.snapshot().get('session_id'):
                self._pet_selected = True
            elif self.monitor.select_session(session):
                self._pet_selected = False
            else:
                raise ValueError('会话已不可用，请刷新列表')
            self._updated()
            return {'accepted': True}
        if command == 'codex_connect':
            return self.client.connect_server()
        if command == 'codex_new_task':
            self._select_new = True
            try:
                return self.client.new_task(args.get('text', ''), args.get('cwd', ''))
            except ValueError:
                self._select_new = False
                raise
        if not self._pet_selected:
            raise ValueError('现有 Codex 桌面对话为只读，请打开 Codex 回答')
        session, turn = args.get('session_id'), args.get('turn_id')
        if command == 'codex_send':
            return self.client.send_message(session, turn, args.get('text', ''))
        if command == 'codex_answer':
            return self.client.answer(session, turn, args.get('request_id'), args.get('answers'), args.get('generation'))
        if command == 'codex_approve':
            return self.client.approve(session, turn, args.get('request_id'), args.get('decision'), args.get('generation'))
        if command == 'codex_interrupt':
            return self.client.interrupt(session, turn)
        raise ValueError('不支持的 Codex 命令')
