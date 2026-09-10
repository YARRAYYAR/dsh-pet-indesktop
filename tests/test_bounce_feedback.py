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
from tests import test_media_runtime as media_tests


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
        window._phys_pos = [0.0, 300.0]
        window._phys_vel = [0.0, 0.0]
        window._drag_target = QPoint(100, 300)
        positions = []
        with patch('pet.window.QTimer.singleShot') as callback:
            for _ in range(250):
                window._tick_drag_physics(0.008)
                positions.append(window._phys_pos[0])
            assert max(positions) > 110
            assert abs(positions[-1] - 100) < 0.01
            callback.assert_not_called()


def test_floor_rest_is_silent_but_fast_wall_impact_keeps_original_bounce():
    harness = media_tests.MediaRuntimeTests()
    with harness.interaction_window() as window:
        screen = QRect(0, 0, 2000, 1600)
        window._phys_pos = [500.0, float(screen.bottom() - window._h)]
        window._phys_vel = [0.0, 0.0]
        with patch('pet.window.QTimer.singleShot') as callback:
            for _ in range(10):
                window._tick_throw_physics(0.008, screen)
            callback.assert_not_called()
            window._phys_pos = [-window._w / 3.0, 300.0]
            window._phys_vel = [-800.0, 0.0]
            window._tick_throw_physics(0.008, screen)
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
