"""有限时长的真实窗口 A/B 工作负载，使用隔离配置，不注册全局快捷键。

内存采样改用 tools/memprobe.py（libproc）：
- 本机沙箱禁用 `ps`，原实现会抛 PermissionError；
- `RUSAGE_CHILDREN` 只统计已收割的子进程，长期存活的 ffmpeg 会漏统计。
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import memprobe  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seconds', type=float, default=64.0)
    args = parser.parse_args()
    sys.path.insert(0, str(args.root))
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from pet.app import PetApp
    from pet.config import Config

    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    errors = []
    old_hook = sys.excepthook

    def record_error(kind, value, traceback):
        errors.append(f'{kind.__name__}: {value}')
        old_hook(kind, value, traceback)

    sys.excepthook = record_error
    samples = []
    with tempfile.TemporaryDirectory(prefix='pet-benchmark-') as config_base:
        config = Config(base=config_base)
        config.data.update(scale=0.72, sound_enabled=False, proactive_greetings=False,
                           action_interval_seconds=600)
        controller = PetApp(app, config)
        with patch.object(controller.hotkeys, 'start'):
            controller.start()
        win = controller.win
        win._resource_timer.stop()  # 两次运行使用同样的播放策略
        win._action_switch_timer.stop()
        actions = sorted(win.acts)[:8]
        started = time.monotonic()
        action_index = -1
        hidden = False
        resumed = False
        timer = QTimer()

        def sample():
            nonlocal action_index, hidden, resumed
            elapsed = time.monotonic() - started
            phase = ('idle' if elapsed < 20 else 'switch' if elapsed < 44
                     else 'hidden' if elapsed < 54 else 'resume')
            if 20 <= elapsed < 44:
                index = int((elapsed - 20) / 2)
                if index != action_index:
                    action_index = index
                    win._switch(actions[index % len(actions)])
            elif elapsed >= 44 and not hidden:
                win.suspend_animation()
                win.hide()
                hidden = True
            if elapsed >= 54 and not resumed:
                win.show()
                win.resume_animation()
                win._resource_timer.stop()
                resumed = True
            tree = memprobe.process_tree()
            retained = sum(
                clip._current_frame.image.sizeInBytes()
                for name, clip in win.lib.movies().items()
                if name != win.anim and getattr(clip, '_current_frame', None) is not None
            )
            samples.append({
                'seconds': round(elapsed, 2),
                'phase': phase,
                'parent_footprint_mib': (tree['self'] or {}).get('footprint_mib', 0.0),
                'parent_resident_mib': (tree['self'] or {}).get('resident_mib', 0.0),
                'child_total_mib': tree['child_total_mib'],
                'child_count': tree['child_count'],
                'children': [{'pid': c['pid'], 'status': c['status'],
                              'footprint_mib': c['footprint_mib']}
                             for c in tree['children']],
                'total_mib': tree['total_mib'],
                'inactive_frame_bytes': retained,
            })
            if 10 <= elapsed < 11:
                win.grab().save(str(args.output.with_suffix('.png')))
            if elapsed >= args.seconds:
                timer.stop()
                controller.shutdown()
                app.quit()

        timer.timeout.connect(sample)
        timer.start(500)
        app.exec()

    summaries = {}
    for phase, start in [('idle', 5), ('switch', 25), ('hidden', 47), ('resume', 57)]:
        rows = [r for r in samples if r['phase'] == phase and r['seconds'] >= start]
        if not rows:
            continue
        summaries[phase] = {
            'median_total_mib': round(statistics.median(r['total_mib'] for r in rows), 2),
            'peak_total_mib': round(max(r['total_mib'] for r in rows), 2),
            'median_parent_mib': round(
                statistics.median(r['parent_footprint_mib'] for r in rows), 2),
            'median_child_mib': round(
                statistics.median(r['child_total_mib'] for r in rows), 2),
            'max_inactive_frame_mib': round(
                max(r['inactive_frame_bytes'] for r in rows) / 1048576.0, 2),
            'max_child_count': max(r['child_count'] for r in rows),
            'max_ffmpeg_count': max(r['child_count'] for r in rows),
        }
    args.output.write_text(json.dumps(
        {'root': str(args.root), 'probe': 'libproc',
         'libproc_available': memprobe.available(),
         'errors': errors, 'summary': summaries, 'samples': samples},
        indent=2) + '\n')
    print(json.dumps({'errors': errors, 'summary': summaries}))
    return bool(errors)


if __name__ == '__main__':
    raise SystemExit(main())
