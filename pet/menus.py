# -*- coding: utf-8 -*-
"""右键菜单与托盘菜单共用的分节构造器。

重构前 `PetWindow.contextMenuEvent` 与 `PetApp._build_tray` 各自手写了一遍
同名开关（控制面板 / 暂停 / 随机动作 / 气泡 / 切换角色 / 清理透明底噪 /
声音 / 主动打招呼 / 开机自启 / 退出），接线方式还略有出入。这里把每一节
收敛成唯一实现，调用方只声明"要不要反向同步"，避免以后改一处漏一处。

保持行为一致的关键点：
- 勾选状态必须在连接信号之前写入，否则会触发一次多余的 set_* 调用；
- `sound` 这一项在托盘用 `triggered`、在右键用 `toggled`，因为托盘会通过
  `soundChanged` 反向同步勾选状态，用 `toggled` 会形成回路。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu

from . import autostart as autostart_mod
from . import catalog

BUBBLE_LABEL = '显示对话框（气泡）'
MEME_LABEL = '气泡显示表情图片（随机）'
SOFT_EDGES_LABEL = '清理透明底噪（Alpha=1）'
EDGE_PROBE_LABEL = '边缘探头（左右贴边）'


@dataclass(frozen=True)
class ToggleSpec:
    """一个可勾选菜单项的完整声明。"""

    label: str
    checked: Callable[[], bool]
    toggled: Callable[[bool], None]
    enabled: bool = True
    sync_signal: object | None = None

    def build(self, menu: QMenu) -> QAction:
        action = menu.addAction(self.label)
        action.setCheckable(True)
        # 先写状态再连信号：避免构建时触发一次多余的 set_* 调用。
        action.setChecked(bool(self.checked()))
        action.setEnabled(self.enabled)
        action.toggled.connect(self.toggled)
        if self.sync_signal is not None:
            self.sync_signal.connect(action.setChecked)
        return action


def add_toggle(menu: QMenu, spec: ToggleSpec) -> QAction:
    return spec.build(menu)


def add_settings(menu: QMenu, open_settings: Callable[[], None]) -> QAction:
    return menu.addAction('控制面板…', open_settings)


def add_pause(menu: QMenu, win, *, checkable: bool = False,
              sync: bool = False) -> QAction:
    """暂停/继续。托盘需要显示勾选状态，右键菜单是纯命令项。"""
    action = menu.addAction('暂停 / 继续')
    if not checkable:
        action.triggered.connect(win.toggle_pause)
        return action
    action.setCheckable(True)
    action.setChecked(win.paused)
    action.toggled.connect(win.set_paused)
    if sync:
        win.pausedChanged.connect(action.setChecked)
    return action


def add_random_action(menu: QMenu, win) -> QAction:
    return menu.addAction('随机动作', win.play_random_action)


def add_bubble_toggle(menu: QMenu, win) -> QAction:
    """无文字气泡开关；关闭时窗口立即清掉命中区域。"""
    action = menu.addAction(BUBBLE_LABEL)
    action.setCheckable(True)
    action.setChecked(win.bubble_enabled)
    action.triggered.connect(win.set_bubble_enabled)
    win.bubbleChanged.connect(action.setChecked)
    return action


def add_meme_toggle(menu: QMenu, win) -> QAction:
    """v0.2.9 本地等价开关；独立版不调用模型，只随机展示包内 PNG。"""
    action = menu.addAction(MEME_LABEL)
    action.setCheckable(True)
    action.setChecked(win.whisper_image_enabled)
    action.triggered.connect(win.set_whisper_image_enabled)
    win.whisperImageChanged.connect(action.setChecked)
    return action


def add_interaction_menu(parent: QMenu, win, *, sync: bool = False,
                         sound_signal: str = 'toggled') -> QMenu:
    """互动反馈：声音开关 + 偶尔主动打招呼。"""
    menu = parent.addMenu('互动反馈')

    sound = menu.addAction('声音开关')
    sound.setCheckable(True)
    sound.setChecked(win.sound_enabled)
    if sound_signal == 'triggered':
        sound.triggered.connect(win.set_sound_enabled)
    else:
        sound.toggled.connect(win.set_sound_enabled)
    if sync:
        win.soundChanged.connect(sound.setChecked)

    greetings = menu.addAction('偶尔主动打招呼')
    greetings.setCheckable(True)
    greetings.setChecked(win.proactive_greetings)
    greetings.toggled.connect(win.set_proactive_greetings)
    if sync:
        win.proactiveGreetingsChanged.connect(greetings.setChecked)
    return menu


def add_display_menu(parent: QMenu, win, *, sync: bool = False) -> QMenu:
    """画面调整：清理透明底噪（Alpha=1）。"""
    menu = parent.addMenu('画面调整')
    add_toggle(menu, ToggleSpec(
        label=SOFT_EDGES_LABEL,
        checked=lambda: win.soft_edges,
        toggled=win.set_soft_edges,
        sync_signal=win.softEdgesChanged if sync else None,
    ))
    return menu


def add_character_menu(parent: QMenu, config, on_switch: Callable[[str], None],
                       *, label: str = '切换角色') -> QMenu:
    """切换角色；勾选当前角色，触发时交给调用方处理。"""
    menu = parent.addMenu(label)
    current = str(config.get('character', catalog.DEFAULT_CHARACTER))
    for character_id in catalog.list_available_characters():
        action = menu.addAction(character_id)
        action.setCheckable(True)
        action.setChecked(character_id == current)
        action.triggered.connect(
            lambda checked=False, cid=character_id: on_switch(cid)
        )
    return menu


def add_autostart(menu: QMenu) -> QAction:
    """开机自启；状态直接来自系统，没有持久化副本。"""
    action = menu.addAction('开机自启')
    action.setCheckable(True)
    action.setChecked(autostart_mod.is_enabled())
    action.toggled.connect(autostart_mod.set_enabled)
    return action


def add_quit(menu: QMenu, request_quit: Callable[[], None]) -> QAction:
    return menu.addAction('退出', request_quit)


SHORTCUT_ROWS = (
    ('H', '显示 / 隐藏'),
    ('P', '暂停 / 继续'),
    ('R', '随机动作'),
    ('M', '鼠标穿透'),
    ('D', '尖叫鸭'),
)
SHORTCUT_PREFIX = '⌃⌥⌘'


def add_shortcut_legend(parent: QMenu, *, enabled: bool) -> QMenu:
    """全局快捷键说明（只读展示）。"""
    menu = parent.addMenu('全局快捷键')
    for key, label in SHORTCUT_ROWS:
        item = menu.addAction(f'{SHORTCUT_PREFIX}{key}  {label}')
        item.setEnabled(False)
    status = '已启用' if enabled else '不可用（仍可使用菜单）'
    status_item = menu.addAction(f'状态：{status}')
    status_item.setEnabled(False)
    return menu
