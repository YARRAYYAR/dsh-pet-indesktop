# -*- coding: utf-8 -*-
"""贴顶倒立：把角色慢慢放到屏幕最顶端时逐渐翻转 180°。

与「边缘探头」同族但触发方式与副作用都不同：

- 边缘探头由「停在左/右/下边缘」触发，会**平移**窗口把角色推出去一截；
- 贴顶倒立由「角色头顶接近屏幕顶端」触发，只**原地旋转**，不改水平位置。
- 姿态是**直接到位**的（`TOP_FLIP_MS = 0`）：放到顶端就立刻倒立并露出设定比例，
  不做旋转过场；露出多少由 `exposure` 决定（设置面板可调，默认半个身体）。

角度由「窗口 y 距贴顶上限还有多远」决定：角色头顶进入
`TOP_FLIP_BAND_PX` 之内开始转，正好贴顶时转满 `TOP_FLIP_DEG`。

判定基准必须是**未旋转**的贴顶上限，而且**贴顶对齐也要用同一个基准**：
180° 旋转的包围盒与正立时相同，但**部分**旋转时包围盒会被撑大几十像素。若一侧
用旋转版上限、另一侧用正立版上限，两者会互相追尾（对齐推窗口 → 进度回落 →
包围盒缩小 → 窗口回来），真机表现为角色在屏幕顶端来回抽动。所以：

- 触发端：`flip_target()` 对着正立上限算进度（本模块）；
- 对齐端：`_workspace_window_top()` 在倒立期间同样用正立可见区。

两侧共用同一个常量基准，环就断了。

纯几何在 `flip_target()` 里（不碰 Qt，可直接单测）；`TopFlipController` 只负责
按时间插值当前角度、同步遮罩并请求重绘。计时器由控制器自己持有，与
`EdgeProbeController` 保持同一种生命周期形状（pause / resume / cancel）。
"""

from __future__ import annotations

import time
from typing import Any, Protocol, cast

from PySide6.QtCore import QObject, Qt, QTimer

from .window_effects import eased_progress

# ---------------------------------------------------------------- 参数
TOP_FLIP_DEG = 180.0        # 完全倒立
TOP_FLIP_BAND_PX = 110      # 角色头顶进入屏幕顶端这么多像素内开始翻转
TOP_FLIP_MS = 0             # 0 = 直接到位（放到顶端就直接倒立进去，不播过场动画）
TOP_FLIP_MIN_MS = 60        # 收尾/微小调整的最短时长，避免"咔"地跳一下
TOP_FLIP_INTERVAL_MS = 16
TOP_FLIP_EPS_DEG = 0.05     # 小于该角度视为已回正，不留残角
TOP_FLIP_EXPOSURE_DEFAULT = 0.5  # 默认露出半个身体（用户可在设置面板调"探出头多少"）
TOP_FLIP_EXPOSURE_MAX = 0.95     # 上限：全露出去就看不见角色了


def flip_target(window_y: int, limit: int, *,
                band: int = TOP_FLIP_BAND_PX) -> float:
    """目标倒立进度（0~1）：0=正立，1=完全倒立。

    `limit` 是正立状态下的贴顶上限：`window_y <= limit` 表示已经贴到（或越过）
    屏幕顶端，进度为 1；离上限还有 `band` 像素以上时为 0，中间线性过渡。
    """
    band = max(1, int(band))
    remaining = int(window_y) - int(limit)
    if remaining <= 0:
        return 1.0
    if remaining >= band:
        return 0.0
    return 1.0 - remaining / band


class TopFlipHost(Protocol):
    """贴顶倒立对宿主窗口的最小依赖（纯注解，无运行时开销）。"""

    cfg: Any

    def _workspace_screen_top(self) -> int: ...
    def character_local_region_unrotated(self): ...
    def _presenter_layout(self): ...
    def _sync_mask(self) -> None: ...
    def update(self) -> None: ...


