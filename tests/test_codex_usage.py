"""Read-only Codex monitoring through temporary files and the real Qt loop.

No real Codex home, conversation, credentials, or model is accessed. Malformed
wire records are written locally because a live model cannot reliably produce
these failures without touching a user's task.
"""
import json
import os

import pytest


def record(kind, **payload):
    return {'type': 'event_msg', 'timestamp': '2026-10-21T06:00:00Z',
            'payload': {'type': kind, **payload}}


def token(total=100, last=25, limits=None):
    return record('token_count', info={
        'total_token_usage': {'total_tokens': total, 'input_tokens': 80,
                              'cached_input_tokens': 30, 'output_tokens': 20,
                              'reasoning_output_tokens': 10},
        'last_token_usage': {'total_tokens': last}, 'model_context_window': 200000},
        rate_limits=limits)


def write(path, *records):
    with path.open('a') as stream:
        for item in records:
            stream.write(json.dumps(item) + '\n')


def session(path, session_id, *records):
    write(path, {'type': 'session_meta', 'payload': {'id': session_id, 'cwd': '/work/' + session_id}}, *records)
    return path


@pytest.fixture
def monitor(qtbot, tmp_path, monkeypatch):
    from pet.codex_link import CodexMonitor

    monkeypatch.setenv('CODEX_HOME', str(tmp_path))
    instance = CodexMonitor(tmp_path, date_dirs=[tmp_path])
    yield instance
    instance.stop()


def test_initial_usage_and_incremental_replacements_do_not_replay_alerts(monitor, tmp_path, qtbot):
    path = session(tmp_path / 'rollout-a.jsonl', 'a', record('task_started'),
                   token(limits={'primary': {'used_percent': 30, 'window_minutes': 15, 'resets_at': 100}}))
    alerts, updates = [], []
    monitor.event.connect(alerts.append)
    monitor.updated.connect(updates.append)
    monitor.start()
    snap = monitor.snapshot()
    assert snap['enabled'] and snap['usage']['total']['total_tokens'] == 100
    assert snap['usage']['last']['total_tokens'] == 25
    assert snap['usage']['total']['cache_write_input_tokens'] is None
    assert snap['usage']['observed_at'] == '2026-10-21T06:00:00Z'
    assert snap['limits']['windows'][0]['window_minutes'] == 15
    assert alerts == [] and updates
    write(path, token(), token(), token(120, 20))
    monitor.poll()
    assert monitor.snapshot()['usage']['total']['total_tokens'] == 120
    assert monitor.snapshot()['usage']['last']['total_tokens'] == 20
    assert alerts == []
    write(path, token(80, 5))  # A server correction is allowed to reduce total.
    monitor.poll()
    assert monitor.snapshot()['usage']['total']['total_tokens'] == 80
    write(path, record('task_complete', last_agent_message='done'))
    qtbot.waitUntil(lambda: bool(alerts), timeout=5000)
    assert alerts[-1]['state'] == 'complete'


def test_partial_line_then_independent_usage_and_quota_updates(monitor, tmp_path):
    path = session(tmp_path / 'rollout-a.jsonl', 'a', token())
    monitor.start()
    encoded = (json.dumps(record('token_count', info=None, rate_limits={
        'secondary': {'used_percent': 44, 'window_minutes': 10080, 'resets_at': 200}})) + '\n').encode()
    with path.open('ab') as stream:
        stream.write(encoded[:25])
    monitor.poll()
    assert monitor.snapshot()['limits']['windows'] == []
    with path.open('ab') as stream:
        stream.write(encoded[25:])
    monitor.poll()
    assert monitor.snapshot()['limits']['windows'][0]['window_minutes'] == 10080
    assert monitor.snapshot()['usage']['total']['total_tokens'] == 100
    write(path, token(130, 30))  # Null quota must not erase an observed snapshot.
    monitor.poll()
    assert monitor.snapshot()['limits']['windows'][0]['used_percent'] == 44


