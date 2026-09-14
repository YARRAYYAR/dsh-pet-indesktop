# -*- coding: utf-8 -*-
"""边缘探头：贴住屏幕左右边缘，只露出角色一部分并保持可点击。

稳定探头状态不运行 timer；只有进入、拉直、返回和物理落地重进时才短暂
使用一个 16ms timer，不读取视频、不启动线程。
"""

from __future__ import annotations

import time
from typing import Any

from PySide6.QtCore import QRect, Qt, QTimer

from .window_effects import eased_progress, rotated_region_bounds

EDGE_PROBE_ANGLE = 45.0
EDGE_PEEK_EXPOSURE = 0.55
EDGE_ENGAGE_EXPOSURE = 0.82
EDGE_ENTER_MS = 300
EDGE_STRAIGHTEN_MS = 250
EDGE_RETURN_MS = 300
EDGE_IDLE_SECONDS = 5.0
EDGE_REENTRY_SECONDS = 5.0

OFF = 'OFF'
ENTERING = 'ENTERING'
PEEKING = 'PEEKING'
STRAIGHTENING = 'STRAIGHTENING'
STRAIGHTENED = 'STRAIGHTENED'
RETURNING = 'RETURNING'
_TRANSITION_MODES = {ENTERING, STRAIGHTENING, RETURNING}


def probe_window_x(side: str, exposure: float, visible: QRect, available: QRect) -> int:
    """按旋转后可见区域，把窗口放到左右屏幕边缘。"""
    exposure = max(0.0, min(1.0, float(exposure)))
    offscreen = (1.0 - exposure) * visible.width()
    if side == 'left':
        return round(available.left() - offscreen - visible.left())
    if side == 'right':
        return round(available.right() + offscreen - visible.right())
    raise ValueError(f'unknown edge side: {side!r}')


def edge_side_at_rest(win: Any, available: QRect) -> str | None:
    visible = win.character_local_region()
    if visible is None or visible.isEmpty():
        return None
    frame = win.frameGeometry()
    if frame.left() + visible.left() <= available.left():
        return 'left'
    if frame.left() + visible.right() >= available.right():
        return 'right'
    return None


