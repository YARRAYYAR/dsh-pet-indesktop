# -*- coding: utf-8 -*-
"""轻量本地音效：首次触发时生成并用系统播放器异步播放。"""

from __future__ import annotations

import logging
import math
import shutil
import struct
import subprocess
import sys
import wave
from pathlib import Path


class DuckScream:
    """生成一段短促的卡通尖叫鸭，不把音频解码库塞进桌宠包。"""

    def __init__(self, output_dir: Path) -> None:
        self.path = Path(output_dir) / "sounds" / "screaming-duck.wav"
        self.enabled = True
        self._process: subprocess.Popen | None = None
        self._warned = False

    def play(self) -> None:
        if not self.enabled:
            return
        try:
            self._ensure_wave()
            if sys.platform == "darwin":
                player = shutil.which("afplay")
                if not player:
                    self._warn_once("找不到 afplay，尖叫鸭音效不可用")
                    return
                if self._process is not None and self._process.poll() is None:
                    self._process.terminate()
                self._process = subprocess.Popen(
                    [player, str(self.path)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return
            if sys.platform == "win32":
                import winsound

                winsound.PlaySound(
                    str(self.path),
                    winsound.SND_FILENAME | winsound.SND_ASYNC,
                )
                return
            player = shutil.which("paplay") or shutil.which("aplay")
            if player:
                self._process = subprocess.Popen(
                    [player, str(self.path)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
        except (OSError, RuntimeError, ValueError) as exc:
            self._warn_once("尖叫鸭音效播放失败: %s", exc)

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

    def _ensure_wave(self) -> None:
        if self.path.is_file() and self.path.stat().st_size > 44:
            return
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
