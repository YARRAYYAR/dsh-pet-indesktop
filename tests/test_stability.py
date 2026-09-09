# -*- coding: utf-8 -*-
"""稳定性修复的无 GUI 回归测试。"""

from __future__ import annotations

import json
import queue
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pet import catalog  # noqa: E402
from pet.config import Config  # noqa: E402
from pet.library import MovieLibrary  # noqa: E402
from pet.preflight import preflight  # noqa: E402
from pet.webm_clip import WebMClip, _reader_loop  # noqa: E402
from tools.experiment_alpha_edges import bleed_low_alpha_rgb  # noqa: E402


class StabilityTests(unittest.TestCase):
    def test_malformed_config_is_normalized_and_saved_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Config(base=tmp)
            config.path.parent.mkdir(parents=True, exist_ok=True)
            config.path.write_text(
                json.dumps({
                    'version': 'not-a-number',
                    'scale': 'not-a-number',
                    'playback_speed': float('inf'),
                    'rx': 'not-a-ratio',
                    'favorites': 'not-a-list',
                    'character': '../outside',
                    'playlist_mode': 'invalid',
                    'personality': 'invalid',
                    'action_switch_delay_ms': 999999,
                }),
                encoding='utf-8',
            )

            loaded = Config(base=tmp)
            self.assertEqual(loaded.get('version'), 2)
            self.assertEqual(loaded.get('scale'), catalog.DEFAULT_SCALE)
            self.assertEqual(loaded.get('playback_speed'), 1.0)
            self.assertIsNone(loaded.get('rx'))
            self.assertEqual(loaded.get('favorites'), [])
            self.assertEqual(loaded.get('playlist_mode'), 'off')
            self.assertEqual(loaded.get('personality'), 'lively')
            self.assertEqual(loaded.get('action_switch_delay_ms'), 60_000)
            self.assertTrue(loaded.get('sound_enabled'))
            self.assertEqual(loaded.get('character'), catalog.DEFAULT_CHARACTER)

    def test_legacy_duck_sound_config_migrates_to_global_sound(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Config(base=tmp)
            config.path.parent.mkdir(parents=True, exist_ok=True)
            config.path.write_text(json.dumps({'duck_sound': False}), encoding='utf-8')
            loaded = Config(base=tmp)
            self.assertFalse(loaded.get('sound_enabled'))
            self.assertFalse(loaded.get('duck_sound'))

            loaded.save()
            persisted = json.loads(config.path.read_text(encoding='utf-8'))
            self.assertEqual(persisted['version'], 2)
            self.assertFalse((config.path.parent / '.config.json.tmp').exists())

    def test_category_fallback_preserves_input_order(self) -> None:
        categories = catalog.build_categories(['待机甲', '动作乙', '动作丙'])
        self.assertEqual(categories['idle'], '待机甲')
        self.assertEqual(categories['acts'], ['动作乙', '动作丙'])
        self.assertEqual(catalog.decode_size_for_scale(0.72, 1.0), (462, 260))

    def test_empty_external_character_dir_does_not_hide_builtin_assets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            external = root / 'external'
            builtin = root / 'builtin'
            (external / 'demo' / 'videos').mkdir(parents=True)
            builtin.mkdir()
            (builtin / 'idle.webm').write_bytes(b'placeholder')

            with patch.object(catalog, 'external_character_dirs', return_value=[external]), \
                    patch.object(catalog, 'character_video_dir', return_value=builtin), \
                    patch.object(catalog, 'character_gif_video_dir', return_value=root / 'gif'):
                self.assertEqual(catalog.resolve_character_video_dir('demo'), builtin)

    def test_duplicate_animation_stems_fail_clearly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'idle').mkdir()
            (root / 'random').mkdir()
            (root / 'idle' / 'same.gif').write_bytes(b'gif')
            (root / 'random' / 'same.gif').write_bytes(b'gif')

            with self.assertRaisesRegex(ValueError, '动画名冲突'):
                MovieLibrary(asset_dir=root)

    def test_manifest_path_cannot_escape_asset_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'videos'
            root.mkdir()
            with self.assertRaisesRegex(FileNotFoundError, '非法素材路径'):
                MovieLibrary(asset_dir=root, manifest={'bad': '../outside.webm'})

    def test_preflight_accepts_current_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Config(base=tmp)
            with patch.object(catalog, 'resolve_character_video_dir', return_value=ROOT / 'assets' / 'characters' / 'shenshen' / 'videos'):
                self.assertEqual(preflight(config), [])

    def test_reader_loop_returns_messages_without_touching_clip_objects(self) -> None:
        class FakeFFmpeg:
            @staticmethod
            def read_frames(*args, **kwargs):
                yield {'size': (1, 1), 'fps': 24.0, 'duration': 1.0}
                yield b'rgba-frame'

        output = queue.Queue()
        stop = threading.Event()
        with patch('pet.webm_clip.imageio_ffmpeg', FakeFFmpeg):
            _reader_loop('demo.webm', 'scale', 4, stop, output)

        self.assertEqual(output.get_nowait()[0], 'meta')
        self.assertEqual(output.get_nowait(), ('frame', b'rgba-frame'))
        self.assertEqual(output.get_nowait(), ('end', None))

    def test_active_rewind_does_not_decode_a_synchronous_first_frame(self) -> None:
        clip = WebMClip(Path('not-used.webm'))
        clip._decode_first_frame_sync = Mock()
        clip.rewind()
        clip._decode_first_frame_sync.assert_not_called()
        clip.deleteLater()

    def test_rgb_bleed_uses_only_confident_foreground_within_radius(self) -> None:
        rgb = np.zeros((7, 7, 3), dtype=np.uint8)
        alpha = np.zeros((7, 7), dtype=np.uint8)
        rgb[3, 3] = (200, 100, 50)
        alpha[3, 3] = 255
        rgb[3, 4] = (0, 255, 0)
        alpha[3, 4] = 2

        result = bleed_low_alpha_rgb(
            rgb,
            alpha,
            foreground_threshold=48,
            alpha_floor=4,
            radius=2,
        )

        np.testing.assert_array_equal(result[3, 3], (200, 100, 50))
        np.testing.assert_array_equal(result[3, 4], (200, 100, 50))
        np.testing.assert_array_equal(result[0, 0], (0, 0, 0))


if __name__ == '__main__':
    unittest.main()
