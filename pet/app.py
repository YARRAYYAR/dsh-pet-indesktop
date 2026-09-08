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

from . import autostart as autostart_mod
from . import catalog
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
        self.tray: QSystemTrayIcon | None = None
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

    def _create_library(self, character_id: str) -> MovieLibrary:
        scale = float(self.config.get('scale', catalog.DEFAULT_SCALE))
        lib = MovieLibrary(
            character_id=character_id,
            decode_size=catalog.decode_size_for_scale(scale),
            soft_edges=bool(self.config.get('soft_edges', True)),
        )
        logging.info('素材加载完成：%s %d 段动画', character_id, len(lib.names()))
        return lib

    def _create_ui(self, character_id: str) -> None:
        lib = self._create_library(character_id)
        win = PetWindow(lib, self.config)
        win.on_switch_character = self.switch_character
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
        win.on_switch_character = self.switch_character
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
        if self.win is not None:
            self.win._save_position()
            self.win.shutdown()
        self.hotkeys.stop()

    def _toggle_visible(self) -> None:
        if self.win is None:
            return
        if self.win.isVisible():
            self.win.suspend_animation()
            self.win.hide()
        else:
            self.win.show()
            self.win.resume_animation()

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
        tray = QSystemTrayIcon(QIcon(win.icon_pixmap()))

        menu = QMenu()
        menu.addAction('设置与动作预览…', win.open_settings)
        menu.addAction('显示 / 隐藏', self._toggle_visible)
        pause = menu.addAction('暂停 / 继续')
        pause.setCheckable(True)
        pause.setChecked(win._paused)
        pause.toggled.connect(win.set_paused)
        win.pausedChanged.connect(pause.setChecked)
        menu.addAction('随机动作', win.play_random_action)

        m_char = menu.addMenu('切换角色')
        current = str(self.config.get('character', catalog.DEFAULT_CHARACTER))
        for cid in catalog.list_available_characters():
            act = m_char.addAction(cid)
            act.setCheckable(True)
            act.setChecked(cid == current)
            act.triggered.connect(lambda checked=False, cid=cid: self.switch_character(cid))

        display = menu.addMenu('画面调整')
        soft_edges = display.addAction('清理透明底噪（Alpha=1）')
        soft_edges.setCheckable(True)
        soft_edges.setChecked(win.soft_edges)
        soft_edges.toggled.connect(win.set_soft_edges)
        win.softEdgesChanged.connect(soft_edges.setChecked)

        interaction = menu.addMenu('互动反馈')
        sound = interaction.addAction('声音开关')
        sound.setCheckable(True)
        sound.setChecked(win.sound_enabled)
        sound.toggled.connect(win.set_sound_enabled)
        win.soundChanged.connect(sound.setChecked)
        greetings = interaction.addAction('偶尔主动打招呼')
        greetings.setCheckable(True)
        greetings.setChecked(win.proactive_greetings)
        greetings.toggled.connect(win.set_proactive_greetings)
        win.proactiveGreetingsChanged.connect(greetings.setChecked)

        win.add_action_menu(menu)
        win.add_personality_menu(menu)

        shortcuts = menu.addMenu('全局快捷键')
        shortcut_prefix = '⌃⌥⌘'
        shortcut_rows = (
            ('H', '显示 / 隐藏'),
            ('P', '暂停 / 继续'),
            ('R', '随机动作'),
            ('M', '鼠标穿透'),
            ('D', '尖叫鸭'),
        )
        for key, label in shortcut_rows:
            item = shortcuts.addAction(f'{shortcut_prefix}{key}  {label}')
            item.setEnabled(False)
        status = '已启用' if self.hotkeys.enabled else '不可用（仍可使用菜单）'
        status_item = shortcuts.addAction(f'状态：{status}')
        status_item.setEnabled(False)

        mouse_through = menu.addAction('鼠标穿透')
        mouse_through.setCheckable(True)
        mouse_through.setChecked(bool(self.config.get('mouse_through', False)))
        mouse_through.toggled.connect(win.set_mouse_through)

        menu.addSeparator()

        auto = menu.addAction('开机自启')
        auto.setCheckable(True)
        auto.setChecked(autostart_mod.is_enabled())
        auto.toggled.connect(autostart_mod.set_enabled)

        menu.addSeparator()
        menu.addAction('退出', self.app.quit)

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
