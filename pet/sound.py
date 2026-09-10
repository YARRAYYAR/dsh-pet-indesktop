# -*- coding: utf-8 -*-
"""轻量本地音效：首次触发时生成并用系统播放器异步播放。"""

from __future__ import annotations

import logging
import math
import random
import shutil
import struct
import subprocess
import sys
import time
import wave
from pathlib import Path


class DuckScream:
    """生成一段短促的卡通尖叫鸭，不把音频解码库塞进桌宠包。"""

    COOLDOWN = 0.35

    def __init__(self, output_dir: Path) -> None:
        self.path = Path(output_dir) / "sounds" / "screaming-duck.wav"
        self.enabled = True
        self.volume = 80
        self._process: subprocess.Popen | None = None
        self._warned = False
        self._last_play = 0.0

    def play(self) -> None:
        if not self.enabled or self.volume <= 0:
            return
        now = time.monotonic()
        if now - self._last_play < self.COOLDOWN:
            return
        self._last_play = now
        try:
            self._ensure_wave()
            self._play_path(self._playback_path())
        except (OSError, RuntimeError, ValueError) as exc:
            self._warn_once("音效播放失败: %s", exc)

    def _play_path(self, path: Path) -> None:
        try:
            if sys.platform == "darwin":
                player = shutil.which("afplay")
                if not player:
                    self._warn_once("找不到 afplay，音效不可用")
                    return
                if self._process is not None and self._process.poll() is None:
                    self._process.terminate()
                self._process = subprocess.Popen(
                    [player, '-v', str(self.volume / 100.0), str(path)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return
            if sys.platform == "win32":
                import winsound

                winsound.PlaySound(
                    str(path),
                    winsound.SND_FILENAME | winsound.SND_ASYNC,
                )
                return
            player = shutil.which("paplay") or shutil.which("aplay")
            if player:
                self._process = subprocess.Popen(
                    [player, str(path)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
        except (OSError, RuntimeError, ValueError) as exc:
            self._warn_once("音效播放失败: %s", exc)

    def close(self) -> None:
        if self._process is not None and self._process.poll() is None:
            try:
                self._process.terminate()
            except OSError:
                pass
        self._process = None

    def _warn_once(self, message: str, *args) -> None:
        if not self._warned:
            logging.warning(message, *args)
            self._warned = True

    def _ensure_wave(self) -> Path:
        if self.path.is_file() and self.path.stat().st_size > 44:
            return self.path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        sample_rate = 24_000
        duration = 0.46
        total = int(sample_rate * duration)
        phase = 0.0
        frames = bytearray()
        for index in range(total):
            t = index / sample_rate
            # 先短促“嘎”一下，再上扬成尖叫，最后快速收尾。
            if t < 0.09:
                frequency = 780.0 - 420.0 * (t / 0.09)
            elif t < 0.36:
                frequency = 360.0 + 1_050.0 * ((t - 0.09) / 0.27)
            else:
                frequency = 1_410.0 - 900.0 * ((t - 0.36) / 0.10)
            frequency *= 1.0 + 0.08 * math.sin(2.0 * math.pi * 7.0 * t)
            phase += 2.0 * math.pi * frequency / sample_rate
            envelope = min(1.0, t / 0.012) * min(1.0, (duration - t) / 0.055)
            tone = (
                math.sin(phase)
                + 0.32 * math.sin(phase * 2.01)
                + 0.13 * math.sin(phase * 3.02)
            )
            sample = max(-1.0, min(1.0, tone * 0.24 * envelope))
            frames.extend(struct.pack("<h", int(sample * 32767)))
        with wave.open(str(self.path), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(sample_rate)
            output.writeframes(frames)
        return self.path

    def _playback_path(self) -> Path:
        return self.path


class BounceSound(DuckScream):
    """短促回弹音；音频仍交给系统播放器，不引入音频解码依赖。"""

    COOLDOWN = 0.16
    VARIANTS = ('classic', 'retro', 'cute', 'random')
    VARIANT_LABELS = {
        'classic': '原版柔和',
        'retro': '复古跳跃（CC0）',
        'cute': '可爱弹簧（CC0）',
        'random': '随机混合',
    }

    def __init__(self, output_dir: Path) -> None:
        super().__init__(output_dir)
        self.path = Path(output_dir) / 'sounds' / 'bounce-pop-v1.wav'
        asset_root = Path(__file__).resolve().parent.parent / 'assets' / 'sounds'
        if getattr(sys, 'frozen', False):
            asset_root = Path(getattr(sys, '_MEIPASS', Path(sys.executable).resolve().parent)) / 'assets' / 'sounds'
        self._asset_paths = {
            'retro': asset_root / 'bounce-retro-cc0.wav',
            'cute': asset_root / 'bounce-cute-cc0.wav',
        }
        self.variant = 'random'

    def set_variant(self, variant: str) -> None:
        self.variant = variant if variant in self.VARIANTS else 'random'

    def _selected_path(self) -> Path:
        if self.variant == 'classic':
            return self.path
        if self.variant == 'random':
            choices = [self.path]
            choices.extend(path for path in self._asset_paths.values() if path.is_file())
            return random.choice(choices)
        candidate = self._asset_paths.get(self.variant)
        return candidate if candidate is not None and candidate.is_file() else self.path

    def _ensure_wave(self) -> Path:
        return self._ensure_generated_wave()

    def _playback_path(self) -> Path:
        return self._selected_path()

    def _ensure_generated_wave(self) -> Path:
        if self.path.is_file() and self.path.stat().st_size > 44:
            return self.path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        sample_rate = 24000
        duration = 0.18
        total = round(sample_rate * duration)
        phase = 0.0
        frames = bytearray()
        for index in range(total):
            t = index / sample_rate
            frequency = 220.0 + 540.0 * math.exp(-t * 24.0)
            phase += math.tau * frequency / sample_rate
            # 5ms 淡入、30ms 收尾，避免尖锐爆音；音量低于点击尖叫鸭。
            envelope = min(1.0, t / 0.005) * min(1.0, (total - 1 - index) / (sample_rate * 0.03))
            envelope *= math.exp(-t * 15.0)
            tone = math.sin(phase) + 0.15 * math.sin(phase * 2)
            frames.extend(struct.pack('<h', round(tone * envelope * 0.25 * 32767)))
        with wave.open(str(self.path), 'wb') as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(sample_rate)
            output.writeframes(frames)
        return self.path
