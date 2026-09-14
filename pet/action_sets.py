# -*- coding: utf-8 -*-
"""收藏夹与播放列表的数据层：增删、持久化与下一条选择。

原本这段逻辑散在窗口里，和对话框、QMenu、QTimer 交织在一起，只能靠
真实窗口才能验证"循环播放的下一条对不对"。抽出来之后它是纯数据操作，
可以直接单测（见 tests/test_action_sets.py）。

不含任何 UI 与信号：窗口负责弹对话框、发 playlistChanged。
"""

from __future__ import annotations

from typing import Callable, Sequence

FAVORITES_KEY = 'favorites'
PLAYLIST_KEY = 'playlist'
MODE_KEY = 'playlist_mode'

MODE_OFF = 'off'
MODE_LOOP = 'loop'
MODE_RANDOM = 'random'
MODES = (MODE_OFF, MODE_LOOP, MODE_RANDOM)


class ActionSets:
    """当前角色的收藏夹与播放列表。"""

    def __init__(self, config, available: Sequence[str]) -> None:
        self._config = config
        self.favorites: list[str] = []
        self.playlist: list[str] = []
        self.mode: str = MODE_OFF
        self.index: int = -1
        self.reload(available)

    # ------------------------------------------------------------ 载入
    def reload(self, available: Sequence[str]) -> None:
        """从配置载入并丢弃当前角色不存在的动作。"""
        names = list(available)
        known = set(names)
        self.favorites = [n for n in self._config_names(FAVORITES_KEY) if n in known]
        self.playlist = [n for n in self._config_names(PLAYLIST_KEY) if n in known]
        mode = str(self._config.get(MODE_KEY, MODE_OFF))
        self.mode = mode if mode in MODES else MODE_OFF
        self.index = -1

    def _config_names(self, key: str) -> list[str]:
        """读取配置中的动作名列表，过滤异常值并保持原顺序。"""
        value = self._config.get(key, [])
        return [n for n in value if isinstance(n, str)] if isinstance(value, list) else []

    def _persist(self, key: str) -> None:
        self._config.set(key, list(self.favorites if key == FAVORITES_KEY
                                   else self.playlist))
        self._config.save()

    # ------------------------------------------------------------ 收藏夹
    def toggle_favorite(self, name: str) -> list[str]:
        if name in self.favorites:
            self.favorites.remove(name)
        else:
            self.favorites.append(name)
        self._persist(FAVORITES_KEY)
        return list(self.favorites)

    # ------------------------------------------------------------ 播放列表
    def apply(self, key: str, selected: Sequence[str],
              available: Sequence[str]) -> list[str]:
        """用对话框结果覆盖某个动作集合；返回过滤后的结果。"""
        known = set(available)
        picked = [n for n in selected if n in known]
        if key == FAVORITES_KEY:
            self.favorites = list(picked)
        else:
            self.playlist = list(picked)
            self.index = -1
            if not self.playlist and self.mode != MODE_OFF:
                self.mode = MODE_OFF
                self._config.set(MODE_KEY, MODE_OFF)
        self._persist(key)
        return list(picked)

    def playlist_from_favorites(self) -> list[str]:
        self.playlist = list(self.favorites)
        self.index = -1
        self._persist(PLAYLIST_KEY)
        return list(self.playlist)

    def set_mode(self, mode: str) -> bool:
        """设置播放模式；非法值或空列表时返回 False 且保持原状。"""
        if mode not in MODES:
            return False
        if mode != MODE_OFF and not self.playlist:
            return False
        self.mode = mode
        self._config.set(MODE_KEY, mode)
        self._config.save()
        return True

    def next_name(self, *, current: str | None,
                  picker: Callable[[list[str], str | None], str | None]) -> str | None:
        """下一条要播的动作；播放列表为空时返回 None。

        循环模式按固定顺序推进，随机模式交给 picker（以便复用"排除当前
        动作 / 跳过坏素材"的既有规则）。
        """
        if not self.playlist:
            return None
        if self.mode == MODE_RANDOM:
            return picker(list(self.playlist), current)
        self.index = (self.index + 1) % len(self.playlist)
        return self.playlist[self.index]

    def mark_current(self, name: str) -> None:
        """跟随外部切换，让循环播放的游标停在当前动作上。"""
        if name in self.playlist:
            self.index = self.playlist.index(name)
