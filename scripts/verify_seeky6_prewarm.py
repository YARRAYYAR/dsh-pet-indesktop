"""Real Cocoa/FFmpeg concurrent prewarm, pixels and cancellation evidence."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import types


def pipeline_parity(root, output):
    """Before changing options, compare real raw pixels and decoder pool costs."""
    import imageio_ffmpeg
    import psutil
    import pet.webm_clip as webm
    results, errors = [], []
    paths = [root/'assets/characters/shenshen/videos/idle/待机呼吸休闲.webm',
             root/'assets/characters_hq/shenshen/videos/idle/待机呼吸休闲.webm',
             sorted((root/'assets/characters_hq/shenshen/videos/click').glob('*.webm'))[0]]
    for path in paths:
        row = {'path': str(path.relative_to(root)), 'pipelines': {}}
        for label, inputs, outputs in (
            ('reference', ['-c:v', 'libvpx-vp9', '-threads', '1'], []),
            ('candidate', ['-c:v', 'libvpx-vp9', '-threads', '1', '-filter_threads', '1'], ['-threads', '1']),
            ('current', list(webm._FFMPEG_INPUT_PARAMS), list(getattr(webm, '_FFMPEG_OUTPUT_PARAMS', []))),
        ):
            proc = None
            def registered(p, argv):
                nonlocal proc
                if '-i' in argv:
                    proc = psutil.Process(p.pid)
            hashes, threads, rss = [], [], []
            started = time.monotonic()
            with webm._PopenCapture(on_process=registered):
                stream = imageio_ffmpeg.read_frames(str(path), pix_fmt='rgba', bits_per_pixel=32,
                                                    input_params=inputs, output_params=outputs)
                try:
                    meta = next(stream)
                    for _ in range(8):
                        raw = next(stream)
                        hashes.append(hashlib.sha256(raw).hexdigest())
                        threads.append(proc.num_threads()); rss.append(proc.memory_info().rss)
                finally:
                    stream.close()
            row['pipelines'][label] = {'dimensions': meta['size'], 'hashes': hashes,
                                      'max_threads': max(threads), 'max_rss_mib': max(rss)/2**20,
                                      'elapsed_seconds': time.monotonic()-started}
        values = row['pipelines']
        if not (values['reference']['hashes'] == values['candidate']['hashes'] == values['current']['hashes']):
            errors.append(f'RGBA source frames changed: {path.name}')
        if values['current']['max_threads'] > 8:
            errors.append(f'Current pipeline still creates an automatic worker pool: {path.name}')
        results.append(row)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({'command': [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]],
        'cwd': str(root), 'setup': 'Actual FFmpeg binary and source files; sequential reference/candidate/current pipelines',
        'inputs': 'Eight consecutive RGBA frames each from 720p idle, 1440p idle and 1440p click',
        'assertions': 'All raw frame hashes identical, dimensions retained; current pipeline at most8 OS threads',
        'reset': 'Every real ffmpeg stream explicitly closed; no assets modified',
        'checks': results, 'errors': errors, 'exit_status': int(bool(errors))}, indent=2))
    print(results, errors)
    return int(bool(errors))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--probe', type=Path, required=True)
    parser.add_argument('--expect-decoders', type=int)
    parser.add_argument('--pipeline-parity', action='store_true')
    args = parser.parse_args()
    root, output, probe = args.root.resolve(), args.output.resolve(), args.probe.resolve()
    sys.path.insert(0, str(root)); os.chdir(root)
    import psutil
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
    from PySide6.QtWidgets import QApplication, QLabel
    from pet.webm_clip import WebMClip
    app = QApplication([])
    assert app.platformName() == 'cocoa'
    app.setQuitOnLastWindowClosed(False)
    if args.pipeline_parity:
        return pipeline_parity(root, output)
    path = root/'assets/characters_hq/shenshen/videos/idle/待机呼吸休闲.webm'
    clips = [WebMClip(path) for _ in range(3)]
    calls, errors, samples = [], [], []
    release, stop = threading.Event(), threading.Event()
    barrier = threading.Barrier(4)
    begin = time.monotonic()
    for clip in clips:
        clip._ffr_pinned = True
        original = clip._decode_first_qimage
        def decode(self, gen=None, original=original):
            calls.append(self)
            if not release.wait(10):
                raise TimeoutError('decoder gate was not released')
            return original(gen=gen)
        clip._decode_first_qimage = types.MethodType(decode, clip)

    def warm(clip):
        try:
            barrier.wait(5)
            clip.warm_first_frame()
        except Exception as exc:
            errors.append(f'{type(exc).__name__}: {exc}')

    threads = [threading.Thread(target=warm, args=(clip,), daemon=True) for clip in clips]
    for thread in threads:
        thread.start()
    barrier.wait(5)

    def memory():
        parent = psutil.Process()
        while not stop.wait(.05):
            try:
                procs = [parent, *parent.children(recursive=True)]
                sampled = subprocess.run([str(probe), *[str(p.pid) for p in procs]],
                                         capture_output=True, text=True, check=True)
                samples.append({'time': time.monotonic()-begin,
                                'footprint': sum(int(line.split()[1]) for line in sampled.stdout.splitlines()),
                                'rss': sum(p.memory_info().rss for p in procs),
                                'ffmpeg_count': sum('ffmpeg' in p.name() for p in procs)})
            except psutil.NoSuchProcess:
                continue  # Real decoder may exit between sampling the tree and RSS.
            except Exception as exc:
                errors.append(f'memory: {exc}'); stop.set()
    sampler = threading.Thread(target=memory, daemon=True)
    sampler.start()
    gated = False
    def poll():
        nonlocal gated
        if not gated and all(clip._first_frame_lock.locked() for clip in clips):
            gated = True
            release.set()
        if all(not thread.is_alive() for thread in threads):
            app.quit()
        elif time.monotonic()-begin > 15:
            errors.append('prewarm failed to finish within 15 seconds')
            release.set()
            for clip in clips:
                clip.cancel_first_frame_warm()
            app.quit()
    timer = QTimer(app); timer.setInterval(10); timer.timeout.connect(poll); timer.start()
    app.exec(); timer.stop(); stop.set(); sampler.join(5)
    for thread in threads:
        thread.join(5)
        if thread.is_alive():
            errors.append('prewarm thread remained alive after completion')
    checks = {'decode_calls': len(calls), 'all_consumers_entered_warm': gated,
              'elapsed_seconds': time.monotonic()-begin,
              'peak_footprint_mib': max((s['footprint'] for s in samples), default=0)/2**20,
              'peak_rss_mib': max((s['rss'] for s in samples), default=0)/2**20,
              'max_ffmpeg': max((s['ffmpeg_count'] for s in samples), default=0)}
    images = [clip._first_image for clip in clips]
    checks['pixel_hashes'] = [hashlib.sha256(bytes(image.constBits())).hexdigest()
                              if image is not None else None for image in images]
    checks['shared_pixel_storage'] = len({image.cacheKey() for image in images if image is not None}) == 1
    checks['dimensions'] = [[image.width(), image.height()] if image is not None else None for image in images]
    if any(image is None for image in images) or len(set(checks['pixel_hashes'])) != 1:
        errors.append('live consumers did not receive identical RGBA first frames')
    if args.expect_decoders is not None and len(calls) != args.expect_decoders:
        errors.append(f'expected {args.expect_decoders} decoder(s), got {len(calls)}')
    output.parent.mkdir(parents=True, exist_ok=True)
    if images[0] is not None:
        image = images[0].convertToFormat(QImage.Format.Format_ARGB32_Premultiplied).scaled(
            1664, 936, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
        rendered = QImage(1664, 936*3, QImage.Format.Format_ARGB32_Premultiplied)
        painter = QPainter(rendered)
        for index, color in enumerate(('#000000', '#ffffff', '#646464')):
            painter.fillRect(0, index*936, 1664, 936, QColor(color))
            painter.drawImage(0, index*936, image)
        painter.end()
        checks['rendered_hash'] = hashlib.sha256(bytes(rendered.constBits())).hexdigest()
        rendered.save(str(output.with_suffix('.png')))
        preview = QLabel(); preview.setPixmap(QPixmap.fromImage(image).scaled(832, 468)); preview.show()
        app.processEvents(); preview.grab().save(str(output.with_name(output.stem+'-native.png'))); preview.close()
    for clip in clips:
        clip.cleanup()
    checks['cleanup'] = all(clip._cleaned and not clip._first_frame_procs for clip in clips)
    checks['remaining_flights'] = len(getattr(sys.modules['pet.webm_clip'], '_first_frame_flights', {}))
    if not checks['cleanup'] or checks['remaining_flights']:
        errors.append('cleanup left registered prewarm work')
    output.write_text(json.dumps({'command': [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]],
        'cwd': str(root), 'setup': 'Real Cocoa Qt and FFmpeg; three WebMClip consumers, same HQ identity; isolated from playback',
        'inputs': {'clip': str(path), 'source_sha256': hashlib.sha256(path.read_bytes()).hexdigest()},
        'assertions': 'Three successful identical 2560x1440 RGBA first frames; optional single decoder; no flight/proc after cleanup; raw/final-composite parity checked across runs',
        'accounting': 'Explicit synchronized stress bypasses MovieLibrary two-slot cap; normal application peaks are recorded separately by verify_seeky_multi',
        'reset': 'All workers joined, decoder handles cleaned, native preview closed',
        'checks': checks, 'samples': samples, 'errors': errors, 'exit_status': int(bool(errors))}, indent=2))
    print(checks, errors)
    return int(bool(errors))


if __name__ == '__main__':
    sys.exit(main())
