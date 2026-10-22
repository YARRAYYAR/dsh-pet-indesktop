"""GUI-owned stdio client for tasks created by this pet's Codex app-server.

This never resumes Desktop threads or reads credentials. Existing Desktop tasks
belong to a different transport and must remain read-only in this client.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import shutil
import time

from PySide6.QtCore import QCoreApplication, QObject, QProcess, QProcessEnvironment, QTimer, Signal

MAX_FRAME_BYTES = 1024 * 1024
MAX_TEXT = 32768
REQUEST_TIMEOUT_SECONDS = 30.0


def _request_key(value):
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError('无效的 Codex 请求标识')
    return type(value), value


def _close_process(process):
    """Bounded fallback, also used before QObject ownership destroys QProcess."""
    if process.state() == QProcess.ProcessState.NotRunning:
        return
    process.closeWriteChannel()
    if not process.waitForFinished(400):
        process.terminate()
        if not process.waitForFinished(400):
            process.kill()
            process.waitForFinished(1000)


class CodexClient(QObject):
    changed = Signal(dict)

    def __init__(self, parent=None, *, program=None, arguments=None, home=None):
        super().__init__(parent)
        self._program = program if program is not None else shutil.which('codex')
        self._arguments = list(arguments) if arguments is not None else ['app-server', '--listen', 'stdio://']
        self.process = QProcess(self)
        if home is not None:
            env = QProcessEnvironment.systemEnvironment()
            env.insert('CODEX_HOME', str(home))
            self.process.setProcessEnvironment(env)
        self.process.started.connect(self._started)
        self.process.readyReadStandardOutput.connect(self._read)
        # Diagnostics may contain private task/provider details; consume without
        # retaining or logging them. Protocol errors use our own bounded text.
        self.process.readyReadStandardError.connect(self.process.readAllStandardError)
        self.process.errorOccurred.connect(self._process_error)
        self.process.finished.connect(self._finished)
        self.destroyed.connect(lambda _obj=None, process=self.process: _close_process(process))
        app = QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.stop)
        self._deadline = QTimer(self)
        self._deadline.setSingleShot(True)
        self._deadline.timeout.connect(self._expire)
        self._limits_timer = QTimer(self)
        self._limits_timer.setInterval(60000)
        self._limits_timer.timeout.connect(self._refresh_limits)
        self._generation = 0
        self._sequence = 0
        self._buffer = b''
        self._requests = {}
        self._pending = {}
        self._stopping = False
        self._starting = False
        self._connection = 'disconnected'
        self._state = 'idle'
        self._session_id = ''
        self._turn_id = ''
        self._text = ''
        self._project = ''
        self._token_usage = None
        self._rate_limits = None
        self._account_usage = None
        self._error = ''

    def snapshot(self):
        ready = self._connection == 'ready' and not self._starting
        text = self._text
        if self._pending:
            pending = next(iter(self._pending.values()))
            if pending['kind'] == 'question':
                text = '\n'.join(str(q.get('question') or q.get('header') or '')
                                 for q in pending['questions']).strip() or 'Codex 需要你回答'
            else:
                text = pending['summary'] or ('Codex 请求运行命令' if pending['kind'] == 'command_approval'
                                               else 'Codex 请求修改文件')
            text = text[:MAX_TEXT]
        return deepcopy({'connection': self._connection, 'generation': self._generation,
                         'session_id': self._session_id, 'turn_id': self._turn_id,
                         'state': self._state, 'text': text, 'project': self._project,
                         'pending': list(self._pending.values()), 'token_usage': self._token_usage,
                         'rate_limits': self._rate_limits, 'account_usage': self._account_usage,
                         'error': self._error,
                         'can_send': ready and bool(self._session_id) and not self._pending,
                         'can_interrupt': ready and bool(self._turn_id)})

    def _emit(self):
        self.changed.emit(self.snapshot())

    def connect_server(self):
        if self.process.state() != QProcess.ProcessState.NotRunning:
            return {'accepted': True}
        self._generation += 1
        self._buffer = b''
        self._requests.clear()
        self._pending.clear()
        self._session_id = self._turn_id = self._text = self._project = self._error = ''
        self._token_usage = self._rate_limits = self._account_usage = None
        self._starting = False
        self._state = 'idle'
        self._connection = 'connecting'
        self._emit()
        if not self._program:
            self._fail('未找到 Codex CLI，请先安装或将 codex 加入 PATH')
            return {'accepted': True}
        self.process.start(str(self._program), self._arguments)
        return {'accepted': True}

    def _started(self):
        if self._stopping:
            return
        self._request('initialize', {'clientInfo': {'name': 'seeky_pet', 'title': 'seeky pet', 'version': '1.0'},
                                     'capabilities': {'experimentalApi': True}}, self._initialized)

    def _initialized(self, result):
        del result
        self._write({'method': 'initialized'})
        self._connection = 'ready'
        self._emit()
        self._refresh_limits()
        self._request('account/usage/read', {}, self._set_account_usage, optional=True)
        self._limits_timer.start()

    def _refresh_limits(self):
        if self._connection == 'ready' and not any(r['method'] == 'account/rateLimits/read' for r in self._requests.values()):
            self._request('account/rateLimits/read', {}, self._set_rate_limits, optional=True)

    def _set_rate_limits(self, result):
        value = result.get('rateLimits')
        self._rate_limits = value if isinstance(value, dict) else None
        self._emit()

    def _set_account_usage(self, result):
        self._account_usage = result
        self._emit()

    def _write(self, message):
        if self.process.state() != QProcess.ProcessState.Running:
            raise ValueError('Codex 连接已经断开')
        raw = json.dumps(message, ensure_ascii=False, allow_nan=False).encode() + b'\n'
        if len(raw) > MAX_FRAME_BYTES or self.process.write(raw) != len(raw):
            raise ValueError('无法提交 Codex 请求')

    def _request(self, method, params, callback, *, optional=False):
        self._sequence += 1
        request_id = self._sequence
        self._requests[request_id] = {'method': method, 'callback': callback, 'optional': optional,
                                      'deadline': time.monotonic() + REQUEST_TIMEOUT_SECONDS}
        try:
            self._write({'id': request_id, 'method': method, 'params': params})
        except ValueError:
            self._requests.pop(request_id, None)
            raise
        self._arm_deadline()

    def _arm_deadline(self):
        self._deadline.stop()
        if self._requests:
            remaining = min(r['deadline'] for r in self._requests.values()) - time.monotonic()
            self._deadline.start(max(1, int(remaining * 1000) + 1))

    def _expire(self):
        now = time.monotonic()
        for key, request in list(self._requests.items()):
            if request['deadline'] <= now:
                self._requests.pop(key)
                message = f"Codex 请求超时：{request['method']}"
                if not request['optional']:
                    self._fail(message)
                    return
                self._error = message
                self._emit()
        self._arm_deadline()

    def _read(self):
        if self._stopping:
            self.process.readAllStandardOutput()
            return
        self._buffer += bytes(self.process.readAllStandardOutput())
        while b'\n' in self._buffer:
            line, self._buffer = self._buffer.split(b'\n', 1)
            if not line.strip():
                continue
            if len(line) > MAX_FRAME_BYTES:
                self._fail('Codex 协议消息超过大小限制')
                return
            try:
                message = json.loads(line)
                if not isinstance(message, dict):
                    raise ValueError
                self._consume(message)
            except (ValueError, TypeError, KeyError, RecursionError):
                self._fail('Codex 返回了无效的协议消息')
                return
            if self._connection == 'error':
                return
        if len(self._buffer) > MAX_FRAME_BYTES:
            self._fail('Codex 协议消息超过大小限制')

    def _consume(self, message):
        method = message.get('method')
        if method is not None:
            params = message.get('params') or {}
            if not isinstance(method, str) or not isinstance(params, dict):
                raise ValueError
            if 'id' in message:
                self._server_request(message['id'], method, params)
            else:
                self._notification(method, params)
            return
        request_id = message.get('id')
        # Our request IDs are ints; bool/string IDs cannot consume their callback.
        if type(request_id) is not int:
            return
        request = self._requests.pop(request_id, None)
        if request is None:
            return  # Unknown/stale responses cannot mutate the current task.
        self._arm_deadline()
        if 'error' in message:
            error = message['error']
            detail = str(error.get('message', '请求失败')) if isinstance(error, dict) else '请求失败'
            text = f"{request['method']}: {detail[:500]}"
            if request['method'] == 'initialize':
                self._fail(text)
                return
            self._error = text
            if not request['optional']:
                self._starting = False
                self._state = 'error'
            self._emit()
            return
        result = message.get('result')
        if not isinstance(result, dict):
            raise ValueError
        request['callback'](result)

    def _notification(self, method, params):
        if method == 'account/rateLimits/updated':
            self._set_rate_limits(params)
            return
        if params.get('threadId') != self._session_id or not self._session_id:
            return
        if method == 'serverRequest/resolved':
            key = _request_key(params.get('requestId'))
            if self._pending.pop(key, None) is not None:
                self._state = 'question' if self._pending else ('working' if self._turn_id else 'idle')
                self._emit()
            return
        turn = params.get('turn')
        if method == 'turn/started' and isinstance(turn, dict):
            if self._starting or turn.get('id') == self._turn_id:
                self._accept_turn(turn)
            return
        turn_id = turn.get('id') if isinstance(turn, dict) else params.get('turnId')
        if not self._turn_id or turn_id != self._turn_id:
            return
        if method == 'turn/completed':
            self._pending.clear()
            self._turn_id = ''
            self._starting = False
            status = turn.get('status')
            self._state = 'complete' if status == 'completed' else 'idle'
            if status == 'failed':
                error = turn.get('error') or {}
                self._error = str(error.get('message') or 'Codex 任务失败')[:500]
                self._state = 'error'
            self._emit()
        elif method == 'thread/tokenUsage/updated':
            if isinstance(params.get('tokenUsage'), dict):
                self._token_usage = params['tokenUsage']
                self._emit()
        elif method == 'item/completed':
            item = params.get('item')
            if isinstance(item, dict) and item.get('type') == 'agentMessage':
                self._text = str(item.get('text') or '')[:MAX_TEXT]
                self._emit()
        elif method == 'item/agentMessage/delta':
            self._text = (self._text + str(params.get('delta') or ''))[-MAX_TEXT:]
            self._emit()
        elif method == 'error':
            error = params.get('error') or {}
            self._error = str(error.get('message') or 'Codex 任务失败')[:500]
            self._emit()

    def _server_request(self, request_id, method, params):
        key = _request_key(request_id)
        kinds = {'item/tool/requestUserInput': 'question',
                 'item/commandExecution/requestApproval': 'command_approval',
                 'item/fileChange/requestApproval': 'file_approval'}
        kind = kinds.get(method)
        if kind is None:
            self._write({'id': request_id, 'error': {'code': -32601, 'message': 'Unsupported request in seeky pet'}})
            self._error = f'不支持此 Codex 请求：{method[:160]}'
            self._emit()
            return
        if params.get('threadId') != self._session_id or params.get('turnId') != self._turn_id or not self._turn_id:
            self._write({'id': request_id, 'error': {'code': -32602, 'message': 'Stale or foreign task request'}})
            return
        if key in self._pending:
            return  # A replay must not reset an already submitted answer.
        if len(self._pending) >= 16:
            self._fail('Codex 待回答请求过多，连接已停止')
            return
        questions = params.get('questions', []) if kind == 'question' else []
        if not isinstance(questions, list) or (kind == 'question' and (not questions or any(
                not isinstance(q, dict) or not isinstance(q.get('id'), str) or not q['id'] for q in questions))):
            raise ValueError
        self._pending[key] = {'request_id': request_id, 'session_id': self._session_id,
                              'turn_id': self._turn_id, 'generation': self._generation,
                              'kind': kind, 'questions': questions,
                              'summary': '\n'.join(str(params.get(k) or '') for k in ('command', 'cwd', 'reason', 'grantRoot')).strip()[:MAX_TEXT],
                              'sending': False}
        self._state = 'question'
        self._emit()

    def _ready(self):
        if self._connection != 'ready' or self.process.state() != QProcess.ProcessState.Running:
            raise ValueError('请先连接 Codex')

    @staticmethod
    def _input(text):
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT:
            raise ValueError('请输入有效内容（最多 32768 个字符）')
        return [{'type': 'text', 'text': text}]

    def new_task(self, text, cwd):
        self._ready()
        inputs = self._input(text)
        if self._starting or self._turn_id or self._pending:
            raise ValueError('请先完成或停止当前任务')
        if not isinstance(cwd, str) or not cwd or not Path(cwd).is_absolute() or not Path(cwd).is_dir():
            raise ValueError('请选择有效的绝对项目目录')
        self._error = self._text = ''
        self._token_usage = None
        self._starting = True
        self._state = 'working'

        def created(result):
            thread = result.get('thread')
            if not isinstance(thread, dict) or not isinstance(thread.get('id'), str) or not thread['id']:
                raise ValueError
            self._session_id = thread['id']
            self._project = Path(cwd).name
            self._start_turn(inputs)

        self._request('thread/start', {'cwd': str(Path(cwd).resolve()), 'sandbox': 'workspace-write',
                                       'approvalPolicy': 'on-request'}, created)
        self._emit()
        return {'accepted': True}

    def _start_turn(self, inputs):
        self._starting = True
        self._state = 'working'
        self._text = self._error = ''
        self._request('turn/start', {'threadId': self._session_id, 'input': inputs},
                      lambda result: self._accept_turn(result.get('turn')))
        self._emit()

    def _accept_turn(self, turn):
        if not isinstance(turn, dict) or not isinstance(turn.get('id'), str) or not turn['id']:
            raise ValueError
        self._turn_id = turn['id']
        self._starting = False
        self._state = 'working'
        self._emit()

    def _matching_task(self, session_id, turn_id):
        self._ready()
        if not self._session_id or session_id != self._session_id or turn_id != self._turn_id or self._starting:
            raise ValueError('任务已变化，请刷新后重试')

    def send_message(self, session_id, turn_id, text):
        self._matching_task(session_id, turn_id)
        inputs = self._input(text)
        if self._pending:
            raise ValueError('请先回答当前问题或审批')
        if self._turn_id:
            self._request('turn/steer', {'threadId': self._session_id, 'expectedTurnId': self._turn_id,
                                         'input': inputs}, lambda _result: self._emit())
        else:
            self._start_turn(inputs)
        return {'accepted': True}

    def _matching_pending(self, session_id, turn_id, request_id, generation):
        self._matching_task(session_id, turn_id)
        pending = self._pending.get(_request_key(request_id))
        if generation != self._generation or not pending or pending['sending']:
            raise ValueError('问题已过期或已提交，请刷新后重试')
        return pending

    def answer(self, session_id, turn_id, request_id, answers, generation):
        pending = self._matching_pending(session_id, turn_id, request_id, generation)
        if pending['kind'] != 'question' or not isinstance(answers, dict):
            raise ValueError('无效的问题回答')
        ids = [q['id'] for q in pending['questions']]
        if set(answers) != set(ids):
            raise ValueError('请回答每一个问题')
        for value in answers.values():
            entries = value.get('answers') if isinstance(value, dict) else None
            if not isinstance(entries, list) or not entries or any(
                    not isinstance(entry, str) or not entry.strip() or len(entry) > MAX_TEXT for entry in entries):
                raise ValueError('请填写有效回答')
        self._write({'id': request_id, 'result': {'answers': answers}})
        pending['sending'] = True
        self._emit()
        return {'accepted': True}

    def approve(self, session_id, turn_id, request_id, decision, generation):
        pending = self._matching_pending(session_id, turn_id, request_id, generation)
        if pending['kind'] not in {'command_approval', 'file_approval'} or decision not in {'accept', 'decline'}:
            raise ValueError('无效的审批决定')
        self._write({'id': request_id, 'result': {'decision': decision}})
        pending['sending'] = True
        self._emit()
        return {'accepted': True}

    def interrupt(self, session_id, turn_id):
        self._matching_task(session_id, turn_id)
        if not self._turn_id:
            raise ValueError('没有正在运行的任务')
        self._request('turn/interrupt', {'threadId': self._session_id, 'turnId': self._turn_id}, lambda _result: None)
        return {'accepted': True}

    def _process_error(self, _error):
        if not self._stopping:
            self._fail('无法启动或维持 Codex 连接，请检查 CLI 和登录状态')

    def _finished(self, _code, _status):
        if not self._stopping and self._connection != 'disconnected':
            self._fail('Codex 连接已退出，请重新连接')

    def _fail(self, message):
        self._connection = 'error'
        self._state = 'error'
        self._error = message
        self._pending.clear()
        self._requests.clear()
        self._buffer = b''
        self._starting = False
        self._deadline.stop()
        self._limits_timer.stop()
        self._stopping = True
        try:
            _close_process(self.process)
        finally:
            self._stopping = False
        self._emit()

    def stop(self):
        if self._stopping:
            return
        self._stopping = True
        try:
            if self._turn_id and self.process.state() == QProcess.ProcessState.Running:
                self._sequence += 1
                try:
                    self._write({'id': self._sequence, 'method': 'turn/interrupt',
                                 'params': {'threadId': self._session_id, 'turnId': self._turn_id}})
                except ValueError:
                    # The child is still reaped below if its input pipe is unavailable.
                    pass
        finally:
            try:
                _close_process(self.process)
            finally:
                self._stopping = False
                self._generation += 1
                self._requests.clear()
                self._pending.clear()
                self._buffer = b''
                self._starting = False
                self._deadline.stop()
                self._limits_timer.stop()
                self._connection = 'disconnected'
                self._state = 'idle'
                self._session_id = self._turn_id = self._text = self._project = self._error = ''
                self._token_usage = self._rate_limits = self._account_usage = None
                self._emit()
