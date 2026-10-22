"""Deterministic stdio peer: no models, login, network, or real user sessions."""
import json
import os
from pathlib import Path
import sys

default_scenario = len(sys.argv) == 1
scenario, trace_path = sys.argv[1:] if not default_scenario else ('question', str(Path(os.environ['CODEX_HOME']) / 'peer-wire.jsonl'))
trace = Path(trace_path)
trace.parent.mkdir(parents=True, exist_ok=True)
thread_id, turn_id = 'owned-thread', 'owned-turn'
request_id = '7' if scenario == 'string-id' else 7


def emit(value):
    raw = json.dumps(value).encode() + b'\n'
    # Split every frame to exercise real pipe/Qt incremental reads.
    sys.stdout.buffer.write(raw[:7])
    sys.stdout.buffer.flush()
    sys.stdout.buffer.write(raw[7:])
    sys.stdout.buffer.flush()


def note(method, params):
    emit({'method': method, 'params': params})


def complete():
    note('item/completed', {'threadId': thread_id, 'turnId': turn_id,
                           'item': {'type': 'agentMessage', 'text': '完成 <b>原文</b>'}})
    note('turn/completed', {'threadId': thread_id,
                           'turn': {'id': turn_id, 'status': 'completed', 'error': None}})


for line in sys.stdin.buffer:
    message = json.loads(line)
    with trace.open('a') as stream:
        stream.write(json.dumps(message) + '\n')
    method, params = message.get('method'), message.get('params', {})
    if method == 'initialize':
        if scenario == 'init-timeout':
            continue
        if scenario == 'eof':
            break
        if scenario == 'bad-json':
            sys.stdout.write('not-json\n'); sys.stdout.flush(); continue
        if scenario == 'oversize':
            sys.stdout.write('x' * (1024 * 1024 + 1)); sys.stdout.flush(); continue
        if scenario == 'init-error':
            emit({'id': message['id'], 'error': {'code': -1, 'message': 'init denied'}})
        else:
            emit({'id': 'unknown-id', 'result': {}})
            emit({'id': message['id'], 'result': {'userAgent': 'isolated-peer'}})
    elif method == 'account/rateLimits/read':
        if scenario == 'account-error':
            emit({'id': message['id'], 'error': {'code': 401, 'message': 'not signed in'}})
        else:
            emit({'id': message['id'], 'result': {'rateLimits': {'primary': {'usedPercent': 17, 'windowDurationMins': 300, 'resetsAt': 1800000000}}}})
    elif method == 'account/usage/read':
        emit({'id': message['id'], 'result': {'daily': [], 'totalTokens': 321}})
    elif method == 'thread/start':
        if scenario == 'thread-error':
            emit({'id': message['id'], 'error': {'code': -1, 'message': 'thread denied'}})
        else:
            emit({'id': message['id'], 'result': {'thread': {'id': thread_id, 'cwd': params['cwd']}}})
    elif method == 'turn/start':
        if scenario == 'turn-error':
            emit({'id': message['id'], 'error': {'code': -1, 'message': 'turn denied'}}); continue
        emit({'id': message['id'], 'result': {'turn': {'id': turn_id, 'status': 'inProgress'}}})
        note('turn/started', {'threadId': thread_id, 'turn': {'id': turn_id}})
        usage = {'total': {'totalTokens': 100, 'inputTokens': 80, 'cachedInputTokens': 20, 'outputTokens': 20, 'reasoningOutputTokens': 5}, 'last': {'totalTokens': 30}, 'modelContextWindow': 200000}
        note('thread/tokenUsage/updated', {'threadId': thread_id, 'turnId': turn_id, 'tokenUsage': usage})
        if scenario in ('active', 'thread-error', 'turn-error'):
            continue
        if scenario in ('command', 'file'):
            kind = 'commandExecution' if scenario == 'command' else 'fileChange'
            emit({'id': request_id, 'method': f'item/{kind}/requestApproval',
                  'params': {'threadId': thread_id, 'turnId': turn_id, 'itemId': 'item-1', 'command': 'echo hello', 'reason': '需要批准'}})
        elif scenario == 'unknown-request':
            emit({'id': request_id, 'method': 'future/unsupported', 'params': {'threadId': thread_id, 'turnId': turn_id}})
        else:
            emit({'id': request_id, 'method': 'item/tool/requestUserInput', 'params': {
                'threadId': thread_id, 'turnId': turn_id, 'itemId': 'item-1', 'isBlocking': True,
                'questions': [{'id': 'q1', 'header': '颜色', 'question': '选择颜色？', 'options': [{'label': '蓝色', 'description': 'Blue'}]},
                              {'id': 'q2', 'header': '说明', 'question': '补充内容', 'isOther': True, 'isSecret': True, 'options': None}][:1] if default_scenario else [{'id': 'q1', 'header': '颜色', 'question': '选择颜色？', 'options': [{'label': '蓝色', 'description': 'Blue'}]}, {'id': 'q2', 'header': '说明', 'question': '补充内容', 'isOther': True, 'isSecret': True, 'options': None}]}})
    elif method == 'turn/steer':
        emit({'id': message['id'], 'result': {'turnId': turn_id}})
    elif method == 'turn/interrupt':
        emit({'id': message['id'], 'result': {}})
        note('turn/completed', {'threadId': thread_id, 'turn': {'id': turn_id, 'status': 'interrupted'}})
    elif method is None and ('result' in message or 'error' in message):
        if scenario != 'no-resolve':
            note('serverRequest/resolved', {'threadId': thread_id, 'requestId': message['id']})
            complete()
