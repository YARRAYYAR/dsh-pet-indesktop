"""Read-only Codex Desktop rollout adapter; no model process or API key."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from copy import deepcopy
import heapq
import json
import logging
import os
from pathlib import Path
import time

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices

from .codex_usage import normalize_limits, normalize_usage

log = logging.getLogger(__name__)
MAX_RECORD = 1024 * 1024
MAX_DISCOVERY_FILES = 512
MAX_METADATA_READS = 64
MAX_SESSIONS = 8
MAX_PENDING_QUESTIONS = 64


def open_codex(session_id: str = '') -> bool:
    return QDesktopServices.openUrl(QUrl(f'codex://threads/{session_id}' if session_id else 'codex://'))


class CodexMonitor(QObject):
    event = Signal(dict)
    updated = Signal(dict)

    def __init__(self, home: Path | None = None, parent=None, *, date_dirs=None):
        super().__init__(parent)
        self.home = home or Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex')
        self._date_dirs = date_dirs
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.poll)
        self._active = False
        self._last_scan = 0.0
        self._path = None
        self._identity = None
        self._offset = 0
        self._buffer = b''
        self._discarding = False
        self._sessions = []
        self._selected_session_id = ''
        self._pending = {}
        self._state = 'disconnected'
        self._session_id = ''
        self._project = ''
        self._text = ''
        self._usage = normalize_usage(None, source='rollout', session_id='')
        self._limits_data = {}
        self._limits = normalize_limits(None, source='rollout')
        self._error = ''
        self._published = None

    def start(self):
        self._active = True
        self.timer.start()
        self.poll()

    def stop(self):
        self._active = False
        self.timer.stop()
        self._path = None
        self._reset(None)
        self._sessions.clear()
        self._state = 'disconnected'
        self._session_id = ''
        self._project = ''
        self._selected_session_id = ''
        self._error = ''
        self._publish()

    def snapshot(self):
        return deepcopy({
            'state': self._state,
            'session_id': self._session_id,
            'project': self._project,
            'text': self._text,
            'sessions': self._sessions,
            'enabled': self.timer.isActive(),
            'selected_session_id': self._selected_session_id,
            'usage': self._usage,
            'limits': self._limits,
            'questions': list(self._pending.values()),
            'error': self._error,
        })

    def _publish(self):
        snapshot = self.snapshot()
        if snapshot != self._published:
            self._published = deepcopy(snapshot)
            self.updated.emit(snapshot)

    def _reset(self, selected):
        self._identity = None
        self._offset = 0
        self._buffer = b''
        self._discarding = False
        self._pending.clear()
        self._state = 'idle' if selected else 'unavailable'
        self._text = ''
        self._session_id = selected['id'] if selected else ''
        self._project = selected['project'] if selected else ''
        self._usage = normalize_usage(None, source='rollout', session_id=self._session_id)
        self._limits_data = {}
        self._limits = normalize_limits(None, source='rollout')
        self._error = ''

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
                try:
                    stat = path.stat()
                except OSError:
                    continue
                candidate = (stat.st_mtime, path)
                # Directory enumeration has no time order. Bound retained
                # candidates only after comparing mtimes so a busy directory
                # cannot hide its newest session or starve the next date.
                if len(candidates) < MAX_DISCOVERY_FILES:
                    heapq.heappush(candidates, candidate)
                else:
                    heapq.heappushpop(candidates, candidate)
        candidates.sort(reverse=True)
        metadata_candidates = candidates[:MAX_METADATA_READS]
        if self._selected_session_id and self._path is not None:
            pinned_path = self._path
            if all(path != pinned_path for _, path in metadata_candidates):
                try:
                    pinned_stat = pinned_path.stat()
                except OSError:
                    pinned_stat = None
                if pinned_stat is not None:
                    metadata_candidates = candidates[:MAX_METADATA_READS - 1]
                    metadata_candidates.append((pinned_stat.st_mtime, pinned_path))
        discovered = []
        for modified, path in metadata_candidates:
            try:
                with path.open('rb') as stream:
                    first = stream.readline(MAX_RECORD + 1)
                if len(first) > MAX_RECORD:
                    continue
                record = json.loads(first)
            except (OSError, ValueError, UnicodeDecodeError):
                continue
            if not isinstance(record, dict) or not isinstance(record.get('payload'), dict):
                continue
            meta = record['payload']
            # Subagents have separate rollouts; their completion is not the
            # parent task's completion. Only follow user-owned root sessions.
            source = meta.get('source')
            if isinstance(source, dict) and 'subagent' in source:
                continue
            session_id = meta.get('id')
            if not isinstance(session_id, str) or not session_id:
                continue
            cwd = meta.get('cwd')
            item = {'id': session_id, 'project': Path(cwd).name if isinstance(cwd, str) else '',
                    'path': str(path), 'modified': modified}
            if all(existing['id'] != session_id for existing in discovered):
                discovered.append(item)
        by_id = {item['id']: item for item in discovered}
        selected = by_id.get(self._selected_session_id) if self._selected_session_id else None
        if selected is None and not self._selected_session_id and discovered:
            selected = discovered[0]
        self._sessions = discovered[:MAX_SESSIONS]
        if selected and all(item['id'] != selected['id'] for item in self._sessions):
            self._sessions[-1:] = [selected]
        path = Path(selected['path']) if selected else None
        if path != self._path:
            self._path = path
            if path:
                self._reset(selected)
                self._recover(path)
            else:
                self._reset(None)
                if self._selected_session_id:
                    self._error = '所选 Codex 会话暂不可用，请选择其他会话或自动跟随'

    def _recover(self, path):
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

    def select_session(self, session_id='') -> bool:
        if not self._active or not isinstance(session_id, str):
            return False
        if session_id and not any(item['id'] == session_id for item in self._sessions):
            return False
        if self._selected_session_id == session_id:
            return True
        self._selected_session_id = session_id
        self.poll(rescan=True)
        return True

    def poll(self, *, rescan=False):
        if not self._active:
            return
        try:
            now = time.monotonic()
            if rescan or self._path is None or now - self._last_scan >= 5:
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
                if not self._discarding and len(line) <= MAX_RECORD:
                    self._consume(line)
                elif len(line) > MAX_RECORD:
                    self._error = 'Codex 状态记录超过大小限制，已跳过'
                self._discarding = False
            if len(self._buffer) > MAX_RECORD:
                # Tool outputs can be very large. Skip that record without
                # retaining it indefinitely; following state records still work.
                self._buffer = b''
                self._discarding = True
                self._error = 'Codex 状态记录超过大小限制，已跳过'
        except OSError as exc:
            log.warning('Codex 状态读取失败: %s', exc.strerror or type(exc).__name__)
            self._path = None
            self._reset(None)
            self._error = f'Codex 状态读取失败: {exc.strerror or type(exc).__name__}'
        finally:
            self._publish()

    def _consume(self, line, *, announce=True):
        try:
            record = json.loads(line)
        except (ValueError, UnicodeDecodeError):
            self._error = 'Codex 状态记录格式无效'
            return
        if not isinstance(record, dict) or not isinstance(record.get('payload'), dict):
            self._error = 'Codex 状态记录结构无效'
            return
        payload = record['payload']
        state, text = None, ''
        kind = payload.get('type')
        if record.get('type') == 'event_msg' and kind == 'token_count':
            info = payload.get('info')
            limits = payload.get('rate_limits')
            if info is not None and not isinstance(info, dict):
                self._error = 'Codex 用量数据结构无效'
                return
            if limits is not None and not isinstance(limits, dict):
                self._error = 'Codex 额度数据结构无效'
                return
            observed_at = record.get('timestamp')
            if isinstance(info, dict):
                self._usage = normalize_usage(info, source='rollout', session_id=self._session_id,
                                              observed_at=observed_at)
            if isinstance(limits, dict):
                for key in ('primary', 'secondary'):
                    if key not in limits:
                        continue
                    if isinstance(limits[key], dict):
                        self._limits_data[key] = limits[key]
                    else:
                        self._limits_data.pop(key, None)
                self._limits = normalize_limits(self._limits_data, source='rollout',
                                                observed_at=observed_at)
            self._error = ''
            return
        if record.get('type') == 'event_msg':
            if kind == 'task_started':
                state, text = 'working', 'Codex 正在工作'
            elif kind == 'task_complete':
                if self._pending:
                    return  # An asynchronous question can outlive its turn.
                message = payload.get('last_agent_message')
                state, text = 'complete', message if isinstance(message, str) and message else 'Codex 已完成这一轮工作'
            elif kind == 'turn_aborted':
                self._pending.clear()
                state, text = 'idle', 'Codex 已停止'
            elif kind == 'user_message':
                self._pending.clear()
                state, text = 'working', 'Codex 正在处理你的回复'
        elif record.get('type') == 'response_item' and kind in {'function_call', 'custom_tool_call'}:
            name = payload.get('name')
            name = name.split('.')[-1] if isinstance(name, str) else ''
            # A long-running turn's start can be outside the bounded initial
            # tail. A subsequent tool call is also evidence of active work.
            state, text = 'working', 'Codex 正在工作'
            if name in {'request_user_input', 'request_user_input_async'}:
                arguments = payload.get('arguments') or '{}'
                try:
                    args = json.loads(arguments) if isinstance(arguments, str) else arguments
                except (TypeError, ValueError):
                    self._error = 'Codex 问题数据格式无效'
                    return
                call_id = payload.get('call_id')
                if not isinstance(args, dict) or type(call_id) not in (str, int):
                    self._error = 'Codex 问题数据结构无效'
                    return
                questions = self._normalize_questions(args.get('questions'))
                if not questions:
                    self._error = 'Codex 问题列表为空或格式无效'
                    return
                key = (type(call_id), call_id)
                self._pending[key] = {'request_id': call_id, 'session_id': self._session_id,
                                      'questions': questions}
                while len(self._pending) > MAX_PENDING_QUESTIONS:
                    self._pending.pop(next(iter(self._pending)))
                text = '\n'.join(question['question'] for question in questions)
                state = 'question'
        elif record.get('type') == 'response_item' and kind == 'function_call_output':
            # Blocking questions complete only after the answer. Async calls
            # return immediately, so their acknowledgements must not clear them.
            call_id = payload.get('call_id')
            output = payload.get('output')
            output = output if isinstance(output, str) else ''
            key = (type(call_id), call_id)
            if key in self._pending and ('answers' in output or 'user_response' in output):
                self._pending.pop(key, None)
                state, text = 'working', 'Codex 正在处理你的回复'
        if state is None:
            return
        if state == 'working' and self._pending:
            return
        self._error = ''
        changed = state != self._state or str(text)[:300] != self._text
        self._state = state
        self._text = str(text)[:300]
        if announce and changed:
            self.event.emit(self.snapshot())

    @staticmethod
    def _normalize_questions(raw_questions):
        if not isinstance(raw_questions, list):
            return []
        normalized = []
        for index, raw in enumerate(raw_questions[:32]):
            if not isinstance(raw, dict):
                continue
            question = raw.get('question') or raw.get('title')
            if not isinstance(question, str) or not question:
                continue
            options = []
            raw_options = raw.get('options')
            if isinstance(raw_options, list):
                for option in raw_options[:32]:
                    if not isinstance(option, dict):
                        continue
                    label = option.get('label')
                    description = option.get('description')
                    if not isinstance(label, str):
                        continue
                    options.append({'label': label[:500],
                                    'description': description[:1000] if isinstance(description, str) else ''})
            question_id = raw.get('id')
            header = raw.get('header')
            normalized.append({
                'id': question_id[:200] if isinstance(question_id, str) else f'question-{index + 1}',
                'header': header[:300] if isinstance(header, str) else '',
                'question': question[:4000],
                'options': options,
                'is_other': raw.get('is_other', raw.get('isOther')) is True,
                'is_secret': raw.get('is_secret', raw.get('isSecret')) is True,
            })
        return normalized
