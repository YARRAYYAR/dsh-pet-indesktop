"""Native three-pet playback, process-tree footprint, prewarm and exit E2E."""
import argparse
import json
import os
from pathlib import Path
import random
import statistics
import subprocess
import sys
import tempfile
import threading
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--probe', type=Path, required=True)
    parser.add_argument('--expect-warm-limit', type=int)
    parser.add_argument('--expect-shared-first-frames', action='store_true')
    parser.add_argument('--scale', type=float, default=.72)
    parser.add_argument('--spawn-api', action='store_true')
    parser.add_argument('--churn', action='store_true')
    parser.add_argument('--duration', type=float, default=32)
    parser.add_argument('--steady-after', type=float, default=12)
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.probe = args.probe.resolve()
    root = args.root.resolve()
    sys.path.insert(0, str(root))
    os.chdir(root)
    import psutil
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from pet.app import AppShell
    from pet.config import Config
    from pet import perfstats
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    assert app.platformName() == 'cocoa'
    cfg = Config(Path(tempfile.mkdtemp(prefix='seeky-multi-')))
    cfg.data.update({'no_move': True, 'mouse_through': True, 'cursor_hidden_passthrough': False,
                     'idle_low_fps_enabled': False, 'self_talk_enabled': False, 'codex_link_enabled': False,
                     'harness_autostart': False, 'top_flip_enabled': False, 'click_sound_enabled': False,
                     'collision_sound_enabled': False, 'scale': args.scale,
                     'experimental_single_process_spawn': True, 'experimental_shared_decode': True})
    cfg.save()
    random.seed(42)
    perfstats.enable()
    shell = AppShell(app, cfg, enable_chat=False, slot_id=0)
    shell.start()
    wins = [shell.win]
    frames = {0: [], 1: [], 2: []}
    errors, samples = [], []
    start = time.monotonic()
    max_warm = 0
    stop = threading.Event()
    stage = 'startup'
    duplicates = []

    def fail(kind, value, tb):
        import traceback
        traceback.print_exception(kind, value, tb)
        errors.append(str(value))
        app.quit()
    sys.excepthook = fail

    def play(win, index):
        idle = next(n for n in win.lib.names() if '待机呼吸' in n)
        win._on_anim_ended = lambda _name: win.switch_clip(idle)
        win.switch_clip(idle)
        movie = win.movie
        movie.frameChanged.connect(lambda n: frames[index].append((round(time.monotonic()-start, 4), n)))

    play(wins[0], 0)
    for index in (1, 2):
        if args.spawn_api:
            shell.spawn_pet()
            instance = shell.instances[-1]
        else:
            instance = shell.spawn_in_process_window(index)
        wins.append(instance.win)
        play(instance.win, index)

    def warm_sample():
        nonlocal max_warm
        count = 0
        for win in wins:
            for clip in win.lib._movies.values():
                count += sum(p.poll() is None for p in tuple(getattr(clip, '_first_frame_procs', ())))
        max_warm = max(max_warm, count)
    probe_timer = QTimer(app)
    probe_timer.setInterval(40)
    probe_timer.timeout.connect(warm_sample)
    probe_timer.start()

    def memory_worker():
        parent = psutil.Process()
        while not stop.wait(.5):
            try:
                procs = [parent, *parent.children(recursive=True)]
                result = subprocess.run([str(args.probe), *[str(p.pid) for p in procs]], capture_output=True, text=True, check=True)
                footprint = sum(int(line.split()[1]) for line in result.stdout.splitlines())
                samples.append({'time': round(time.monotonic()-start, 3), 'stage': stage,
                                'footprint': footprint, 'ffmpeg_count': sum('ffmpeg' in p.name() for p in procs),
                                'rss': sum(p.memory_info().rss for p in procs)})
            except psutil.NoSuchProcess:
                continue  # A decoder exited between tree enumeration and sampling.
            except Exception as exc:
                errors.append(str(exc)); stop.set()
    worker = threading.Thread(target=memory_worker, daemon=True)
    worker.start()

    def steady():
        nonlocal stage
        stage = 'steady'
    def check_first_images():
        grouped = {}
        for win in wins:
            for clip in win.lib.movies().values():
                img = getattr(clip, '_first_image', None)
                if img is not None:
                    grouped.setdefault(str(clip.path), set()).add(img.cacheKey())
        duplicates.extend(path for path, keys in grouped.items() if len(keys) > 1)
    lifecycle = {}
    def close_child():
        wins[2].on_exit_window()
        QTimer.singleShot(500, lambda: lifecycle.update(windows_after_close=len(shell.instances)))
    def respawn():
        shell.spawn_pet()
        wins[2] = shell.instances[-1].win
        play(wins[2], 2)
        lifecycle['windows_after_respawn'] = len(shell.instances)
    if args.churn:
        QTimer.singleShot(25000, close_child)
        QTimer.singleShot(27000, respawn)
    QTimer.singleShot(33000 if args.churn else int((args.duration-2)*1000), check_first_images)
    QTimer.singleShot(int(args.steady_after*1000), steady)
    source_widths = []
    def finish():
        source_widths.extend(win.movie.currentPixmap().width() for win in wins)
        app.quit()
    QTimer.singleShot(36000 if args.churn else int(args.duration*1000), finish)
    result = app.exec()
    probe_timer.stop()
    stop.set(); worker.join(5)
    stable = [s['footprint'] for s in samples if s['stage'] == 'steady']
    checks = {'max_first_frame_decoders': max_warm, 'steady_mib': statistics.median(stable)/2**20 if stable else None,
              'peak_mib': max(s['footprint'] for s in samples)/2**20 if samples else None,
              'growth_mib': (statistics.median(stable[-8:])-statistics.median(stable[:8]))/2**20 if stable else None,
              'playback': {}, 'queue_drops': perfstats.snapshot().get('webm.queue_drop', {}).get('count', 0)}
    checks['duplicate_first_images'] = [str(Path(p).relative_to(root)) for p in duplicates]
    checks['lifecycle'] = lifecycle
    checks['shared_process_enabled'] = shell._single_process_spawn
    checks['source_widths'] = source_widths
    if args.churn and lifecycle != {'windows_after_close': 2, 'windows_after_respawn': 3}:
        errors.append(f'Child-only close/respawn did not preserve the other pets: {lifecycle}')
    for index, values in frames.items():
        values = [(t, n) for t, n in values if args.steady_after+2 <= t < (24 if args.churn else args.duration-1)]
        gaps = sum(b-a-1 for (_, a), (_, b) in zip(values, values[1:]) if b > a+1)
        fps = (len(values)-1)/(values[-1][0]-values[0][0]) if len(values)>1 else 0
        checks['playback'][index] = {'fps': fps, 'forward_gaps': gaps, 'frames': len(values)}
        if fps < 22 or gaps: errors.append(f'Pet {index}: fps={fps:.2f}, skipped source frames={gaps}')
    if args.expect_warm_limit is not None and max_warm > args.expect_warm_limit:
        errors.append(f'Prewarm decoder peak {max_warm} exceeds process-wide budget {args.expect_warm_limit}')
    if args.expect_shared_first_frames and duplicates:
        errors.append(f'{len(duplicates)} clips retain separate identical first-frame buffers')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({'command': [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]],
        'cwd': str(root), 'setup': 'Real Cocoa AppShell, three same-character windows, same idle clip, isolated config, seed 42',
        'inputs': f'{args.steady_after}s startup + {args.duration-args.steady_after}s observation; .5s footprint and 40ms first-frame process sampling; churn={args.churn}',
        'assertions': 'All three pets >=22 delivered fps, no forward source gaps; optional process-wide warm cap',
        'reset': 'aboutToQuit performs actual per-window cleanup; sampler stopped and joined',
        'checks': checks, 'samples': samples, 'errors': errors, 'exit_status': int(bool(errors)) or result}, indent=2))
    print(checks, errors)
    return int(bool(errors)) or result


if __name__ == '__main__':
    sys.exit(main())
