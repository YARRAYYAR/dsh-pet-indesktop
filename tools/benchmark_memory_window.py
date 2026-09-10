"""Finite real-window A/B workload with isolated configuration and no global hotkeys."""
from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    parser.add_argument('--output', type=Path, required=True)
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
        config.data.update(scale=0.72, sound_enabled=False, proactive_greetings=False, action_interval_seconds=600)
        controller = PetApp(app, config)
        with patch.object(controller.hotkeys, 'start'):
            controller.start()
        win = controller.win
        win._resource_timer.stop()  # Identical playback policy in both runs.
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
            phase = 'idle' if elapsed < 20 else 'switch' if elapsed < 44 else 'hidden' if elapsed < 54 else 'resume'
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
            table = subprocess.check_output(['ps', '-axo', 'pid=,ppid=,rss=,comm='], text=True)
            parent_rss = 0
            children = []
            for line in table.splitlines():
                fields = line.split(None, 3)
                if len(fields) != 4:
                    continue
                pid, ppid, rss, command = fields
                if int(pid) == os.getpid():
                    parent_rss = int(rss)
                elif int(ppid) == os.getpid() and 'ffmpeg' in command.lower():
                    children.append(int(rss))
            retained = sum(
                clip._current_frame.image.sizeInBytes()
                for name, clip in win.lib.movies().items()
                if name != win.anim and getattr(clip, '_current_frame', None) is not None
            )
            samples.append({'seconds': round(elapsed, 2), 'phase': phase, 'parent_kib': parent_rss, 'ffmpeg_kib': sum(children), 'ffmpeg_count': len(children), 'inactive_frame_bytes': retained})
            if 10 <= elapsed < 11:
                win.grab().save(str(args.output.with_suffix('.png')))
            if elapsed >= 64:
                timer.stop()
                controller.shutdown()
                app.quit()

        timer.timeout.connect(sample)
        timer.start(500)
        app.exec()
    summaries = {}
    for phase, start in [('idle', 5), ('switch', 25), ('hidden', 47), ('resume', 57)]:
        rows = [r for r in samples if r['phase'] == phase and r['seconds'] >= start]
        summaries[phase] = {
            'median_total_mib': round(statistics.median(r['parent_kib'] + r['ffmpeg_kib'] for r in rows) / 1024, 2),
            'peak_total_mib': round(max(r['parent_kib'] + r['ffmpeg_kib'] for r in rows) / 1024, 2),
            'max_inactive_frame_mib': round(max(r['inactive_frame_bytes'] for r in rows) / 1048576, 2),
            'max_ffmpeg_count': max(r['ffmpeg_count'] for r in rows),
        }
    args.output.write_text(json.dumps({'root': str(args.root), 'errors': errors, 'summary': summaries, 'samples': samples}, indent=2) + '\n')
    print(json.dumps({'errors': errors, 'summary': summaries}))
    return bool(errors)


if __name__ == '__main__':
    raise SystemExit(main())
