"""Native AppShell cache lifecycle and real-media memory/latency evidence."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import traceback


def image_hash(image):
    return hashlib.sha256(bytes(image.constBits())).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--probe', type=Path, required=True)
    parser.add_argument('--mode', choices=('window', 'thumbnails', 'pixels', 'first-frames'), default='window')
    parser.add_argument('--count', type=int, default=12)
    parser.add_argument('--background', action='store_true')
    args = parser.parse_args()
    root = args.root.resolve()
    args.output = args.output.resolve()
    args.probe = args.probe.resolve()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    os.chdir(root)
    sys.path.insert(0, str(root))
    import psutil
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication
    from pet import animation_thumbnail as thumbnail
    from pet.app import AppShell
    from pet.config import Config
    from pet.webm_clip import WebMClip
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
    cfg = Config(Path(tempfile.mkdtemp(prefix='seeky8-native-')))
    cfg.data.update({'no_move': True, 'mouse_through': True,
                     'self_talk_enabled': False, 'codex_link_enabled': False,
                     'harness_autostart': False, 'top_flip_enabled': False,
                     'click_sound_enabled': False, 'collision_sound_enabled': False,
                     'idle_low_fps_enabled': False, 'media_prewarm': 'minimal', 'scale': .72})
    cfg.save()
    shell = AppShell(app, cfg, enable_chat=False)
    shell.start()
    win = shell.win
    names = sorted(win.lib.names())
    names = names[::max(1, len(names) // args.count)][:args.count]
    thumbnail._DISK_CACHE_DIR = Path(tempfile.mkdtemp(prefix='seeky8-thumbnails-'))
    errors, checks, samples, results = [], {}, [], []
    done, stop = threading.Event(), threading.Event()
    decode_entered, decode_release, decode_returned = threading.Event(), threading.Event(), threading.Event()
    waiter_entered, waiter_finished = threading.Event(), threading.Event()
    close_tasks, close_owner, close_results = [], [], [None, None]
    started = time.monotonic()

    def fail(kind, value, tb):
        traceback.print_exception(kind, value, tb)
        errors.append(f'{kind.__name__}: {value}')
        app.quit()

    sys.excepthook = fail

    def sampler():
        parent = psutil.Process()
        while not stop.wait(.05):
            try:
                procs = [parent, *parent.children(recursive=True)]
                measured = subprocess.check_output([str(args.probe), *[str(p.pid) for p in procs]], text=True)
                rows = {int(r.split()[0]): [int(v) for v in r.split()[1:]] for r in measured.splitlines()}
                if parent.pid not in rows:
                    raise RuntimeError('Memory probe did not return the parent process')
                samples.append({'time': time.monotonic()-started,
                                'physical': sum(r[0] for r in rows.values()),
                                'rss': sum(r[1] for r in rows.values()),
                                'ffmpeg_count': sum('ffmpeg' in p.name() for p in procs),
                                'ffmpeg_threads': sum(p.num_threads() for p in procs if 'ffmpeg' in p.name())})
            except psutil.NoSuchProcess:
                continue
            except Exception as exc:
                errors.append(f'sampler: {exc}')
                break

    def work():
        try:
            if args.mode == 'window':
                name = names[0]
                first = win.animation_icon_image(name)
                repeated = win.animation_icon_image(name)
                assert not first.isNull() and image_hash(first) == image_hash(repeated)
                cache = win._animation_icon_image_cache
                assert cache.total_bytes() <= cache.max_bytes() == 8*1024*1024
                checks.update({'name': name, 'thumbnail_hash': image_hash(first), 'cache_bytes': cache.total_bytes()})
                # Hold one real decoder at its entry to deterministically close
                # with an owner and waiter in flight; no fake image is supplied.
                from pet import window as window_module
                original_decode = window_module.decode_representative_frame
                def delayed_decode(path):
                    decode_entered.set()
                    assert decode_release.wait(240), 'Close flow did not release decoder'
                    try:
                        return original_decode(path)
                    finally:
                        decode_returned.set()
                window_module.decode_representative_frame = delayed_decode
                def closing_request(index):
                    try:
                        close_results[index] = win.animation_icon_image(names[1]).isNull()
                    except Exception as exc:
                        errors.append(f'closing request: {exc}')
                    finally:
                        if index == 1:
                            waiter_finished.set()
                owner = threading.Thread(target=closing_request, args=(0,), daemon=True)
                close_owner.append(owner)
                close_tasks.append(owner)
                owner.start()
                assert decode_entered.wait(5), 'No thumbnail owner reached decoder'
                with win._animation_icon_cache_lock:
                    pending = win._animation_icon_inflight[names[1]]
                    original_wait = pending.wait
                    def observed_wait(*args, **kwargs):
                        waiter_entered.set()
                        return original_wait(*args, **kwargs)
                    pending.wait = observed_wait
                waiter = threading.Thread(target=closing_request, args=(1,), daemon=True)
                close_tasks.append(waiter)
                waiter.start()
                assert waiter_entered.wait(5), 'No waiter reached the in-flight event'
                assert close_owner[0].is_alive() and not decode_returned.is_set(), 'Decoder was not held for close'
                checks['decoder_held_for_close'] = True
            elif args.mode == 'first-frames':
                # Worker QObject owns no active QTimer: only the existing warm seam runs.
                for name in names:
                    clip = WebMClip(win.lib.clip_path(name))
                    begin = time.perf_counter()
                    clip.warm_first_frame()
                    elapsed = (time.perf_counter()-begin)*1000
                    image = clip._first_image
                    assert image is not None and not image.isNull(), name
                    results.append({'name': name, 'hash': image_hash(image),
                                    'width': image.width(), 'height': image.height(),
                                    'fps': clip._fps, 'duration': clip._duration,
                                    'latency_ms': elapsed})
                    clip.cleanup()
            else:
                for name in names:
                    path = win.lib.clip_path(name)
                    begin = time.perf_counter()
                    image = thumbnail.decode_representative_frame(path)
                    elapsed = (time.perf_counter()-begin)*1000
                    assert not image.isNull(), name
                    assert max(image.width(), image.height()) <= 128
                    result = {'name': name, 'hash': image_hash(image),
                              'width': image.width(), 'height': image.height(), 'latency_ms': elapsed}
                    begin = time.perf_counter()
                    repeated = thumbnail.decode_representative_frame(path)
                    result['cached_latency_ms'] = (time.perf_counter()-begin)*1000
                    assert image_hash(repeated) == result['hash']
                    if args.mode == 'pixels':
                        # Independent old pipeline oracle: full-size private copy then Qt Smooth scale.
                        generator = thumbnail.imageio_ffmpeg.read_frames(str(path), pix_fmt='rgba', bits_per_pixel=32,
                            input_params=['-c:v', 'libvpx-vp9', '-threads', '1', '-filter_threads', '1'],
                            output_params=['-threads', '1'])
                        try:
                            meta = next(generator)
                            count = max(1, round(float(meta.get('fps') or 24)*float(meta.get('duration') or 0)))
                            target = thumbnail.representative_frame_index(count)
                            for index, frame in enumerate(generator):
                                if index == target:
                                    width, height = meta['size']
                                    full = QImage(frame, width, height, width*4, QImage.Format.Format_RGBA8888).copy()
                                    expected = thumbnail._as_thumbnail(full)
                                    assert image_hash(expected) == result['hash'], name
                                    result['oracle_hash'] = image_hash(expected)
                                    break
                            else:
                                raise AssertionError(f'No representative source frame: {name}')
                        finally:
                            generator.close()
                    results.append(result)
        except Exception as exc:
            errors.append(f'{type(exc).__name__}: {exc}')
        finally:
            done.set()

    sampler_thread = threading.Thread(target=sampler, daemon=True)
    task = threading.Thread(target=work, daemon=True)

    def begin():
        win.lib.pause_warm()
        sampler_thread.start()
        task.start()

    def poll():
        if done.is_set():
            checks['visible_frames'] = win.movie.currentFrameNumber()
            if not win.grab().save(str(args.output.with_suffix('.png'))):
                errors.append('Native screenshot could not be saved')
            if args.mode == 'window' and not errors:
                win.hide()
                assert win._hidden_paused and win.lib._warm_paused
                win.show()
                assert not win._hidden_paused
                checks['hide_restore'] = True
                win.close()
                cache_empty = win._animation_icon_image_cache.total_bytes() == 0
                assert waiter_finished.wait(1) and close_results[1], 'Close did not wake the waiting request before decoder completion'
                checks['close_wakes_waiter_before_owner'] = True
                decode_release.set()
                for thread in close_tasks:
                    thread.join(5)
                assert cache_empty, 'Closed window retained its thumbnail cache'
                assert not any(thread.is_alive() for thread in close_tasks), 'Closed thumbnail waiter survived'
                assert close_results == [True, True], f'Closed requests returned images: {close_results}'
                assert win.animation_icon_image(names[0]).isNull(), 'Closed window started a new decode'
                assert win._animation_icon_image_cache.total_bytes() == 0, 'Late decoder repopulated closed cache'
                checks['closed_cache_empty'] = True
            app.quit()
        elif time.monotonic()-started > 300:
            errors.append('Native flow exceeded 300s')
            app.quit()

    timer = QTimer(app)
    timer.setInterval(50)
    timer.timeout.connect(poll)
    timer.start()
    QTimer.singleShot(2500, begin)
    code = app.exec()
    timer.stop()
    decode_release.set()
    stop.set()
    task.join(5)
    sampler_thread.join(5)
    if task.is_alive():
        errors.append('Background thumbnail task survived shutdown')
    remaining = [p.pid for p in psutil.Process().children(recursive=True) if 'ffmpeg' in p.name()]
    if remaining:
        errors.append(f'Decoders survived cleanup: {remaining}')
        for pid in remaining:
            try:
                owned = psutil.Process(pid)
                owned.terminate()
                owned.wait(5)
            except psutil.NoSuchProcess:
                pass
    if not samples:
        errors.append('No valid memory samples; memory cost is unverified')
    latencies = sorted(r['latency_ms'] for r in results)
    checks.update({'p95_latency_ms': latencies[max(0, math.ceil(len(latencies)*.95)-1)] if latencies else None,
                   'physical_peak_mib': max((r['physical'] for r in samples), default=0)/2**20,
                   'rss_peak_mib': max((r['rss'] for r in samples), default=0)/2**20,
                   'physical_median_mib': statistics.median(r['physical'] for r in samples)/2**20 if samples else None,
                   'max_ffmpeg_threads': max((r['ffmpeg_threads'] for r in samples), default=0),
                   'decoders_after_cleanup': remaining})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({'command': [sys.executable, *sys.argv], 'cwd': str(root),
        'setup': 'Real Cocoa AppShell, isolated config and thumbnail disk cache; one pet; background opacity zero. Probe pauses optional prewarm; window mode explicitly exercises hide/show/close lifecycle',
        'inputs': {'mode': args.mode, 'names': names, 'background': args.background},
        'assertions': 'owned <=128px pixel-identical images, bounded window cache, cache hit equality, no leftover decoders',
        'checks': checks, 'results': results, 'samples': samples,
        'errors': errors, 'exit_status': int(bool(errors)) or code}, indent=2))
    print(checks, errors)
    return int(bool(errors)) or code


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception:
        # Bootstrap/probe failures must leave the same repeatable evidence as a failed assertion.
        if '--output' in sys.argv:
            output = Path(sys.argv[sys.argv.index('--output')+1]).resolve()
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps({'command': [sys.executable, *sys.argv], 'cwd': str(Path.cwd()),
                'setup': 'Native flow failed during bootstrap or cleanup', 'inputs': sys.argv[1:],
                'assertions': 'Native flow completes with valid samples and no residual decoders',
                'errors': [traceback.format_exc()], 'exit_status': 1}, indent=2))
        traceback.print_exc()
        sys.exit(1)
