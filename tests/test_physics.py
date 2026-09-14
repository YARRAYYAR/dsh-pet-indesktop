# -*- coding: utf-8 -*-
"""抛掷/拖拽数值核心的纯单元测试（不需要窗口，也不需要 Qt）。"""

import math

import pytest

from pet.physics import (
    IMPACT_SOUND_MIN_SPEED,
    MAX_FRAME_SECONDS,
    MODE_DRAG,
    MODE_THROW,
    THROW_RESTITUTION,
    PhysicsEngine,
    ThrowBounds,
)


def bounds_800x600(window_w=20.0, window_h=20.0) -> ThrowBounds:
    return ThrowBounds.from_screen(
        0.0, 0.0, 800.0, 600.0,
        window_width=window_w, window_height=window_h,
    )


def test_throw_bounds_reserve_a_third_of_the_window_each_side():
    bounds = bounds_800x600(window_w=30.0, window_h=10.0)
    assert bounds.left == pytest.approx(-10.0)          # 0 - 30/3
    assert bounds.right == pytest.approx(800 - 30 + 10)
    assert bounds.top == pytest.approx(0.0)
    assert bounds.bottom == pytest.approx(590.0)        # 600 - 10


def test_no_motion_without_a_mode_or_without_time():
    engine = PhysicsEngine(position=(5.0, 5.0), velocity=(1.0, 1.0))
    for mode, elapsed in ((None, 0.016), (MODE_DRAG, 0.0), (MODE_DRAG, -1.0)):
        result = engine.step_frame(elapsed, mode=mode, drag_target=(9.0, 9.0),
                                   bounds=None)
        assert result.pos == (5.0, 5.0)
        assert result.impacts == ()
        assert result.stopped is False


def test_drag_spring_reaches_target_and_keeps_the_rebound():
    """按住拖拽要来回回弹（这是被明确要求保留的原版手感）。"""
    engine = PhysicsEngine(position=(0.0, 300.0))
    positions = []
    for _ in range(250):
        engine.step_frame(0.008, mode=MODE_DRAG, drag_target=(100.0, 300.0),
                          bounds=None)
        positions.append(engine.pos[0])
    assert max(positions) > 110.0            # 明显过冲
    assert positions[-1] == pytest.approx(100.0, abs=0.01)
    assert engine.pos[1] == pytest.approx(300.0)


def test_drag_without_target_leaves_state_untouched():
    engine = PhysicsEngine(position=(3.0, 4.0), velocity=(5.0, 6.0))
    engine.step_frame(0.008, mode=MODE_DRAG, drag_target=None, bounds=None)
    assert engine.pos == [3.0, 4.0]
    assert engine.vel == [5.0, 6.0]


def test_frame_time_is_clamped_to_avoid_integration_blowup():
    """长卡顿最多补 33ms，否则弹簧积分会不稳定。"""
    coarse = PhysicsEngine(position=(0.0, 0.0))
    coarse.step_frame(0.5, mode=MODE_DRAG, drag_target=(100.0, 0.0), bounds=None)

    clamped = PhysicsEngine(position=(0.0, 0.0))
    clamped.step_frame(MAX_FRAME_SECONDS, mode=MODE_DRAG,
                       drag_target=(100.0, 0.0), bounds=None)

    assert coarse.pos[0] == pytest.approx(clamped.pos[0])
    assert coarse.vel[0] == pytest.approx(clamped.vel[0])
    # 单帧位移不得跳到目标附近，说明确实被拆成了小步
    assert coarse.pos[0] < 40.0


def test_throw_without_bounds_applies_gravity_only():
    engine = PhysicsEngine(position=(0.0, 0.0))
    result = engine.step_frame(0.008, mode=MODE_THROW, drag_target=None, bounds=None)
    assert engine.pos[0] == pytest.approx(0.0)
    assert engine.pos[1] > 0.0
    assert engine.vel[1] > 0.0
    assert result.impacts == ()
    assert result.stopped is False


def test_wall_impact_uses_the_original_restitution():
    bounds = bounds_800x600()
    engine = PhysicsEngine(position=(bounds.left, 300.0), velocity=(-800.0, 0.0))
    result = engine.step_frame(0.008, mode=MODE_THROW, drag_target=None,
                               bounds=bounds)
    assert engine.vel[0] == pytest.approx(800.0 * THROW_RESTITUTION)
    assert engine.vel[0] > 0
    assert result.impacts == pytest.approx((800.0,))


def test_slow_impact_does_not_request_a_sound():
    bounds = bounds_800x600()
    engine = PhysicsEngine(position=(bounds.right, 300.0), velocity=(40.0, 0.0))
    result = engine.step_frame(0.008, mode=MODE_THROW, drag_target=None,
                               bounds=bounds)
    assert result.impacts == ()          # 低于 80 的撞击不发声


def test_impact_threshold_boundary():
    bounds = bounds_800x600()
    just_below = PhysicsEngine(position=(bounds.left, 300.0),
                               velocity=(-(IMPACT_SOUND_MIN_SPEED - 1e-6), 0.0))
    assert just_below.step_frame(0.008, mode=MODE_THROW, drag_target=None,
                                 bounds=bounds).impacts == ()

    at_threshold = PhysicsEngine(position=(bounds.left, 300.0),
                                 velocity=(-IMPACT_SOUND_MIN_SPEED, 0.0))
    assert at_threshold.step_frame(0.008, mode=MODE_THROW, drag_target=None,
                                   bounds=bounds).impacts


def test_floor_contact_brakes_horizontal_speed_and_keeps_bouncing_multiple_times():
    bounds = bounds_800x600()
    engine = PhysicsEngine(position=(400.0, bounds.bottom - 1), velocity=(120.0, 900.0))
    bounces = 0
    stopped = False
    for _ in range(5000):
        incoming = engine.vel[1]
        result = engine.step_frame(0.008, mode=MODE_THROW, drag_target=None,
                                   bounds=bounds)
        if incoming > 0 and engine.vel[1] < 0:
            bounces += 1
        if result.stopped:
            stopped = True
            break
    assert bounces >= 4
    assert stopped
    # 停下来时竖直速度必须归零；水平残速上限是 40（原实现的静止判据），
    # 而且此时物理已关闭，残速不会再驱动窗口移动。
    assert engine.vel[1] == 0.0
    assert math.hypot(*engine.vel) < 40.0
    assert engine.pos[1] == pytest.approx(bounds.bottom)


def test_resting_on_the_floor_is_silent_and_settles_at_once():
    bounds = bounds_800x600()
    engine = PhysicsEngine(position=(500.0, bounds.bottom), velocity=(0.0, 0.0))
    result = engine.step_frame(0.008, mode=MODE_THROW, drag_target=None,
                               bounds=bounds)
    assert result.impacts == ()
    assert result.stopped is True


def test_rest_at_floor_never_creates_runaway_position():
    bounds = bounds_800x600()
    engine = PhysicsEngine(position=(500.0, bounds.bottom), velocity=(0.0, 0.0))
    for _ in range(200):
        engine.step_frame(0.016, mode=MODE_THROW, drag_target=None, bounds=bounds)
    assert engine.pos[1] == pytest.approx(bounds.bottom)
    assert math.isfinite(engine.pos[0])


def test_reset_restores_a_clean_state():
    engine = PhysicsEngine(position=(1.0, 2.0), velocity=(3.0, 4.0))
    engine.reset((10.0, 20.0), (0.0, -5.0))
    assert engine.pos == [10.0, 20.0]
    assert engine.vel == [0.0, -5.0]
