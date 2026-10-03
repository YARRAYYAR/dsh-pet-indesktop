"""Persisted Codex message appearance, independent of Qt and pet scale."""
import math
import re

DEFAULT_TASK_APPEARANCE = {'background': '#1c1c1e', 'accent': '#707078', 'scale': 100}
TASK_PRESETS = {
    '中性黑灰': DEFAULT_TASK_APPEARANCE,
    '海洋蓝': {'background': '#102d46', 'accent': '#75bde8', 'scale': 100},
    '暖纸白': {'background': '#f3e7d0', 'accent': '#805c40', 'scale': 100},
}


def valid_task_color(value):
    return isinstance(value, str) and re.fullmatch(r'#[0-9a-fA-F]{6}', value) is not None


def clean_task_appearance(value):
    source = value if isinstance(value, dict) else {}
    result = dict(DEFAULT_TASK_APPEARANCE)
    for key in ('background', 'accent'):
        if valid_task_color(source.get(key)):
            result[key] = source[key].lower()
    try:
        scale = float(source.get('scale', 100))
    except (TypeError, ValueError, OverflowError):
        scale = 100
    if not math.isfinite(scale) or isinstance(source.get('scale'), bool):
        scale = 100
    result['scale'] = round(max(80, min(160, scale)))
    return result


def task_foreground(background):
    channels = [int(background[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    luminance = sum(c * weight for c, weight in zip(linear, (0.2126, 0.7152, 0.0722)))
    return '#ffffff' if 1.05 / (luminance + 0.05) >= (luminance + 0.05) / 0.05 else '#000000'
