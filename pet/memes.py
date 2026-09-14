# -*- coding: utf-8 -*-
"""v0.2.9 表情包目录与按需读取。

这里只持有轻量的文件名/描述索引；QPixmap 只在气泡显示时创建，关闭气泡后
由窗口释放引用，避免 27 张 PNG 常驻内存。
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

from PySide6.QtGui import QPixmap


def memes_dir() -> Path:
    """返回源码运行与 PyInstaller 运行都可用的表情包目录。"""
    if getattr(sys, 'frozen', False):
        root = Path(getattr(sys, '_MEIPASS', Path(sys.executable).resolve().parent))
    else:
        root = Path(__file__).resolve().parent.parent
    return root / 'assets' / 'memes'


def _load_manifest() -> dict[str, str]:
    path = memes_dir() / 'manifest.json'
    try:
        raw = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError, TypeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {
        str(name): str(description)
        for name, description in raw.items()
        if isinstance(name, str) and isinstance(description, str)
        and description.strip()
    }


MEME_DESCRIPTIONS = _load_manifest()


def available_names() -> tuple[str, ...]:
    """只返回实际存在的 PNG，避免配置与资源不一致时触发异常。"""
    directory = memes_dir()
    return tuple(
        name for name in MEME_DESCRIPTIONS
        if (directory / f'{name}.png').is_file()
    )


def random_pixmap(*, exclude: str | None = None,
                  rng: random.Random | object | None = None
                  ) -> tuple[str | None, QPixmap | None]:
    """随机按需读取一张图片；失败时返回空结果，不影响气泡。"""
    names = [name for name in available_names() if name != exclude]
    if not names:
        names = list(available_names())
    if not names:
        return None, None
    picker = rng or random
    name = picker.choice(names)
    pixmap = QPixmap(str(memes_dir() / f'{name}.png'))
    if pixmap.isNull():
        return None, None
    return name, pixmap
