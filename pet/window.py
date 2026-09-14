# -*- coding: utf-8 -*-
"""
桌宠主窗口 —— 透明无边框置顶窗口 + 动画链状态机 + 移动驱动 + 交互。

状态机（对应原插件 dsh-pet lib/client.js 的链式模型，行为 1:1 移植）：
  - 每个动画一次性播放，播完按概率选下一个：30% 待机 / 10% 转向 / 40% 动作 / 20% 移动；
  - 转向（东张西望）播完翻转朝向；facing=right 时水平镜像；
  - 点击回应 / 拖拽动画播完先回待机缓冲，待机播完再进随机链；
  - 移动：动画只提供"走路姿态"（3 选 1），位置由 QTimer 驱动，
    开头/结尾各 2s 不动，中间按播放进度插值；
  - 透明区域鼠标穿透：定期用当前帧 alpha 同步窗口 mask，并复用它判断交互命中。
"""

from __future__ import annotations

import logging
import math
import random
import sys
import time

from PySide6.QtCore import QElapsedTimer, QPoint, QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBitmap,
    QColor,
    QCursor,
    QGuiApplication,
    QImage,
    QPainter,
    QPixmap,
    QRegion,
)
from PySide6.QtWidgets import QApplication, QInputDialog, QMenu, QWidget

from . import autostart as autostart_mod
from . import catalog
from . import anim_chain
from . import bubble as bubble_visual
from .action_dialog import ActionSetDialog
from .action_sets import ActionSets
from .config import Config
from .interaction import classify_tap_burst, cursor_facing, edge_contacts
from .library import MovieLibrary
from . import menus
from .performance import LoadGovernor, system_load_ratio
from .presenter import FramePresenter, PresenterLayout
from .sound import BounceSound, DuckScream
from .settings_dialog import SettingsDialog
from .drag_motion import pointer_velocity, release_velocity
from .physics import PhysicsEngine, ThrowBounds
from .edge_probe import EdgeProbeController


def _mac_set_window_level(view_id: int, level: int) -> bool:
    """macOS 原生：把 NSWindow 层级设为指定值（3=置顶浮动，0=普通）。

    Qt 的 WindowStaysOnTopHint 在 macOS 上对无边框 Tool 窗口/运行时切换不可靠，
    这里用 objc runtime 直接调 [NSWindow setLevel:] 强制生效（ctypes 零依赖）。
    """
    app = QApplication.instance()
    if (
        sys.platform != 'darwin'
        or app is None
        or app.platformName().lower() != 'cocoa'
    ):
        return False
    try:
        import ctypes
        import ctypes.util

        lib_path = ctypes.util.find_library('objc') or '/usr/lib/libobjc.A.dylib'
        objc = ctypes.cdll.LoadLibrary(lib_path)

        # 关键：sel_registerName 返回 SEL（64 位指针）。ctypes 默认按 c_int(32 位)
        # 截断返回值，损坏的 SEL 会让 ObjC runtime 段错误（SIGSEGV），必须显式声明
        objc.sel_registerName.restype = ctypes.c_void_p
        objc.sel_registerName.argtypes = [ctypes.c_char_p]

        msg = objc.objc_msgSend
        msg.restype = ctypes.c_void_p

        sel_window = objc.sel_registerName(b'window')
        sel_set_level = objc.sel_registerName(b'setLevel:')

        # [view window] —— 无参，返回 NSWindow*
        msg.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        window = msg(ctypes.c_void_p(view_id), sel_window)
        if not window:
            return False

        # [window setLevel:level] —— 一个 NSInteger 参数
        msg.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long]
        msg(ctypes.c_void_p(window), sel_set_level, level)
        return True
    except Exception:
        return False


