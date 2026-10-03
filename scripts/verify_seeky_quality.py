"""Native resize / action-boundary resolution / release acceptance flow."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    args.output = args.output.resolve()
    root = args.root.resolve()
    sys.path.insert(0, str(root))
    os.chdir(root)
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from pet.app import AppShell
    from pet.config import Config
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    assert app.platformName() == 'cocoa'
    config = Config(Path(tempfile.mkdtemp(prefix='seeky-quality-')))
    config.data.update({'scale': .72, 'no_move': True, 'mouse_through': True,
                        'idle_low_fps_enabled': False, 'self_talk_enabled': False,
                        'codex_link_enabled': False, 'harness_autostart': False,
                        'top_flip_enabled': False, 'click_sound_enabled': False,
                        'collision_sound_enabled': False, 'media_prewarm': 'minimal'})
    config.save()
    shell = AppShell(app, config, enable_chat=False)
    shell.start()
    win = shell.win
    idle = next(n for n in win.lib.names() if '待机呼吸' in n)
    win._on_anim_ended = lambda _name: win.switch_clip(idle)
    win.switch_clip(idle)
    errors, checks, frames = [], {}, []
    begin = time.monotonic()
    small = win.movie
    large = None
    args.output.parent.mkdir(parents=True, exist_ok=True)

    def checked(condition, message):
        if not condition:
            errors.append(message)

    def fail(kind, value, tb):
        import traceback
        traceback.print_exception(kind, value, tb)
        errors.append(str(value))
        app.quit()
    sys.excepthook = fail

    def enlarge():
        checks['small_source'] = small.currentPixmap().size().width()
        checked(checks['small_source'] == 1280, 'Default rendering must retain the existing 720p source')
        win.change_scale(1.3)
        checked(win.movie is small, 'Resize restarted the current action')
        win.grab().save(str(args.output.with_name(args.output.stem + '-before.png')))

    def next_action():
        nonlocal large
        checked(win.movie is small, 'Resolution changed in the middle of an action')
        checked(win.switch_clip(idle), 'Large action did not start')
        large = win.movie
        large.frameChanged.connect(lambda n: frames.append((time.monotonic()-begin, n)))

    def large_ready():
        checks['large_source'] = large.currentPixmap().size().width()
        checked(checks['large_source'] == 2560, 'Enlarged action still decodes the 720p source')
        checks['render_width'] = win._frame_pixmap.width()
        checks['duration'] = large.duration()
        checks['small_duration'] = small.duration()
        checked(abs(checks['duration']-checks['small_duration']) < .05, 'Action duration changed')
        win.grab().save(str(args.output.with_name(args.output.stem + '-after.png')))

    def shrink():
        win.change_scale(.72)
        checked(win.movie is large, 'Shrinking restarted the current action')
        checked(win.switch_clip(idle), 'Default action did not restart')

    def final_checks():
        checks['returned_source'] = win.movie.currentPixmap().size().width()
        checked(checks['returned_source'] == 1280, 'Default size kept a high-resolution reader')
        checks['old_high_queue'] = large._queue.qsize()
        checked(large is small or large._cleaned, 'Superseded high-resolution player was not cleaned')
        stable = [(t, n) for t, n in frames if 3 <= t < 7.5]
        gaps = sum(b-a-1 for (_, a), (_, b) in zip(stable, stable[1:]) if b > a+1)
        fps = (len(stable)-1)/(stable[-1][0]-stable[0][0]) if len(stable)>1 else 0
        checks.update({'fps': fps, 'forward_gaps': gaps})
        checked(fps >= 22 and gaps == 0, 'Large playback lost frames or slowed below 22 fps')
        app.quit()

    QTimer.singleShot(1000, enlarge)
    QTimer.singleShot(1500, next_action)
    QTimer.singleShot(2500, large_ready)
    QTimer.singleShot(8000, shrink)
    QTimer.singleShot(9000, final_checks)
    result = app.exec()
    args.output.write_text(json.dumps({'command': [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]],
        'cwd': str(root), 'setup': 'Cocoa, Retina DPR=2, actual AppShell; isolated config; .72 -> 1.3 -> .72',
        'inputs': 'Resize while playing; explicitly start next idle; return to default size',
        'assertions': 'No mid-action restart; 1280 -> 2560 -> 1280 sources; unchanged duration; >=22 fps; no gaps; old HQ reader cleanup',
        'reset': 'Real AppShell aboutToQuit shuts down all libraries and decoders',
        'checks': checks, 'errors': errors, 'exit_status': int(bool(errors)) or result}, indent=2))
    print(checks, errors)
    return int(bool(errors)) or result


if __name__ == '__main__':
    sys.exit(main())