def test_select_session_pins_atomic_usage_and_unknown_id_is_rejected(monitor, tmp_path):
    a = session(tmp_path / 'rollout-a.jsonl', 'a', token(100))
    b = session(tmp_path / 'rollout-b.jsonl', 'b', token(200))
    os.utime(a, (100, 100))
    os.utime(b, (200, 200))
    monitor.start()
    assert monitor.snapshot()['session_id'] == 'b'
    assert monitor.select_session('a')
    assert monitor.snapshot()['selected_session_id'] == 'a'
    assert monitor.snapshot()['session_id'] == 'a'
    assert monitor.snapshot()['usage']['session_id'] == 'a'
    assert monitor.snapshot()['usage']['total']['total_tokens'] == 100
    write(b, token(250))
    os.utime(b, (300, 300))
    monitor.poll()
    before = monitor.snapshot()
    assert not monitor.select_session('not-found')
    assert monitor.snapshot() == before
    assert monitor.select_session('')
    assert monitor.snapshot()['session_id'] == 'b'
    assert monitor.snapshot()['selected_session_id'] == ''
    assert monitor.snapshot()['usage']['total']['total_tokens'] == 250


@pytest.mark.parametrize('replacement', [True, False])
def test_rotation_and_truncation_reset_usage_and_pending(monitor, tmp_path, replacement):
    path = session(tmp_path / 'rollout-a.jsonl', 'a', token(10000), question())
    monitor.start()
    assert monitor.snapshot()['questions']
    updated = tmp_path / 'replacement.jsonl'
    session(updated, 'a', token(2, 1))
    if replacement:
        updated.replace(path)
    else:
        path.write_bytes(updated.read_bytes())
    monitor.poll()
    assert monitor.snapshot()['usage']['total']['total_tokens'] == 2
    assert monitor.snapshot()['questions'] == []
    assert monitor.snapshot()['state'] == 'idle'


def test_deleted_pinned_session_cannot_fall_back_or_keep_tokens(monitor, tmp_path):
    a = session(tmp_path / 'rollout-a.jsonl', 'a', token())
    session(tmp_path / 'rollout-b.jsonl', 'b', token(200))
    monitor.start()
    assert monitor.select_session('a')
    a.unlink()
    monitor.poll()
    snap = monitor.snapshot()
    assert snap['state'] == 'unavailable' and snap['error']
    assert snap['usage']['total'] is None and snap['questions'] == []
    monitor.poll()
    assert monitor.snapshot()['selected_session_id'] == 'a'
    assert monitor.snapshot()['session_id'] != 'b'


def test_stop_clears_snapshot_and_late_poll_cannot_refill(monitor, tmp_path):
    path = session(tmp_path / 'rollout-a.jsonl', 'a', token(), question())
    monitor.start()
    monitor.stop()
    write(path, token(150))
    monitor.poll()
    snap = monitor.snapshot()
    assert not snap['enabled'] and snap['state'] == 'disconnected'
    assert snap['session_id'] == '' and snap['usage']['total'] is None
    assert snap['limits']['windows'] == [] and snap['questions'] == []


def question():
    return {'type': 'response_item', 'payload': {'type': 'function_call', 'name': 'request_user_input_async',
            'call_id': 'ask-1', 'arguments': json.dumps({'questions': [{'id': 'color', 'header': '颜色',
            'question': '选择哪个颜色？', 'isOther': True, 'isSecret': False,
            'options': [{'label': '灰色', 'description': '安静'}]}]})}}


def test_question_structure_ack_and_answer_cleanup(monitor, tmp_path):
    path = session(tmp_path / 'rollout-a.jsonl', 'a', question())
    monitor.start()
    group = monitor.snapshot()['questions'][0]
    assert group['request_id'] == 'ask-1' and group['session_id'] == 'a'
    assert group['questions'][0] == {'id': 'color', 'header': '颜色', 'question': '选择哪个颜色？',
        'is_other': True, 'is_secret': False, 'options': [{'label': '灰色', 'description': '安静'}]}
    write(path, {'type': 'response_item', 'payload': {'type': 'function_call_output',
          'call_id': 'ask-1', 'output': 'Question displayed'}})
    monitor.poll()
    assert monitor.snapshot()['questions']
    write(path, record('user_message', message='灰色'))
    monitor.poll()
    assert monitor.snapshot()['questions'] == []


@pytest.mark.parametrize('bad', [None, [], 123, {'type': 'event_msg', 'payload': []},
                                    {'type': 'response_item', 'payload': {'type': 'function_call',
                                     'name': 'request_user_input', 'arguments': '[]'}}])
def test_malformed_records_are_visible_and_recover_without_crashing(monitor, tmp_path, bad):
    path = session(tmp_path / 'rollout-a.jsonl', 'a', token())
    monitor.start()
    write(path, bad)
    monitor.poll()
    assert monitor.snapshot()['error']
    write(path, token(125))
    monitor.poll()
    assert monitor.snapshot()['usage']['total']['total_tokens'] == 125
    assert not monitor.snapshot()['error']


