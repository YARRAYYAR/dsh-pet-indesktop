"""Rebound motion, sound throttling and mute/lifecycle checks."""

import os
import struct
import wave
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import QPoint, QRect
from PySide6.QtWidgets import QApplication, QMenu

from pet.sound import BounceSound
from pet.config import Config
from pet.physics import ThrowBounds
from tests import test_media_runtime as media_tests


class _FixedScreen:
    """把窗口所在屏幕固定成指定矩形，供物理边界计算使用。"""

    def __init__(self, rect: QRect) -> None:
        self._rect = rect
        self._dpr = 1.0

    def availableGeometry(self) -> QRect:
        return self._rect

    def name(self) -> str:
        return 'fixed'

    def devicePixelRatio(self) -> float:
        return self._dpr

    def refreshRate(self) -> float:
        return 60.0


def _drive_physics(window, ticks: int, *, clock, step: float = 0.008) -> None:
    """用受控时钟驱动窗口的物理帧（每步一个 8ms 子步）。"""
    for _ in range(ticks):
        clock[0] += step
        with patch('pet.window.time.monotonic', return_value=clock[0]):
            window._on_physics_tick()


@pytest.fixture(scope='module', autouse=True)
def app():
    instance = QApplication.instance() or QApplication([])
    yield instance


def test_bounce_wave_is_short_quiet_and_has_clean_endpoints(tmp_path):
    sound = BounceSound(tmp_path)
    sound._ensure_wave()
    with wave.open(str(sound.path), 'rb') as wav:
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2
        assert wav.getnframes() / wav.getframerate() == pytest.approx(0.18)
        frames = wav.readframes(wav.getnframes())
    values = struct.unpack(f'<{len(frames) // 2}h', frames)
    assert values[0] == values[-1] == 0
    assert 1000 < max(abs(value) for value in values) < 10000
    assert sound.path.stat().st_size < 10000


def test_bounce_audio_obeys_volume_mute_and_rate_limit(tmp_path):
    sound = BounceSound(tmp_path)
    sound.volume = 30
    with patch('pet.sound.sys.platform', 'darwin'), \
            patch('pet.sound.shutil.which', return_value='/usr/bin/afplay'), \
            patch('pet.sound.subprocess.Popen') as player, \
            patch('pet.sound.time.monotonic', side_effect=[10, 10.08, 10.2]):
        sound.play()
        sound.play()
        assert player.call_count == 1
        assert player.call_args.args[0][1:3] == ['-v', '0.3']
        sound.play()
        assert player.call_count == 2
        sound.enabled = False
        sound.play()
        sound.enabled = True
        sound.volume = 0
        sound.play()
        assert player.call_count == 2


def test_bounce_variants_use_bundled_paths_without_loading_audio_in_process(tmp_path):
    sound = BounceSound(tmp_path)
    assert set(sound.VARIANTS) == {'classic', 'retro', 'cute', 'random'}
    sound.set_variant('retro')
    assert sound.variant == 'retro'
    with patch('pet.sound.sys.platform', 'darwin'), \
            patch('pet.sound.shutil.which', return_value='/usr/bin/afplay'), \
            patch('pet.sound.subprocess.Popen') as player, \
            patch('pet.sound.time.monotonic', return_value=10):
        sound.play()
        assert player.call_args.args[0][-1].endswith('bounce-retro-cc0.wav')
    sound.set_variant('not-a-variant')
    assert sound.variant == 'random'


def test_drag_rebound_is_silent_and_settles_normally():
    harness = media_tests.MediaRuntimeTests()
    with harness.interaction_window() as window:
        window._physics.reset((0.0, 300.0))
        window._drag_target = QPoint(100, 300)
        window._physics_mode = 'drag'
        window._last_physics_time = 0.0
        positions = []
        clock = [0.0]
        with patch('pet.window.QTimer.singleShot') as callback:
            for _ in range(250):
                _drive_physics(window, 1, clock=clock)
                positions.append(window._phys_pos[0])
            assert max(positions) > 110
            assert abs(positions[-1] - 100) < 0.01
            callback.assert_not_called()


def test_floor_rest_is_silent_but_fast_wall_impact_keeps_original_bounce():
    harness = media_tests.MediaRuntimeTests()
    with harness.interaction_window() as window:
        screen = QRect(0, 0, 2000, 1600)
        bounds = ThrowBounds.from_screen(
            0.0, 0.0, 2000.0, 1600.0,
            window_width=float(window._w), window_height=float(window._h),
        )
        window._screen_available = lambda: _FixedScreen(screen)
        clock = [0.0]
        with patch('pet.window.QTimer.singleShot') as callback:
            # 静止躺在地面上：不该有任何音效
            window._physics.reset((500.0, bounds.bottom), (0.0, 0.0))
            window._physics_mode = 'throw'
            window._last_physics_time = 0.0
            _drive_physics(window, 10, clock=clock)
            callback.assert_not_called()
            # 高速撞左墙：保留原来的一次回弹音
            window._physics.reset((-window._w / 3.0, 300.0), (-800.0, 0.0))
            window._physics_mode = 'throw'
            _drive_physics(window, 1, clock=clock)
            assert window._phys_vel[0] == pytest.approx(800 * 0.78)
            callback.assert_called_once()


def test_sound_controls_and_lifecycle_cover_bounce():
    harness = media_tests.MediaRuntimeTests()
    with harness.interaction_window() as window:
        window.set_volume(27)
        assert window._bounce_sound.volume == 27
        with patch.object(window._bounce_sound, 'close') as close:
            window.set_sound_enabled(False)
            assert not window._bounce_sound.enabled
            close.assert_called_once()
            window.set_sound_enabled(True)
            window.set_volume(0)
            assert close.call_count == 2
        with patch.object(window._bounce_sound, 'play') as play:
            window.set_paused(True)
            window._play_bounce_sound()
            play.assert_not_called()
            window.set_paused(False)
            window.suspend_animation()
            window._play_bounce_sound()
            play.assert_not_called()


def test_bubble_switch_syncs_menus_stops_preview_and_persists():
    harness = media_tests.MediaRuntimeTests()
    with harness.interaction_window() as window:
        first_menu, second_menu = QMenu(window), QMenu(window)
        first = window.add_bubble_toggle(first_menu)
        second = window.add_bubble_toggle(second_menu)
        window.preview_bubble(True)
        assert window._bubble_visible
        first.trigger()
        assert not second.isChecked()
        assert not window._bubble_visible
        assert not window._bubble_timer.isActive()
        assert not window._bubble_anim_timer.isActive()
        assert window._bubble_preview is None
        window.show_bubble()
        assert not window._bubble_visible
        assert Config(base=window.cfg.dir.parent).get('bubble_enabled') is False
        second.trigger()
        assert first.isChecked()
        assert window._bubble_visible
