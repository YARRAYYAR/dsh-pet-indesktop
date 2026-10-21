"""Real Cocoa single-pet residency and lifecycle evidence, with isolated data.

Compile the probe with: clang -O2 scripts/dsr_proc_memory.c -o /tmp/seeky-probe
Run with the repository venv interpreter; --root selects baseline or candidate.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import signal
import socket
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import traceback


def mach_timebase_info():
    """rusage CPU counters use Mach ticks; convert with this host's timebase."""
    class MachTimebaseInfo(ctypes.Structure):
        _fields_ = [('numer', ctypes.c_uint32), ('denom', ctypes.c_uint32)]
    function = ctypes.CDLL('/usr/lib/libSystem.B.dylib').mach_timebase_info
    function.argtypes = [ctypes.POINTER(MachTimebaseInfo)]
    function.restype = ctypes.c_int
    info = MachTimebaseInfo()
    status = function(ctypes.byref(info))
    if status or not info.denom:
        raise RuntimeError(f'mach_timebase_info failed: {status}, denominator={info.denom}')
    return {'numer': info.numer, 'denom': info.denom}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--probe', type=Path, required=True)
    parser.add_argument('--duration', type=float, default=36)
    parser.add_argument('--steady-after', type=float, default=12)
    parser.add_argument('--scale', type=float, default=.72)
    parser.add_argument('--require-hq', action='store_true')
    parser.add_argument('--background', action='store_true')
    parser.add_argument('--prewarm', choices=('minimal', 'balanced', 'full'), default='balanced')
    parser.add_argument('--exercise', action='store_true')
    args = parser.parse_args()
    root, output, probe = args.root.resolve(), args.output.resolve(), args.probe.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    sandbox = Path(tempfile.mkdtemp(prefix='seeky-residency-'))
    test_home = sandbox / 'home'
    test_home.mkdir()
    # Isolate Python business paths without changing the user's HOME variable.
    Path.home = classmethod(lambda cls: test_home)
    os.environ['DSH_HOME'] = str(test_home / '.dsh')
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    start = time.monotonic()
    errors, samples, frames, lifecycle = [], [], [], []
    result = {'command': list(getattr(sys, 'orig_argv', [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]])),
              'cwd': str(root), 'setup': 'Real Cocoa AppShell, single pet, seed 42; isolated Config and Python home/DSH_HOME; no chat or credential fixtures',
              'inputs': {**vars(args), 'root': str(root), 'output': str(output), 'probe': str(probe)},
              'assertions': 'Cocoa; requested duration complete; >=22 FPS during active steady playback; zero source gaps and queue drops; original media hashes; no FFmpeg after exit; lifecycle assertions for --exercise',
              'sandbox': str(sandbox), 'samples': samples, 'frames': frames,
              'lifecycle': lifecycle, 'errors': errors, 'exit_status': None}
    state = {'stage': 'startup', 'capture_complete': False, 'epoch': 0, 'app': None,
             'shell': None, 'interrupted': False}
    stop = threading.Event()
    worker = None

    def save():
        result['elapsed_seconds'] = round(time.monotonic() - start, 3)
        pending = output.with_suffix(output.suffix + '.tmp')
        snapshot = dict(result)
        if result['exit_status'] is None:
            snapshot['frames'] = {'captured': len(frames), 'last': frames[-1] if frames else None}
        pending.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2, default=str))
        pending.replace(output)

    def interrupt(signum, _frame):
        state['interrupted'] = True
        errors.append(f'interrupted by signal {signum}')
        save()
        if state['app'] is not None:
            state['app'].quit()

    signal.signal(signal.SIGTERM, interrupt)
    signal.signal(signal.SIGINT, interrupt)
    save()
    try:
        sys.path.insert(0, str(root))
        os.chdir(root)
        timebase = mach_timebase_info()
        result['cpu_accounting'] = {
            'raw_unit': 'Mach absolute-time ticks', 'rate_input_unit': 'nanoseconds',
            'timebase': timebase,
            'conversion': 'ticks * numer // denom',
            'source': 'https://github.com/apple-oss-distributions/xnu/blob/main/osfmk/kern/task.c#L6811',
        }
        import psutil
        from PySide6 import __version__ as pyside_version
        from PySide6.QtCore import QTimer, QStandardPaths, qVersion
        from PySide6.QtWidgets import QApplication
        from pet import catalog, perfstats
        from pet.app import AppShell
        from pet.config import Config
        from pet.window import PetWindow
        QStandardPaths.setTestModeEnabled(True)
        character_root = sandbox / 'characters'
        character_root.mkdir()
        catalog.external_character_dirs = lambda: [character_root]
        if args.background:
            original_opacity = PetWindow._apply_opacity

            def background_opacity(window):
                original_opacity(window)
                window.setWindowOpacity(0)
            PetWindow._apply_opacity = background_opacity
        app = QApplication([])
        state['app'] = app
        app.setQuitOnLastWindowClosed(False)
        assert app.platformName() == 'cocoa', app.platformName()
        cfg = Config(sandbox / 'config-base')
        cfg.data.update({'character': 'shenshen', 'no_move': True, 'mouse_through': not args.exercise,
                         'cursor_hidden_passthrough': False, 'auto_hide_fullscreen': False,
                         'idle_low_fps_enabled': False, 'self_talk_enabled': False,
                         'codex_link_enabled': False, 'harness_autostart': False,
                         'autostart_wanted': False, 'top_flip_enabled': False,
                         'click_sound_enabled': False, 'collision_sound_enabled': False,
                         'todo_reminder_enabled': False, 'scale': args.scale,
                         'settings_process_isolation': False, 'media_prewarm': args.prewarm,
                         'experimental_single_process_spawn': True,
                         'experimental_shared_decode': True})
        cfg.data['agent_link']['enabled'] = False
        cfg.data['proactive_screen']['enabled'] = False
        cfg.data['dynamic_island']['enabled'] = False
        cfg.save()
        random.seed(42)
        perfstats.enable()
        shell = AppShell(app, cfg, enable_chat=False, slot_id=0)
        state['shell'] = shell
        # Reserve a non-listening local port: offline is deterministic, and no
        # real DSH instance or bridge/profile is contacted by this fixture.
        offline_socket = socket.socket()
        offline_socket.bind(('127.0.0.1', 0))
        offline_port = offline_socket.getsockname()[1]
        shell._dsh_state_tracker.port = offline_port
        shell._dsh_state_tracker._candidate_ports = lambda: [offline_port]
        offline_event_timeouts = []
        shell._dsh_state_tracker._event_timer.timeout.connect(
            lambda: offline_event_timeouts.append(round(time.monotonic() - start, 3)))
        shell.start()
        win = shell.win
        media = root / 'assets/characters/shenshen/videos/idle/待机呼吸休闲.webm'
        hq_media = root / 'assets/characters_hq/shenshen/videos/idle/待机呼吸休闲.webm'
        result['media_sha256_before'] = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                                         for p in (media, hq_media)}
        result['environment'] = {'python': sys.version, 'pyside': pyside_version, 'qt': qVersion(),
                                 'platform': platform.platform(), 'cpu_count': os.cpu_count(),
                                 'memory_bytes': psutil.virtual_memory().total, 'qt_platform': app.platformName()}
        start = time.monotonic()

        def observe(window):
            state['epoch'] += 1
            epoch = state['epoch']
            if abs(window.scale - args.scale) > 1e-6:
                window.change_scale(args.scale)
            idle = next(n for n in window.lib.names() if '待机呼吸' in n)
            original_frame = window._on_frame

            def on_frame(name, n):
                if name == window.anim and not window._hidden_paused and not getattr(window, '_closing', False):
                    movie = window.movie
                    frames.append((round(time.monotonic() - start, 4), n, epoch,
                                   str(movie.path), movie._generation, state['stage']))
                original_frame(name, n)
            window._on_frame = on_frame
            window._on_anim_ended = lambda _name: window.switch_clip(idle)
            if window.anim != idle:
                window.switch_clip(idle)
            if args.require_hq and '/characters_hq/' not in str(window.movie.path):
                errors.append(f'required HQ source not selected: {window.movie.path}')
            lifecycle.append({'at': round(time.monotonic() - start, 3), 'event': 'observe',
                              'epoch': epoch, 'path': str(window.movie.path), 'scale': window.scale})
        observe(win)
        parent = psutil.Process()

        def sample_worker():
            previous = None
            while not stop.wait(1):
                try:
                    procs = [parent, *parent.children(recursive=True)]
                    observed = {}
                    for p in procs:
                        try:
                            observed[p.pid] = {'name': p.name(), 'threads': p.num_threads()}
                        except psutil.NoSuchProcess:
                            continue
                    raw = subprocess.run([str(probe), *map(str, observed)], capture_output=True,
                                         text=True, check=True, timeout=5)
                    rows = {int(cols[0]): list(map(int, cols[1:])) for line in raw.stdout.splitlines()
                            if (cols := line.split())}
                    stamp = time.monotonic() - start
                    cpu_ticks = sum(r[2] + r[3] for r in rows.values())
                    pkg = sum(r[4] for r in rows.values())
                    interrupts = sum(r[5] for r in rows.values())
                    if parent.pid in rows:
                        r = rows[parent.pid]
                        cpu_ticks += r[6] + r[7]
                        pkg += r[8]
                        interrupts += r[9]
                    cpu_ns = cpu_ticks * timebase['numer'] // timebase['denom']
                    sample = {'time': round(stamp, 3), 'stage': state['stage'],
                              'footprint': sum(r[0] for r in rows.values()),
                              'rss': sum(r[1] for r in rows.values()),
                              'threads': sum(p['threads'] for pid, p in observed.items() if pid in rows),
                              'ffmpeg_count': sum('ffmpeg' in p['name'] for pid, p in observed.items() if pid in rows),
                              'cpu_mach_ticks_including_exited_children': cpu_ticks,
                              'cpu_ns_including_exited_children': cpu_ns,
                              'pkg_idle_wakeups_total': pkg, 'interrupt_wakeups_total': interrupts}
                    stable_tree = frozenset(rows)
                    if previous is not None and stable_tree == previous[4] and cpu_ns >= previous[1] and pkg >= previous[2] and interrupts >= previous[3]:
                        dt = stamp - previous[0]
                        sample.update(cpu_percent=max(0, cpu_ns - previous[1]) / (dt * 1e7),
                                      pkg_idle_wakeups_per_second=max(0, pkg - previous[2]) / dt,
                                      interrupt_wakeups_per_second=max(0, interrupts - previous[3]) / dt)
                    sample['counter_tree_transition'] = previous is not None and stable_tree != previous[4]
                    previous = (stamp, cpu_ns, pkg, interrupts, stable_tree)
                    samples.append(sample)
                except psutil.NoSuchProcess:
                    continue
                except Exception as exc:
                    errors.append(f'metric sampler: {exc!r}')
                    stop.set()
        worker = threading.Thread(target=sample_worker, name='residency-metrics', daemon=True)
        worker.start()
        checkpoint = QTimer(app)
        checkpoint.setInterval(10000)
        checkpoint.timeout.connect(save)
        checkpoint.start()

        def fail(kind, value, tb):
            traceback.print_exception(kind, value, tb)
            errors.append(f'Qt callback: {value!r}')
            app.quit()
        sys.excepthook = fail
        QTimer.singleShot(int(args.steady_after * 1000), lambda: state.update(stage='steady'))
        exercise_timer = None
        if args.exercise:
            from PySide6.QtCore import Qt
            from PySide6.QtTest import QTest
            from pet.settings_actions import ActionLibrary
            from pet.settings_commands import SettingsCommandClient
            if args.require_hq:
                raise ValueError('Run lifecycle exercise at normal scale; temporary external character deliberately retains the original normal media package')
            fixture = character_root / 'residency-fixture' / 'videos'
            fixture.mkdir(parents=True)
            source_dir = catalog.character_video_dir('shenshen')
            for source in source_dir.rglob('*'):
                target = fixture / source.relative_to(source_dir)
                if source.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                elif source.name != 'manifest.json':
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.symlink_to(source.resolve())
            assert list(fixture.rglob('*.webm')), 'temporary character has no discoverable media'
            manifest = json.loads((source_dir / 'manifest.json').read_text())
            manifest['name'] = 'Residency fixture - same original videos'
            (fixture / 'manifest.json').write_text(json.dumps(manifest))
            result['temporary_character'] = str(fixture)
            exercise = {'phase': 'ready', 'since': time.monotonic(), 'before_frames': 0,
                        'switches': 0, 'library_pass': 0, 'widget': None, 'client': None,
                        'done': False, 'retired': []}
            result['exercise'] = {'completed': False, 'switches': 0, 'action_library_cycles': 0}

            def phase(name):
                exercise.update(phase=name, since=time.monotonic(), before_frames=len(frames))
                state['stage'] = name
                lifecycle.append({'at': round(time.monotonic() - start, 3), 'event': name})

            def retirement(window, library):
                cache = getattr(window, '_animation_icon_image_cache', None)
                return {'closing': bool(getattr(window, '_closing', False)),
                        'library_shutdown': bool(getattr(library, '_shutdown', False)),
                        'thumbnail_bytes': cache.total_bytes() if cache is not None else 0,
                        'cleaned_clips': all(getattr(clip, '_cleaned', False)
                                             for clip in library._movies.values())}

            def drive_exercise():
                current = shell.win
                age = time.monotonic() - exercise['since']
                if age > 25:
                    errors.append('exercise phase deadline exceeded: ' + exercise['phase'])
                    exercise_timer.stop()
                    app.quit()
                    return
                name = exercise['phase']
                if name == 'ready' and len(frames) >= 30:
                    current.set_mouse_through(False)
                    body = current._stable_body_local_rect().translated(current._draw_delta)
                    point = body.intersected(current.rect()).center()
                    lifecycle.append({'event': 'mouse_press', 'point': (point.x(), point.y()),
                                      'interactive': current._is_in_interactive_area(point),
                                      'visible': current.isVisible()})
                    QTest.mousePress(current, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
                    if not current._interaction_hold_active:
                        raise AssertionError('real mouse press did not establish interaction hold')
                    phase('sustained_interaction')
                elif name == 'sustained_interaction' and age >= 3:
                    if not current._interaction_hold_active:
                        raise AssertionError('interaction hold disappeared before mouse release')
                    QTest.mouseRelease(current, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                                       current._stable_body_local_rect().center())
                    phase('interaction_released')
                elif name == 'interaction_released' and not current._interaction_hold_active:
                    current.hide(notify=False)
                    if not current._hidden_paused:
                        raise AssertionError('hide did not pause the real pet')
                    phase('hidden')
                elif name == 'hidden' and age >= 1:
                    current.show()
                    phase('restored')
                elif name == 'restored' and len(frames) - exercise['before_frames'] >= 24:
                    client = SettingsCommandClient(cfg, app)
                    widget = ActionLibrary(client)
                    widget.resize(640, 480)
                    widget.show()
                    exercise.update(widget=widget, client=client)
                    phase('action_library_open')
                elif name == 'action_library_open':
                    widget = exercise['widget']
                    if widget._error:
                        raise AssertionError('action library real IPC failed: ' + widget._error)
                    if widget._actions and widget._watch_seen:
                        widget.hide()
                        if widget._requests:
                            raise AssertionError('action library retained requests after hide')
                        widget.close()
                        widget.deleteLater()
                        exercise['client'].close()
                        exercise['client'].deleteLater()
                        exercise.update(widget=None, client=None)
                        exercise['library_pass'] += 1
                        result['exercise']['action_library_cycles'] = exercise['library_pass']
                        phase('library_closed')
                elif name == 'library_closed':
                    if exercise['library_pass'] < 2:
                        phase('restored')
                    else:
                        phase('character_switch')
                elif name == 'character_switch':
                    old, old_lib = current, current.lib
                    target = 'residency-fixture' if cfg.get('character') == 'shenshen' else 'shenshen'
                    switch_started = time.monotonic()
                    shell.instance.switch_character(target)
                    switch_call_ms = round((time.monotonic() - switch_started) * 1000, 3)
                    if shell.win is old:
                        raise AssertionError('character switch retained old window')
                    checked = retirement(old, old_lib)
                    lifecycle.append({'at': round(time.monotonic() - start, 3),
                                      'event': 'retired_character', 'target': target,
                                      'switch_call_ms': switch_call_ms, **checked})
                    if not all((checked['closing'], checked['library_shutdown'], checked['cleaned_clips'])) or checked['thumbnail_bytes']:
                        errors.append('old character resources not fully released: ' + str(checked))
                    exercise['retired'].append((old, old_lib))
                    exercise['switches'] += 1
                    result['exercise']['switches'] = exercise['switches']
                    observe(shell.win)
                    phase('character_recovery')
                elif name == 'character_recovery' and len(frames) - exercise['before_frames'] >= 24:
                    if exercise['switches'] < 4:
                        phase('character_switch')
                    else:
                        # Check again after real queued work has had event-loop
                        # turns to complete; old caches must remain empty.
                        late = [retirement(w, lib) for w, lib in exercise['retired']]
                        result['exercise']['retired_after_queued_work'] = late
                        if any(not x['library_shutdown'] or x['thumbnail_bytes'] for x in late):
                            errors.append('retired library/cache refilled after queued work')
                        exercise_timer.stop()
                        exercise['done'] = True
                        result['exercise']['completed'] = True
                        phase('steady')
            exercise_timer = QTimer(app)
            exercise_timer.setInterval(40)
            exercise_timer.timeout.connect(drive_exercise)
            exercise_timer.start()

        def finish():
            current = shell.win
            image = current.movie.currentPixmap()
            result['source_width'] = image.width() if image is not None else 0
            if image is None or image.isNull():
                errors.append('missing final decoded image')
            if not current.grab().save(str(output.with_suffix('.png'))):
                errors.append('native capture failed')
            state['capture_complete'] = True
            app.quit()
        QTimer.singleShot(int(args.duration * 1000), finish)
        qt_result = app.exec()
        checkpoint.stop()
        if exercise_timer is not None:
            exercise_timer.stop()
        result['offline_event_timeouts'] = offline_event_timeouts
        offline_socket.close()
        if args.exercise and not result['exercise']['completed']:
            errors.append('exercise did not complete all required phases')
        stop.set()
        worker.join(6)
        if worker.is_alive():
            errors.append('metric sampler did not finish')
        # The application's actual aboutToQuit cleanup has completed here.
        remaining = []
        for proc in parent.children(recursive=True):
            try:
                if 'ffmpeg' in proc.name() and proc.is_running():
                    remaining.append(proc.pid)
            except psutil.NoSuchProcess:
                continue
        result['live_ffmpeg_after_cleanup'] = remaining
        if remaining:
            errors.append(f'FFmpeg survived application cleanup: {remaining}')
        result['performance_counters'] = perfstats.snapshot()
        drops = perfstats.snapshot().get('webm.queue_drop', {}).get('count', 0)
        if drops:
            errors.append(f'queue drops: {drops}')
        result['media_sha256_after'] = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                                        for p in (media, hq_media)}
        if result['media_sha256_before'] != result['media_sha256_after']:
            errors.append('source media changed')
        steady = [s for s in samples if s['stage'] == 'steady']
        values = [v for v in frames if args.steady_after + 2 <= v[0] < args.duration - 1 and v[5] == 'steady']
        intervals = [b[0] - a[0] for a, b in zip(values, values[1:]) if a[2] == b[2]]
        fps = len(intervals) / sum(intervals) if intervals else 0
        gaps = sum(b[1] - a[1] - 1 for a, b in zip(values, values[1:])
                   if a[2:5] == b[2:5] and b[1] > a[1] + 1)
        summary = {'fps': fps, 'source_gaps': gaps, 'queue_drops': drops,
                   'delivered_frames': len(frames), 'steady_samples': len(steady)}
        for key in ('footprint', 'rss', 'threads', 'ffmpeg_count', 'cpu_percent',
                    'pkg_idle_wakeups_per_second', 'interrupt_wakeups_per_second'):
            entries = [s[key] for s in steady if key in s]
            summary[key + '_median'] = statistics.median(entries) if entries else None
            summary[key + '_peak'] = max(entries) if entries else None
        if steady:
            summary['footprint_growth_bytes'] = statistics.median(s['footprint'] for s in steady[-8:]) - statistics.median(s['footprint'] for s in steady[:8])
        result['summary'] = summary
        if not state['capture_complete'] or not samples or samples[-1]['time'] < args.duration - 3:
            errors.append('observation ended before the requested duration')
        if fps < 22 or gaps:
            errors.append(f'playback FPS={fps:.3f}, source gaps={gaps}')
        result['exit_status'] = int(bool(errors)) or qt_result
    except BaseException as exc:
        traceback.print_exc()
        errors.append(f'{type(exc).__name__}: {exc}')
        result['exit_status'] = 1
        stop.set()
        if state['app'] is not None and state['shell'] is not None:
            try:
                state['shell']._on_about_to_quit()
            except Exception as cleanup_error:
                errors.append(f'exception cleanup: {cleanup_error!r}')
        if worker is not None:
            worker.join(6)
    finally:
        result['reset'] = 'Application aboutToQuit cleanup; sampling stop/join; all fixture data remains in the recorded sandbox for reproduction'
        result['accounting'] = 'Process tree physical footprint and RSS include current descendants. CPU and wakeups include parent child counters to retain exited descendants; observer process costs are included. Rates spanning a process-tree transition or regressing counter are omitted to avoid non-atomic enumeration/exit artifacts. Kernel pkg-idle and interrupt wakeups are distinct counters, not Energy Impact.'
        save()
    print(json.dumps({'summary': result.get('summary'), 'errors': errors,
                      'artifact': str(output), 'exit_status': result['exit_status']}, ensure_ascii=False))
    return result['exit_status']


if __name__ == '__main__':
    raise SystemExit(main())
