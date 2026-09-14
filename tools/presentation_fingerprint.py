# -*- coding: utf-8 -*-
"""画面与行为指纹：证明重构前后"逐像素 + 逐决策"不变。

用法：
    # 在候选树上生成指纹（会顺带建立缩小版素材夹具）
    python tools/presentation_fingerprint.py --output /tmp/fp_after.json

    # 与重构前的指纹比对，不一致则非零退出
    python tools/presentation_fingerprint.py --compare /tmp/fp_before.json

覆盖范围：
- 呈现层：每个动作逐帧的最终画面（QPixmap 原始字节 + win.grab() 合成结果）、
  逻辑画布尺寸/裁剪矩形、镜像朝向。
- 命中层：窗口 mask 的 QRegion 矩形列表。
- 行为层：固定随机种子下 `_pick_next` 的动作选择序列、`_on_anim_ended` 的
  分支结果、暂停/隐藏/资源受限模式下的选择。
- 叠加层：气泡 5 个展开进度、点击 Q 弹 5 个进度、拖拽预载首帧。

不覆盖：真实窗口的时序抖动、音频输出、全局快捷键。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# 与信号无关的固定随机起点；两棵树用同一序列才能比较决策。
SEED = 20260911

# 夹具保留的素材（覆盖 idle/turn/move/click/drag/random 六类）。
FIXTURE_FILES = {
    'idle': ['待机呼吸休闲.webm'],
    'turn': ['东张西望.webm'],
    'move': ['螃蟹走路.webm', '原地漂浮踏步.webm'],
    'click': ['点击回应-开心跃动.webm', '点击回应-元气挥手.webm'],
    'drag': ['被鼠标拖拽悬空反馈.webm'],
    'random': [
        '被吓一跳.webm', '吃西瓜.webm', '写代码.webm', '撸猫.webm',
        '舞狮头.webm', '小提琴演奏.webm',
    ],
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def image_digest(image) -> str:
    if image is None or image.isNull():
        return 'null'
    return sha256(bytes(image.constBits()))


def pixmap_digest(pixmap) -> str:
    if pixmap is None:
        return 'null'
    return image_digest(pixmap.toImage())


def region_digest(region) -> str:
    """QRegion 可迭代产出 QRect；逐矩形拼接后取哈希，并带上矩形数量。"""
    if region is None:
        return 'null'
    rects = list(region)
    payload = ';'.join(
        f'{r.x()},{r.y()},{r.width()},{r.height()}' for r in rects
    )
    return sha256(payload.encode('utf-8')) + f':{len(rects)}'


def build_fixture(target: Path) -> Path:
    """把真实素材的固定子集复制成一个稳定的解码输入。"""
    source_root = ROOT / 'assets' / 'characters' / 'shenshen' / 'videos'
    if not source_root.is_dir():
        raise SystemExit(f'找不到素材目录: {source_root}')
    videos = target / 'videos'
    for folder, names in FIXTURE_FILES.items():
        (videos / folder).mkdir(parents=True, exist_ok=True)
        for name in names:
            origin = source_root / folder / name
            if not origin.is_file():
                raise SystemExit(f'夹具缺失素材: {origin}')
            shutil.copyfile(origin, videos / folder / name)
    return videos


def _pump(app, predicate, *, timeout: float = 20.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.002)
    return False


def render_and_hash(win, app, *, frames: int, out: dict, key: str) -> None:
    """等待 frames 帧后记录最终画面与命中区域。"""
    movie = win.movie
    target = getattr(movie, '_frame_index', 0) + frames
    _pump(app, lambda: getattr(win.movie, '_frame_index', 0) >= target)
    win._rebuild_frame(force_mask=True)
    app.processEvents()
    out[key] = {
        'anim': win.anim,
        'frame_index': getattr(movie, '_frame_index', None),
        'pixmap': pixmap_digest(win._frame_pixmap),
        'grabbed': pixmap_digest(win.grab()),
        'logical_size': list(win._frame_logical_size),
        'logical_rect': list(win._frame_logical_rect),
        'region': region_digest(getattr(win, '_pet_mask_region', None)),
        'window': [win._w, win._h, win._bubble_h],
        'facing': win.facing,
    }


def fingerprint() -> dict:
    from PySide6.QtWidgets import QApplication
    from pet import catalog
    from pet.config import Config
    from pet.library import MovieLibrary
    from pet.window import PetWindow

    result: dict = {'files': {}, 'sequence': {}, 'branches': {}, 'overlays': {}}
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)

    with tempfile.TemporaryDirectory(prefix='pet-fp-') as tmp:
        tmp_path = Path(tmp)
        videos = build_fixture(tmp_path / 'fixture')
        # 记录夹具内容，确保两棵树吃的是同一份输入
        for path in sorted(videos.rglob('*.webm')):
            result['files'][path.name] = sha256(path.read_bytes())

        config = Config(base=tmp_path / 'config')
        config.data.update(
            scale=0.72, sound_enabled=False, proactive_greetings=False,
            action_interval_seconds=600, personality='random', no_move=False,
            soft_edges=True,
        )
        decode_size = catalog.decode_size_for_scale(0.72, 1.0)
        lib = MovieLibrary(
            character_id='shenshen',
            asset_dir=videos,
            decode_size=decode_size,
            soft_edges=True,
        )
        win = PetWindow(lib, config)
        win.show()
        result['decode_size'] = list(lib._decode_size)
        result['categories'] = {k: v for k, v in win.cats.items()}

        # 冻结一切自动行为，保证逐帧驱动是确定性的
        for timer in (win._resource_timer, win._action_switch_timer,
                      win._cursor_timer, win._greeting_timer,
                      win._idle_pause_timer, win._tap_timer,
                      win._long_press_timer):
            timer.stop()
        win._pick_next = lambda: None       # 只由本脚本决定动作序列
        win._schedule_next_greeting = lambda: None

        # ---- 1. 每个动作逐帧最终画面 ----
        sequence = (
            [win.idle] + list(win.idles) + list(win.turns) + list(win.moves)
            + list(win.clicks) + ([win.drag] if win.drag else []) + list(win.acts)
        )
        for name in dict.fromkeys(n for n in sequence if n):
            win._switch(name)
            render_and_hash(win, app, frames=3, out=result['sequence'],
                            key=f'anim::{name}')

        # ---- 2. 朝向镜像 ----
        for facing in ('left', 'right'):
            win._switch(win.idle)
            win.facing = facing
            render_and_hash(win, app, frames=2, out=result['sequence'],
                            key=f'facing::{facing}')

        # ---- 3. 缩放档位 ----
        for scale in catalog.SCALE_STEPS:
            win.change_scale(scale, persist=False)
            _pump(app, lambda: True, timeout=0.3)
            render_and_hash(win, app, frames=2, out=result['sequence'],
                            key=f'scale::{scale}')
        win.change_scale(0.72, persist=False)

        # ---- 4. 行为决策：固定种子下比较选择序列 ----
        def drive(rounds: int, *, setup=None, constrained=False) -> list:
            random.seed(SEED)
            win._resource_constrained = constrained
            if setup is not None:
                setup()
            picked = []
            for _ in range(rounds):
                win._switch(win.idle)
                win._pick_next()
                picked.append(win.anim)
            win._resource_constrained = False
            return picked

        result['branches']['default'] = drive(60)
        result['branches']['constrained'] = drive(60, constrained=True)
        result['branches']['no_move'] = drive(30, setup=lambda: setattr(win, 'no_move', True))
        win.no_move = False
        result['branches']['interval'] = drive(
            30, setup=lambda: setattr(win, 'action_interval_seconds', 1)
        )
        win.action_interval_seconds = 0
        for personality in catalog.PERSONALITY_PRESETS:
            win.personality = personality
            win._personality_frequent_acts = catalog.personality_frequent_actions(
                personality, win.acts, win._action_tags
            )
            result['branches'][f'personality::{personality}'] = drive(40)

        # 播放列表三种模式
        win.playlist = list(win.acts)[:4]
        win._playlist_index = -1
        for mode in ('loop', 'random'):
            random.seed(SEED)
            win.playlist_mode = mode
            picked = []
            for _ in range(20):
                win._play_next_playlist()
                picked.append(win.anim)
            result['branches'][f'playlist::{mode}'] = picked
        win.playlist_mode = 'off'

        # ---- 5. 动画结束分支 ----
        win._switch(win.turn or win.idle)
        before = win.facing
        win._on_anim_ended(win.anim)
        result['branches']['turn_flip'] = [before, win.facing]

        if win.drag:
            win._dragging = True
            win._switch(win.drag)
            win._on_anim_ended(win.drag)
            result['branches']['drag_loop'] = [win.anim, win._ended_fired]
            win._dragging = False
        if win.clicks:
            win._switch(win.clicks[0])
            win._on_anim_ended(win.clicks[0])
            result['branches']['click_to_idle'] = win.anim

        # ---- 6. 叠加层：气泡展开进度 ----
        # 先停掉媒体读取，把画面冻结在当前帧；否则叠加层抓图会随着
        # 动画继续推进而抖动，产生假的"差异"。
        if win.movie is not None:
            win.movie.stop()
        app.processEvents()
        win._rebuild_frame(force_mask=True)
        win._bubble_preview = None
        win.bubble_enabled = True
        for progress in (0.0, 0.25, 0.5, 0.75, 1.0):
            win._bubble_visible = True
            win._bubble_progress = progress
            win._sync_mask()
            app.processEvents()
            result['overlays'][f'bubble::{progress}'] = {
                'grabbed': pixmap_digest(win.grab()),
                'region': region_digest(getattr(win, '_pet_mask_region', None)),
            }
        win._bubble_visible = False

        # ---- 7. 叠加层：点击 Q 弹 ----
        for progress in (0.0, 0.25, 0.5, 0.75, 1.0):
            win._squash_active = True
            win._squash_progress = progress
            app.processEvents()
            result['overlays'][f'squash::{progress}'] = {
                'grabbed': pixmap_digest(win.grab()),
            }
        win._squash_active = False

        # ---- 8. 拖拽预载首帧 ----
        if win.drag:
            win.lib.movie(win.drag).jumpToFrame(0)
            frame = win.lib.movie(win.drag).currentFrame()
            result['overlays']['drag_preload'] = {
                'image': image_digest(frame.image if frame else None),
                'offset': list(frame.offset) if frame else None,
                'canvas': list(frame.canvas_size) if frame else None,
            }

        # ---- 9. 生命周期：暂停/恢复/隐藏/关闭 ----
        result['lifecycle'] = {}
        win.set_paused(True)
        result['lifecycle']['paused'] = [win._paused, win.anim]
        win.set_paused(False)
        result['lifecycle']['resumed'] = [win._paused, win.anim]
        win.suspend_animation()
        result['lifecycle']['suspended'] = [win._suspended, win.lib.loaded_count()]
        win.resume_animation()
        _pump(app, lambda: getattr(win.movie, '_frame_index', 0) >= 1)
        result['lifecycle']['after_resume'] = [win._suspended, win.anim,
                                               win.lib.loaded_count()]
        win.set_soft_edges(False)
        render_and_hash(win, app, frames=2, out=result['sequence'],
                        key='soft_edges::off')
        win.set_soft_edges(True)

        win.shutdown()
    return result


def compare(before: dict, after: dict) -> list[str]:
    diffs: list[str] = []

    def walk(prefix: str, a, b) -> None:
        if type(a) is not type(b):
            diffs.append(f'{prefix}: 类型不同 {type(a).__name__} -> {type(b).__name__}')
            return
        if isinstance(a, dict):
            for key in sorted(set(a) | set(b)):
                if key not in a:
                    diffs.append(f'{prefix}.{key}: 新增')
                elif key not in b:
                    diffs.append(f'{prefix}.{key}: 丢失')
                else:
                    walk(f'{prefix}.{key}', a[key], b[key])
        elif isinstance(a, list):
            if len(a) != len(b):
                diffs.append(f'{prefix}: 长度不同 {len(a)} -> {len(b)}')
                return
            for index, (x, y) in enumerate(zip(a, b)):
                walk(f'{prefix}[{index}]', x, y)
        elif a != b:
            diffs.append(f'{prefix}: {a!r} -> {b!r}')

    walk('', before, after)
    return diffs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='画面与行为指纹')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--compare', type=Path)
    args = parser.parse_args(argv)

    if args.compare is not None:
        before = json.loads(args.compare.read_text(encoding='utf-8'))
        after = fingerprint()
        if args.output is not None:
            args.output.write_text(
                json.dumps(after, ensure_ascii=False, indent=2, sort_keys=True) + '\n',
                encoding='utf-8',
            )
        diffs = compare(before, after)
        if diffs:
            print(f'指纹不一致：{len(diffs)} 处差异')
            for line in diffs[:40]:
                print('  ' + line)
            return 1
        print('指纹一致：画面、命中区域、行为决策全部逐项相同')
        return 0

    if args.output is None:
        parser.error('需要 --output 或 --compare')
    data = fingerprint()
    args.output.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + '\n',
        encoding='utf-8',
    )
    print(f'指纹已写入 {args.output}：'
          f'{len(data["sequence"])} 项画面、'
          f'{sum(len(v) for v in data["branches"].values())} 项决策、'
          f'{len(data["overlays"])} 项叠加层')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
