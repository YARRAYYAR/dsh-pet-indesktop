"""Finite Cocoa drag check with real media and silent spring-follow feedback."""

import json
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QEvent, QPoint, QPointF, QTimer, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from pet.app import PetApp
from pet.config import Config


def main():
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    errors, samples = [], []
    sound_status = {}
    sys.excepthook = lambda kind, value, tb: errors.append(f'{kind.__name__}: {value}')
    with tempfile.TemporaryDirectory(prefix='pet-rebound-') as base:
        config = Config(base=base)
        config.data.update(sound_enabled=True, volume=20, proactive_greetings=False)
        controller = PetApp(app, config)
        with patch.object(controller.hotkeys, 'start'):
            controller.start()
        window = controller.win
        window.drag_physics = True
        window.move(200, 180)
        target_x = None
        started = None
        timer = QTimer()
        deadline = time.monotonic() + 12

        def mouse(kind, global_point):
            return QMouseEvent(kind, QPointF(window.mapFromGlobal(global_point)), QPointF(global_point),
                Qt.MouseButton.LeftButton if kind == QEvent.Type.MouseButtonPress else Qt.MouseButton.NoButton,
                Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)

        def begin():
            nonlocal target_x, started
            try:
                if window.movie is None or window.movie.currentFrame() is None or window.mask().isEmpty():
                    assert time.monotonic() < deadline, 'video frame did not become ready'
                    QTimer.singleShot(100, begin)
                    return
                point = next(QPoint(x, y) for y in range(0, window.height(), 3)
                    for x in range(0, window.width(), 3)
                    if window._is_in_interactive_area(QPoint(x, y)) and not window._bubble_hit_test(QPoint(x, y)))
                origin = window.mapToGlobal(point)
                window.mousePressEvent(mouse(QEvent.Type.MouseButtonPress, origin))
                window.mouseMoveEvent(mouse(QEvent.Type.MouseMove, origin + QPoint(40, 0)))
                window.mouseMoveEvent(mouse(QEvent.Type.MouseMove, origin + QPoint(180, 0)))
                target_x = window._drag_target.x()
                started = time.monotonic()
                timer.start(8)
                QTimer.singleShot(2400, finish)
            except Exception as exc:
                errors.append(repr(exc))
                finish()

        def sample():
            # `_phys_pos` is the physics authority; macOS may report the native
            # window frame one event behind while the spring is settling.
            samples.append((time.monotonic() - started, window._phys_pos[0]))

        def finish():
            try:
                assert target_x is not None and samples
                assert max(x for _, x in samples) > target_x + 10
                assert abs(window._phys_pos[0] - target_x) < 4
                process = window._bounce_sound._process
                sound_status.update(enabled=window._bounce_sound.enabled, volume=window._bounce_sound.volume,
                    drag_silent=process is None or process.poll() is not None,
                    file_exists=window._bounce_sound.path.exists())
                assert sound_status['drag_silent'], sound_status
                assert window.movie.currentFrame() is not None
                window._bounce_sound._ensure_wave()
                (ROOT / 'verification/bounce-pop-preview.wav').write_bytes(window._bounce_sound.path.read_bytes())
            except Exception as exc:
                errors.append(repr(exc))
            timer.stop()
            controller.shutdown()
            app.quit()

        timer.timeout.connect(sample)
        QTimer.singleShot(1200, begin)
        QTimer.singleShot(16000, app.quit)
        app.exec()
        report = {'platform': app.platformName(), 'target_x': target_x,
            'peak_x': max((x for _, x in samples), default=None),
            'final_x': samples[-1][1] if samples else None,
            'native_x': window.x() if window is not None else None,
            'samples': len(samples), 'sound': sound_status, 'errors': errors}
        (ROOT / 'verification/drag-rebound-native.json').write_text(json.dumps(report, indent=2))
        print(json.dumps(report))
        return int(bool(errors) or not samples)


if __name__ == '__main__':
    raise SystemExit(main())
