"""Reproducible native macOS process-tree memory and playback probe.

Run with the same Python runtime for both source trees. Temporary Config roots
keep every measurement isolated from user settings. No source pixels change.
"""
import argparse
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import threading
import time
import traceback


def arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--base', type=Path)
    parser.add_argument('--probe', type=Path)
    parser.add_argument('--settings-child', action='store_true')
    return parser.parse_args()


def main():
    args = arguments()
    args.root = args.root.resolve()
    args.output = args.output.resolve()
    args.probe = args.probe.resolve() if args.probe else None
    args.output.parent.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(args.root.resolve()))
    os.chdir(args.root)
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtWidgets import QApplication
    from pet.config import Config

    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    errors = []

    def fail_callback(kind, error, trace):
        errors.append(str(error))
        traceback.print_exception(kind, error, trace)
        app.quit()

    sys.excepthook = fail_callback
    assert app.platformName() == 'cocoa', 'Native Cocoa is required'
    base = args.base or Path(tempfile.mkdtemp(prefix='dsr-bench-'))
    config = Config(base)
    if args.settings_child:
        from pet.__main__ import _exec_settings
        from pet.modern_settings_dialog import ModernSettingsDialog

        def protect_input():
            for dialog in app.topLevelWidgets():
                if isinstance(dialog, ModernSettingsDialog):
                    dialog.setWindowFlag(Qt.WindowType.WindowTransparentForInput, True)
                    dialog.show()

        def close_settings():
            for dialog in app.topLevelWidgets():
                if isinstance(dialog, ModernSettingsDialog):
                    dialog.close()
            QTimer.singleShot(200, app.quit)

        QTimer.singleShot(0, protect_input)
        QTimer.singleShot(2400, close_settings)
        return _exec_settings(app, config, include_ai=False)

    import psutil
    from pet.app import AppShell
    from pet import perfstats
    random.seed(42)
    config.data.update({'no_move': True, 'mouse_through': True,
                        'cursor_hidden_passthrough': False, 'idle_low_fps_enabled': False,
                        'self_talk_enabled': False, 'harness_autostart': False,
                        'top_flip_enabled': False, 'codex_link_enabled': False,
                        'click_sound_enabled': False, 'collision_sound_enabled': False,
                        'experimental_single_process_spawn': True,
                        'experimental_shared_decode': True, 'show_dock_icon': True,
                        'dynamic_island': {'enabled': False, 'collision_enabled': False}})
    config.save()
    perfstats.enable()
    shell = AppShell(app, config, enable_chat=False)
    shell.start()
    windows = [shell.win]
    stage = 'warm'
    samples = []
    frames = []
    children = []
    attached_movies = set()
    started = time.monotonic()
    action_names = sorted(shell.win.lib.names())
    action_index = 0
    settings_remaining = 8
    switching = QTimer(app)

    def record_frame(window, movie, index):
        if window.movie is not movie or not window.isVisible():
            return
        frames.append({'stage': stage, 'window': id(window), 'movie': str(movie.path),
                       'index': index, 'time': round(time.monotonic() - started, 4)})

    def attach(window):
        movie = window.movie
        if id(movie) not in attached_movies:
            attached_movies.add(id(movie))
            movie.frameChanged.connect(lambda index, window=window, movie=movie:
                                       record_frame(window, movie, index))

    def steady(window):
        # Native input must pass through the probe windows: a user click can
        # drag or exit a pet and invalidate the controlled workload.
        # Input passthrough is seeded in Config before construction. Changing
        # window flags during playback hides/shows it and interrupts prewarm.
        window.show()
        idle = next(name for name in window.lib.names() if '待机呼吸' in name)
        window._on_anim_ended = lambda _name: window.switch_clip(idle)
        window.switch_clip(idle)
        attach(window)

    steady(shell.win)

    def switch():
        nonlocal action_index
        name = action_names[action_index % len(action_names)]
        action_index += 1
        shell.win.switch_clip(name)
        attach(shell.win)

    switching.timeout.connect(switch)

    def set_stage(name):
        nonlocal stage
        stage = 'transition'
        if name == 'multi':
            for index in (1, 2):
                instance = shell.spawn_in_process_window(index)
                windows.append(instance.win)
                steady(instance.win)
        elif name == 'switch':
            for instance in list(shell._instances)[1:]:
                shell._on_window_exit_requested(instance)
            windows[:] = [shell.win]
            switching.start(1800)
        elif name == 'settings':
            switching.stop()
            steady(shell.win)
        stage = name
        print(name, flush=True)
        if name == 'settings':
            open_settings()
        elif name == 'return':
            QTimer.singleShot(20000, finish)
        else:
            following = {'single': 'multi', 'multi': 'switch', 'switch': 'settings'}[name]
            QTimer.singleShot(20000, lambda: set_stage(following))

    def open_settings():
        nonlocal settings_remaining
        with args.output.with_suffix('.settings.log').open('a') as stream:
            child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()),
                                      '--root', str(args.root), '--output', str(args.output),
                                      '--base', str(base), '--settings-child'],
                                     stdout=stream, stderr=subprocess.STDOUT)
        children.append(child)
        settings_remaining -= 1

        def after_close():
            if child.poll() is None:
                QTimer.singleShot(200, after_close)
            elif settings_remaining:
                QTimer.singleShot(300, open_settings)
            else:
                set_stage('return')

        QTimer.singleShot(200, after_close)

    process = psutil.Process()

    def sample():
        processes = [process, *process.children(recursive=True)]
        pids = []
        rss = 0
        kinds = {}
        for item in processes:
            try:
                rss += item.memory_info().rss
                pids.append(item.pid)
                kinds[str(item.pid)] = ('main' if item.pid == process.pid else
                                        'ffmpeg' if 'ffmpeg' in item.name().lower() else 'settings')
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        footprints = {}
        if args.probe:
            result = subprocess.run([str(args.probe), *map(str, pids)],
                                    capture_output=True, text=True, check=True)
            for line in result.stdout.splitlines():
                pid, footprint, resident = map(int, line.split())
                footprints[str(pid)] = {'footprint': footprint, 'resident': resident,
                                        'kind': kinds[str(pid)]}
        samples.append({'time': round(time.monotonic() - started, 3), 'stage': stage,
                        'rss': rss, 'pids': pids, 'processes': footprints,
                        'footprint': sum(item['footprint'] for item in footprints.values())})
        for child in children:
            child.poll()

    stop_sampling = threading.Event()

    def sample_worker():
        while not stop_sampling.wait(1):
            try:
                sample()
            except Exception as exc:
                errors.append(str(exc))
                traceback.print_exc()
                stop_sampling.set()

    worker = threading.Thread(target=sample_worker, name='memory-probe', daemon=True)
    worker.start()
    timer = QTimer(app)
    timer.timeout.connect(lambda: [attach(window) for window in windows])
    timer.start(1000)
    QTimer.singleShot(10000, lambda: set_stage('single'))

    def finish():
        timer.stop()
        stop_sampling.set()
        worker.join(timeout=10)
        switching.stop()
        for child in children:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=10)
            if child.returncode != 0:
                errors.append(f'Settings child exited {child.returncode}')
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({'root': str(args.root), 'base': str(base),
                                          'platform': app.platformName(), 'samples': samples,
                                          'frames': frames, 'errors': errors,
                                          'perfstats': perfstats.snapshot()},
                                         ensure_ascii=False, indent=2))
        app.quit()

    result = app.exec()
    if not args.output.is_file():
        raise RuntimeError('Measurement ended before the complete report was written')
    return 1 if errors else result


if __name__ == '__main__':
    sys.exit(main())
