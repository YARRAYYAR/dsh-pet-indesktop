# -*- coding: utf-8 -*-
"""启动前的无 GUI 环境自检，供 --selftest 和故障诊断使用。"""

from __future__ import annotations

import os
import sys

from . import catalog
from .config import Config
from .webm_clip import WebMClip, _ffmpeg_safe_path, imageio_ffmpeg


def preflight(config: Config) -> list[str]:
    """返回必须在启动前修复的问题；空列表表示可进入 GUI 启动。"""
    problems: list[str] = []
    character_id = str(config.get('character', catalog.DEFAULT_CHARACTER))
    if not catalog.is_valid_character_id(character_id):
        problems.append(f'角色 ID 非法：{character_id!r}')
        character_id = catalog.DEFAULT_CHARACTER

    video_dir = catalog.resolve_character_video_dir(character_id)
    webm_exists = video_dir.is_dir() and any(video_dir.rglob('*.webm'))
    gif_exists = video_dir.is_dir() and any(video_dir.rglob('*.gif'))
    if not video_dir.is_dir():
        problems.append(f'角色素材目录不存在：{video_dir}')
    elif not webm_exists and not gif_exists:
        problems.append(f'角色素材目录为空：{video_dir}')
    elif webm_exists and not WebMClip.available:
        detail = str(getattr(imageio_ffmpeg, '__name__', 'imageio-ffmpeg'))
        problems.append(f'缺少 WebM 解码依赖：{detail}')

    if sys.platform == 'win32' and not str(video_dir).isascii():
        safe = _ffmpeg_safe_path(video_dir)
        if safe == str(video_dir):
            problems.append('素材路径含非 ASCII 字符且无法获取短路径名')

    try:
        config.dir.mkdir(parents=True, exist_ok=True)
        if not os.access(config.dir, os.W_OK):
            problems.append(f'配置目录不可写：{config.dir}')
    except OSError as exc:
        problems.append(f'配置目录不可用：{config.dir}（{exc}）')
    return problems


def format_preflight(problems: list[str]) -> str:
    if not problems:
        return 'preflight: OK'
    return 'preflight: FAILED\n' + '\n'.join(f'- {problem}' for problem in problems)