class TopFlipController:
    """由 PetWindow 持有的贴顶倒立控制器。"""

    def __init__(self, win: TopFlipHost, *, clock=None) -> None:
        self.win = win
        self._clock = clock if callable(clock) else time.monotonic
        self.enabled = bool(getattr(win, 'cfg', None)
                            and win.cfg.get('top_flip_enabled', True))
        self._progress = 0.0
        self._target = 0.0
        self._from = 0.0
        self._transition_start = 0.0
        self._transition_ms = TOP_FLIP_MS
        self._hidden = False
        self.edge_y = None
        self.edge_kind = 'screen'
        # 宿主一定是 QWidget（QObject 子类）；Protocol 无法表达这一点。
        self._timer = QTimer(cast(QObject, win))
        self._timer.setInterval(TOP_FLIP_INTERVAL_MS)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._on_timer)

    # ------------------------------------------------------------ 对外状态
    @property
    def progress(self) -> float:
        return self._progress

    @property
    def active(self) -> bool:
        return self._progress > 0.0

    def current_angle_deg(self) -> float:
        return TOP_FLIP_DEG * self._progress

    def update_screen_edge(self, screen, window_x, body) -> None:
        from .ceiling_geometry import screen_notch_rect
        notch = screen_notch_rect(screen)
        center = int(window_x) + body.center().x()
        in_notch = notch is not None and notch.left() <= center <= notch.right()
        self.edge_kind = 'notch' if in_notch else 'screen'
        self.edge_y = notch.y() + notch.height() if in_notch else screen.availableGeometry().top()

    def set_enabled(self, on: bool) -> None:
        was_active = self.active
        self.enabled = bool(on)
        if not self.enabled:
            self.reset()
            if was_active:
                position = getattr(self.win, '_virtual_pos', None)
                mover = getattr(self.win, '_move_window_towards', None)
                if callable(position) and callable(mover):
                    point = position()
                    mover(point.x(), point.y())

    def pause(self) -> None:
        """暂停（托盘隐藏 / 空闲暂停 / 退出过程）：冻结当前姿态，不再推进。"""
        self._hidden = True
        self._timer.stop()

    def resume(self) -> None:
        if not self._hidden:
            return
        self._hidden = False
        if self._progress != self._target:
            self._begin(self._target)

    def reset(self) -> None:
        """立即回正（不播动画）。"""
        if not self._progress and not self._timer.isActive():
            return
        self._progress = 0.0
        self._target = 0.0
        self._timer.stop()
        self._sync()

    def cancel(self, reason: str = '') -> None:
        """与边缘探头同名的收尾入口（退出 / 切角色 / 换缩放时调用）。"""
        self.reset()

    # ------------------------------------------------------------ 触发
    def on_position(self, window_y: int) -> None:
        """每次窗口位置提交后调用，按新的 y 更新目标角度。

        位置提交统一走 `apply_window_move()`，所以拖拽跟手、物理抛掷、走动、
        贴顶逐帧对齐都会经过这里，不需要各自再挂一次。
        """
        if not self.enabled or self._hidden:
            return
        # 探头与倒立不同族：探头期间（窗口被推出去一截）必须保持正立，
        # 否则 45°(探头) + 180°(倒立) 会叠成一个谁也没设计过的角度。
        probe = getattr(self.win, '_edge_probe', None)
        if probe is not None and getattr(probe, 'active', False):
            target = 0.0
        else:
            target = flip_target(window_y, self.reference_limit())
        if abs(target - self._target) < 1e-4:
            return
        self._target = target
        if abs(self._progress - target) < 1e-4:
            self._progress = target
            self._sync()
            return
        if TOP_FLIP_MS <= 0:
            # 直接到位：放到顶端就直接倒立进去（不做旋转过场）。姿态与露出量
            # 同帧一起生效，避免"先转一半再往上滑"的中间态。
            self._timer.stop()
            self._progress = target
            self._sync()
            return
        self._begin(target)

    def in_top_zone(self, window_y: int) -> bool:
        """窗口是否处在贴顶倒立的作用区（已贴顶，或还在触发带内）。

        逐帧对齐只在作用区内才介入：否则角色被拖到下方、进度还在回落的几百
        毫秒里会被对齐"抓"回顶端，表现为松手后又被吸上去。
        """
        return int(window_y) <= self.reference_limit() + TOP_FLIP_BAND_PX

    @property
    def exposure(self) -> float:
        """露在屏幕顶端之外的身高比例（设置面板里的"探出头多少"，0~0.95）。"""
        value = getattr(self.win, 'top_flip_exposure', TOP_FLIP_EXPOSURE_DEFAULT)
        try:
            value = float(value)
        except (TypeError, ValueError):
            value = TOP_FLIP_EXPOSURE_DEFAULT
        return max(0.0, min(TOP_FLIP_EXPOSURE_MAX, value))

    def top_offset_px(self, character_height: int) -> int:
        """倒立时窗口需要额外上移的像素（让半个身体露在屏幕顶端之外）。

        旋转不改变包围盒，所以"露出多少"只能靠把窗口整体抬高实现：按角色可见区
        高度的 `TOP_FLIP_EXPOSURE` 比例算，并随翻转进度线性生效——翻转过程中
        角色一边转一边往上滑，不会在某一帧突然跳一段。

        注意这里**只**影响贴顶上限（对齐与拖拽钳制），不影响 `_reference_limit()`：
        触发进度始终对着"正立上限"算，保持与对齐基准同源、不自激。
        """
        if self._progress <= 0.0 or character_height <= 0:
            return 0
        return int(round(character_height * self.exposure * self._progress))

    def reference_limit(self) -> int:
        """正立状态下的贴顶上限（判定基准，不含旋转、不含露出偏移）。"""
        screen_top = self.win._workspace_screen_top() if self.edge_y is None else self.edge_y
        getter = getattr(self.win, 'character_local_region_unrotated', None)
        region = getter() if callable(getter) else None
        if region is not None and not region.isEmpty():
            character_top = max(0, region.top())
        else:
            layout = getattr(self.win, '_presenter_layout', None)
            character_top = layout().pet_top() if callable(layout) else 0
        return screen_top - character_top

    # ------------------------------------------------------------ 动画
    def _begin(self, target: float) -> None:
        remaining = abs(target - self._progress)
        self._from = self._progress
        self._transition_start = self._clock()
        self._transition_ms = max(
            TOP_FLIP_MIN_MS, int(round(TOP_FLIP_MS * remaining))
        )
        self._timer.start()

    def _on_timer(self) -> None:
        if self._hidden:
            return
        elapsed = (self._clock() - self._transition_start) * 1000.0
        ratio = eased_progress(elapsed, self._transition_ms)
        progress = self._from + (self._target - self._from) * ratio
        if abs(progress - self._target) <= 1e-3:
            progress = self._target
            self._progress = progress
            self._timer.stop()
        else:
            self._progress = progress
        self._sync()

    def _sync(self) -> None:
        """角度变了：命中遮罩按旋转重算、请求重绘，并让窗口跟上变化的贴顶上限。

        露出量随进度变化 → 贴顶上限每一帧都在抬升，位置必须跟着走：拖拽中由
        钳制跟随（按住鼠标不动也要跟），静止时由逐帧对齐跟随。两者都由
        `_follow_top_flip_clamp()` 分发，避免在这里判断窗口状态。
        """
        self.win._sync_mask()
        self.win.update()
        follower = getattr(self.win, '_follow_top_flip_clamp', None)
        if self.active and callable(follower):
            follower()
