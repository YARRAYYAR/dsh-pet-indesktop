"""Drag response, event ordering and stale release velocity regressions."""

import math
import os
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QImage, QMouseEvent
from PySide6.QtWidgets import QApplication

from pet.drag_motion import MAX_THROW_SPEED, pointer_velocity, release_velocity, spring_step
from pet.frames import DecodedFrame
from pet.webm_clip import WebMClip
from tests import test_media_runtime as media_tests


def test_original_spring_overshoots_then_rebounds_and_settles():
    position, velocity = 0.0, 0.0
    positions = []
    for _ in range(250):
        position, velocity = spring_step(position, velocity, 100, 0.008)
        positions.append(position)
    assert 110 < max(positions) < 113
    peak = positions.index(max(positions))
    assert min(positions[peak:]) < 100
    assert abs(position - 100) < 0.01


def test_spring_is_independent_of_refresh_rate():
    outcomes = []
    for rate in [60, 120, 240]:
        position, velocity = 0.0, 0.0
        for _ in range(rate):
            position, velocity = spring_step(position, velocity, 100, 1 / rate)
        outcomes.append((position, velocity))
    for outcome in outcomes:
        assert outcome == pytest.approx(outcomes[0], abs=1e-10)


def test_pointer_filter_is_time_based_and_throw_is_bounded():
    for rate in [60, 120, 240]:
        velocity = (0.0, 0.0)
        for _ in range(rate):
            velocity = pointer_velocity(velocity, 600 / rate, 0, 1 / rate)
        assert velocity == pytest.approx((600, 0), abs=1e-6)
    velocity = pointer_velocity((0, 0), 10000, 10000, 0.000001)
    assert math.hypot(*velocity) <= MAX_THROW_SPEED
    assert release_velocity((600, 0), 0.02) == (600, 0)
    assert release_velocity((600, 0), 0.2) == (0, 0)


def test_rewind_uses_preloaded_drag_frame_without_sync_decode():
    app = QApplication.instance() or QApplication([])
    clip = WebMClip('unused.webm')
    image = QImage(4, 4, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor('red'))
    frame = DecodedFrame(image, 0, 0, 4, 4)
    clip._first_frame = frame
    clip._current_frame = None
    with patch.object(clip, '_decode_first_frame_sync') as decode:
        clip.rewind(preload=False)
        decode.assert_not_called()
        assert clip.currentFrame() is frame
    clip.release_frames(keep_first=False)


def test_first_drag_moves_before_animation_work():
    app = QApplication.instance() or QApplication([])
    harness = media_tests.MediaRuntimeTests()
    with harness.interaction_window() as window:
        window.drag_physics = True
        window.drag = window.idle
        point = QPoint(window._w // 5, window._bubble_h + int(round(180 * window.scale)))
        window.mousePressEvent(harness.mouse_event(window, QEvent.Type.MouseButtonPress, point))
        global_point = window.mapToGlobal(point) + QPoint(50, 0)
        expected = global_point - window._grab_offset
        move = QMouseEvent(QEvent.Type.MouseMove, QPointF(window.mapFromGlobal(global_point)), QPointF(global_point), Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        def check_position(name):
            assert window.pos() == expected
            return True

        with patch.object(window, '_switch', side_effect=check_position) as switch:
            window.mouseMoveEvent(move)
            assert window.pos() == expected
            switch.assert_called_once()
            assert window._dragging
            assert window.cursor().shape() == Qt.CursorShape.ClosedHandCursor
            assert window._physics_timer.timerType() == Qt.TimerType.PreciseTimer


def test_paused_drag_moves_without_restarting_animation_or_physics():
    app = QApplication.instance() or QApplication([])
    harness = media_tests.MediaRuntimeTests()
    with harness.interaction_window() as window:
        window.drag_physics = True
        window.set_paused(True)
        point = QPoint(window._w // 5, window._bubble_h + int(round(180 * window.scale)))
        window.mousePressEvent(harness.mouse_event(window, QEvent.Type.MouseButtonPress, point))
        origin = window.mapToGlobal(point)
        offset = window._grab_offset
        with patch.object(window, '_switch') as switch:
            for distance in (50, 100):
                target = origin + QPoint(distance, 0)
                move = QMouseEvent(QEvent.Type.MouseMove, QPointF(window.mapFromGlobal(target)), QPointF(target), Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
                window.mouseMoveEvent(move)
                assert window.pos() == target - offset
            window.mouseReleaseEvent(harness.mouse_event(window, QEvent.Type.MouseButtonRelease, window.mapFromGlobal(target)))
            switch.assert_not_called()
            assert not window._physics_timer.isActive()
            assert window._paused


@pytest.mark.parametrize('cancel', ['set_paused', 'suspend_animation', 'set_mouse_through'])
def test_cancel_drag_clears_input_and_timers(cancel):
    app = QApplication.instance() or QApplication([])
    harness = media_tests.MediaRuntimeTests()
    with harness.interaction_window() as window:
        point = QPoint(window._w // 5, window._bubble_h + int(round(180 * window.scale)))
        window.mousePressEvent(harness.mouse_event(window, QEvent.Type.MouseButtonPress, point))
        window.mouseMoveEvent(harness.mouse_event(window, QEvent.Type.MouseMove, point + QPoint(50, 0)))
        method = getattr(window, cancel)
        method() if cancel == 'suspend_animation' else method(True)
        assert window._press_global is None
        assert not window._dragging
        assert not window._physics_timer.isActive()
        assert not window._long_press_timer.isActive()
        assert not window._tap_timer.isActive()
        assert window.cursor().shape() != Qt.CursorShape.ClosedHandCursor


def test_metadata_does_not_delay_first_frame_or_skip_later_frames():
    app = QApplication.instance() or QApplication([])
    clip = WebMClip('unused.webm')
    clip._queue.put(('meta', {'size': (4, 4), 'fps': 30}))
    clip._queue.put(('frame', b'first'))
    with patch.object(clip, '_process_frame') as process:
        clip._poll()
        process.assert_called_once_with(b'first')
        clip._queue.put(('frame', b'second'))
        clip._queue.put(('frame', b'third'))
        clip._poll()
        assert process.call_args.args == (b'second',)
        assert process.call_count == 2
        clip._poll()
        assert process.call_args.args == (b'third',)
    clip.release_frames(keep_first=False)
