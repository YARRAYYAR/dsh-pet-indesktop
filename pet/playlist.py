"""Versioned playlist exchange; names only, never executable paths or settings."""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QIODevice, QSaveFile

MAX_PLAYLIST_BYTES = 1024 * 1024
MAX_ACTIONS = 10000
PLAYLIST_FORMAT = 'dsh-pet-playlist'


def read_playlist(path: str | Path, available: list[str]) -> tuple[list[str], list[str]]:
    with Path(path).open('rb') as handle:
        data = handle.read(MAX_PLAYLIST_BYTES + 1)
    if len(data) > MAX_PLAYLIST_BYTES:
        raise ValueError('播放列表超过 1 MB，无法导入。')
    try:
        payload = json.loads(data.decode('utf-8-sig'))
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise ValueError('文件不是有效的 UTF-8 JSON 播放列表。') from exc
    if not isinstance(payload, dict) or payload.get('format') != PLAYLIST_FORMAT:
        raise ValueError('不是 DSH-Pet 播放列表文件。')
    if type(payload.get('version')) is not int or payload['version'] != 1:
        raise ValueError('不支持这个播放列表版本。')
    actions = payload.get('actions')
    if not isinstance(actions, list) or len(actions) > MAX_ACTIONS:
        raise ValueError('动作列表格式错误或数量过多。')
    if any(not isinstance(name, str) or not name.strip() or len(name) > 512 for name in actions):
        raise ValueError('动作名称必须是非空字符串，且不超过 512 个字符。')
    available_set = set(available)
    unique = list(dict.fromkeys(actions))
    selected = [name for name in unique if name in available_set]
    missing = [name for name in unique if name not in available_set]
    if unique and not selected:
        raise ValueError('当前角色没有文件中的动作，原列表保持不变。')
    return selected, missing


def write_playlist(path: str | Path, actions: list[str]) -> None:
    data = (json.dumps({
        'format': PLAYLIST_FORMAT,
        'version': 1,
        'actions': list(dict.fromkeys(actions)),
    }, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    output = QSaveFile(str(path))
    if not output.open(QIODevice.OpenModeFlag.WriteOnly):
        raise OSError(output.errorString())
    if output.write(data) != len(data):
        output.cancelWriting()
        raise OSError(output.errorString())
    if not output.commit():
        raise OSError(output.errorString())
