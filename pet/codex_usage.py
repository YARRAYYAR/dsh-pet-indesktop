"""Normalize public Codex usage snapshots without account or file access."""
from __future__ import annotations

import math


TOKEN_FIELDS = {
    'total_tokens': 'totalTokens',
    'input_tokens': 'inputTokens',
    'cached_input_tokens': 'cachedInputTokens',
    'cache_write_input_tokens': 'cacheWriteInputTokens',
    'output_tokens': 'outputTokens',
    'reasoning_output_tokens': 'reasoningOutputTokens',
}


def _integer(value, *, minimum=0):
    return value if type(value) is int and minimum <= value <= 2**63 - 1 else None


def _field(data, snake, camel):
    return data.get(snake) if snake in data else data.get(camel)


def _breakdown(data):
    if not isinstance(data, dict):
        return None
    values = {snake: _integer(_field(data, snake, camel)) for snake, camel in TOKEN_FIELDS.items()}
    return values if any(value is not None for value in values.values()) else None


def normalize_usage(info, *, source, session_id, observed_at=None):
    """Keep cumulative total and last response separate; missing is not zero."""
    info = info if isinstance(info, dict) else {}
    return {
        'source': source, 'session_id': session_id,
        'observed_at': observed_at if isinstance(observed_at, str) else None,
        'total': _breakdown(_field(info, 'total_token_usage', 'total')),
        'last': _breakdown(_field(info, 'last_token_usage', 'last')),
        'model_context_window': _integer(_field(info, 'model_context_window', 'modelContextWindow'), minimum=1),
    }


def normalize_limits(data, *, source, observed_at=None):
    """Display the reported window duration, never assume primary means 5h."""
    data = data if isinstance(data, dict) else {}
    windows = []
    for name in ('primary', 'secondary'):
        window = data.get(name)
        if not isinstance(window, dict):
            continue
        used = _field(window, 'used_percent', 'usedPercent')
        if type(used) not in (int, float) or not 0 <= used <= 100 or not math.isfinite(used):
            continue
        windows.append({
            'window_minutes': _integer(_field(window, 'window_minutes', 'windowDurationMins'), minimum=1),
            'used_percent': used,
            'reset_at': _integer(_field(window, 'resets_at', 'resetsAt')),
        })
    return {'source': source, 'observed_at': observed_at if isinstance(observed_at, str) else None,
            'windows': windows}
