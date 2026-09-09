# -*- coding: utf-8 -*-
"""媒体热路径的行为回归测试。"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QRect, Qt, Signal  # noqa: E402
from PySide6.QtGui import QColor, QImage, QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from pet.config import Config  # noqa: E402
from pet import catalog  # noqa: E402
from pet.library import MovieLibrary  # noqa: E402
from pet.window import PetWindow  # noqa: E402
from pet.settings_dialog import SettingsDialog  # noqa: E402
from pet.webm_clip import clear_alpha_floor, trim_transparent_frame  # noqa: E402


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


class _FrameOnlyClip(QObject):
    frameChanged = Signal(int)
    finished = Signal()
    errorOccurred = Signal(str)

    def __init__(self, frame) -> None:
        super().__init__()
        self._frame = frame

    def currentFrame(self):
        return self._frame

    def currentPixmap(self):
        raise AssertionError("运行时不应再走 QPixmap -> QImage 回转")

    def start(self) -> None:
        return

    def stop(self) -> None:
        return

    def jumpToFrame(self, frame_index: int) -> bool:
        return frame_index == 0

    def frameCount(self) -> int:
        return 100

    def currentTimeSeconds(self) -> float:
        return 0.0

    def set_playback_speed(self, speed: float) -> None:
        return


class _FrameOnlyLibrary(QObject):
    manifest = None
    folder_map = {"idle": "idle"}
    folder_files = {"idle": ["idle"]}

    def __init__(self, clip: _FrameOnlyClip) -> None:
        super().__init__()
        self.clip = clip
        self.soft_edges = True

    def names(self):
        return ["idle"]

    def movie(self, name: str):
        if name != "idle":
            raise KeyError(name)
        return self.clip

    activate = movie

    def frames(self, name: str) -> int:
        return self.clip.frameCount()

    def set_decode_size(self, width: int, height: int) -> None:
        return

    def set_soft_edges(self, enabled: bool) -> None:
        self.soft_edges = bool(enabled)

    def stop_all(self) -> None:
        self.clip.stop()

    def close(self) -> None:
        self.clip.stop()


class _RecreatingLibrary(_FrameOnlyLibrary):
    def __init__(self, frame) -> None:
        self._frame = frame
        self._clip = None
        super().__init__(self._new_clip())

    def _new_clip(self) -> _FrameOnlyClip:
        self._clip = _FrameOnlyClip(self._frame)
        return self._clip

    def movie(self, name: str):
        if name != "idle":
            raise KeyError(name)
        return self._clip or self._new_clip()

    def activate(self, name: str):
        return self.movie(name)

    def close(self) -> None:
        if self._clip is not None:
            self._clip.stop()
            self._clip = None


class MediaRuntimeTests(unittest.TestCase):
    @contextmanager
    def interaction_window(self):
        image = QImage(100, 80, QImage.Format.Format_RGBA8888)
        image.fill(Qt.GlobalColor.transparent)
        for y in range(20, 60):
            for x in range(10, 30):
                image.setPixelColor(x, y, QColor(255, 255, 255, 255))
        lib = _FrameOnlyLibrary(_FrameOnlyClip(trim_transparent_frame(image)))
        with tempfile.TemporaryDirectory() as tmp:
            window = PetWindow(lib, Config(base=tmp))
            try:
                yield window
            finally:
                window.shutdown()
                window.close()

    def test_hit_region_follows_visible_frame_scale_and_mirroring(self) -> None:
        with self.interaction_window() as window:
            for scale in (0.25, 0.72, 2.0):
                window.change_scale(scale)
                for facing in ('left', 'right'):
                    window.facing = facing
                    window._rebuild_frame(force_mask=True)
                    x = int(window._w * (0.2 if facing == 'left' else 0.8))
                    y = window._bubble_h + int(round(180 * scale))
                    self.assertTrue(window._is_in_interactive_area(QPoint(x, y)))
                    self.assertFalse(window._is_in_interactive_area(QPoint(window._w // 2, y)))
                    self.assertFalse(window._is_in_interactive_area(QPoint(x, 0)))
                    self.assertFalse(window._is_in_interactive_area(QPoint(-1, y)))

    @staticmethod
    def mouse_event(window, kind, point):
        button = Qt.MouseButton.LeftButton
        return QMouseEvent(
            kind, QPointF(point), QPointF(window.mapToGlobal(point)),
            Qt.MouseButton.NoButton if kind == QEvent.Type.MouseMove else button,
            Qt.MouseButton.NoButton if kind == QEvent.Type.MouseButtonRelease else button,
            Qt.KeyboardModifier.NoModifier,
        )

    def test_transparent_press_and_unmatched_release_do_not_trigger_taps(self) -> None:
        with self.interaction_window() as window, patch.object(window, '_queue_tap') as tap:
            point = QPoint(window._w // 2, window._h // 2)
            window.mousePressEvent(self.mouse_event(window, QEvent.Type.MouseButtonPress, point))
            self.assertIsNone(window._press_global)
            window.mouseReleaseEvent(self.mouse_event(window, QEvent.Type.MouseButtonRelease, point))
            tap.assert_not_called()

    def test_bubble_is_drawn_and_removed_from_hit_region(self) -> None:
        with self.interaction_window() as window:
            point = window._bubble_geometry().center().toPoint()
            window.show_bubble('测试气泡')
            self.assertTrue(window._bubble_visible)
            self.assertEqual(window._bubble_text, '测试气泡')
            self.assertTrue(window._is_in_interactive_area(point))
            tail_point = window._bubble_tail_rects(
                window._bubble_geometry()
            )[1].center().toPoint()
            self.assertTrue(window._bubble_hit_test(tail_point))

            window.hide_bubble()
            self.assertFalse(window._bubble_visible)
            self.assertFalse(window._is_in_interactive_area(point))

    def test_bubble_toggle_and_personality_text_persist(self) -> None:
        with self.interaction_window() as window:
            window.set_personality('cool')
            window.show_bubble()
            self.assertIn(window._bubble_text, catalog.PERSONALITY_BUBBLE_LINES['cool'])
            window.set_bubble_enabled(False)
            self.assertFalse(window.bubble_enabled)
            self.assertFalse(window._bubble_visible)
            self.assertFalse(window.cfg.get('bubble_enabled'))
            window.set_bubble_enabled(True)
            self.assertTrue(window.bubble_enabled)
            self.assertTrue(window._bubble_visible)

    def test_small_pet_click_jitter_and_drag_use_system_threshold(self) -> None:
        with self.interaction_window() as window, patch.object(window, '_queue_tap') as tap:
            window.change_scale(0.25)
            point = QPoint(
                window._w // 5,
                window._bubble_h + int(round(180 * window.scale)),
            )
            window.mousePressEvent(self.mouse_event(window, QEvent.Type.MouseButtonPress, point))
            jitter = point + QPoint(2, 0)
            window.mouseMoveEvent(self.mouse_event(window, QEvent.Type.MouseMove, jitter))
            self.assertFalse(window._dragging)
            window.mouseReleaseEvent(self.mouse_event(window, QEvent.Type.MouseButtonRelease, jitter))
            tap.assert_called_once()
            tap.reset_mock()

            window.mousePressEvent(self.mouse_event(window, QEvent.Type.MouseButtonPress, point))
            dragged = point + QPoint(window._drag_threshold(), 0)
            window.mouseMoveEvent(self.mouse_event(window, QEvent.Type.MouseMove, dragged))
            self.assertTrue(window._dragging)
            self.assertFalse(window._long_press_timer.isActive())
            with patch.object(window, '_trigger_edge_feedback', return_value=False):
                window.mouseReleaseEvent(self.mouse_event(window, QEvent.Type.MouseButtonRelease, dragged))
            tap.assert_not_called()

    def test_physics_matches_elapsed_time_across_timer_cadences(self) -> None:
        with self.interaction_window() as window:
            screen = Mock()
            screen.availableGeometry.return_value = QRect(0, 0, 4000, 3000)
            for mode in ('drag', 'throw'):
                outcomes = []
                for interval in (0.008, 0.016, 0.032):
                    window._stop_physics()
                    window._phys_pos = [500.0, 300.0]
                    window._phys_vel = [100.0, 0.0]
                    window._drag_target = QPoint(600, 400)
                    with patch('pet.window.time.monotonic', return_value=100):
                        window._start_physics(mode)
                    for tick in range(1, round(0.32 / interval) + 1):
                        with patch('pet.window.time.monotonic', return_value=100 + tick * interval), \
                                patch.object(window, '_screen_available', return_value=screen), \
                                patch.object(window, 'move') as move:
                            window._on_physics_tick()
                            move.assert_called_once()
                    outcomes.append(window._phys_pos + window._phys_vel)
                for outcome in outcomes[1:]:
                    for expected, actual in zip(outcomes[0], outcome):
                        self.assertAlmostEqual(expected, actual, places=6)

    def test_physics_stall_is_bounded_and_restart_resets_clock(self) -> None:
        with self.interaction_window() as window:
            screen = Mock()
            screen.availableGeometry.return_value = QRect(0, 0, 4000, 3000)
            window._phys_pos = [500.0, 300.0]
            window._phys_vel = [100.0, 0.0]
            with patch('pet.window.time.monotonic', return_value=10):
                window._start_physics('throw')
            with patch('pet.window.time.monotonic', return_value=20), \
                    patch.object(window, '_screen_available', return_value=screen):
                window._on_physics_tick()
            self.assertAlmostEqual(window._phys_pos[0], 503.3)
            self.assertAlmostEqual(window._phys_vel[1], 1400 * 0.033)
            screen.availableGeometry.assert_called_once()

            window._physics_timer.stop()
            with patch('pet.window.time.monotonic', return_value=30):
                window._start_physics('throw')
            with patch('pet.window.time.monotonic', return_value=30.016), \
                    patch.object(window, '_screen_available', return_value=screen):
                window._on_physics_tick()
            self.assertAlmostEqual(window._phys_pos[0], 504.9)
            window._paused = True
            before = window._phys_pos[:]
            window._on_physics_tick()
            self.assertEqual(window._phys_pos, before)
            self.assertIsNone(window._physics_mode)
            self.assertFalse(window._physics_timer.isActive())

    def test_settings_cancel_save_and_defaults(self) -> None:
        image = QImage(100, 80, QImage.Format.Format_RGBA8888)
        image.fill(QColor(255, 255, 255, 255))
        lib = _FrameOnlyLibrary(_FrameOnlyClip(trim_transparent_frame(image)))
        with tempfile.TemporaryDirectory() as tmp:
            config = Config(base=tmp)
            window = PetWindow(lib, config)
            try:
                dialog = SettingsDialog(window)
                dialog.volume.setValue(12)
                dialog.reject()
                self.assertEqual(window._duck_sound.volume, 80)
                dialog = SettingsDialog(window)
                dialog.volume.setValue(24)
                dialog.size.setValue(640)
                self.assertEqual(dialog.size_slider.value(), 640)
                dialog.size_slider.setValue(800)
                self.assertEqual(dialog.size.value(), 800)
                dialog.size.setValue(640)
                dialog.frequency.setValue(30)
                dialog.delay.setValue(7)
                dialog.personality.setCurrentIndex(dialog.personality.findData('cool'))
                dialog.save()
                loaded = Config(base=tmp)
                self.assertEqual(loaded.get('volume'), 24)
                self.assertEqual(loaded.get('personality'), 'cool')
                self.assertEqual(loaded.get('action_switch_delay_ms'), 7000)
                self.assertEqual(loaded.get('action_interval_seconds'), 30)
                self.assertEqual(window.scale, 1.0)
                dialog = SettingsDialog(window)
                dialog.reset_fields()
                self.assertEqual(window._duck_sound.volume, 24)
                dialog.save()
                self.assertEqual(window._duck_sound.volume, 80)
                self.assertEqual(window.personality, 'lively')
                self.assertEqual(window.action_interval_seconds, 0)
                window.acts = ['first', 'second']
                window.personality = 'random'
                window._recent_actions = ['first', 'second']
                with patch('pet.window.random.choice', return_value='first') as choice:
                    self.assertEqual(window._pick_personality_action(exclude='first'), 'first')
                    self.assertEqual(choice.call_args.args[0], ['first', 'second'])
                window.action_interval_seconds = 30
                window._last_action_started = 100
                window._resource_constrained = False
                with patch.object(window, '_switch') as switch, \
                        patch('pet.window.time.monotonic', return_value=110):
                    window._pick_next()
                    self.assertEqual(switch.call_args.args[0], 'idle')
                with patch.object(window, '_switch') as switch, \
                        patch('pet.window.time.monotonic', return_value=131):
                    window._pick_next()
                    self.assertIn(switch.call_args.args[0], window.acts)
            finally:
                window.shutdown()
                window.close()

    def test_alpha_cleanup_preserves_all_non_floor_levels(self) -> None:
        image = QImage(256, 1, QImage.Format.Format_RGBA8888)
        for value in range(256):
            image.setPixelColor(value, 0, QColor(255, 255, 255, value))
        result = clear_alpha_floor(image)
        for value in range(256):
            self.assertEqual(result.pixelColor(value, 0).alpha(),
                             0 if value == 1 else value)
        self.assertEqual(clear_alpha_floor(result), result)

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = _app()

    def test_transparent_crop_preserves_canvas_coordinates(self) -> None:
        image = QImage(100, 80, QImage.Format.Format_RGBA8888)
        image.fill(QColor(0, 0, 0, 0))
        for y in range(20, 61):
            for x in range(10, 41):
                image.setPixelColor(x, y, QColor(255, 255, 255, 255))

        frame = trim_transparent_frame(image)

        self.assertEqual(frame.canvas_size, (100, 80))
        self.assertEqual(frame.offset, (2, 12))
        self.assertEqual((frame.image.width(), frame.image.height()), (47, 57))

    def test_soft_edges_clear_only_alpha_one_floor(self) -> None:
        image = QImage(12, 12, QImage.Format.Format_RGBA8888)
        image.fill(QColor(255, 0, 255, 0))
        for y in range(3, 9):
            for x in range(3, 9):
                image.setPixelColor(x, y, QColor(255, 255, 255, 255))
        image.setPixelColor(3, 5, QColor(255, 255, 255, 1))
        image.setPixelColor(4, 5, QColor(255, 255, 255, 2))
        image.setPixelColor(0, 0, QColor(255, 255, 255, 1))

        soft = trim_transparent_frame(image, padding=2, soften_edges=True)
        floor_x, floor_y = 3 - soft.x, 5 - soft.y
        low_alpha_x, low_alpha_y = 4 - soft.x, 5 - soft.y
        center_x, center_y = 5 - soft.x, 5 - soft.y

        self.assertEqual(
            soft.image.format(),
            QImage.Format.Format_ARGB32_Premultiplied,
        )
        self.assertEqual(soft.offset, (1, 1))
        self.assertEqual(soft.image.pixelColor(floor_x, floor_y).alpha(), 0)
        self.assertEqual(soft.image.pixelColor(low_alpha_x, low_alpha_y).alpha(), 2)
        self.assertGreaterEqual(soft.image.pixelColor(center_x, center_y).alpha(), 240)

    def test_window_renders_directly_from_cropped_qimage(self) -> None:
        image = QImage(100, 80, QImage.Format.Format_RGBA8888)
        image.fill(QColor(0, 0, 0, 0))
        for y in range(20, 61):
            for x in range(10, 41):
                image.setPixelColor(x, y, QColor(255, 255, 255, 255))
        frame = trim_transparent_frame(image)
        lib = _FrameOnlyLibrary(_FrameOnlyClip(frame))

        with tempfile.TemporaryDirectory() as tmp:
            window = PetWindow(lib, Config(base=tmp))
            window._resource_timer.stop()
            self.assertIsNotNone(window._frame_pixmap)
            self.assertEqual(window._frame_logical_rect[:2], (0, 0))
            self.assertEqual(window._frame_logical_rect[2:], window._frame_logical_size)
            window.shutdown()
            window.close()

    def test_movie_library_lru_keeps_active_clip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            one_pixel_gif = (
                b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff"
                b"!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00"
                b"\x00\x02\x02D\x01\x00;"
            )
            for name in ("a", "b", "c"):
                (root / f"{name}.gif").write_bytes(one_pixel_gif)

            library = MovieLibrary(asset_dir=root, cache_limit=2)
            active = library.activate("a")
            library.movie("b")
            library.movie("c")

            self.assertIs(library.movie("a"), active)
            self.assertEqual(set(library.movies()), {"a", "c"})
            self.assertEqual(library.loaded_count(), 2)
            library.close()

    def test_hidden_window_rebinds_recreated_clip(self) -> None:
        red = QImage(20, 20, QImage.Format.Format_RGBA8888)
        red.fill(QColor(255, 0, 0, 255))
        library = _RecreatingLibrary(trim_transparent_frame(red))

        with tempfile.TemporaryDirectory() as tmp:
            window = PetWindow(library, Config(base=tmp))
            window._resource_timer.stop()
            first = window.movie

            window.suspend_animation()
            window.resume_animation()
            second = window.movie
            self.assertIsNot(first, second)

            green = QImage(20, 20, QImage.Format.Format_RGBA8888)
            green.fill(QColor(0, 255, 0, 255))
            second._frame = trim_transparent_frame(green)
            second.frameChanged.emit(1)
            self.app.processEvents()

            color = window._frame_pixmap.toImage().pixelColor(0, 0)
            self.assertEqual((color.red(), color.green(), color.blue()), (0, 255, 0))
            window.shutdown()
            window.close()

    def test_window_soft_edges_toggle_persists_and_reloads_clip(self) -> None:
        image = QImage(20, 20, QImage.Format.Format_RGBA8888)
        image.fill(QColor(255, 255, 255, 255))
        library = _FrameOnlyLibrary(_FrameOnlyClip(trim_transparent_frame(image)))

        with tempfile.TemporaryDirectory() as tmp:
            config = Config(base=tmp)
            window = PetWindow(library, config)
            window._resource_timer.stop()

            window.set_soft_edges(False)

            self.assertFalse(window.soft_edges)
            self.assertFalse(library.soft_edges)
            self.assertFalse(config.get("soft_edges"))
            window.shutdown()
            window.close()

    def test_empty_action_pool_falls_back_to_existing_idle(self) -> None:
        image = QImage(20, 20, QImage.Format.Format_RGBA8888)
        image.fill(QColor(255, 255, 255, 255))
        library = _FrameOnlyLibrary(_FrameOnlyClip(trim_transparent_frame(image)))

        with tempfile.TemporaryDirectory() as tmp:
            window = PetWindow(library, Config(base=tmp))
            window._resource_timer.stop()
            window.acts = []
            window.turns = []
            window.moves = []
            window.clicks = []
            self.assertEqual(window._pick_available([]), 'idle')

            with patch('pet.window.random.random', return_value=0.5):
                window._pick_next()
            self.assertEqual(window.anim, 'idle')

            window.shutdown()
            window.close()

    def test_last_frame_does_not_end_before_finished_signal(self) -> None:
        image = QImage(20, 20, QImage.Format.Format_RGBA8888)
        image.fill(QColor(255, 255, 255, 255))
        clip = _FrameOnlyClip(trim_transparent_frame(image))
        library = _FrameOnlyLibrary(clip)

        with tempfile.TemporaryDirectory() as tmp:
            window = PetWindow(library, Config(base=tmp))
            window._resource_timer.stop()
            window._rebuild_frame = Mock()
            window._on_anim_ended = Mock()

            clip.frameChanged.emit(99)

            window._on_anim_ended.assert_not_called()
            window.shutdown()
            window.close()


if __name__ == "__main__":
    unittest.main()
