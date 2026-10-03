"""Read-only Codex Desktop rollout adapter; no model process or API key."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
import time

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices

log = logging.getLogger(__name__)
MAX_RECORD = 1024 * 1024


def open_codex(session_id: str = '') -> bool:
    return QDesktopServices.openUrl(QUrl(f'codex://threads/{session_id}' if session_id else 'codex://'))


class CodexMonitor(QObject):
    event = Signal(dict)

    def __init__(self, home: Path | None = None, parent=None, *, date_dirs=None):
        super().__init__(parent)
        self.home = home or Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex')
        self._date_dirs = date_dirs
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.poll)
        self._last_scan = 0.0
        self._path = None
        self._identity = None
        self._offset = 0
        self._buffer = b''
        self._discarding = False
        self._sessions = []
        self._pending = set()
        self._state = 'disconnected'
        self._session_id = ''
        self._project = ''
        self._text = ''

    def start(self):
        self.poll()
        self.timer.start()

    def stop(self):
        self.timer.stop()
        self._path = None
        self._buffer = b''
        self._sessions.clear()
        self._pending.clear()
        self._state = 'disconnected'

    def snapshot(self):
        return {'state': self._state, 'session_id': self._session_id,
                'project': self._project, 'text': self._text,
                'sessions': self._sessions, 'enabled': self.timer.isActive()}

    def _directories(self):
        if self._date_dirs is not None:
            return self._date_dirs
        now = datetime.now(timezone.utc)
        return [self.home / 'sessions' / (now - timedelta(days=day)).strftime('%Y/%m/%d')
                for day in range(2)]

    def _discover(self):
        candidates = []
        for directory in self._directories():
            for path in directory.glob('rollout-*.jsonl'):
                stat = path.stat()
                candidates.append((stat.st_mtime, path))
        candidates.sort(reverse=True)
        self._sessions = []
        for modified, path in candidates:
            with path.open('rb') as stream:
                first = stream.readline(MAX_RECORD)
            try:
                meta = json.loads(first).get('payload', {})
            except (ValueError, UnicodeDecodeError):
                continue
            # Subagents have separate rollouts; their completion is not the
            # parent task's completion. Only follow user-owned root sessions.
            if isinstance(meta.get('source'), dict) and 'subagent' in meta['source']:
                continue
            session_id = str(meta.get('id') or '')
            if not session_id:
                continue
            item = {'id': session_id, 'project': Path(meta.get('cwd') or '').name,
                    'path': str(path), 'modified': modified}
            if all(existing['id'] != session_id for existing in self._sessions):
                self._sessions.append(item)
            if len(self._sessions) == 8:
                break
        selected = self._sessions[0] if self._sessions else None
        path = Path(selected['path']) if selected else None
        if path != self._path:
            self._path = path
            self._buffer = b''
            self._discarding = False
            self._pending.clear()
            self._state = 'idle' if path else 'unavailable'
            self._text = ''
            self._session_id = selected['id'] if selected else ''
            self._project = selected['project'] if selected else ''
            if path:
                stat = path.stat()
                self._identity = (stat.st_dev, stat.st_ino)
                # Recover current state without announcing historical messages.
                with path.open('rb') as stream:
                    offset = max(0, stat.st_size - MAX_RECORD)
                    stream.seek(offset)
                    parts = stream.read(stat.st_size - offset).split(b'\n')
                    if offset:
                        parts.pop(0)
                    self._buffer = parts.pop()
                    for line in parts:
                        self._consume(line, announce=False)
                self._offset = stat.st_size

    def poll(self):
        try:
            now = time.monotonic()
            if self._path is None or now - self._last_scan >= 5:
                self._discover()
                self._last_scan = now
            if self._path is None:
                return
            stat = self._path.stat()
            if (stat.st_dev, stat.st_ino) != self._identity or stat.st_size < self._offset:
                self._path = None
                self._discover()
                return
            with self._path.open('rb') as stream:
                stream.seek(self._offset)
                chunk = stream.read(262144)
                self._offset += len(chunk)
            self._buffer += chunk
            while b'\n' in self._buffer:
                line, self._buffer = self._buffer.split(b'\n', 1)
                if not self._discarding:
                    self._consume(line)
                self._discarding = False
            if len(self._buffer) > MAX_RECORD:
                # Tool outputs can be very large. Skip that record without
                # retaining it indefinitely; following state records still work.
                self._buffer = b''
                self._discarding = True
        except OSError as exc:
            log.warning('Codex 状态读取失败: %s', exc)
            self._state = 'unavailable'
            self._path = None

    def _consume(self, line, *, announce=True):
        try:
            record = json.loads(line)
        except (ValueError, UnicodeDecodeError):
            return  # An incomplete boundary in the initial tail is expected.
        payload = record.get('payload', {})
        state, text = None, ''
        kind = payload.get('type')
        if record.get('type') == 'event_msg':
            if kind == 'task_started':
                state, text = 'working', 'Codex 正在工作'
            elif kind == 'task_complete':
                if self._pending:
                    return  # An asynchronous question can outlive its turn.
                state, text = 'complete', payload.get('last_agent_message') or 'Codex 已完成这一轮工作'
            elif kind == 'turn_aborted':
                self._pending.clear()
                state, text = 'idle', 'Codex 已停止'
            elif kind == 'user_message':
                self._pending.clear()
                state, text = 'working', 'Codex 正在处理你的回复'
        elif record.get('type') == 'response_item' and kind in {'function_call', 'custom_tool_call'}:
            name = str(payload.get('name') or '').split('.')[-1]
            # A long-running turn's start can be outside the bounded initial
            # tail. A subsequent tool call is also evidence of active work.
            state, text = 'working', 'Codex 正在工作'
            if name in {'request_user_input', 'request_user_input_async'}:
                try:
                    args = json.loads(payload.get('arguments') or '{}')
                except ValueError:
                    return
                text = '\n'.join(str(q.get('question') or q.get('title') or '')
                                 for q in args.get('questions', []))
                if text:
                    self._pending.add(payload.get('call_id'))
                    state = 'question'
        elif record.get('type') == 'response_item' and kind == 'function_call_output':
            # Blocking questions complete only after the answer. Async calls
            # return immediately, so their acknowledgements must not clear them.
            output = str(payload.get('output') or '')
            if payload.get('call_id') in self._pending and ('answers' in output or 'user_response' in output):
                self._pending.discard(payload.get('call_id'))
                state, text = 'working', 'Codex 正在处理你的回复'
        if state is None:
            return
        if state == 'working' and self._pending:
            return
        changed = state != self._state or str(text)[:300] != self._text
        self._state = state
        self._text = str(text)[:300]
        if announce and changed:
            self.event.emit(self.snapshot())
