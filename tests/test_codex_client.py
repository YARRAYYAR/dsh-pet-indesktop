"""Transport regression through a real QProcess and Qt event loop.

A real model cannot deterministically/safely force approval, malformed protocol,
EOF, and stale answers without touching a user's work. The isolated stdio peer
models that external boundary; the client, serialization, process and Qt are real.
Expected failures: invalid input rejects without a wire write; missing executable,
handshake error/timeout/EOF/broken frames expose error and invalidate pending;
optional account errors preserve task connection; wrong session/turn/generation/
typed request id and duplicate answers reject; stop reaps and invalidates replies.
"""
import json
from pathlib import Path
import sys

import pytest
from PySide6.QtCore import QProcess


@pytest.fixture
def make_client(qtbot, tmp_path):
    from pet.codex_client import CodexClient
    clients = []

    def create(scenario='question'):
        trace = tmp_path / (scenario + '.jsonl')
        client = CodexClient(program=sys.executable, arguments=[str(Path(__file__).parent / 'fixtures/codex_peer.py'), scenario, str(trace)], home=tmp_path / 'empty-home')
        clients.append(client)
        return client, trace
    yield create
    for client in clients:
        client.stop()
        assert client.process.state() == QProcess.ProcessState.NotRunning


def ready(qtbot, client):
    client.connect_server()
    qtbot.waitUntil(lambda: client.snapshot()['connection'] == 'ready', timeout=10000)


def start(qtbot, client, tmp_path):
    client.new_task('只处理隔离样例', str(tmp_path))
    qtbot.waitUntil(lambda: bool(client.snapshot()['turn_id']), timeout=10000)


