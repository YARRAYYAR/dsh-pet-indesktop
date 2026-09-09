# -*- coding: utf-8 -*-
"""
配置持久化（跨平台）：
- Windows：%APPDATA%/dsh-pet-standalone/config.json
- macOS：~/Library/Application Support/dsh-pet-standalone/config.json
- Linux：~/.config/dsh-pet-standalone/config.json

记录：位置（相对屏幕可用区的中心比例，分辨率变化后仍正确）、
朝向、缩放、置顶开关。
"""

from __future__ import annotations

import json
import logging
import math
import os
import sys
from contextlib import contextmanager
from pathlib import Path

from . import catalog


def _default_base() -> Path:
    """按平台返回配置根目录（Windows=APPDATA，macOS=Application Support，Linux=~/.config）。"""
    if sys.platform == 'win32':
        return Path(os.environ.get('APPDATA') or Path.home())
    if sys.platform == 'darwin':
        return Path.home() / 'Library' / 'Application Support'
    return Path.home() / '.config'


class Config:
    def __init__(self, base: Path | str | None = None) -> None:
        base = Path(base) if isinstance(base, str) else (base or _default_base())
        self.dir = base / 'dsh-pet-standalone'
        self.path = self.dir / 'config.json'
        self._warned_save = False
        self._save_depth = 0
        self._save_pending = False
        self.data: dict = {
            'version': 2,  # 配置结构版本；scale 语义变更时递增
            'rx': None,    # 窗口中心 x / 屏幕可用区宽（None=默认右下角）
            'ry': None,    # 窗口中心 y / 屏幕可用区高
            'screen': None,  # 上次使用的屏幕名称；找不到时回退主屏
            'facing': 'left',
            'scale': catalog.DEFAULT_SCALE,
            'on_top': True,
            'no_move': False,  # 不移动：勾选后状态机不再自动移动，仅手动点移动动画才走动
            'character': catalog.DEFAULT_CHARACTER,  # 当前形象 ID
            'playback_speed': 1.0,       # 动画播放速率
            'mouse_through': False,        # 鼠标穿透
            'drag_physics': False,         # 拖动物理效果
            'soft_edges': True,             # 兼容旧配置：清理精确 Alpha=1 底噪
            'sound_enabled': True,          # 全部音效开关
            'volume': 80,
            'duck_sound': True,             # 旧配置兼容字段
            'proactive_greetings': True,    # 偶尔主动播放挥手问候
            'bubble_enabled': True,         # 显示无文字动态气泡
            'bubble_offset_x': 0,
            'bubble_offset_y': 0,
            'favorites': [],                # 用户收藏的动画名
            'playlist': [],                 # 播放列表动画名
            'playlist_mode': 'off',         # off / loop / random
            'personality': 'lively',        # catalog.PERSONALITY_PRESETS 中的随机/性格模式
            'action_switch_delay_ms': 0,    # 动作结束后的切换等待，0=立即
            'action_interval_seconds': 0,   # 0=跟随模式；否则自动动作最小开始间隔
        }
        self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return
        if not isinstance(raw, dict):
            return
        if 'sound_enabled' not in raw and 'duck_sound' in raw:
            raw['sound_enabled'] = raw['duck_sound']
        try:
            version = int(raw.get('version', 1))
        except (TypeError, ValueError):
            version = 1
        if version < 2:
            # v1 → v2：素材从 220×124 换成 640×360，scale 语义变化，
            # 旧 scale（如 1.0 表示 220px）需重置为新的默认值。
            raw.pop('scale', None)
        for key in self.data:
            if key in raw and raw[key] is not None:
                self.data[key] = raw[key]
        self._normalize()

    def _normalize(self) -> None:
        """把外部 JSON 限制到窗口层可以安全消费的类型和值域。"""
        for key in ('bubble_offset_x', 'bubble_offset_y'):
            try:
                value = int(self.data[key])
            except (TypeError, ValueError, OverflowError):
                value = 0
            self.data[key] = max(-90, min(90, value))
        for key, default in (
            ('scale', catalog.DEFAULT_SCALE),
            ('playback_speed', 1.0),
        ):
            try:
                value = float(self.data[key])
            except (TypeError, ValueError):
                value = float(default)
            if not math.isfinite(value):
                value = float(default)
            self.data[key] = max(0.1, min(4.0 if key == 'playback_speed' else 2.0, value))

        try:
            delay = int(self.data['action_switch_delay_ms'])
        except (KeyError, TypeError, ValueError):
            delay = 0
        self.data['action_switch_delay_ms'] = max(0, min(60_000, delay))
        try:
            interval = int(self.data['action_interval_seconds'])
        except (TypeError, ValueError, OverflowError):
            interval = 0
        self.data['action_interval_seconds'] = max(0, min(3600, interval))
        try:
            volume = int(self.data['volume'])
        except (TypeError, ValueError, OverflowError):
            volume = 80
        self.data['volume'] = max(0, min(100, volume))

        for key in (
            'on_top', 'no_move', 'mouse_through', 'drag_physics',
            'soft_edges', 'sound_enabled', 'duck_sound', 'proactive_greetings',
            'bubble_enabled',
        ):
            if not isinstance(self.data[key], bool):
                value = self.data[key]
                if isinstance(value, (int, float)):
                    value = bool(value)
                elif isinstance(value, str):
                    value = value.strip().lower() not in ('', '0', 'false', 'no', 'off')
                else:
                    value = True
                self.data[key] = value
        self.data['duck_sound'] = self.data['sound_enabled']

        if self.data['facing'] not in ('left', 'right'):
            self.data['facing'] = 'left'
        if not catalog.is_valid_character_id(self.data['character']):
            self.data['character'] = catalog.DEFAULT_CHARACTER

        for key in ('rx', 'ry'):
            value = self.data[key]
            if value is None:
                continue
            try:
                value = float(value)
            except (TypeError, ValueError):
                value = None
            if value is not None and math.isfinite(value):
                self.data[key] = max(0.0, min(1.0, value))
            else:
                self.data[key] = None

        if not isinstance(self.data['screen'], str) or not self.data['screen'].strip():
            self.data['screen'] = None

        for key in ('favorites', 'playlist'):
            value = self.data[key]
            if not isinstance(value, list):
                self.data[key] = []
            else:
                self.data[key] = list(dict.fromkeys(
                    item for item in value if isinstance(item, str)
                ))
        if self.data['playlist_mode'] not in ('off', 'loop', 'random'):
            self.data['playlist_mode'] = 'off'
        if self.data['personality'] not in catalog.PERSONALITY_PRESETS:
            self.data['personality'] = 'lively'
        self.data['version'] = 2

    def get(self, key: str, default=None):
        return self.data.get(key, default)

    def set(self, key: str, value) -> None:
        self.data[key] = value

    @contextmanager
    def batch_save(self):
        """合并同一次设置操作的写盘请求，保留现有原子保存方式。"""
        self._save_depth += 1
        try:
            yield
        finally:
            self._save_depth -= 1
            if self._save_depth == 0 and self._save_pending:
                self._save_pending = False
                self.save()

    def save(self) -> None:
        if self._save_depth:
            self._save_pending = True
            return
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            tmp_path = self.path.with_name(f'.{self.path.name}.tmp')
            with tmp_path.open('w', encoding='utf-8') as handle:
                json.dump(self.data, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, self.path)
            self._warned_save = False
        except (OSError, TypeError, ValueError):
            if not self._warned_save:
                logging.error('配置保存失败：%s', self.path, exc_info=True)
                self._warned_save = True
