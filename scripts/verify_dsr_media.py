"""Compare full-quality WebM delivery and Retina rendering across source trees."""
import argparse
import hashlib
import json
from pathlib import Path
import queue
import sys
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.root.resolve()))
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QApplication
    from pet.webm_clip import WebMClip

    app = QApplication([])
    results = []
    started = time.monotonic()
    for path in sorted((args.root / 'assets/characters').rglob('*.webm')):
        movie = WebMClip(path)
        errors = []
        movie.errorOccurred.connect(errors.append)
        raw_hash = hashlib.sha256()
        retina_hash = hashlib.sha256()
        count = 0
        assert movie.start(), str(path)
        movie._timer.stop()
        try:
            while True:
                try:
                    item = movie._queue.get(timeout=30)
                except queue.Empty:
                    raise RuntimeError(f'{path}: decoder did not deliver a frame') from None
                if item is None:
                    break
                data, index = item
                assert index == count, (path, index, count)
                movie._process_frame(item)
                image = movie.currentImage()
                assert image.size().width() == 1280 and image.size().height() == 720
                assert bytes(image.constBits()) == data, (path, index, 'changed RGBA')
                raw_hash.update(data)
                rendered = image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
                rendered = rendered.scaled(1088, 612, Qt.AspectRatioMode.IgnoreAspectRatio,
                                           Qt.TransformationMode.SmoothTransformation)
                retina_hash.update(bytes(rendered.constBits()))
                count += 1
            assert not errors, errors
            assert count == movie.frameCount(), (path, count, movie.frameCount())
            results.append({'path': str(path.relative_to(args.root)), 'frames': count,
                            'fps': movie._fps, 'duration': movie._duration,
                            'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                            'rgba_sha256': raw_hash.hexdigest(),
                            'retina_sha256': retina_hash.hexdigest()})
            print(len(results), path.stem, count, flush=True)
        finally:
            movie.cleanup()
            app.processEvents()
    args.output.write_text(json.dumps({'root': str(args.root), 'clips': results,
                                      'seconds': time.monotonic() - started},
                                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
