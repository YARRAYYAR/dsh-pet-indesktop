# -*- coding: utf-8 -*-
"""
应用入口 —— QApplication + 桌宠窗口 + 系统托盘。

支持运行时切换角色：
- 右键桌宠 →「切换角色」
- 托盘菜单 →「切换角色」
切换后会热加载对应形象的 webm，并保留位置/朝向等配置。
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from . import catalog
from . import menus
from .config import Config
from .hotkeys import GlobalHotkeys
from .library import MovieLibrary
from .preflight import format_preflight, preflight
from .window import PetWindow


def _setup_logging(config: Config) -> None:
    config.dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        config.dir / 'pet.log',
        maxBytes=2 * 1024 * 1024,
        backupCount=2,
        encoding='utf-8',
    )
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(message)s',
        handlers=[handler],
        force=True,
    )


def _show_startup_error(title: str, message: str) -> None:
    QMessageBox.critical(None, title, message)


def _resource_path(*parts: str) -> Path:
    """返回源码运行与 PyInstaller 运行都可用的资源路径。"""
    if getattr(sys, 'frozen', False):
        root = Path(getattr(sys, '_MEIPASS', Path(sys.executable).resolve().parent))
    else:
        root = Path(__file__).resolve().parent.parent
    return root.joinpath(*parts)


def _configure_qt_plugins() -> None:
    """注册随应用分发的 Qt 插件目录，避免 macOS 找不到平台插件。"""
    plugin_root = _resource_path('qt-plugins')
    if plugin_root.is_dir():
        QCoreApplication.addLibraryPath(str(plugin_root))


def _application_icon() -> QIcon:
    icon_path = _resource_path('assets', 'app-icon.png')
    return QIcon(str(icon_path)) if icon_path.is_file() else QIcon()


class PetApp:
    """管理桌宠窗口、托盘与角色热切换。"""

    def __init__(self, app: QApplication, config: Config) -> None:
        self.app = app
        self.config = config
        self.win: PetWindow | None = None
        self.clones: list[PetWindow] = []
        self.tray: QSystemTrayIcon | None = None
        self._clone_count_action = None
        self._quit_bound = False
        self.hotkeys = GlobalHotkeys(self._handle_hotkey)

    # ------------------------------------------------------------ 启动
    def start(self) -> None:
        character_id = str(self.config.get('character', catalog.DEFAULT_CHARACTER))
        logging.info('当前形象: %s', character_id)
        if not self._quit_bound:
            self.app.aboutToQuit.connect(self.shutdown)
            self._quit_bound = True
        self.hotkeys.start()
        try:
            self._create_ui(character_id)
        except FileNotFoundError:
            if character_id == catalog.DEFAULT_CHARACTER:
                raise
            logging.exception('配置中的形象不可用，回退到默认形象: %s', character_id)
            self.config.set('character', catalog.DEFAULT_CHARACTER)
            self.config.save()
            self._create_ui(catalog.DEFAULT_CHARACTER)

    def _create_library(self, character_id: str, *, cache_limit: int | None = None) -> MovieLibrary:
        scale = float(self.config.get('scale', catalog.DEFAULT_SCALE))
        options = dict(
            character_id=character_id,
            decode_size=catalog.decode_size_for_scale(scale),
            soft_edges=bool(self.config.get('soft_edges', True)),
        )
        if cache_limit is not None:
            options['cache_limit'] = cache_limit
        lib = MovieLibrary(**options)
        logging.info('素材加载完成：%s %d 段动画', character_id, len(lib.names()))
        return lib

    def _wire_window(self, win: PetWindow, *, is_clone: bool = False) -> None:
        win.on_switch_character = self.switch_character
        win.on_add_clone = self.add_clone
        win.on_remove_clone = self.remove_clone if is_clone else None

    @staticmethod
    def _clone_position(base: PetWindow, clone: PetWindow, index: int) -> tuple[int, int]:
        """从主桌宠旁边按网格错开放置复制体，并限制在联合工作区内。"""
        step = max(32, int(round(56 * clone.scale)))
        slot = max(0, index - 1)
        column, row = slot % 4, slot // 4
        x = base.x() + step * (column + 1)
        y = base.y() - step * row
        available = clone._workspace_geometry()
        if available is None:
            return x, y
        top = clone._workspace_window_top()
        x = min(max(x, available.left()), available.right() - clone.width() + 1)
        y = min(max(y, top), available.bottom() - clone.height() + 1)
        return x, y

    def _create_ui(self, character_id: str) -> None:
        lib = self._create_library(character_id)
        win = PetWindow(lib, self.config)
        self._wire_window(win)
        win.show()

        tray = self._build_tray(win)

        # 清理旧对象（热切换时使用）
        old_win = self.win
        old_tray = self.tray
        self.win = win
        self.tray = tray

        if old_win is not None:
            old_win.shutdown()
            old_win.hide()
            old_tray.hide() if old_tray is not None else None
            QTimer.singleShot(0, old_win.deleteLater)
            if old_tray is not None:
                QTimer.singleShot(0, old_tray.deleteLater)


    # ------------------------------------------------------------ 复制体
    def add_clone(self) -> None:
        """增加一个独立桌宠窗口；不设应用层数量上限，媒体缓存保持最小。"""
        if self.win is None:
            return
        character_id = str(self.config.get('character', catalog.DEFAULT_CHARACTER))
        lib = None
        try:
            # 复制体只缓存当前动作，避免每个窗口各自保留完整动作缓存。
            lib = self._create_library(character_id, cache_limit=1)
            clone = PetWindow(lib, self.config, persist_position=False, is_clone=True)
            self._wire_window(clone, is_clone=True)
            clone.move(*self._clone_position(self.win, clone, len(self.clones) + 1))
            self.clones.append(clone)
            clone.show()
            self._update_clone_menu()
            logging.info('增加桌宠复制体: count=%d', len(self.clones))
        except Exception as exc:
            if lib is not None:
                lib.close()
                lib.deleteLater()
            logging.exception('增加桌宠复制体失败')
            _show_startup_error('增加复制体失败', str(exc))

    def remove_clone(self, clone: PetWindow) -> None:
        """关闭一个复制体；不会影响主桌宠或边缘探头配置。"""
        if clone not in self.clones:
            return
        self.clones.remove(clone)
        clone.hide()
        clone.shutdown()
        clone.deleteLater()
        self._update_clone_menu()
        logging.info('关闭桌宠复制体: count=%d', len(self.clones))

    def close_all_clones(self) -> None:
        for clone in list(self.clones):
            self.remove_clone(clone)

    def _update_clone_menu(self) -> None:
        if self._clone_count_action is not None:
            self._clone_count_action.setText(f'当前复制体：{len(self.clones)}')


    # ------------------------------------------------------------ 角色切换
    def switch_character(self, character_id: str) -> None:
        if self.win is None:
            return
        current = str(self.config.get('character', catalog.DEFAULT_CHARACTER))
        if character_id == current:
            return

        try:
            # 预创建新库，失败则保留当前角色
            lib = self._create_library(character_id)
        except Exception as exc:
            logging.exception('切换角色失败: %s', character_id)
            _show_startup_error('切换角色失败', str(exc))
            return

        # 素材库验证成功后再提交配置，失败时不会留下不可启动的角色。
        self.config.set('character', character_id)
        self.config.save()

        logging.info('切换角色: %s -> %s', current, character_id)

        # 用新库创建新窗口/托盘，旧对象延迟销毁
        win = PetWindow(lib, self.config)
        self._wire_window(win)
        win.show()

        tray = self._build_tray(win)

        old_win = self.win
        old_tray = self.tray
        self.win = win
        self.tray = tray

        old_win.hide()
        old_win.shutdown()
        if old_tray is not None:
            old_tray.hide()
        QTimer.singleShot(0, old_win.deleteLater)
        if old_tray is not None:
            QTimer.singleShot(0, old_tray.deleteLater)


    def shutdown(self) -> None:
        """应用唯一退出入口；避免每次热切换重复连接 aboutToQuit。"""
        if self.tray is not None:
            self.tray.hide()
        self.close_all_clones()
        if self.win is not None:
            self.win._save_position()
            self.win.shutdown()
        self.hotkeys.stop()

    def _toggle_visible(self) -> None:
        if self.win is None:
            return
        windows = [self.win, *self.clones]
        if any(window.isVisible() for window in windows):
            for window in windows:
                window.suspend_animation()
                window.hide()
        else:
            for window in windows:
                window.show()
                window.resume_animation()

    def _handle_hotkey(self, action: str) -> None:
        win = self.win
        if win is None:
            return
        if action == 'toggle_visible':
            self._toggle_visible()
        elif action == 'toggle_pause':
            win.toggle_pause()
        elif action == 'random_action':
            win.play_random_action()
        elif action == 'toggle_mouse_through':
            win.set_mouse_through(not win.mouse_through)
        elif action == 'duck_sound':
            win.trigger_duck_sound()

    # ------------------------------------------------------------ 托盘
    def _build_tray(self, win: PetWindow) -> QSystemTrayIcon:
        # 固定使用应用图标，避免从当前动画帧复制/缩放图像；
        # macOS 会把 QSystemTrayIcon 显示为菜单栏状态图标。
        menu_bar_icon = _application_icon()
        if menu_bar_icon.isNull():
            menu_bar_icon = QIcon(win.icon_pixmap(32))
        tray = QSystemTrayIcon(menu_bar_icon)

        # 托盘与右键菜单共用同一批分节构造器（见 pet/menus.py）。
        # 托盘需要把外部状态变化反向同步回勾选状态，右键菜单不需要。
        menu = QMenu()
        menus.add_settings(menu, win.open_settings)
        menu.addAction('显示 / 隐藏', self._toggle_visible)
        menus.add_bubble_toggle(menu, win)
        menus.add_meme_toggle(menu, win)
        menus.add_pause(menu, win, checkable=True, sync=True)
        menus.add_random_action(menu, win)

        clones = menu.addMenu('复制体')
        self._clone_count_action = clones.addAction('当前复制体：0')
        self._clone_count_action.setEnabled(False)
        clones.addAction('增加复制体', self.add_clone)
        clones.addAction('关闭全部复制体', self.close_all_clones)
        self._update_clone_menu()

        menus.add_character_menu(menu, self.config, self.switch_character)
        menus.add_display_menu(menu, win, sync=True)
        menus.add_interaction_menu(menu, win, sync=True, sound_signal='triggered')
        menus.add_toggle(menu, menus.ToggleSpec(
            label='边缘探头（左右贴边）',
            checked=lambda: win.edge_probe_enabled,
            toggled=win.set_edge_probe_enabled,
            sync_signal=win.edgeProbeChanged,
        ))

        win.add_action_menu(menu)
        win.add_personality_menu(menu)
        menus.add_shortcut_legend(menu, enabled=self.hotkeys.enabled)

        menus.add_toggle(menu, menus.ToggleSpec(
            label='鼠标穿透',
            checked=lambda: bool(self.config.get('mouse_through', False)),
            toggled=win.set_mouse_through,
        ))

        menu.addSeparator()
        menus.add_autostart(menu)
        menu.addSeparator()
        menus.add_quit(menu, self.app.quit)

        tray.setContextMenu(menu)
        tray.setToolTip('dsh-pet 独立桌宠')
        tray.activated.connect(
            lambda reason: self._toggle_visible()
            if reason == QSystemTrayIcon.ActivationReason.DoubleClick
            else None
        )
        tray.show()
        return tray


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv if argv is None else argv)
    if '--selftest' in args:
        result = format_preflight(preflight(Config()))
        print(result)
        return 0 if result == 'preflight: OK' else 1

    _configure_qt_plugins()
    app = QApplication(args)
    app.setWindowIcon(_application_icon())
    app.setApplicationName('dsh-pet-standalone')
    app.setQuitOnLastWindowClosed(False)

    config = Config()
    _setup_logging(config)
    logging.info('dsh-pet-standalone 启动')
    controller = PetApp(app, config)
    try:
        controller.start()
    except Exception as exc:
        logging.exception('启动失败')
        controller.shutdown()
        _show_startup_error('dsh-pet-standalone', str(exc))
        return 1

    logging.info('进入事件循环')
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
