"""Discover actual temporary rollouts through the public monitor and Qt loop.

The inputs are synthetic files because filling a real Codex home would touch
private sessions. A directory beyond the candidate budget must still expose its
latest session; a busy first date directory must not starve the next one.
Metadata parsing remains covered by the existing bounded-read/pinning flow.
"""
import json
import os

import pytest


@pytest.mark.parametrize('split_dates', [False, True])
def test_latest_rollout_beyond_candidate_budget_is_discovered(qtbot, tmp_path, split_dates):
    from pet.codex_link import CodexMonitor, MAX_DISCOVERY_FILES

    today = tmp_path / 'today'
    previous = tmp_path / 'previous'
    today.mkdir()
    previous.mkdir()
    for index in range(MAX_DISCOVERY_FILES + 1):
        directory = previous if split_dates and index == MAX_DISCOVERY_FILES else today
        path = directory / f'rollout-{index:04d}.jsonl'
        path.write_text(json.dumps({
            'type': 'session_meta',
            'payload': {'id': f'session-{index}', 'cwd': '/isolated/project'},
        }) + '\n')
        os.utime(path, (1000 + index, 1000 + index))
    # The actual filesystem enumeration, rather than a guessed filename order,
    # identifies the entry excluded by the old early-islice implementation.
    paths = [*today.glob('rollout-*.jsonl'), *previous.glob('rollout-*.jsonl')]
    newest = paths[MAX_DISCOVERY_FILES]
    os.utime(newest, (100000, 100000))
    expected = json.loads(newest.read_text())['payload']['id']
    monitor = CodexMonitor(tmp_path, date_dirs=[today, previous])
    try:
        monitor.start()
        qtbot.waitUntil(lambda: monitor.snapshot()['session_id'] == expected, timeout=1000)
        assert monitor.snapshot()['sessions'][0]['id'] == expected
        assert monitor.snapshot()['enabled']
    finally:
        monitor.stop()