class PetWindow(QWidget):
    """桌宠窗口本体。"""

    softEdgesChanged = Signal(bool)
    duckSoundChanged = Signal(bool)
    soundChanged = Signal(bool)
    bounceSoundVariantChanged = Signal(str)
    proactiveGreetingsChanged = Signal(bool)
    bubbleChanged = Signal(bool)
    playlistChanged = Signal(str)
    personalityChanged = Signal(str)
    pausedChanged = Signal(bool)
    edgeProbeChanged = Signal(bool)

    def __init__(self, lib: MovieLibrary, config: Config) -> None:
        super().__init__()
        self.lib = lib
        # 让窗口成为媒体库的生命周期所有者；角色切换/退出时不留下孤立 reader。
        if lib.parent() is None:
            lib.setParent(self)
        self.cfg = config
        self.on_switch_character = None  # 由 app 注入，用于运行时切换角色
        self.soft_edges: bool = bool(config.get('soft_edges', True))
        self.lib.set_soft_edges(self.soft_edges)

        # 根据当前形象实际拥有的动画动态计算分类，支持不同角色动作不一致
        self.cats = catalog.build_categories(
            lib.names(),
            getattr(lib, 'category_hints', getattr(lib, 'manifest', None)),
            getattr(lib, 'folder_map', None),
            getattr(lib, 'folder_files', None),
        )
        self.idle = self.cats['idle']
        self.turn = self.cats['turn']
        self.idles = self.cats['idles']
        self.turns = self.cats['turns']
        self.moves = self.cats['moves']
        self.clicks = self.cats['clicks']
        self.drag = self.cats['drag']
        self.acts = self.cats['acts']
        # 收藏夹/播放列表的数据与持久化在 pet/action_sets.py；
        # 下面的属性把旧的读写形状保留下来，窗口其余部分无需改动。
        self._sets = ActionSets(config, lib.names())
        self.personality = self._normalize_personality(
            config.get('personality', 'lively')
        )

        # 预载拖拽动画首帧，避免第一次进入拖拽状态时同步解码卡顿
        if self.drag:
            self.lib.movie(self.drag).jumpToFrame(0)

        self.playback_speed: float = float(config.get('playback_speed', 1.0))
        self.mouse_through: bool = bool(config.get('mouse_through', False))
        self.drag_physics: bool = bool(config.get('drag_physics', False))
        self.edge_probe_enabled: bool = bool(config.get('edge_probe_enabled', False))
        self.sound_enabled: bool = bool(
            config.get('sound_enabled', config.get('duck_sound', True))
        )
        self.duck_sound_enabled: bool = self.sound_enabled
        self.proactive_greetings: bool = bool(
            config.get('proactive_greetings', True)
        )
        self.bubble_enabled: bool = bool(config.get('bubble_enabled', True))
        self.bubble_offset_x = int(config.get('bubble_offset_x', 0))
        self.bubble_offset_y = int(config.get('bubble_offset_y', 0))
        self._duck_sound = DuckScream(config.dir)
        self._duck_sound.enabled = self.sound_enabled
        self._duck_sound.volume = int(config.get('volume', 80))
        self._bounce_sound = BounceSound(config.dir)
        self.set_bounce_sound_variant(config.get('bounce_sound_variant', 'random'), persist=False)
        self._bounce_sound.enabled = self.sound_enabled
        self._bounce_sound.volume = self._duck_sound.volume
        self._recent_actions = []
        self.action_interval_seconds = int(config.get('action_interval_seconds', 0))
        self._last_action_started = time.monotonic()
        manifest = getattr(lib, 'manifest', None) or {}
        self._action_tags = manifest.get('action_tags', {})
        self._personality_frequent_acts = catalog.personality_frequent_actions(
            self.personality, self.acts, self._action_tags
        )

        # ---- 窗口属性：无边框 + 透明 + 不进任务栏；置顶可配置 ----
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        if config.get('on_top', True):
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        if self.mouse_through:
            self.setWindowFlag(Qt.WindowType.WindowTransparentForInput, True)
        if sys.platform == 'darwin' and config.get('on_top', True):
            # macOS 上 Tool 窗口的置顶由 WA_MacAlwaysShowToolWindow 控制，
            # WindowStaysOnTopHint 对 Tool 窗口不可靠（Qt 官方已知问题 QTBUG-38580）
            self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow, True)

        # ---- 状态 ----
        self.anim: str = self.idle
        self.facing: str = config.get('facing', 'left')  # left | right
        self.scale: float = float(config.get('scale', catalog.DEFAULT_SCALE))
        self.no_move: bool = bool(config.get('no_move', False))  # 不移动：禁用自动移动
        self.movie = None
        self._bound_movie = None
        self._bound_movie_name: str | None = None
        # 帧呈现（pixmap / 逻辑画布 / 命中遮罩）由独立呈现层持有；
        # 窗口只保留只读桥接属性，便于单独测试且不重复实现取整规则。
        self._presenter = FramePresenter(
            canvas_w=catalog.CANVAS_W,
            canvas_h=catalog.CANVAS_H,
            pad=catalog.PAD,
            dpr_cap=catalog.RENDER_DPR_CAP,
        )
        self._ended_fired = False
        self._shutting_down = False
        self._suspended = False
        self._paused = False
        self._failure_counts: dict[str, int] = {}
        self._failed_animations: set[str] = set()
        self._screen_hooked = False
        self._screens_hooked = False

        # ---- 交互状态 ----
        self._press_global: QPoint | None = None
        self._grab_offset: QPoint | None = None  # 按下时 鼠标全局坐标 - 窗口左上角
        self._dragging = False
        self._just_dragged = False               # 抑制拖拽结束后的幽灵点击
        self._long_press_fired = False
        self._tap_count = 0

        self._long_press_timer = QTimer(self)
        self._long_press_timer.setSingleShot(True)
        self._long_press_timer.timeout.connect(self._on_long_press)
        self._tap_timer = QTimer(self)
        self._tap_timer.setSingleShot(True)
        self._tap_timer.timeout.connect(self._flush_tap_burst)

        # ---- 移动驱动 ----
        self._move_plan: dict | None = None
        self._move_timer = QTimer(self)
        self._move_timer.setInterval(33)         # ~30fps 位置插值
        self._move_timer.timeout.connect(self._on_move_tick)

        # ---- 点击 Q 弹效果 ----
        self._squash_timer = QTimer(self)
        self._squash_timer.setInterval(16)
        self._squash_timer.timeout.connect(self._on_squash_tick)
        self._squash_clock = QElapsedTimer()
        self._squash_active = False
        self._squash_duration_ms = 220
        self._squash_progress = 1.0

        # ---- 自适应省资源：系统持续繁忙时降低动作/解码频率 ----
        self._load_governor = LoadGovernor()
        self._resource_constrained = False
        self._resource_timer = QTimer(self)
        self._resource_timer.setInterval(catalog.LOAD_SAMPLE_MS)
        self._resource_timer.timeout.connect(self._check_system_load)
        self._idle_pause_timer = QTimer(self)
        self._idle_pause_timer.setSingleShot(True)
        self._idle_pause_timer.timeout.connect(self._resume_busy_idle)
        self.action_switch_delay_ms = int(
            config.get('action_switch_delay_ms', 0)
        )
        self._action_switch_timer = QTimer(self)
        self._action_switch_timer.setSingleShot(True)
        self._action_switch_timer.timeout.connect(self._pick_next)

        # ---- 拖动物理 ----
        self._physics_timer = QTimer(self)
        self._physics_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._physics_timer.setInterval(16)
        self._physics_timer.timeout.connect(self._on_physics_tick)
        self._physics_mode: str | None = None  # None / 'drag' / 'throw'
        self._last_physics_time: float | None = None
        # 位置/速度由纯数值核心持有（见 pet/physics.py）；
        # `_phys_pos` / `_phys_vel` 保留为桥接属性以维持既有访问形状。
        self._physics = PhysicsEngine()
        self._drag_target: QPoint | None = None
        self._last_global: QPoint | None = None
        self._last_move_time = 0.0
        self._pointer_velocity = (0.0, 0.0)
        self._edge_probe = EdgeProbeController(self)

        # ---- 鼠标靠近与主动问候 ----
        self._cursor_timer = QTimer(self)
        self._cursor_timer.setInterval(catalog.CURSOR_POLL_MS)
        self._cursor_timer.timeout.connect(self._on_cursor_tick)
        self._greeting_timer = QTimer(self)
        self._greeting_timer.setSingleShot(True)
        self._greeting_timer.timeout.connect(self._on_greeting_timer)

        # ---- 低负载对话气泡：只在出现/收起动画期间重绘 ----
        self._bubble_visible = False
        self._bubble_preview: bool | None = None
        self._bubble_progress = 0.0
        self._bubble_timer = QTimer(self)
        self._bubble_timer.setSingleShot(True)
        self._bubble_timer.timeout.connect(self.hide_bubble)
        self._bubble_anim_timer = QTimer(self)
        self._bubble_anim_timer.setInterval(16)
        self._bubble_anim_timer.timeout.connect(self._on_bubble_anim_tick)
        self._bubble_anim_clock = QElapsedTimer()
        self._bubble_anim_direction = 1

        # ---- 尺寸与初始状态 ----
        self._apply_scale()
        self._restore_position()
        self.lib.set_decode_size(*catalog.decode_size_for_scale(self.scale, self._screen_dpr()))
        self._switch(self.idle)
        self._resource_timer.start()
        self._check_system_load()
        self._cursor_timer.start()
        self._schedule_next_greeting()

    # ------------------------------------------------------------ 动作集合桥接
    @property
    def favorites(self) -> list[str]:
        return self._sets.favorites

    @favorites.setter
    def favorites(self, value) -> None:
        self._sets.favorites = list(value)

    @property
    def playlist(self) -> list[str]:
        return self._sets.playlist

    @playlist.setter
    def playlist(self, value) -> None:
        self._sets.playlist = list(value)

    @property
    def playlist_mode(self) -> str:
        return self._sets.mode

    @playlist_mode.setter
    def playlist_mode(self, value: str) -> None:
        self._sets.mode = value

    @property
    def _playlist_index(self) -> int:
        return self._sets.index

    @_playlist_index.setter
    def _playlist_index(self, value: int) -> None:
        self._sets.index = int(value)

    def _config_names(self, key: str) -> list[str]:
        """读取配置中的动作名列表，过滤异常值并保持原顺序。"""
        return self._sets._config_names(key)

    @staticmethod
    def _normalize_personality(value: str) -> str:
        return value if value in catalog.PERSONALITY_PRESETS else 'lively'

    # ================================================================ 尺寸
    def _apply_scale(self) -> None:
        """按逻辑画布缩放窗口；素材分辨率不会改变桌宠大小。"""
        self._w = max(1, int(round(catalog.CANVAS_W * self.scale)))
        self._bubble_h = int(round(bubble_visual.HEADER_HEIGHT * self.scale))
        canvas_height = int(round((catalog.CANVAS_H + catalog.PAD) * self.scale))
        self._h = max(1, canvas_height + self._bubble_h)
        self.setFixedSize(self._w, self._h)

    def change_scale(self, scale: float, *, persist: bool = True) -> None:
        """切换缩放；保持窗口底边不动（脚踩的地面不变）。"""
        scale = max(0.25, min(2.0, float(scale)))
        if abs(scale - self.scale) < 1e-6:
            return
        self._edge_probe.cancel('scale_changed', restore=False)
        old_bottom = self.geometry().bottom()
        self.scale = scale
        self.lib.set_decode_size(*catalog.decode_size_for_scale(scale, self._screen_dpr()))
        self._apply_scale()
        self.move(self.x(), old_bottom - self._h + 1)
        self._switch(self.anim)
        self.update()
        if persist:
            self._save_position()

    # ================================================================ 位置
    def _screen_available(self):
        """窗口所在屏幕；macOS 上 self.screen() 可能失效，兜底主屏。"""
        scr = self.screen()
        if scr is None:
            scr = self._configured_screen()
        if scr is None:
            scr = QGuiApplication.primaryScreen()
        return scr

    def _configured_screen(self):
        preferred = self.cfg.get('screen')
        if isinstance(preferred, str):
            for screen in QGuiApplication.screens():
                if screen.name() == preferred:
                    return screen
        return None

    def _screen_dpr(self) -> float:
        screen = self.screen()
        if screen is None or not self.isVisible():
            screen = self._configured_screen() or screen
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        return float(screen.devicePixelRatio()) if screen is not None else 1.0

    def _clamp_into_screen(self) -> None:
        screen = self._screen_available()
        if screen is None:
            return
        avail = screen.availableGeometry()
        max_x = max(avail.left(), avail.right() - self._w + 1)
        max_y = max(avail.top(), avail.bottom() - self._h + 1)
        x = min(max(self.x(), avail.left()), max_x)
        y = min(max(self.y(), avail.top()), max_y)
        if (x, y) != (self.x(), self.y()):
            self.move(x, y)

    def _on_screen_changed(self, screen) -> None:
        if screen is None:
            return
        self.lib.set_decode_size(
            *catalog.decode_size_for_scale(self.scale, screen.devicePixelRatio())
        )
        self._clamp_into_screen()
        self._rebuild_frame(force_mask=True)
        self._save_position()

    def _on_screen_removed(self, _screen) -> None:
        QTimer.singleShot(0, self._clamp_into_screen)

    def _restore_position(self) -> None:
        """恢复上次位置（按屏幕比例），无记录则落右下角。"""
        scr = self._configured_screen() or self._screen_available()
        avail = scr.availableGeometry()
        rx, ry = self.cfg.get('rx'), self.cfg.get('ry')
        if rx is None or ry is None:
            x = avail.right() - self._w - catalog.CORNER_MARGIN
            y = avail.bottom() - self._h
        else:
            x = int(round(avail.left() + rx * avail.width())) - self._w // 2
            y = int(round(avail.top() + ry * avail.height())) - self._h // 2
            x = min(max(x, avail.left()), avail.right() - self._w)
            y = min(max(y, avail.top()), avail.bottom() - self._h)
        logging.info('恢复位置 screen=%s avail=(%d,%d,%d,%d) dpr=%s -> (%d,%d)',
                     scr.name(), avail.left(), avail.top(), avail.right(),
                     avail.bottom(), scr.devicePixelRatio(), x, y)
        self.move(x, y)

    def _save_position(self) -> None:
        """以"窗口中心相对屏幕可用区的比例"持久化位置（分辨率变化后仍正确）。"""
        scr = self._screen_available()
        avail = scr.availableGeometry()
        if avail.width() <= 0 or avail.height() <= 0:
            return
        cx = self.x() + self._w / 2
        cy = self.y() + self._h / 2
        self.cfg.set('rx', (cx - avail.left()) / avail.width())
        self.cfg.set('ry', (cy - avail.top()) / avail.height())
        self.cfg.set('screen', scr.name())
        self.cfg.set('facing', self.facing)
        self.cfg.set('scale', self.scale)
        self.cfg.save()

    def _go_default_corner(self) -> None:
        self._edge_probe.cancel('return_corner', restore=False)
        scr = self._screen_available()
        avail = scr.availableGeometry()
        x = avail.right() - self._w - catalog.CORNER_MARGIN
        y = avail.bottom() - self._h
        logging.info('回到右下角 screen=%s avail=(%d,%d,%d,%d) dpr=%s -> (%d,%d)',
                     scr.name(), avail.left(), avail.top(), avail.right(),
                     avail.bottom(), scr.devicePixelRatio(), x, y)
        self.move(x, y)
        self._save_position()

    def set_on_top(self, on: bool) -> None:
        was_visible = self.isVisible()
        if sys.platform == 'darwin':
            # 先设属性再改 flag：setWindowFlag 触发窗口重建时一并应用
            self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow, on)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, on)
        self.cfg.set('on_top', on)
        self.cfg.save()
        if was_visible:
            self.show()
        else:
            self.hide()
        if sys.platform == 'darwin' and was_visible:
            # 延迟到 Qt 窗口重建完成后再强制原生层级，避免被 Qt 覆盖
            QTimer.singleShot(0, lambda: _mac_set_window_level(int(self.winId()), 3 if on else 0))
        if on and was_visible:
            self.raise_()

    def showEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        """窗口显示时校正层级（延迟执行，避免被 Qt 窗口重建覆盖）。"""
        super().showEvent(event)
        handle = self.windowHandle()
        if handle is not None and not self._screen_hooked:
            handle.screenChanged.connect(self._on_screen_changed)
            self._screen_hooked = True
        app = QGuiApplication.instance()
        if app is not None and not self._screens_hooked:
            app.screenRemoved.connect(self._on_screen_removed)
            self._screens_hooked = True
        if sys.platform == 'darwin':
            on = bool(self.cfg.get('on_top', True))
            QTimer.singleShot(0, lambda: _mac_set_window_level(int(self.winId()), 3 if on else 0))

    def set_no_move(self, on: bool) -> None:
        """切换「不移动」：禁用自动移动；勾选瞬间若正在移动则立即停下回待机。"""
        self.no_move = bool(on)
        self.cfg.set('no_move', self.no_move)
        self.cfg.save()
        if self.no_move and self._move_plan is not None:
            if self.idles:
                self._switch(self._pick(self.idles))  # 打断进行中的移动

    # ================================================================ 播放
    def _bind_movie(self, name: str, movie) -> None:
        """只绑定当前播放器；LRU 重建同名动作时也会重新绑定。"""
        if movie is self._bound_movie:
            self._bound_movie_name = name
            return
        self._unbind_movie()
        movie.frameChanged.connect(self._on_frame)
        movie.finished.connect(self._on_movie_finished)
        movie.errorOccurred.connect(self._on_movie_error)
        self._bound_movie = movie
        self._bound_movie_name = name

    def _unbind_movie(self) -> None:
        movie = self._bound_movie
        if movie is not None:
            for signal, slot in (
                (movie.frameChanged, self._on_frame),
                (movie.finished, self._on_movie_finished),
                (movie.errorOccurred, self._on_movie_error),
            ):
                try:
                    signal.disconnect(slot)
                except (RuntimeError, TypeError):
                    pass
        self._bound_movie = None
        self._bound_movie_name = None

    def _switch(self, name: str | None) -> bool:
        """切换到指定动画（链式模型：全部一次性播放）。"""
        if not name or name in self._failed_animations:
            return False
        self._idle_pause_timer.stop()
        self._action_switch_timer.stop()
        self._cancel_move()
        previous = self.movie
        movie = self.lib.activate(name)
        if previous is not None and previous is not movie:
            previous.stop()
        self._bind_movie(name, movie)
        self.anim = name
        if name in self.acts:
            self._last_action_started = time.monotonic()
        if name in self.playlist:
            self._sets.mark_current(name)
        self.movie = movie
        if hasattr(movie, 'rewind'):
            movie.rewind(preload=self._suspended or self._paused)
        else:
            movie.stop()
            movie.jumpToFrame(0)
        if hasattr(movie, 'set_playback_speed'):
            movie.set_playback_speed(self._effective_playback_speed(name))
        self._ended_fired = False
        self._presenter.reset_mask_counter()
        self._rebuild_frame(force_mask=True)
        if not self._suspended and not self._paused:
            movie.start()
        return True

    def _on_frame(self, n: int) -> None:
        """媒体帧推进回调：只重建当前画面，结束由播放器 finished 信号处理。"""
        name = self._bound_movie_name
        if name != self.anim or self.movie is None or self.sender() is not self.movie:
            return
        self._failure_counts.pop(name, None)
        self._failed_animations.discard(name)
        self._rebuild_frame()
        self.update()

    def _on_movie_finished(self) -> None:
        name = self._bound_movie_name
        if (
            name != self.anim
            or self.movie is None
            or self.sender() is not self.movie
            or self._ended_fired
        ):
            return
        self._ended_fired = True
        self._on_anim_ended(name)

    def _on_movie_error(self, message: str) -> None:
        name = self._bound_movie_name
        if not name:
            return
        count = self._failure_counts.get(name, 0) + 1
        self._failure_counts[name] = count
        self._failed_animations.add(name)
        logging.error('动画解码失败 %s（第 %d 次）: %s', name, count, message)
        if count >= 3:
            logging.error('动画已停用，避免坏素材切换风暴: %s', name)
        self._ended_fired = True
        if self.movie is not None:
            self.movie.stop()
        QTimer.singleShot(300, lambda name=name: self._recover_from_movie_error(name))

    def _recover_from_movie_error(self, name: str) -> None:
        if self._shutting_down or self._suspended or self._paused or self.anim != name:
            return
        self._schedule_action_switch()

    def _schedule_action_switch(self) -> None:
        """用单个一次性计时器实现低负载的动作切换等待。"""
        delay = max(0, int(self.action_switch_delay_ms))
        if delay <= 0:
            self._pick_next()
        else:
            self._action_switch_timer.start(delay)

    # ------------------------------------------------------------ 呈现层桥接
    @property
    def _frame_pixmap(self) -> QPixmap | None:
        return self._presenter.frame_pixmap

    @property
    def _frame_logical_size(self) -> tuple[int, int]:
        return self._presenter.logical_size

    @property
    def _frame_logical_rect(self) -> tuple[int, int, int, int]:
        return self._presenter.logical_rect

    @property
    def _pet_mask_region(self) -> QRegion | None:
        return self._presenter.mask_region

    @property
    def _pet_mask_key(self):
        return self._presenter.mask_key

    def _presenter_layout(self) -> PresenterLayout:
        return PresenterLayout(
            window_w=self._w,
            window_h=self._h,
            bubble_h=self._bubble_h,
            scale=self.scale,
            dpr=float(self.devicePixelRatioF()),
            canvas_w=catalog.CANVAS_W,
            canvas_h=catalog.CANVAS_H,
            pad=catalog.PAD,
            dpr_cap=catalog.RENDER_DPR_CAP,
        )

    def _frame_draw_rect(self) -> QRect:
        """当前帧在窗口局部坐标中的绘制矩形，绘制/探头共用。"""
        x, y, width, height = self._frame_logical_rect
        return QRect(x, self._presenter_layout().pet_top() + y, width, height)

    def character_local_region(self) -> QRect:
        """当前角色可见区域，供边缘探头判断真实像素是否已贴边。"""
        return self._presenter.pet_region(
            self._presenter_layout(),
            rotation_deg=self._edge_probe.current_angle_deg(),
        ).boundingRect()

    def _rebuild_frame(self, *, force_mask: bool = False) -> None:
        """把当前解码帧交给呈现层，并按间隔同步窗口 mask。"""
        if self.movie is None:
            return
        mask_interval = (
            catalog.BUSY_MASK_FRAME_INTERVAL
            if self._resource_constrained
            else catalog.MASK_FRAME_INTERVAL
        )
        needs_mask = self._presenter.render(
            self.movie.currentFrame(),
            facing=self.facing,
            layout=self._presenter_layout(),
            force_mask=force_mask,
            mask_interval=mask_interval,
        )
        if needs_mask:
            self._sync_mask()

    def _bubble_mask_region(self) -> QRegion | None:
        """气泡当前的命中区域（已平移到窗口坐标）；不可见时返回 None。"""
        if not (self._bubble_visible and self._bubble_progress > 0):
            return None
        rect = self._bubble_geometry()
        padding = bubble_visual.stroke_width(rect) / 2 + 1
        bounds = bubble_visual.shape(rect, self._bubble_progress).boundingRect()
        bounds = bounds.adjusted(-padding, -padding, padding, padding).toAlignedRect()
        canvas = QImage(bounds.size(), QImage.Format.Format_ARGB32)
        canvas.fill(Qt.GlobalColor.transparent)
        painter = QPainter(canvas)
        painter.translate(-bounds.left(), -bounds.top())
        self._paint_bubble(painter)
        painter.end()
        return QRegion(QBitmap.fromImage(canvas.createAlphaMask())).translated(
            bounds.topLeft()
        )

    def _sync_mask(self) -> None:
        """按当前帧 alpha 设置窗口 mask：透明区域鼠标穿透到下层窗口。

        这是命中测试层，不参与实际透明边缘的绘制；画面边缘仍由原始
        Alpha + QPainter 合成，因此降低同步频率不会让可见边角变粗。
        """
        region = self._presenter.compose_region(
            self._presenter_layout(),
            bubble_region=self._bubble_mask_region(),
            rotation_deg=self._edge_probe.current_angle_deg(),
        )
        if region != self.mask():
            self.setMask(region)

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        if self._bubble_visible:
            self._paint_bubble(painter)
        self._presenter.paint(
            painter,
            layout=self._presenter_layout(),
            squash_progress=self._squash_progress if self._squash_active else None,
            rotation_deg=self._edge_probe.current_angle_deg(),
        )
        painter.end()

    def _bubble_geometry(self) -> QRectF:
        """返回与当前桌宠大小联动的气泡区域。"""
        return bubble_visual.geometry(
            self._w, self.scale, self.bubble_offset_x, self.bubble_offset_y
        )

    def set_bubble_position(self, x: int, y: int, *, persist: bool = False) -> None:
        self.bubble_offset_x = max(-90, min(90, int(x)))
        self.bubble_offset_y = max(-90, min(90, int(y)))
        if persist:
            self.cfg.set('bubble_offset_x', self.bubble_offset_x)
            self.cfg.set('bubble_offset_y', self.bubble_offset_y)
            self.cfg.save()
        self._sync_mask()
        self.update()

    _bubble_tail_rects = staticmethod(bubble_visual.tail_rects)

    def _bubble_hit_test(self, point: QPoint) -> bool:
        return self._bubble_visible and bubble_visual.shape(
            self._bubble_geometry(), self._bubble_progress
        ).contains(QPointF(point))

    def _paint_bubble(self, painter: QPainter) -> None:
        bubble_visual.paint(painter, self._bubble_geometry(), self._bubble_progress)

    def _start_squash(self) -> None:
        """点击时启动 Q 弹效果：画面先变矮再恢复。"""
        self._squash_active = True
        self._squash_progress = 0.0
        self._squash_clock.start()
        self._squash_timer.start()
        self.update()

    def _on_squash_tick(self) -> None:
        elapsed = self._squash_clock.elapsed()
        self._squash_progress = min(1.0, elapsed / self._squash_duration_ms)
        if self._squash_progress >= 1.0:
            self._squash_active = False
            self._squash_timer.stop()
        self.update()

    def icon_pixmap(self, size: int = 64) -> QPixmap:
        """托盘图标：取当前帧（无则待机首帧）缩放。"""
        image = self._presenter.icon_image(
            fallback_frame_provider=self._idle_first_frame,
        )
        return FramePresenter.scaled_icon(image, size)

    def _idle_first_frame(self):
        if not self.idle:
            return None
        return self.lib.movie(self.idle).currentFrame()

    # ================================================================ 动画链
    def _on_anim_ended(self, name: str) -> None:
        if self._suspended or self._paused or self._shutting_down:
            return
        if self._edge_probe.active:
            return
        if name == self.drag and self._dragging:
            # 超长拖拽：拖拽动画循环重播，继续跟手
            self.movie.jumpToFrame(0)
            self._ended_fired = False
            self.movie.start()
            return
        if name in self.turns:
            # 转向动画播完 → 翻转朝向
            self.facing = 'right' if self.facing == 'left' else 'left'
        if self.playlist_mode != 'off' and name in self.playlist:
            self._play_next_playlist()
            return
        if name == self.drag or name in self.clicks:
            # 交互打断的动画播完 → 待机缓冲（一次性），待机播完再进链
            if self.idles:
                self._switch(self._pick_available(self.idles))
            return
        if self._resource_constrained and name in self.idles:
            # 保留最后一帧短暂停顿，不启动解码器；交互会通过 _switch 立即取消等待。
            self._idle_pause_timer.start(catalog.BUSY_IDLE_PAUSE_MS)
            return
        self._schedule_action_switch()

    def _pick_next(self) -> None:
        """按播放列表或当前性格模式选择下一个动画。

        决策规则本身在 `anim_chain`（纯逻辑、可单测）；这里只负责把
        窗口状态喂进去并执行结果。随机数调用顺序与重构前逐个对应。
        """
        if self.playlist_mode != 'off' and self.playlist:
            self._play_next_playlist()
            return
        if self._edge_probe.active:
            return
        if self.action_interval_seconds and self.acts and self.idles:
            elapsed = time.monotonic() - self._last_action_started
            if elapsed < self.action_interval_seconds:
                self._switch(self._pick(self.idles))
                return
            if not self._resource_constrained:
                self._switch(self._pick_personality_action())
                return
        roll = random.random()
        if self._resource_constrained:
            category = anim_chain.busy_category_for_roll(
                roll, has_idles=bool(self.idles), has_turns=bool(self.turns)
            )
        else:
            category = anim_chain.category_for_roll(
                roll,
                catalog.PERSONALITY_PRESETS[self.personality],
                no_move=self.no_move,
            )
        if category == anim_chain.CATEGORY_IDLE:
            if self.idles:
                self._switch(self._pick_available(self.idles, exclude=self.anim))
            else:
                self._switch(self._pick_personality_action(exclude=self.anim))
        elif category == anim_chain.CATEGORY_TURN:
            if self.turns:
                self._switch(self._pick_available(self.turns, exclude=self.anim))
            else:
                self._switch(self._pick_available(self.acts, exclude=self.anim))
        elif category == anim_chain.CATEGORY_ACTS:
            self._switch(self._pick_personality_action(exclude=self.anim))
        else:
            if self.no_move or not self._try_move():
                self._switch(self._pick_personality_action(exclude=self.anim))

    def _fallback_pools(self) -> list[list[str]]:
        """分类池缺失时按优先级回退；顺序与重构前一致。"""
        return [
            self.idles,
            self.turns,
            self.acts,
            self.moves,
            self.clicks,
            list(self.lib.names()),
        ]

    def _pick(self, pool: list[str], exclude: str | None = None) -> str | None:
        return anim_chain.pick(
            pool, exclude=exclude, failed=self._failed_animations, rng=random
        )

    def _pick_available(self, pool: list[str], exclude: str | None = None) -> str | None:
        """从目标池选择；角色缺少该类动作时回退到已有动作。"""
        return anim_chain.pick_available(
            pool, self._fallback_pools(), exclude=exclude,
            failed=self._failed_animations, rng=random,
        )

    def _pick_personality_action(self, exclude: str | None = None) -> str | None:
        """按当前性格提高前 40% 高匹配动作的出现频率。"""
        picked = anim_chain.pick_personality_action(
            self.acts,
            self._personality_frequent_acts,
            personality=self.personality,
            focus=float(catalog.PERSONALITY_PRESETS[self.personality]['action_focus']),
            exclude=exclude,
            recent=self._recent_actions,
            failed=self._failed_animations,
            fallback_pools=self._fallback_pools(),
            rng=random,
        )
        if picked:
            self._recent_actions = anim_chain.remember(self._recent_actions, picked)
        return picked

    def _edit_action_set(self, key: str, title: str) -> None:
        current = list(self.favorites if key == 'favorites' else self.playlist)
        dialog = ActionSetDialog(
            title, list(self.lib.names()), current, self,
            allow_exchange=key == 'playlist',
        )
        try:
            accepted = dialog.exec() == dialog.DialogCode.Accepted
            selected = dialog.selected_names() if accepted else None
        finally:
            dialog.deleteLater()
        if selected is None:
            return
        self._apply_action_set(key, selected)

    def _apply_action_set(self, key: str, selected: list[str]) -> None:
        was_active = key == 'playlist' and self.playlist_mode != 'off'
        self._sets.apply(key, selected, self.lib.names())
        if key == 'playlist' and self.playlist_mode == 'off' and was_active:
            # 列表被清空导致播放模式自动关闭时，同步一次 UI。
            self.playlistChanged.emit('off')
        if was_active and self.playlist:
            self._cancel_move()
            self._play_next_playlist()

    def _toggle_current_favorite(self) -> None:
        self._sets.toggle_favorite(self.anim)

    def _set_playlist_from_favorites(self) -> None:
        self._sets.playlist_from_favorites()
        if self.playlist_mode != 'off':
            self._play_next_playlist()

    def _play_next_playlist(self) -> None:
        name = self._sets.next_name(
            current=self.anim,
            picker=lambda pool, current: self._pick(pool, exclude=current),
        )
        if name is None:
            self.set_playlist_mode('off')
            return
        self._switch(name)

    def set_playlist_mode(self, mode: str) -> None:
        if not self._sets.set_mode(mode):
            return
        self.playlistChanged.emit(mode)
        if mode != 'off':
            self._cancel_move()
            self._play_next_playlist()

    def add_action_menu(self, parent_menu: QMenu) -> QMenu:
        """给桌宠右键菜单和状态栏菜单共用动作管理入口。"""
        menu = parent_menu.addMenu('动作管理')
        menu.aboutToShow.connect(lambda menu=menu: self._populate_action_menu(menu))
        self._populate_action_menu(menu)
        return menu

    def _populate_action_menu(self, menu: QMenu) -> None:
        menu.clear()
        current_label = (
            '取消收藏当前动作' if self.anim in self.favorites else '收藏当前动作'
        )
        menu.addAction(current_label, self._toggle_current_favorite)
        menu.addAction(
            '编辑收藏夹…',
            lambda: self._edit_action_set('favorites', '编辑收藏夹'),
        )
        menu.addAction(
            '编辑播放列表…',
            lambda: self._edit_action_set('playlist', '编辑播放列表'),
        )

        favorites = menu.addMenu('收藏夹')
        if self.favorites:
            for name in self.favorites:
                favorites.addAction(name, lambda checked=False, name=name: self._switch(name))
        else:
            empty = favorites.addAction('暂无收藏')
            empty.setEnabled(False)

        playlist = menu.addMenu('播放列表')
        if self.favorites:
            playlist.addAction('用收藏夹覆盖播放列表', self._set_playlist_from_favorites)
        if self.playlist:
            playlist.addAction(f'当前列表：{len(self.playlist)} 段').setEnabled(False)
        else:
            empty = playlist.addAction('暂无动作，请先编辑列表')
            empty.setEnabled(False)
        for mode, label in (
            ('off', '关闭播放列表'),
            ('loop', '循环播放'),
            ('random', '随机播放'),
        ):
            action = playlist.addAction(label)
            action.setCheckable(True)
            action.setChecked(self.playlist_mode == mode)
            action.setEnabled(mode == 'off' or bool(self.playlist))
            action.triggered.connect(lambda checked=False, mode=mode: self.set_playlist_mode(mode))

    def set_personality(self, personality: str) -> None:
        personality = self._normalize_personality(personality)
        if personality == self.personality:
            return
        self.personality = personality
        self._personality_frequent_acts = catalog.personality_frequent_actions(
            personality, self.acts, self._action_tags
        )
        self._recent_actions.clear()
        self.cfg.set('personality', personality)
        self.cfg.save()
        self._schedule_next_greeting()
        if self.anim in self.acts and self._personality_frequent_acts:
            self._switch(self._pick_personality_action(exclude=self.anim))
        if self._bubble_visible:
            self.show_bubble()
        self.personalityChanged.emit(personality)

    def add_personality_menu(self, parent_menu: QMenu) -> QMenu:
        menu = parent_menu.addMenu('性格模式')
        for key, profile in catalog.PERSONALITY_PRESETS.items():
            action = menu.addAction(str(profile['label']))
            action.setCheckable(True)
            action.setChecked(self.personality == key)
            action.triggered.connect(
                lambda checked=False, key=key: self.set_personality(key)
            )
            menu.aboutToShow.connect(
                lambda action=action, key=key: action.setChecked(self.personality == key)
            )
        return menu

    def open_settings(self) -> None:
        dialog = SettingsDialog(self)
        try:
            dialog.exec()
        finally:
            dialog.deleteLater()

    def set_volume(self, value: int, *, persist: bool = True) -> None:
        self._duck_sound.volume = max(0, min(100, int(value)))
        self._bounce_sound.volume = self._duck_sound.volume
        if persist:
            self.cfg.set('volume', self._duck_sound.volume)
            self.cfg.save()
        if self._duck_sound.volume == 0:
            self._duck_sound.close()
            self._bounce_sound.close()

    def set_action_interval(self, seconds: int) -> None:
        self.action_interval_seconds = max(0, min(3600, int(seconds)))
        self.cfg.set('action_interval_seconds', self.action_interval_seconds)
        self.cfg.save()

    def _special_animation(self, preferred: str, fallback: list[str]) -> str | None:
        """优先使用有明确语义的动作，没有时回退到当前角色已有动作。"""
        if preferred in self.lib.names():
            return preferred
        pool = [name for name in fallback if name in self.lib.names()]
        return self._pick(pool, exclude=self.anim) if pool else None

    def _schedule_next_greeting(self) -> None:
        self._greeting_timer.stop()
        if (
            not self.proactive_greetings
            or self._suspended
            or self._paused
            or self._shutting_down
        ):
            return
        profile = catalog.PERSONALITY_PRESETS[self.personality]
        self._greeting_timer.start(anim_chain.greeting_delay_ms(profile, random))

    def _on_greeting_timer(self) -> None:
        if (
            self.proactive_greetings
            and not self._suspended
            and not self._paused
            and not self._shutting_down
            and not self._dragging
            and self._move_plan is None
            and random.random() <= float(
                catalog.PERSONALITY_PRESETS[self.personality]['greeting_chance']
            )
        ):
            name = self._special_animation(
                '点击回应-元气挥手', self.clicks or self.acts
            )
            if name:
                self._switch(name)
                self.show_bubble()
        self._schedule_next_greeting()

    def _on_cursor_tick(self) -> None:
        """鼠标进入反应半径时镜像当前帧，让角色自然看向鼠标。"""
        if (self._suspended or self._paused or self._shutting_down
                or self._dragging or self._edge_probe.active):
            return
        center = (self.x() + self._w / 2.0, self.y() + self._h / 2.0)
        cursor = QCursor.pos()
        target = cursor_facing(
            center,
            (float(cursor.x()), float(cursor.y())),
            catalog.CURSOR_REACTION_RADIUS,
            catalog.CURSOR_DEAD_ZONE,
        )
        if target is None or target == self.facing:
            return
        self.facing = target
        self._rebuild_frame(force_mask=True)
        self.update()

    # ================================================================ 移动
    def _try_move(self, name: str | None = None) -> bool:
        """计划一次朝 facing 方向的移动；屏幕空间不够返回 False。

        name 给定时使用指定动画（手动触发），否则随机选一个移动姿态。
        """
        if self._edge_probe.active:
            return False
        if self._move_plan is not None:
            return True  # 已在移动/已计划
        avail = self.screen().availableGeometry()
        dir_sign = 1 if self.facing == 'right' else -1
        cx = self.x() + self._w / 2
        distance = random.randint(catalog.MOVE_MIN_PX, catalog.MOVE_MAX_PX)
        target_cx = cx + dir_sign * distance
        half_w = self._w / 2
        left_bound = avail.left() + catalog.MOVE_MARGIN + half_w
        right_bound = avail.right() - catalog.MOVE_MARGIN - half_w
        if target_cx < left_bound or target_cx > right_bound:
            return False
        if not self.moves:
            return False
        move_name = name or self._pick(self.moves)
        if not self._switch(move_name) or self.movie is None:
            return False
        known_duration = getattr(self.movie, 'known_duration', None)
        duration = known_duration() if callable(known_duration) else 0.0
        if duration <= 0:
            duration = catalog.MOVE_FALLBACK_DURATION_SEC
        self._move_plan = {
            'start_x': self.x(),
            'target_x': int(round(target_cx - half_w)),
            'y': self.y(),
            'duration': duration,
        }
        self._move_timer.start()
        return True

    def _trigger_move(self, name: str) -> None:
        """手动触发移动（右键菜单）：先打断当前移动，再朝 facing 方向走动；
        屏幕空间不足则原地播放走路姿态（不位移）。"""
        if self._edge_probe.active:
            self._edge_probe.cancel('manual_move', restore=False)
        self._cancel_move()
        if not self._try_move(name):
            self._switch(name)  # 贴边放不下：原地播放走路姿态，不位移

    def _on_move_tick(self) -> None:
        """位置驱动：跟随动画播放进度插值（前后各 2s 不动，中间走完全程）。"""
        plan = self._move_plan
        if not plan or self.movie is None:
            self._move_timer.stop()
            return
        t = self.movie.currentTimeSeconds()
        lead, tail = catalog.MOVE_LEAD_SEC, catalog.MOVE_TAIL_SEC
        dur = plan['duration']
        if t <= lead:
            x = plan['start_x']
        elif t >= dur - tail:
            x = plan['target_x']
        else:
            progress = (t - lead) / max(0.1, dur - lead - tail)
            x = plan['start_x'] + (plan['target_x'] - plan['start_x']) * progress
        self.move(int(round(x)), plan['y'])
        if t >= dur - tail:
            # 到位：提交终点，动画自然播完后续链
            self._move_timer.stop()
            self._move_plan = None
            self._save_position()

    def _cancel_move(self) -> None:
        self._move_timer.stop()
        self._move_plan = None

    # ================================================================ 交互
    def _is_in_interactive_area(self, local_pos) -> bool:
        """复用当前透明遮罩，允许点击伸出画布中部的头发、尾巴等部位。"""
        return self.rect().contains(local_pos) and self.mask().contains(local_pos)

    @staticmethod
    def _drag_threshold() -> int:
        """Qt 鼠标坐标使用逻辑像素；阈值跟随系统，不随桌宠尺寸缩小。"""
        return max(catalog.DRAG_THRESHOLD, QApplication.startDragDistance())

    def _boost_throw_velocity(self) -> None:
        """按释放时速度整体放大抛掷向量，保持鼠标拖动方向。"""
        speed = math.hypot(self._phys_vel[0], self._phys_vel[1])
        if speed <= 1e-6:
            return
        target_speed = min(
            catalog.DRAG_THROW_MAX_SPEED,
            speed * catalog.drag_throw_boost(speed),
        )
        scale = target_speed / speed
        self._phys_vel[0] *= scale
        self._phys_vel[1] *= scale

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self._suspended or self._shutting_down:
            return
        if event.button() == Qt.MouseButton.LeftButton:
            local_pos = event.position().toPoint()
            if self._bubble_hit_test(local_pos):
                self.show_bubble()
                event.accept()
                return
            if not self._is_in_interactive_area(local_pos):
                return  # 透明留白区域不参与点击/拖拽
            self._press_global = event.globalPosition().toPoint()
            self._grab_offset = self._press_global - self.pos()
            self._dragging = False
            self._long_press_fired = False
            self._long_press_timer.start(catalog.LONG_PRESS_MS)
            self._cancel_move()  # 按下即打断移动
            self._last_global = self._press_global
            self._last_move_time = time.monotonic()
            self._pointer_velocity = (0.0, 0.0)
            self._phys_vel = [0.0, 0.0]
            self._phys_pos = [float(self.x()), float(self.y())]
            self._stop_physics()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._press_global is None or not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        g = event.globalPosition().toPoint()
        use_physics = self.drag_physics and not self._paused
        delta = g - self._press_global
        if not self._dragging:
            if math.hypot(delta.x(), delta.y()) < self._drag_threshold():
                return  # 未超阈值：仍是点击候选
            self._dragging = True
            self._edge_probe.on_drag_started()
            self._long_press_timer.stop()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            self._record_drag_pointer(g)
            # 移动优先于动画切换；首个拖拽事件立即响应，不等待解码或时钟。
            target = g - self._grab_offset
            self.move(target)
            if use_physics:
                self._phys_pos = [float(target.x()), float(target.y())]
                self._drag_target = target
                self._start_physics('drag')
            if self.drag and not self._paused:
                self._switch(self.drag)  # 已预载时立即展示悬空首帧
            event.accept()
            return

        # 已经处于拖拽中
        self._record_drag_pointer(g)
        if use_physics:
            self._drag_target = g - self._grab_offset
            if self._physics_mode != 'drag':
                self._start_physics('drag')
        else:
            self.move(g - self._grab_offset)  # 跟手（保持抓起时的偏移）
        event.accept()

    def _record_drag_pointer(self, position: QPoint) -> None:
        now = time.monotonic()
        if self._last_global is not None:
            delta = position - self._last_global
            self._pointer_velocity = pointer_velocity(
                self._pointer_velocity,
                delta.x(),
                delta.y(),
                now - self._last_move_time,
                max_speed=catalog.DRAG_SPEED_SAMPLE_MAX,
            )
        self._last_global = position
        self._last_move_time = now

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            super().mouseReleaseEvent(event)
            return
        if self._press_global is None:
            return  # 没有有效按压，不能把透明处松手当成一次点击
        was_dragging = self._dragging
        use_physics = self.drag_physics and not self._paused
        self._long_press_timer.stop()
        g = event.globalPosition().toPoint()
        dist = 0.0
        if self._press_global is not None:
            d = g - self._press_global
            dist = math.hypot(d.x(), d.y())
        if was_dragging:
            self.unsetCursor()
            self._just_dragged = True  # 抑制拖拽结束后的幽灵点击
            QTimer.singleShot(150, self._clear_just_dragged)
            if use_physics:
                # 松手惯性来自鼠标采样，不混入弹簧追赶速度；停住再松手不甩飞。
                if self._last_global is not None and g != self._last_global:
                    self._record_drag_pointer(g)
                self._phys_vel = list(release_velocity(
                    self._pointer_velocity, time.monotonic() - self._last_move_time,
                ))
                self._boost_throw_velocity()
                self._start_physics('throw')
            else:
                if self._grab_offset is not None:
                    self.move(g - self._grab_offset)  # 停在松手处
            edge_bounced = False if self._paused else self._trigger_edge_feedback()
            if not self._paused:
                self._edge_probe.on_release(was_dragging)
            if not use_physics:
                self._save_position()
            if self.idles and not edge_bounced and not self._paused:
                self._switch(self._pick(self.idles))  # 回待机缓冲
        elif dist < self._drag_threshold() and not self._long_press_fired:
            self._queue_tap()
        self._dragging = False
        self._press_global = None
        self._grab_offset = None
        self._long_press_fired = False
        event.accept()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        """Qt 用 DoubleClick 替代第二次 Press；转发以保留拖拽状态。"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.mousePressEvent(event)
        else:
            super().mouseDoubleClickEvent(event)

    def _clear_just_dragged(self) -> None:
        self._just_dragged = False

    def _on_long_press(self) -> None:
        if self._press_global is None or self._dragging or self._suspended:
            return
        self._long_press_fired = True
        self._tap_timer.stop()
        self._tap_count = 0
        self._cancel_move()
        self._start_squash()
        name = self._special_animation('被吓一跳', self.acts or self.clicks)
        if name:
            self._switch(name)
        self._duck_sound.play()

    def _queue_tap(self) -> None:
        """延迟一个短窗口，区分单击、双击和快速连续点击。"""
        self._tap_count += 1
        self._tap_timer.start(catalog.TAP_BURST_WINDOW_MS)

    def _flush_tap_burst(self) -> None:
        count = self._tap_count
        self._tap_count = 0
        action = classify_tap_burst(count)
        if action == 'single':
            self._on_click()
        elif action == 'double':
            self._on_double_click()
        else:
            self._on_rapid_click(count)

    def _play_click_response(self, pool: list[str]) -> None:
        if not pool:
            return
        self._cancel_move()
        self._start_squash()
        self._switch(self._pick(pool, exclude=self.anim))

    def _on_click(self) -> None:
        """单击：播放一个普通点击回应。"""
        if self._just_dragged:
            return
        if self._edge_probe.on_clicked():
            return
        self._play_click_response(self.clicks)
        self.show_bubble()

    def _on_double_click(self) -> None:
        """双击：播放更强的回应，并触发尖叫鸭。"""
        self._play_click_response(self.clicks or self.acts)
        self._duck_sound.play()
        self.show_bubble()

    def _on_rapid_click(self, count: int) -> None:
        """快速连续点击：切到随机动作，次数越多越像被连续戳醒。"""
        self._play_click_response(self.acts or self.clicks)
        self._duck_sound.play()
        self.show_bubble()

    def _on_bubble_anim_tick(self) -> None:
        elapsed = self._bubble_anim_clock.elapsed()
        duration = 220 if self._bubble_anim_direction > 0 else 180
        phase = min(1.0, elapsed / float(duration))
        self._bubble_progress = (
            phase if self._bubble_anim_direction > 0 else 1.0 - phase
        )
        if phase >= 1.0:
            self._bubble_anim_timer.stop()
            if self._bubble_anim_direction < 0:
                self._bubble_visible = False
                self._bubble_progress = 0.0
        self._sync_mask()
        self.update()

    def preview_bubble(self, visible: bool | None) -> None:
        """临时预览不修改持久开关；None 表示退出预览。"""
        self._bubble_preview = visible
        if visible is True:
            self.show_bubble(30_000)
        else:
            self.hide_bubble(immediate=visible is None)

    def show_bubble(self, duration_ms: int = 4800) -> None:
        """无文字渐进展开气泡；只在短暂动画期间增加重绘。"""
        if (
            not (self.bubble_enabled if self._bubble_preview is None else self._bubble_preview)
            or self._suspended
            or self._paused
            or self._shutting_down
        ):
            return
        self._bubble_visible = True
        self._bubble_progress = 0.0
        self._bubble_anim_direction = 1
        self._bubble_anim_clock.restart()
        self._bubble_anim_timer.start()
        self._bubble_timer.start(max(1200, min(30_000, int(duration_ms))))
        self._sync_mask()
        self.update()

    def hide_bubble(self, *, immediate: bool = False) -> None:
        """渐进收起气泡；暂停、隐藏和退出时可立即清除命中区域。"""
        self._bubble_timer.stop()
        if not self._bubble_visible and self._bubble_progress <= 0.0:
            return
        if immediate:
            self._bubble_anim_timer.stop()
            self._bubble_visible = False
            self._bubble_progress = 0.0
            self._sync_mask()
            self.update()
            return
        self._bubble_visible = True
        self._bubble_anim_direction = -1
        self._bubble_anim_clock.restart()
        self._bubble_anim_timer.start()

    def _trigger_edge_feedback(self) -> bool:
        """拖到屏幕边缘时做一次短暂压扁，并用物理反弹离开边缘。"""
        scr = self._screen_available()
        avail = scr.availableGeometry()
        contacts = edge_contacts(
            (float(self.x()), float(self.y()), float(self._w), float(self._h)),
            (
                float(avail.left()),
                float(avail.top()),
                float(avail.width()),
                float(avail.height()),
            ),
            catalog.EDGE_FEEDBACK_MARGIN,
        )
        if not contacts:
            return False

        if 'left' in contacts:
            self.facing = 'right'
            if self.drag_physics:
                self._phys_vel[0] = max(abs(self._phys_vel[0]), catalog.EDGE_BOUNCE_SPEED)
        elif 'right' in contacts:
            self.facing = 'left'
            if self.drag_physics:
                self._phys_vel[0] = -max(abs(self._phys_vel[0]), catalog.EDGE_BOUNCE_SPEED)
        if 'top' in contacts:
            if self.drag_physics:
                self._phys_vel[1] = max(abs(self._phys_vel[1]), catalog.EDGE_BOUNCE_SPEED)
        elif 'bottom' in contacts:
            if self.drag_physics:
                self._phys_vel[1] = -max(abs(self._phys_vel[1]), catalog.EDGE_BOUNCE_SPEED)

        if self.drag_physics:
            self._phys_pos = [float(self.x()), float(self.y())]
            self._start_physics('throw')
        self._start_squash()
        self._play_bounce_sound()
        name = self._special_animation('被吓一跳', self.acts or self.clicks)
        if name:
            self._switch(name)
        return True

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        if not self._is_in_interactive_area(event.pos()):
            return
        root_menu = QMenu(self)
        menus.add_settings(root_menu, self.open_settings)
        root_menu.addAction('暂停 / 继续', self.toggle_pause)
        menus.add_random_action(root_menu, self)
        menus.add_bubble_toggle(root_menu, self)

        menu = root_menu.addMenu('更多控制')
        self._add_animation_shortcuts_menu(menu)
        self.add_action_menu(menu)
        self.add_personality_menu(menu)
        self._add_playback_speed_menu(menu)
        menus.add_toggle(menu, menus.ToggleSpec(
            label='弹性拖拽与抛掷（原版回弹）',
            checked=lambda: self.drag_physics,
            toggled=self.set_drag_physics,
        ))
        menus.add_toggle(menu, menus.ToggleSpec(
            label='边缘探头（左右贴边）',
            checked=lambda: self.edge_probe_enabled,
            toggled=self.set_edge_probe_enabled,
            sync_signal=self.edgeProbeChanged,
        ))
        menus.add_interaction_menu(menu, self)
        menus.add_display_menu(menu, self)
        menus.add_character_menu(menu, self.cfg, self._request_switch_character)

        menu.addSeparator()
        menu.addAction('回到右下角', self._go_default_corner)
        menus.add_toggle(menu, menus.ToggleSpec(
            label='窗口置顶',
            checked=lambda: bool(self.cfg.get('on_top', True)),
            toggled=self.set_on_top,
        ))
        menus.add_toggle(menu, menus.ToggleSpec(
            label='不移动',
            checked=lambda: self.no_move,
            toggled=self.set_no_move,
        ))
        menus.add_autostart(menu)
        self._add_scale_menu(menu)
        self._add_switch_delay_menu(menu)

        menu.addSeparator()
        root_menu.addAction('回到右下角', self._go_default_corner)
        root_menu.addAction('退出', self._request_quit)
        try:
            root_menu.exec(event.globalPos())
        finally:
            root_menu.deleteLater()

    def _add_animation_shortcuts_menu(self, parent: QMenu) -> None:
        """按分类列出当前形象已有的动画，直接点播。"""
        if self.idles:
            menu = parent.addMenu('动画 · 待机')
            for name in self.idles:
                menu.addAction(name, lambda n=name: self._switch(n))
        if self.turns:
            menu = parent.addMenu('动画 · 转向')
            for name in self.turns:
                menu.addAction(name, lambda n=name: self._switch(n))

        menu = parent.addMenu('动画 · 移动')
        for name in self.moves:
            menu.addAction(name, lambda n=name: self._trigger_move(n))

        menu = parent.addMenu('动画 · 点击回应')
        for name in self.clicks:
            menu.addAction(name, lambda n=name: self._switch(n))

        menu = parent.addMenu('动画 · 随机动作')
        for name in self.acts:
            menu.addAction(name, lambda n=name: self._switch(n))

    def _add_playback_speed_menu(self, parent: QMenu) -> None:
        menu = parent.addMenu('播放速率')
        for i in range(10, 21):
            value = i / 10.0
            action = menu.addAction(f'{value:.1f}x')
            action.setCheckable(True)
            action.setChecked(abs(self.playback_speed - value) < 0.01)
            action.triggered.connect(
                lambda checked=False, value=value: self.set_playback_speed(value)
            )

    def _add_scale_menu(self, parent: QMenu) -> None:
        menu = parent.addMenu('大小')
        current_width = int(round(catalog.CANVAS_W * self.scale))
        preset_widths = {
            int(round(catalog.CANVAS_W * step)) for step in catalog.SCALE_STEPS
        }
        if current_width not in preset_widths:
            current = menu.addAction(f'当前：{current_width}px')
            current.setEnabled(False)
        for step in catalog.SCALE_STEPS:
            pixels = int(round(catalog.CANVAS_W * step))
            action = menu.addAction(f'{pixels}px')
            action.setCheckable(True)
            action.setChecked(abs(self.scale - step) < 0.02)
            action.triggered.connect(
                lambda checked=False, step=step: self.change_scale(step)
            )
        custom = menu.addAction('自定义大小…')
        custom.triggered.connect(self._ask_custom_scale)

    def _add_switch_delay_menu(self, parent: QMenu) -> None:
        menu = parent.addMenu('动作切换时间')
        presets = (0, 1, 3, 5, 10)
        if self.action_switch_delay_ms not in {s * 1000 for s in presets}:
            current_seconds = self.action_switch_delay_ms / 1000
            current = menu.addAction(f'当前：{current_seconds:g} 秒')
            current.setEnabled(False)
        for seconds in presets:
            action = menu.addAction('立即' if seconds == 0 else f'{seconds} 秒')
            action.setCheckable(True)
            action.setChecked(self.action_switch_delay_ms == seconds * 1000)
            action.triggered.connect(
                lambda checked=False, seconds=seconds: self.set_action_switch_delay(
                    seconds * 1000
                )
            )
        custom = menu.addAction('自定义…')
        custom.triggered.connect(self._ask_action_switch_delay)

    def _request_switch_character(self, character_id: str) -> None:
        """请求切换角色；优先交给 app 做热切换，否则只保存配置。"""
        if self.on_switch_character is not None:
            self.on_switch_character(character_id)
        else:
            self.cfg.set('character', character_id)
            self.cfg.save()

    def set_playback_speed(self, speed: float) -> None:
        """设置动画播放速率并持久化。"""
        self.playback_speed = max(0.1, float(speed))
        self.cfg.set('playback_speed', self.playback_speed)
        self.cfg.save()
        if self.movie is not None and hasattr(self.movie, 'set_playback_speed'):
            self.movie.set_playback_speed(self._effective_playback_speed(self.anim))

    def _ask_custom_scale(self) -> None:
        width = int(round(catalog.CANVAS_W * self.scale))
        value, accepted = QInputDialog.getInt(
            self, '自定义桌宠大小', '显示宽度（像素）', width, 160, 1280, 16
        )
        if accepted:
            self.change_scale(value / catalog.CANVAS_W)

    def set_action_switch_delay(self, delay_ms: int) -> None:
        """设置动作结束后的等待时间，使用单次 QTimer，不增加常驻负载。"""
        self.action_switch_delay_ms = max(0, min(60_000, int(delay_ms)))
        self.cfg.set('action_switch_delay_ms', self.action_switch_delay_ms)
        self.cfg.save()
        if self._action_switch_timer.isActive():
            self._action_switch_timer.stop()
            self._schedule_action_switch()

    def _ask_action_switch_delay(self) -> None:
        seconds, accepted = QInputDialog.getInt(
            self,
            '自定义动作切换时间',
            '动作结束后等待（秒）',
            self.action_switch_delay_ms // 1000,
            0,
            60,
            1,
        )
        if accepted:
            self.set_action_switch_delay(seconds * 1000)

    def set_soft_edges(self, enabled: bool) -> None:
        """切换 Alpha=1 底噪清理并持久化；重建当前播放器以即时生效。"""
        enabled = bool(enabled)
        if enabled == self.soft_edges:
            return
        self.soft_edges = enabled
        self.cfg.set('soft_edges', enabled)
        self.cfg.save()

        current = self.anim
        self._unbind_movie()
        if self.movie is not None:
            self.movie.stop()
            self.movie = None
        self.lib.set_soft_edges(enabled)
        if not self._suspended and not self._shutting_down:
            self._switch(current if current in self.lib.names() else self.idle)
        self.softEdgesChanged.emit(enabled)

    def _effective_playback_speed(self, name: str) -> float:
        if self._resource_constrained and name in self.idles:
            return self.playback_speed * catalog.BUSY_IDLE_SPEED_FACTOR
        return self.playback_speed

    def _check_system_load(self) -> None:
        ratio = system_load_ratio()
        if not self._load_governor.observe(ratio):
            return
        self._resource_constrained = self._load_governor.constrained
        logging.info(
            '资源模式=%s load_ratio=%.2f',
            '省资源' if self._resource_constrained else '正常',
            ratio,
        )
        interaction_active = self.anim in self.clicks or self.anim == self.drag
        if (
            self._resource_constrained
            and not self._dragging
            and not interaction_active
            and self.idles
        ):
            self._switch(self._pick(self.idles))
        elif self.movie is not None and hasattr(self.movie, 'set_playback_speed'):
            self.movie.set_playback_speed(self._effective_playback_speed(self.anim))
        if not self._resource_constrained and self._frame_pixmap is not None:
            self._sync_mask()

    def _resume_busy_idle(self) -> None:
        if self._resource_constrained and self.idles and not self._dragging:
            self._switch(self._pick(self.idles, exclude=self.anim))
        else:
            self._pick_next()

    def set_paused(self, on: bool) -> None:
        """暂停/继续可见动画，不隐藏窗口，也不释放素材库。"""
        on = bool(on)
        if on == self._paused or self._suspended or self._shutting_down:
            return
        self._paused = on
        if on:
            self._edge_probe.pause()
            self._cancel_drag_input()
            self._bounce_sound.close()
            self.hide_bubble(immediate=True)
            self._cancel_move()
            self._action_switch_timer.stop()
            self._long_press_timer.stop()
            self._tap_timer.stop()
            self._cursor_timer.stop()
            self._greeting_timer.stop()
            self._resource_timer.stop()
            self._physics_timer.stop()
            if self.movie is not None:
                self.movie.stop()
        else:
            self._edge_probe.resume()
            self._cursor_timer.start()
            self._schedule_next_greeting()
            self._resource_timer.start()
            if self.movie is not None:
                self.movie.start()
            else:
                self._switch(self.anim if self.anim in self.lib.names() else self.idle)
        self.pausedChanged.emit(self._paused)

    def toggle_pause(self) -> None:
        self.set_paused(not self._paused)

    @property
    def paused(self) -> bool:
        """对外只读的暂停状态；菜单等外部模块不应读私有字段。"""
        return self._paused

    def play_random_action(self) -> None:
        pool = self.acts or self.clicks or self.idles
        if pool:
            self._cancel_move()
            self._switch(self._pick(pool, exclude=self.anim))

    def trigger_duck_sound(self) -> None:
        self._duck_sound.play()

    def suspend_animation(self) -> None:
        """托盘隐藏时停止解码与高频计时器，保留当前画面和动作名。"""
        if self._suspended or self._shutting_down:
            return
        self._suspended = True
        self._edge_probe.pause()
        self._cancel_drag_input()
        self._bounce_sound.close()
        self.hide_bubble(immediate=True)
        self._long_press_timer.stop()
        self._tap_timer.stop()
        self._cursor_timer.stop()
        self._greeting_timer.stop()
        self._cancel_move()
        self._squash_timer.stop()
        self._physics_timer.stop()
        self._idle_pause_timer.stop()
        self._resource_timer.stop()
        self._action_switch_timer.stop()
        self._unbind_movie()
        if self.movie is not None:
            self.movie.stop()
            self.movie = None
        self.lib.close()

    def resume_animation(self) -> None:
        """从托盘重新显示时恢复当前动作并重新启用负载采样。"""
        if not self._suspended or self._shutting_down:
            return
        self._suspended = False
        self._edge_probe.resume()
        if not self._paused:
            self._cursor_timer.start()
            self._schedule_next_greeting()
            self._resource_timer.start()
            self._check_system_load()
        self._switch(self.anim if self.anim in self.lib.names() else self.idle)

    def set_mouse_through(self, on: bool) -> None:
        """鼠标穿透：开启后桌宠不接收鼠标事件，点击会穿透到下层。"""
        self.mouse_through = bool(on)
        if self.mouse_through:
            self._cancel_drag_input()
        self.cfg.set('mouse_through', self.mouse_through)
        self.cfg.save()
        was_visible = self.isVisible()
        self.setWindowFlag(Qt.WindowType.WindowTransparentForInput, self.mouse_through)
        if was_visible:
            self.show()
        else:
            self.hide()

    def set_drag_physics(self, on: bool, *, persist: bool = True) -> None:
        """拖动物理开关。"""
        self.drag_physics = bool(on)
        if persist:
            self.cfg.set('drag_physics', self.drag_physics)
            self.cfg.save()
        if not self.drag_physics:
            self._stop_physics()

    def set_edge_probe_enabled(self, on: bool, *, persist: bool = True) -> None:
        """启用/关闭左右贴边探头；关闭时恢复进入前的位置。"""
        self.edge_probe_enabled = bool(on)
        self._edge_probe.set_enabled(self.edge_probe_enabled)
        if persist:
            self.cfg.set('edge_probe_enabled', self.edge_probe_enabled)
            self.cfg.save()
        self.edgeProbeChanged.emit(self.edge_probe_enabled)

    def set_sound_enabled(self, on: bool, *, persist: bool = True) -> None:
        """统一声音开关；当前包含尖叫鸭音效，后续音效可复用。"""
        self.sound_enabled = bool(on)
        self.duck_sound_enabled = self.sound_enabled
        self._duck_sound.enabled = self.sound_enabled
        self._bounce_sound.enabled = self.sound_enabled
        if persist:
            self.cfg.set('sound_enabled', self.sound_enabled)
            self.cfg.set('duck_sound', self.sound_enabled)
            self.cfg.save()
        if not self.sound_enabled:
            self._duck_sound.close()
            self._bounce_sound.close()
        self.soundChanged.emit(self.sound_enabled)
        self.duckSoundChanged.emit(self.sound_enabled)

    def set_bounce_sound_variant(self, variant: str, *, persist: bool = True) -> None:
        """选择实际碰撞时播放的回弹音，不影响拖动过程。"""
        self._bounce_sound.set_variant(variant)
        if persist:
            self.cfg.set('bounce_sound_variant', self._bounce_sound.variant)
            self.cfg.save()
        self.bounceSoundVariantChanged.emit(self._bounce_sound.variant)

    def set_duck_sound(self, on: bool) -> None:
        """兼容旧调用名。"""
        self.set_sound_enabled(on)

    def set_proactive_greetings(self, on: bool) -> None:
        """偶尔主动挥手问候开关。"""
        self.proactive_greetings = bool(on)
        self.cfg.set('proactive_greetings', self.proactive_greetings)
        self.cfg.save()
        if self.proactive_greetings:
            self._schedule_next_greeting()
        else:
            self._greeting_timer.stop()
        self.proactiveGreetingsChanged.emit(self.proactive_greetings)

    def add_bubble_toggle(self, menu: QMenu):
        """兼容入口：托盘与右键菜单共用 menus.add_bubble_toggle。"""
        return menus.add_bubble_toggle(menu, self)
        return action

    def set_bubble_enabled(self, on: bool, *, persist: bool = True) -> None:
        """切换无文字对话气泡；关闭时立即清掉窗口命中区域。"""
        self.bubble_enabled = bool(on)
        self._bubble_preview = None
        if persist:
            self.cfg.set('bubble_enabled', self.bubble_enabled)
            self.cfg.save()
        if self.bubble_enabled:
            self.show_bubble()
        else:
            self.hide_bubble(immediate=True)
        self.bubbleChanged.emit(self.bubble_enabled)

    def _start_physics(self, mode: str) -> None:
        if self._physics_mode != mode or not self._physics_timer.isActive():
            screen = self.screen()
            refresh = screen.refreshRate() if screen is not None else 60.0
            self._physics_timer.setInterval(round(1000 / max(60.0, min(120.0, refresh))))
            self._last_physics_time = time.monotonic()
            self._physics_mode = mode
            self._physics_timer.start()

    def _cancel_drag_input(self) -> None:
        """隐藏、暂停或关闭时释放抓手状态，避免恢复后沿用旧按压。"""
        self._dragging = False
        self._press_global = None
        self._grab_offset = None
        self._drag_target = None
        self._last_global = None
        self._pointer_velocity = (0.0, 0.0)
        self._long_press_timer.stop()
        self._tap_timer.stop()
        self.unsetCursor()
        self._stop_physics()

    def _stop_physics(self) -> None:
        self._physics_timer.stop()
        self._physics_mode = None
        self._last_physics_time = None

    def _on_physics_tick(self) -> None:
        if self._paused or self._suspended or self._shutting_down:
            self._stop_physics()
            return
        now = time.monotonic()
        previous = self._last_physics_time
        self._last_physics_time = now
        if previous is None:
            return
        elapsed = now - previous
        if elapsed <= 1e-9 or self._physics_mode is None:
            return
        # 数值核心在 pet.physics；这里只负责计时、屏幕边界与提交位置。
        bounds = None
        if self._physics_mode == 'throw':
            avail = self._screen_available().availableGeometry()
            bounds = ThrowBounds.from_screen(
                float(avail.left()), float(avail.top()),
                float(avail.right()), float(avail.bottom()),
                window_width=float(self._w), window_height=float(self._h),
            )
        target = (
            (float(self._drag_target.x()), float(self._drag_target.y()))
            if self._drag_target is not None else None
        )
        result = self._physics.step_frame(
            elapsed, mode=self._physics_mode,
            drag_target=target, bounds=bounds,
        )
        if result.stopped:
            self._physics_mode = None
        # 先完成本轮位置更新，再播放音效；静止落地不连续发声。
        for _ in result.impacts:
            QTimer.singleShot(0, self._play_bounce_sound)
        self.move(int(round(result.pos[0])), int(round(result.pos[1])))
        if self._physics_mode is None:
            self._stop_physics()
            self._save_position()
            self._edge_probe.on_throw_settled()

    # 物理状态由 pet.physics 持有；这里保持原有的读写形状，
    # 让窗口其余部分（与既有验收工具）继续按 `_phys_pos[0]` 访问。
    def _physics_engine(self) -> PhysicsEngine:
        """返回物理状态容器；测试替身绕过 __init__ 时按需补建。"""
        engine = getattr(self, '_physics', None)
        if engine is None:
            engine = PhysicsEngine()
            self._physics = engine
        return engine

    @property
    def _phys_pos(self) -> list[float]:
        return self._physics_engine().pos

    @_phys_pos.setter
    def _phys_pos(self, value) -> None:
        engine = self._physics_engine()
        engine.pos = [float(value[0]), float(value[1])]

    @property
    def _phys_vel(self) -> list[float]:
        return self._physics_engine().vel

    @_phys_vel.setter
    def _phys_vel(self, value) -> None:
        engine = self._physics_engine()
        engine.vel = [float(value[0]), float(value[1])]

    def _play_bounce_sound(self) -> None:
        if not self._paused and not self._suspended and not self._shutting_down:
            self._bounce_sound.play()

    def _request_quit(self) -> None:
        self._save_position()
        QApplication.instance().quit()

    def shutdown(self) -> None:
        """停止窗口计时器和媒体 reader，可安全重复调用。"""
        self._cancel_drag_input()
        if self._shutting_down:
            return
        self._shutting_down = True
        self.hide_bubble(immediate=True)
        for timer in (
            self._move_timer,
            self._squash_timer,
            self._physics_timer,
            self._resource_timer,
            self._idle_pause_timer,
            self._action_switch_timer,
            self._long_press_timer,
            self._tap_timer,
            self._cursor_timer,
            self._greeting_timer,
        ):
            timer.stop()
        self._edge_probe.cancel('shutdown', restore=False)
        self._unbind_movie()
        if self.movie is not None:
            self.movie.stop()
            self.movie = None
        self.lib.close()
        self._duck_sound.close()
        self._bounce_sound.close()

    def closeEvent(self, event) -> None:  # noqa: N802
        self._save_position()
        self.shutdown()
        super().closeEvent(event)