class EdgeProbeController:
    """由 PetWindow 持有的可暂停、可取消边缘姿态控制器。"""

    def __init__(self, win: Any, *, clock=None) -> None:
        self.win = win
        self._clock = clock if callable(clock) else time.monotonic
        self.enabled = bool(getattr(win, 'cfg', None)
                            and win.cfg.get('edge_probe_enabled', False))
        self._mode = OFF
        self._side: str | None = None
        self._angle_deg = 0.0
        self._exposure = 1.0
        self._visible_region: QRect | None = None
        self._restore_x: int | None = None
        self._idle_remaining = 0.0
        self._reentry_remaining = 0.0
        self._hidden = False
        self._last_tick = 0.0
        self._transition_start = 0.0
        self._transition_duration = 0
        self._from_angle = 0.0
        self._to_angle = 0.0
        self._from_exposure = 1.0
        self._to_exposure = 1.0
        self._reentry_active = False
        self._timer = QTimer(win)
        self._timer.setInterval(16)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._on_timer)

    @property
    def active(self) -> bool:
        return self._mode != OFF

    @property
    def mode(self) -> str:
        return self._mode

    def current_angle_deg(self) -> float:
        return self._angle_deg if self.active else 0.0

    def set_enabled(self, on: bool) -> None:
        self.enabled = bool(on)
        if not self.enabled:
            self.cancel('feature_off', restore=True)

    def on_drag_started(self) -> None:
        self._cancel_reentry()
        if self.active:
            self.cancel('drag_away', restore=False)

    def on_release(self, was_dragging: bool) -> None:
        if not self.enabled or self._hidden or not was_dragging:
            return
        if self.active:
            self.cancel('drag_away', restore=False)
        # 物理抛掷仍由物理引擎负责；停稳后由 on_throw_settled 重评估。
        if getattr(self.win, '_physics_mode', None) is None:
            self._maybe_enter()

    def on_throw_settled(self) -> None:
        """抛掷停稳后延迟重进，避免探头立刻抢走反弹手感。"""
        if not self.enabled or self._hidden or self.active:
            return
        available = self._available_geometry()
        if available is None or edge_side_at_rest(self.win, available) is None:
            return
        self._reentry_active = True
        self._reentry_remaining = EDGE_REENTRY_SECONDS
        self._last_tick = self._clock()
        self._timer.start()

    def on_clicked(self) -> bool:
        """返回 True 表示点击已被探头消费。"""
        if not self.active or self._hidden:
            return False
        if self._mode in (PEEKING, RETURNING):
            self._begin_transition(
                STRAIGHTENING, EDGE_STRAIGHTEN_MS,
                to_angle=0.0, to_exposure=EDGE_ENGAGE_EXPOSURE,
            )
        elif self._mode == STRAIGHTENED:
            self._idle_remaining = EDGE_IDLE_SECONDS
            self._last_tick = self._clock()
            self._timer.start()
        return True

    def cancel(self, reason: str = '', restore: bool = False) -> None:
        was_active = self.active
        restore_x = self._restore_x
        self._mode = OFF
        self._side = None
        self._angle_deg = 0.0
        self._exposure = 1.0
        self._visible_region = None
        self._restore_x = None
        self._idle_remaining = 0.0
        self._reentry_active = False
        self._reentry_remaining = 0.0
        self._timer.stop()
        if was_active and restore and restore_x is not None:
            self.win.move(restore_x, self.win.y())
        if was_active:
            self.win._sync_mask()
            self.win.update()

    def pause(self) -> None:
        if self._hidden:
            return
        self._hidden = True
        self._timer.stop()

    def resume(self) -> None:
        if not self._hidden:
            return
        self._hidden = False
        if self.active or self._reentry_active:
            self._last_tick = self._clock()
            if self._mode in _TRANSITION_MODES or self._mode == STRAIGHTENED or self._reentry_active:
                self._timer.start()

    def _available_geometry(self) -> QRect | None:
        workspace = getattr(self.win, '_workspace_geometry', None)
        if callable(workspace):
            return workspace()
        screen = self.win._screen_available()
        return screen.availableGeometry() if screen is not None else None

    def _maybe_enter(self) -> None:
        if (not self.enabled or self._hidden or self.active
                or getattr(self.win, '_physics_mode', None) is not None):
            return
        available = self._available_geometry()
        if available is None:
            return
        side = edge_side_at_rest(self.win, available)
        if side is None:
            return
        visible = self.win.character_local_region()
        if visible is None or visible.isEmpty():
            return
        self._side = side
        self._visible_region = visible
        self._restore_x = self.win.x()
        self.win._cancel_move()
        self.win._stop_physics()
        if self.win.anim not in self.win.idles and self.win.idles:
            self.win._switch(self.win._pick(self.win.idles))
        sign = 1.0 if side == 'left' else -1.0
        self._begin_transition(
            ENTERING, EDGE_ENTER_MS,
            to_angle=sign * EDGE_PROBE_ANGLE,
            to_exposure=EDGE_PEEK_EXPOSURE,
        )

    def _begin_transition(self, mode: str, duration_ms: int, *,
                          to_angle: float, to_exposure: float) -> None:
        now = self._clock()
        self._mode = mode
        self._transition_start = now
        self._last_tick = now
        self._transition_duration = duration_ms
        self._from_angle = self._angle_deg
        self._to_angle = float(to_angle)
        self._from_exposure = self._exposure
        self._to_exposure = float(to_exposure)
        self._timer.start()

    def _on_timer(self) -> None:
        if self._hidden:
            return
        now = self._clock()
        if self._reentry_active:
            self._reentry_remaining -= max(0.0, now - self._last_tick)
            self._last_tick = now
            if self._reentry_remaining <= 0.0:
                self._reentry_active = False
                self._reentry_remaining = 0.0
                self._timer.stop()
                self._maybe_enter()
            return
        if self._mode in _TRANSITION_MODES:
            elapsed = (now - self._transition_start) * 1000.0
            progress = eased_progress(elapsed, self._transition_duration)
            self._angle_deg = self._from_angle + (self._to_angle - self._from_angle) * progress
            self._exposure = self._from_exposure + (self._to_exposure - self._from_exposure) * progress
            self._apply_pose()
            if progress < 1.0:
                return
            if self._mode in (ENTERING, RETURNING):
                self._mode = PEEKING
                self._timer.stop()
            else:
                self._mode = STRAIGHTENED
                self._idle_remaining = EDGE_IDLE_SECONDS
                self._last_tick = now
        elif self._mode == STRAIGHTENED:
            self._idle_remaining -= max(0.0, now - self._last_tick)
            self._last_tick = now
            if self._idle_remaining <= 0.0:
                sign = 1.0 if self._side == 'left' else -1.0
                self._begin_transition(
                    RETURNING, EDGE_RETURN_MS,
                    to_angle=sign * EDGE_PROBE_ANGLE,
                    to_exposure=EDGE_PEEK_EXPOSURE,
                )

    def _cancel_reentry(self) -> None:
        self._reentry_active = False
        self._reentry_remaining = 0.0
        if self._mode == OFF:
            self._timer.stop()

    def _apply_pose(self) -> None:
        if self._side is None or self._visible_region is None:
            return
        available = self._available_geometry()
        if available is None:
            return
        bounds = rotated_region_bounds(
            self._visible_region, self.win._frame_draw_rect(), self._angle_deg
        )
        x = probe_window_x(self._side, self._exposure, bounds, available)
        if x != self.win.x():
            self.win.move(x, self.win.y())
        self.win._sync_mask()
        self.win.update()
