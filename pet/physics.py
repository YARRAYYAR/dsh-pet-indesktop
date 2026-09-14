# -*- coding: utf-8 -*-
"""拖拽弹簧与抛掷积分的纯数值核心。

从窗口里搬出来的动机：这是全项目最容易出错、又最难验证的一段数学。
它只依赖位置、速度、时间与屏幕边界，**不需要 QWidget**，因此可以脱离
窗口直接把"抛出去会不会乱飞""什么时候停下"这类问题写成断言。

行为与重构前逐位一致，包括这些容易被"顺手优化"掉、但实际是刻意设计的细节：
- 每帧最多补 33ms，且拆成 ≤8ms 的子步，避免弹簧积分不稳定；
- 抛掷的左右边界按窗口宽度的 1/3 留白（角色可视区只有窗口中间部分，
  允许窗口略微越界，让形象真的碰到屏幕边缘才反弹）；
- 落地的水平摩擦力按 dt 计算，速度低于阈值则彻底静止，不会在地面无限滑动。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .drag_motion import spring_step

# 抛掷物理常量（与原实现完全一致）
THROW_GRAVITY = 1400.0
THROW_RESTITUTION = 0.78
THROW_FRICTION_PER_SECOND = 2.5
THROW_STOP_VERTICAL_SPEED = 40.0
THROW_STOP_HORIZONTAL_SPEED = 15.0
THROW_SIDE_MARGIN_RATIO = 1.0 / 3.0

# 冲击音效的最低速度门槛
IMPACT_SOUND_MIN_SPEED = 80.0

# 单次补帧上限与子步上限
MAX_FRAME_SECONDS = 0.033
MAX_SUBSTEP_SECONDS = 0.008

MODE_DRAG = 'drag'
MODE_THROW = 'throw'


@dataclass(frozen=True)
class ThrowBounds:
    """抛掷可用的屏幕矩形（已按窗口尺寸折算成窗口左上角坐标范围）。"""

    left: float
    top: float
    right: float
    bottom: float

    @classmethod
    def from_screen(cls, left: float, top: float, right: float, bottom: float,
                    *, window_width: float, window_height: float) -> 'ThrowBounds':
        """按窗口尺寸与 1/3 留白折算边界。"""
        margin = window_width * THROW_SIDE_MARGIN_RATIO
        return cls(
            left=left - margin,
            top=top,
            right=right - window_width + margin,
            bottom=bottom - window_height,
        )


@dataclass(frozen=True)
class FrameResult:
    """一次补帧的结果。"""

    pos: tuple[float, float]
    impacts: tuple[float, ...]   # 每个 ≥ 门槛的撞击速度，用于决定播放几次音效
    stopped: bool                # 物理是否在本帧结束


class PhysicsEngine:
    """持有位置/速度，按 dv/dt 步进。调用方负责计时与边界。"""

    __slots__ = ('pos', 'vel')

    def __init__(self, position: tuple[float, float] = (0.0, 0.0),
                 velocity: tuple[float, float] = (0.0, 0.0)) -> None:
        self.pos = [float(position[0]), float(position[1])]
        self.vel = [float(velocity[0]), float(velocity[1])]

    def reset(self, position: tuple[float, float],
              velocity: tuple[float, float] = (0.0, 0.0)) -> None:
        self.pos = [float(position[0]), float(position[1])]
        self.vel = [float(velocity[0]), float(velocity[1])]

    def step_frame(self, elapsed: float, *, mode: str | None,
                   drag_target: tuple[float, float] | None,
                   bounds: ThrowBounds | None) -> FrameResult:
        """按实际经过时间推进物理；返回新位置、撞击与是否停下。

        `mode` 为 None 或经过时间过小时不做任何事（与原实现一致，
        此时调用方也不应提交位置）。
        """
        remaining = min(MAX_FRAME_SECONDS, max(0.0, float(elapsed)))
        if remaining <= 1e-9 or mode is None:
            return FrameResult(tuple(self.pos), (), False)

        impacts: list[float] = []
        stopped = False
        while remaining > 1e-9 and mode is not None:
            dt = min(MAX_SUBSTEP_SECONDS, remaining)
            if mode == MODE_DRAG:
                self._drag_step(dt, drag_target)
            else:
                impact, settled = self._throw_step(dt, bounds)
                if impact >= IMPACT_SOUND_MIN_SPEED:
                    impacts.append(impact)
                if settled:
                    mode = None
                    stopped = True
            remaining -= dt
        return FrameResult(tuple(self.pos), tuple(impacts), stopped)

    # ------------------------------------------------------------ 内部
    def _drag_step(self, dt: float, target: tuple[float, float] | None) -> None:
        """目标缺失时本步不修改任何状态（保持原实现的提前返回语义）。"""
        if target is None:
            return
        for axis in (0, 1):
            self.pos[axis], self.vel[axis] = spring_step(
                self.pos[axis], self.vel[axis], target[axis], dt,
            )

    def _throw_step(self, dt: float,
                    bounds: ThrowBounds | None) -> tuple[float, bool]:
        """一次抛掷子步；返回（本步撞击速度, 是否已静止）。

        边界缺失时只做重力积分，不判定碰撞（与原实现一致）。
        """
        self.vel[1] += THROW_GRAVITY * dt
        self.pos[0] += self.vel[0] * dt
        self.pos[1] += self.vel[1] * dt

        if bounds is None:
            return 0.0, False

        bounced = False
        impact_speed = 0.0
        if self.pos[0] < bounds.left:
            impact_speed = abs(self.vel[0])
            self.pos[0] = bounds.left
            self.vel[0] = abs(self.vel[0]) * THROW_RESTITUTION
            bounced = True
        elif self.pos[0] > bounds.right:
            impact_speed = abs(self.vel[0])
            self.pos[0] = bounds.right
            self.vel[0] = -abs(self.vel[0]) * THROW_RESTITUTION
            bounced = True

        if self.pos[1] < bounds.top:
            impact_speed = max(impact_speed, abs(self.vel[1]))
            self.pos[1] = bounds.top
            self.vel[1] = abs(self.vel[1]) * THROW_RESTITUTION
            bounced = True
        elif self.pos[1] >= bounds.bottom:
            impact_speed = max(impact_speed, abs(self.vel[1]))
            self.pos[1] = bounds.bottom
            # 地面摩擦力：水平速度逐渐衰减，避免一直在地面滑/弹
            friction = THROW_FRICTION_PER_SECOND * dt
            self.vel[0] *= max(0.0, 1.0 - friction)
            if abs(self.vel[1]) < THROW_STOP_VERTICAL_SPEED:
                self.vel[1] = 0.0
            else:
                self.vel[1] = -abs(self.vel[1]) * THROW_RESTITUTION
            bounced = True

        speed = math.hypot(self.vel[0], self.vel[1])
        on_ground = self.pos[1] >= bounds.bottom - 1
        if (on_ground and abs(self.vel[1]) < 1
                and abs(self.vel[0]) < THROW_STOP_HORIZONTAL_SPEED):
            return impact_speed, True
        if bounced and speed < 40 and abs(self.vel[1]) < 1:
            return impact_speed, True
        return impact_speed, False
