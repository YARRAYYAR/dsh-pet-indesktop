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
    parser.add_argument('--require-hq', action='store_true')
    parser.add_argument('--pets', type=int, choices=(1, 3), default=3)
    parser.add_argument('--background', action='store_true')
    parser.add_argument('--scale', type=float, default=.72)
    parser.add_argument('--spawn-api', action='store_true')
    parser.add_argument('--churn', action='store_true')
    parser.add_argument('--duration', type=float, default=32)
    parser.add_argument('--steady-after', type=float, default=12)
    parser.add_argument('--prewarm', choices=('minimal', 'balanced', 'full'), default='full')
    parser.add_argument('--different-actions', action='store_true')
    parser.add_argument('--mixed-sizes', action='store_true')
    parser.add_argument('--exercise', action='store_true')
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.output.parent.mkdir(parents=True, exist_ok=True)
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
    from pet.window import PetWindow
    if args.background:
        original_opacity = PetWindow._apply_opacity
        def background_opacity(window):
            original_opacity(window)
            window.setWindowOpacity(0)
        PetWindow._apply_opacity = background_opacity
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    assert app.platformName() == 'cocoa'
    cfg = Config(Path(tempfile.mkdtemp(prefix='seeky-multi-')))
    cfg.data.update({'no_move': True, 'mouse_through': True, 'cursor_hidden_passthrough': False,
                     'idle_low_fps_enabled': False, 'self_talk_enabled': False, 'codex_link_enabled': False,
                     'harness_autostart': False, 'top_flip_enabled': False, 'click_sound_enabled': False,
                     'collision_sound_enabled': False, 'scale': args.scale,
                     'media_prewarm': args.prewarm,
                     'experimental_single_process_spawn': True, 'experimental_shared_decode': True})
    cfg.save()
    random.seed(42)
    perfstats.enable()
    shell = AppShell(app, cfg, enable_chat=False, slot_id=0)
    shell.start()
    wins = [shell.win]
    # Apply the public resize path explicitly; AppShell startup can normalize a
    # saved scale before the frame's backing-screen DPR is available.
    if abs(wins[0].scale - args.scale) > 1e-6:
        wins[0].change_scale(args.scale)
    frames = {index: [] for index in range(args.pets)}
    errors, samples, components = [], [], []
    start = time.monotonic()
    max_warm = 0
    stop = threading.Event()
    stage = 'startup'
    finished_capture = False
    duplicates = []
    epochs = [0, 0, 0]
    actions = {}
    routes = {}

    def fail(kind, value, tb):
        import traceback
        traceback.print_exception(kind, value, tb)
        errors.append(str(value))
        app.quit()
    sys.excepthook = fail

    def play(win, index):
        names = [n for n in win.lib.names() if '待机' in n]
        pools = (win.idles, win.turns, win.acts)
        idle = pools[index][0] if args.different_actions else next(n for n in names if '待机呼吸' in n)
        if args.mixed_sizes:
            win.change_scale((.72, 1.0, args.scale)[index])
        epochs[index] += 1
        epoch = epochs[index]
        actions[index] = idle
        original_frame = win._on_frame
        def observed_frame(name, n):
            if name == win.anim and not win._hidden_paused and not getattr(win, '_closing', False):
                movie = win.movie
                frames[index].append((round(time.monotonic()-start, 4), n, epoch,
                                      str(movie.path), movie._generation))
            original_frame(name, n)
        # The product's existing connection dynamically calls _on_frame. This
        # observes each delivered frame before its real end-of-action handler,
        # including replacements of the movie at a resolution boundary.
        win._on_frame = observed_frame
        win._on_anim_ended = lambda _name: win.switch_clip(idle)
        # AppShell already starts each new window. Reselecting the same clip
        # immediately unsubscribes it, so the last-subscriber teardown can
        # detach a still playing publisher and make this harness decode locally.
        if win.anim != idle:
            win.switch_clip(idle)
        movie = win.movie
        routes[index] = {'idle_eligible': idle in win.idles,
                         'logical_scale': win.scale,
                         'screen_dpr': win.screen().devicePixelRatio() if win.screen() else None,
                         'hq_catalog_entries': len(win.lib._hq_paths),
                         'broker_active': win._broker_active(),
                         'feed': movie._feed_source is not None,
                         'publish': movie._publish_sink is not None,
                         'path': str(movie.path)}
        if args.require_hq and '/characters_hq/' not in str(movie.path):
            errors.append(f'Pet {index}: scale {win.scale} did not select the required HQ source')

    play(wins[0], 0)
    for index in range(1, args.pets):
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
                physical = {int(line.split()[0]): int(line.split()[1]) for line in result.stdout.splitlines()}
                footprint = sum(physical.values())
                ffmpeg = [p for p in procs if 'ffmpeg' in p.name()]
                samples.append({'time': round(time.monotonic()-start, 3), 'stage': stage,
                                'footprint': footprint, 'ffmpeg_count': len(ffmpeg),
                                'ffmpeg_footprint': sum(physical.get(p.pid, 0) for p in ffmpeg),
                                'parent_footprint': physical.get(parent.pid, 0),
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
    def component_sample():
        raw, first, queues, rings = {}, {}, 0, 0
        display, window = 0, 0
        for win in wins:
            if getattr(win.movie, '_cleaned', False):
                continue
            for clip in win.lib._movies.values():
                image = getattr(clip, '_first_image', None)
                if image is not None:
                    first[image.cacheKey()] = image.sizeInBytes()
                with clip._queue.mutex:
                    for item in clip._queue.queue:
                        if item is not None and isinstance(item[0], bytes):
                            data = item[0]; raw[id(data)] = len(data); queues += len(data)
                image = getattr(clip, '_current_image', None)
                if image is not None:
                    display += image.sizeInBytes()
            image = getattr(win, '_hit_alpha_image', None)
            if image is not None:
                window += image.sizeInBytes()
        hub = getattr(shell, '_decode_hub', None)
        if hub is not None:
            for source in hub._sources.values():
                for sub in source.subscriptions:
                    with sub.ring._lock:
                        for data, _src in sub.ring._dq:
                            raw[id(data)] = len(data); rings += len(data)
        components.append({'time': round(time.monotonic()-start, 3), 'stage': stage,
                           'shared_sources': len(hub._sources) if hub is not None else 0,
                           'shared_subscribers': sum(len(s.subscriptions) for s in hub._sources.values()) if hub is not None else 0,
                           'library_prewarm': [{'low_done': w.lib._low_first_frames_done,
                                                'low_in_flight': w.lib._low_warm_in_flight}
                                               for w in wins if not getattr(w, '_closing', False)],
                           'first_frame_unique_bytes': sum(first.values()),
                           'queue_referenced_bytes': queues, 'ring_referenced_bytes': rings,
                           'raw_unique_bytes_across_queues_and_rings': sum(raw.values()),
                           'clip_display_image_bytes': display, 'window_scaled_image_bytes': window,
                           'performance_counters': perfstats.snapshot()})
    component_timer = QTimer(app)
    component_timer.setInterval(2000)
    component_timer.timeout.connect(component_sample)
    component_timer.start()
    def close_child():
        wins[2].on_exit_window()
        QTimer.singleShot(500, lambda: lifecycle.update(windows_after_close=len(shell.instances)))
    def respawn():
        shell.spawn_pet()
        wins[2] = shell.instances[-1].win
        play(wins[2], 2)
        lifecycle['windows_after_respawn'] = len(shell.instances)
    if args.churn and args.pets == 3:
        QTimer.singleShot(int((args.duration-12)*1000), close_child)
        QTimer.singleShot(int((args.duration-9)*1000), respawn)
    if args.exercise:
        for index, scale in enumerate((.72, 1.3, .9, 1.3)):
            def resize(scale=scale):
                for win in wins:
                    win.change_scale(scale)
            QTimer.singleShot(int((args.steady_after+8+index*8)*1000), resize)
    QTimer.singleShot(int((args.duration-2)*1000), check_first_images)
    QTimer.singleShot(int(args.steady_after*1000), steady)
    source_widths = []
    finish_deadline = None
    def finish():
        nonlocal finish_deadline, finished_capture
        if finish_deadline is None:
            finish_deadline = time.monotonic() + 2
        pixmaps = [win.movie.currentPixmap() for win in wins]
        if any(pm is None or pm.isNull() for pm in pixmaps):
            if time.monotonic() < finish_deadline:
                QTimer.singleShot(16, finish)
                return
            errors.append('No decoded source image at final capture after two seconds')
        source_widths.extend(pm.width() if pm is not None else 0 for pm in pixmaps)
        component_sample()
        for index, win in enumerate(wins):
            if not win.grab().save(str(args.output.with_name(args.output.stem+f'-pet-{index}.png'))):
                errors.append(f'Pet {index}: native capture could not be saved')
        finished_capture = True
        app.quit()
    QTimer.singleShot(int(args.duration*1000), finish)
    result = app.exec()
    probe_timer.stop()
    component_timer.stop()
    stop.set(); worker.join(5)
    if not finished_capture:
        errors.append('Application quit before the requested observation and final capture completed')
    if not samples or samples[-1]['time'] < args.duration-3:
        errors.append('Memory samples did not cover the requested observation duration')
    stable = [s['footprint'] for s in samples if s['stage'] == 'steady']
    checks = {'max_first_frame_decoders': max_warm, 'steady_mib': statistics.median(stable)/2**20 if stable else None,
              'peak_mib': max(s['footprint'] for s in samples)/2**20 if samples else None,
              'growth_mib': (statistics.median(stable[-8:])-statistics.median(stable[:8]))/2**20 if stable else None,
              'playback': {}, 'queue_drops': perfstats.snapshot().get('webm.queue_drop', {}).get('count', 0)}
    checks['duplicate_first_images'] = [str(Path(p).relative_to(root)) for p in duplicates]
    checks['lifecycle'] = lifecycle
    checks['shared_process_enabled'] = shell._single_process_spawn
    checks['source_widths'] = source_widths
    checks['actions'] = actions
    checks['initial_decode_routes'] = routes
    remaining = []
    for proc in psutil.Process().children(recursive=True):
        try:
            if 'ffmpeg' in proc.name() and proc.is_running():
                remaining.append(proc.pid)
        except psutil.NoSuchProcess:
            continue
    checks['live_ffmpeg_after_cleanup'] = remaining
    if remaining:
        errors.append(f'Decoder processes survived window cleanup: {remaining}')
    if args.different_actions and len(set(actions.values())) != args.pets:
        errors.append(f'Different-action scenario did not play three distinct actions: {actions}')
    if args.churn and args.pets == 3 and lifecycle != {'windows_after_close': 2, 'windows_after_respawn': 3}:
        errors.append(f'Child-only close/respawn did not preserve the other pets: {lifecycle}')
    for index, values in frames.items():
        if not values or values[-1][0] < args.duration-3:
            errors.append(f'Pet {index}: no delivered frames in the final three seconds')
        bins = []
        for offset in range(0, int(args.duration), 10):
            bucket = [v for v in values if offset <= v[0] < offset+10]
            elapsed = [b[0]-a[0] for a, b in zip(bucket, bucket[1:]) if a[2] == b[2]]
            bins.append({'start': offset, 'fps': len(elapsed)/sum(elapsed) if elapsed else 0,
                         'frames': len(bucket)})
        values = [v for v in values if args.steady_after+2 <= v[0] < (args.duration-13 if args.churn else args.duration-1)]
        gaps = sum(b[1]-a[1]-1 for a, b in zip(values, values[1:])
                   if a[2:] == b[2:] and b[1] > a[1]+1)
        # Include natural action/resolution boundaries in delivered FPS; only
        # a closed window's replacement starts a new independent lifetime.
        intervals = [b[0]-a[0] for a, b in zip(values, values[1:]) if a[2] == b[2]]
        fps = len(intervals)/sum(intervals) if intervals else 0
        checks['playback'][index] = {'fps': fps, 'forward_gaps': gaps, 'frames': len(values), 'ten_second_bins': bins}
        if fps < 22 or gaps: errors.append(f'Pet {index}: fps={fps:.2f}, skipped source frames={gaps}')
    if args.expect_warm_limit is not None and max_warm > args.expect_warm_limit:
        errors.append(f'Prewarm decoder peak {max_warm} exceeds process-wide budget {args.expect_warm_limit}')
    if args.expect_shared_first_frames and duplicates:
        errors.append(f'{len(duplicates)} clips retain separate identical first-frame buffers')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({'command': [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]],
        'cwd': str(root), 'setup': 'Real Cocoa AppShell public spawn, isolated config, seed 42; background opacity zero keeps the Qt drawing path active; same initial action is not unnecessarily restarted',
        'inputs': vars(args) | {'root': str(root), 'output': str(args.output), 'probe': str(args.probe)},
        'assertions': 'Every requested pet >=22 delivered fps, no forward source gaps; optional HQ-path and process-wide warm-cap checks',
        'reset': 'aboutToQuit performs actual per-window cleanup; sampler stopped and joined',
        'checks': checks, 'samples': samples, 'components': components,
        'delivered_frames': frames,
        'accounting': 'Raw frame bytes deduplicated by object identity across queue/ring; QImage storage by cacheKey. Clip/window images are separate categories; QPixmap aliases are not added. Process footprint includes native allocators/ffmpeg and is not the sum of reference categories.',
        'errors': errors, 'exit_status': int(bool(errors)) or result}, indent=2))
    print(checks, errors)
    return int(bool(errors)) or result


if __name__ == '__main__':
    sys.exit(main())