def wire(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_connect_only_handshakes_and_reads_account(qtbot, make_client):
    client, trace = make_client()
    ready(qtbot, client)
    qtbot.waitUntil(lambda: client.snapshot()['account_usage'] is not None)
    methods = [row.get('method') for row in wire(trace)]
    assert methods == ['initialize', 'initialized', 'account/rateLimits/read', 'account/usage/read']
    assert client.snapshot()['rate_limits']['primary']['usedPercent'] == 17
    assert client.snapshot()['session_id'] == ''


@pytest.mark.parametrize('scenario', ['question', 'string-id'])
def test_owned_question_exact_identity_and_resolution(qtbot, make_client, tmp_path, scenario):
    client, trace = make_client(scenario)
    ready(qtbot, client); start(qtbot, client, tmp_path)
    qtbot.waitUntil(lambda: len(client.snapshot()['pending']) == 1)
    state = client.snapshot(); pending = state['pending'][0]
    assert pending['kind'] == 'question' and len(pending['questions']) == 2
    args = (state['session_id'], state['turn_id'], pending['request_id'])
    answers = {'q1': {'answers': ['蓝色']}, 'q2': {'answers': ['safe fixture']}}
    with pytest.raises(ValueError):
        client.answer(*args, answers, state['generation'] - 1)
    with pytest.raises(ValueError):
        client.answer('foreign', args[1], args[2], answers, state['generation'])
    with pytest.raises(ValueError):
        client.answer(args[0], 'old-turn', args[2], answers, state['generation'])
    wrong_type = str(args[2]) if isinstance(args[2], int) else int(args[2])
    with pytest.raises(ValueError):
        client.answer(args[0], args[1], wrong_type, answers, state['generation'])
    with pytest.raises(ValueError):
        client.answer(*args, {'q1': {'answers': []}}, state['generation'])
    assert client.answer(*args, answers, state['generation']) == {'accepted': True}
    with pytest.raises(ValueError):
        client.answer(*args, answers, state['generation'])
    qtbot.waitUntil(lambda: client.snapshot()['state'] == 'complete')
    assert not client.snapshot()['pending']
    assert client.snapshot()['text'] == '完成 <b>原文</b>'
    assert client.snapshot()['token_usage']['total']['totalTokens'] == 100
    responses = [row for row in wire(trace) if 'method' not in row]
    assert len(responses) == 1 and responses[0] == {'id': pending['request_id'], 'result': {'answers': answers}}
    create = next(row for row in wire(trace) if row.get('method') == 'thread/start')
    assert create['params'] == {'cwd': str(tmp_path), 'sandbox': 'workspace-write', 'approvalPolicy': 'on-request'}


@pytest.mark.parametrize('scenario,kind', [('command', 'command_approval'), ('file', 'file_approval')])
def test_approval_is_explicit_and_schema_correct(qtbot, make_client, tmp_path, scenario, kind):
    client, trace = make_client(scenario)
    ready(qtbot, client); start(qtbot, client, tmp_path)
    qtbot.waitUntil(lambda: bool(client.snapshot()['pending']))
    state = client.snapshot(); pending = state['pending'][0]
    assert pending['kind'] == kind
    args = (state['session_id'], state['turn_id'], pending['request_id'])
    with pytest.raises(ValueError):
        client.approve(*args, 'acceptForSession', state['generation'])
    client.approve(*args, 'decline', state['generation'])
    qtbot.waitUntil(lambda: client.snapshot()['state'] == 'complete')
    assert next(row for row in wire(trace) if 'method' not in row)['result'] == {'decision': 'decline'}


def test_active_steer_and_interrupt_have_turn_guards(qtbot, make_client, tmp_path):
    client, trace = make_client('active')
    ready(qtbot, client); start(qtbot, client, tmp_path)
    state = client.snapshot()
    with pytest.raises(ValueError):
        client.new_task('second', str(tmp_path))
    with pytest.raises(ValueError):
        client.send_message(state['session_id'], 'wrong', 'next')
    client.send_message(state['session_id'], state['turn_id'], '继续')
    qtbot.waitUntil(lambda: any(row.get('method') == 'turn/steer' for row in wire(trace)))
    steer = next(row for row in wire(trace) if row.get('method') == 'turn/steer')
    assert steer['params']['expectedTurnId'] == state['turn_id']
    client.interrupt(state['session_id'], state['turn_id'])
    qtbot.waitUntil(lambda: client.snapshot()['state'] == 'idle')
    client.send_message(state['session_id'], '', '新一轮')
    qtbot.waitUntil(lambda: len([row for row in wire(trace) if row.get('method') == 'turn/start']) == 2)


def test_sending_waits_for_resolution_and_stop_reaps(qtbot, make_client, tmp_path):
    client, _ = make_client('no-resolve')
    ready(qtbot, client); start(qtbot, client, tmp_path)
    qtbot.waitUntil(lambda: bool(client.snapshot()['pending']))
    state = client.snapshot(); p = state['pending'][0]
    client.answer(state['session_id'], state['turn_id'], p['request_id'], {'q1': {'answers': ['蓝色']}, 'q2': {'answers': ['x']}}, state['generation'])
    assert client.snapshot()['pending'][0]['sending']
    client.stop()
    assert not client.snapshot()['pending'] and client.snapshot()['generation'] != state['generation']
    assert client.process.state() == QProcess.ProcessState.NotRunning
    client.stop()


def test_stop_reaps_when_interrupt_write_fails(qtbot, make_client, tmp_path):
    client, _ = make_client('active')
    ready(qtbot, client); start(qtbot, client, tmp_path)
    write = client._write

    def fail_interrupt(message):
        if message.get('method') == 'turn/interrupt':
            raise ValueError('isolated write failure')
        write(message)

    client._write = fail_interrupt
    client.stop()
    assert client.process.state() == QProcess.ProcessState.NotRunning
    assert client.snapshot()['connection'] == 'disconnected'


@pytest.mark.parametrize('scenario', ['eof', 'bad-json', 'oversize', 'init-error', 'init-timeout'])
def test_handshake_failure_exposes_error_and_reaps(qtbot, make_client, monkeypatch, scenario):
    from pet import codex_client
    monkeypatch.setattr(codex_client, 'REQUEST_TIMEOUT_SECONDS', .2)
    client, _ = make_client(scenario)
    client.connect_server()
    qtbot.waitUntil(lambda: client.snapshot()['connection'] == 'error', timeout=10000)
    assert client.snapshot()['error']
    qtbot.waitUntil(lambda: client.process.state() == QProcess.ProcessState.NotRunning, timeout=10000)
    assert not client.snapshot()['can_send']


def test_missing_binary_and_invalid_inputs(qtbot, tmp_path):
    from pet.codex_client import CodexClient
    client = CodexClient(program=str(tmp_path / 'missing-binary'), home=tmp_path)
    with pytest.raises(ValueError):
        client.new_task('x', str(tmp_path))
    client.connect_server()
    qtbot.waitUntil(lambda: client.snapshot()['connection'] == 'error')
    client.stop()


@pytest.mark.parametrize('scenario', ['account-error', 'thread-error', 'turn-error', 'unknown-request'])
def test_reachable_server_failures_remain_visible(qtbot, make_client, tmp_path, scenario):
    client, trace = make_client(scenario)
    ready(qtbot, client)
    if scenario == 'account-error':
        qtbot.waitUntil(lambda: bool(client.snapshot()['error']))
        assert client.snapshot()['connection'] == 'ready'
        assert client.snapshot()['rate_limits'] is None
    else:
        client.new_task('隔离测试', str(tmp_path))
        qtbot.waitUntil(lambda: bool(client.snapshot()['error']), timeout=10000)
        assert 'denied' in client.snapshot()['error'] or '不支持' in client.snapshot()['error']
        if scenario == 'unknown-request':
            qtbot.waitUntil(lambda: any('error' in row and 'method' not in row for row in wire(trace)))
            assert not client.snapshot()['pending']
