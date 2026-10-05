"""Actual Cocoa/HD-media ceiling attachment at notch, left edge and right edge."""
import argparse
import json
from pathlib import Path
import tempfile
import time

from PySide6.QtCore import QPoint, QRect, QTimer
from PySide6.QtWidgets import QApplication

from pet.app import AppShell
from pet.config import Config
from scripts.verify_seeky7_interactions import drag_to


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--label', default='ceiling-notches')
    parser.add_argument('--output-dir', type=Path, default=Path('docs/evidence/dsr-pet'))
    args = parser.parse_args()
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    checks, errors = {}, []
    fixture = Path(tempfile.mkdtemp(prefix='seeky-ceiling-'))
    cfg = Config(fixture)
    cfg.data.update({'top_flip_enabled': True, 'top_flip_exposure': 0.5, 'codex_link_enabled': False,
                     'no_move': True, 'self_talk_enabled': False, 'harness_autostart': False,
                     'click_sound_enabled': False, 'drag_physics': False})
    cfg.save()
    shell = AppShell(app, cfg, enable_chat=False)
    shell.start()
    win = shell.win
    started = time.monotonic()

    def disabled():
        try:
            if win._top_flip.enabled:
                assert time.monotonic() - started < 15, 'Disable preference did not arrive'
                QTimer.singleShot(100, disabled)
                return
            assert win._effects_current_angle() == 0
            assert win._virtual_pos().y() + win._stable_body_local_rect().top() >= win._screen_available().availableGeometry().top(), 'Disabling ceiling leaves body hidden'
            checks['disabled_body_restored'] = True
        except Exception as exc:
            errors.append(f'{type(exc).__name__}: {exc}')
        app.quit()

    def verify():
        try:
            from pet.ceiling_geometry import screen_notch_rect
            assert app.platformName() == 'cocoa'
            if win._frame_pixmap is None:
                assert time.monotonic() - started < 15, 'HD frame did not arrive'
                QTimer.singleShot(100, verify)
                return
            screen = win._screen_available()
            notch = screen_notch_rect(screen)
            assert notch is not None and notch.height() > 0, 'Current Mac notch was not detected'
            checks['screen'] = list(screen.geometry().getRect())
            checks['notch_geometry'] = list(notch.getRect())
            body = win._stable_body_local_rect()
            timing = []
            for label, center in (('left', 220), ('notch', notch.center().x()), ('right', screen.geometry().right() - 220)):
                win._move_window_towards(center - body.center().x(), screen.geometry().top() + 250 - body.top())
                drag_to(win, QPoint(center - body.center().x(), screen.geometry().top() - body.top()))
                app.processEvents()
                edge = notch.y() + notch.height() if label == 'notch' else screen.availableGeometry().top()
                position = win._virtual_pos()
                checks[label] = {'edge_y': edge, 'window': list(win.geometry().getRect()),
                                 'virtual_position': [position.x(), position.y()], 'body': list(body.getRect()),
                                 'current_body': list(win._stable_body_local_rect().getRect()),
                                 'angle': win._effects_current_angle(), 'offset': win._top_flip.top_offset_px(body.height()),
                                 'reference': win._top_flip.reference_limit(), 'exposure': win.top_flip_exposure}
                assert win._effects_current_angle() == 180
                assert win._top_flip.edge_y == edge, (label, win._top_flip.edge_y, edge)
                assert abs(position.y() + body.top() - (edge - round(body.height() * 0.5))) <= 1, checks[label]
                assert not win._top_flip._timer.isActive()
                initial_position = position
                win._move_window_towards(position.x(), position.y())
                position = win._virtual_pos()
                native_settle = position - initial_position
                assert abs(native_settle.x()) <= 1 and abs(native_settle.y()) <= 1, native_settle
                for _ in range(100):
                    t0 = time.perf_counter()
                    win._move_window_towards(position.x(), position.y())
                    timing.append((time.perf_counter() - t0) * 1000)
                assert win._virtual_pos() == position, 'Repeated ceiling clamp drifted'
                assert win.mask().boundingRect().top() + win.y() >= edge - 1
                visible = win.geometry().intersected(screen.geometry()).translated(-win.pos())
                image = win.grab().toImage()
                dpr = image.devicePixelRatio()
                image.copy(QRect(round(visible.x() * dpr), round(visible.y() * dpr),
                                 round(visible.width() * dpr), round(visible.height() * dpr))).save(str(output / f'ceiling-{label}.png'))
                checks[label] = {'edge_y': edge, 'window': list(win.geometry().getRect()), 'body': list(body.getRect()),
                                 'angle': win._effects_current_angle(), 'exposure': win.top_flip_exposure,
                                 'native_settle_delta': list(native_settle.toTuple()),
                                 'mask_visible_top': win.mask().boundingRect().top() + win.y()}
            checks['300_moves_mean_ms'] = sum(timing) / len(timing)
            checks['300_moves_max_ms'] = max(timing)
            drag_to(win, QPoint(position.x(), screen.geometry().top() + 250 - body.top()))
            assert win._effects_current_angle() == 0
            checks['pull_down_restored'] = True
            drag_to(win, QPoint(position.x(), screen.geometry().top() - body.top()))
            cfg.set('top_flip_enabled', False)
            assert cfg.save()
            QTimer.singleShot(400, disabled)
            return
        except Exception as exc:
            import traceback
            traceback.print_exc()
            errors.append(f'{type(exc).__name__}: {exc}')
        app.quit()

    QTimer.singleShot(500, verify)
    app.exec()
    result = {'command': 'QT_QPA_PLATFORM=cocoa PYTHONPATH=. .venv/bin/python scripts/verify_seeky_ceiling.py --label ' + args.label + ' --output-dir ' + str(output),
              'cwd': str(Path.cwd()), 'setup': 'Fresh temporary config, real Cocoa PetWindow and unchanged HD WebM',
              'reset': 'New config on each run; normal app shutdown closes services',
              'inputs': 'Public threshold mouse drags to left, physical notch and right ceiling; half-body occlusion; 100 repeat placements each; down-drag',
              'assertions': 'Actual notch detected; distinct attachment edge; half body hidden; 180 degrees; matching mask; no drift or running flip timer; pull down restores zero',
              'checks': checks, 'errors': errors, 'exit_status': 1 if errors else 0}
    (output / (args.label + '.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False))
    return result['exit_status']


if __name__ == '__main__':
    raise SystemExit(main())