def test_oversized_record_is_skipped_and_snapshot_copies_are_isolated(monitor, tmp_path):
    from pet.codex_link import MAX_RECORD

    path = session(tmp_path / 'rollout-a.jsonl', 'a')
    monitor.start()
    with path.open('ab') as stream:
        stream.write(b'x' * (MAX_RECORD + 100) + b'\n')
    write(path, token(11))
    for _ in range(8):
        monitor.poll()
    snap = monitor.snapshot()
    assert snap['usage']['total']['total_tokens'] == 11
    snap['usage']['total']['total_tokens'] = 999
    snap['sessions'].clear()
    assert monitor.snapshot()['usage']['total']['total_tokens'] == 11
    assert monitor.snapshot()['sessions']


def test_bad_metadata_and_subagents_do_not_block_valid_root(monitor, tmp_path):
    (tmp_path / 'rollout-bad.jsonl').write_text('[]\n')
    session(tmp_path / 'rollout-good.jsonl', 'good', token(7))
    write(tmp_path / 'rollout-agent.jsonl', {'type': 'session_meta', 'payload': {
        'id': 'subagent', 'source': {'subagent': {'parent_thread_id': 'good'}}}})
    monitor.start()
    assert monitor.snapshot()['session_id'] == 'good'
    assert [s['id'] for s in monitor.snapshot()['sessions']] == ['good']


def test_discovery_reads_metadata_within_budget_and_keeps_pinned_session(monitor, tmp_path, monkeypatch):
    from pathlib import Path

    for index in range(70):
        path = session(tmp_path / f'rollout-{index}.jsonl', f'session-{index}', token(index))
        os.utime(path, (100 + index, 100 + index))

    original_open = Path.open
    reads = []

    def count_rollout_reads(path, *args, **kwargs):
        if path.parent == tmp_path and path.name.startswith('rollout-'):
            reads.append(path)
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'open', count_rollout_reads)
    monitor.start()
    assert len(reads) <= 66  # Metadata budget, recovery, and a possible live poll.
    assert monitor.snapshot()['session_id'] == 'session-69'
    assert monitor.select_session('session-62')

    for index in range(70, 140):
        path = session(tmp_path / f'rollout-{index}.jsonl', f'session-{index}', token(index))
        os.utime(path, (300 + index, 300 + index))
    reads.clear()
    monitor.poll(rescan=True)
    assert len(reads) <= 66
    assert monitor.snapshot()['session_id'] == 'session-62'
    assert 'session-62' in [item['id'] for item in monitor.snapshot()['sessions']]


def test_normalizers_snake_and_camel_keep_unknown_values_and_true_zero():
    from pet.codex_usage import normalize_limits, normalize_usage

    snake = normalize_usage(token()['payload']['info'], source='rollout', session_id='a')
    camel = normalize_usage({'total': {'totalTokens': 100, 'inputTokens': 80, 'cachedInputTokens': 30,
        'outputTokens': 20, 'reasoningOutputTokens': 10}, 'last': {'totalTokens': 25},
        'modelContextWindow': 200000}, source='app_server', session_id='a')
    assert snake['total'] == camel['total'] and snake['last'] == camel['last']
    invalid = normalize_usage({'total': {'totalTokens': True, 'inputTokens': -1, 'outputTokens': 0,
        'cachedInputTokens': 1.5, 'reasoningOutputTokens': '10'}, 'modelContextWindow': False},
        source='app_server', session_id='b')
    assert invalid['total']['output_tokens'] == 0
    assert all(value is None for key, value in invalid['total'].items() if key != 'output_tokens')
    assert invalid['last'] is None and invalid['model_context_window'] is None
    assert normalize_usage(None, source='rollout', session_id='a')['total'] is None
    quota = normalize_limits({'primary': {'usedPercent': 0, 'windowDurationMins': 15, 'resetsAt': 0},
        'secondary': {'usedPercent': float('nan'), 'windowDurationMins': 10080}}, source='app_server')
    assert quota['windows'] == [{'window_minutes': 15, 'used_percent': 0, 'reset_at': 0}]
    assert normalize_limits({'primary': {'used_percent': -1}}, source='rollout')['windows'] == []
    assert normalize_limits({'primary': {'used_percent': 101}}, source='rollout')['windows'] == []
    assert normalize_limits({'primary': {'used_percent': 10**400}}, source='rollout')['windows'] == []
    assert normalize_limits(None, source='rollout')['windows'] == []
