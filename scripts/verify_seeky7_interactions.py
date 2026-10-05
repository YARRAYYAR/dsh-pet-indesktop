"""Real Qt/WebM interaction acceptance; Cocoa additionally warps the OS pointer."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import tempfile
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6 import __version__ as qt_version
from PySide6.QtCore import QEvent, QEventLoop, QPoint, QPointF, QTimer, Qt
from PySide6.QtGui import QCursor, QMouseEvent, QTransform
from PySide6.QtWidgets import QApplication

from pet import catalog
from pet.app import AppShell
from pet.config import Config


def wait_until(predicate, timeout=10.0):
    """Pump the actual Qt event loop until an observable condition or deadline."""
    loop = QEventLoop()
    timer = QTimer()
    timer.setInterval(10)
    deadline = time.monotonic() + timeout

    def poll():
        if predicate() or time.monotonic() >= deadline:
            loop.quit()

    timer.timeout.connect(poll)
    if not predicate():
        timer.start()
        loop.exec()
        timer.stop()
    assert predicate(), f'Qt condition did not arrive within {timeout}s'


def mouse_event(win, kind, global_point, *, buttons=None):
    button = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseMove else Qt.MouseButton.LeftButton
    if buttons is None:
        buttons = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseButtonRelease else Qt.MouseButton.LeftButton
    event = QMouseEvent(kind, QPointF(win.mapFromGlobal(global_point)), QPointF(global_point),
                        button, buttons, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(win, event)


def drag_to(win, virtual_target, *, release=True):
    body = win._stable_body_local_rect()
    press = win._virtual_pos() + body.center()
    mouse_event(win, QEvent.Type.MouseButtonPress, press)
    assert win._press_global is not None, 'Real mouse press was rejected'
    destination = virtual_target + body.center()
    mouse_event(win, QEvent.Type.MouseMove, destination)
    assert win._dragging, 'Public mouse drag did not cross threshold'
    if not win.drag_physics:
        wait_until(lambda: win._drag_move_pending is None)
    if release:
        mouse_event(win, QEvent.Type.MouseButtonRelease, destination)
    return destination


def body_center(win):
    """Independent forward transform using the same documented paint pivot."""
    body = win._stable_body_local_rect().translated(win._draw_delta)
    pivot = win._effects_rotation_rect(win._frame_draw_rect()).center()
    transform = QTransform()
    transform.translate(pivot.x(), pivot.y())
    transform.rotate(win._effects_current_angle())
    transform.translate(-pivot.x(), -pivot.y())
    center = transform.map(QPointF(body.center()))
    return QPoint(round(win.x() + center.x()), round(win.y() + center.y()))


def image_digest(win):
    image = win.grab().toImage()
    return hashlib.sha256(image.constBits()).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--label', default='seeky7-interactions')
    parser.add_argument('--output-dir', type=Path, default=Path('/tmp/seeky7-runtime-evidence'))
    parser.add_argument('--section', choices=('all', 'ceiling', 'cursor'), default='all')
    args = parser.parse_args(argv)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    original_cursor = QCursor.pos()
    fixture = Path(tempfile.mkdtemp(prefix='seeky7-interactions-'))
    config = Config(fixture)
    config.data.update({'top_flip_enabled': True, 'top_flip_exposure': 0.5,
                        'no_move': True, 'self_talk_enabled': False,
                        'idle_low_fps_enabled': False, 'codex_link_enabled': False,
                        'harness_autostart': False, 'click_sound_enabled': False,
                        'drag_physics': False, 'edge_probe_enabled': False,
                        'media_prewarm': 'minimal',
                        'golden_spin_enabled': False, 'collision_enabled': False})
    config.save()
    shell = AppShell(app, config, enable_chat=False)
    shell.start()
    win = shell.win
    rows, errors = [], []

    def persist(exit_status=None):
        record = {'command': f'QT_QPA_PLATFORM={app.platformName()} PYTHONPATH=. {sys.executable} scripts/verify_seeky7_interactions.py --section {args.section} --label {args.label} --output-dir {args.output_dir}',
                  'cwd': str(ROOT), 'qt_version': qt_version, 'python_version': sys.version,
                  'platform': app.platformName(), 'config_directory': str(fixture),
                  'setup': 'Fresh temporary Config with minimal prewarm, actual AppShell/PetWindow and original HD WebM. Qt mouse events enter QWidget publicly; native pointer cases use real QCursor.setPos. Stop the clip publication timer to hold an actually decoded frame for mirror hash comparison; stop() would clear its display slot.',
                  'inputs': 'Automatic ceiling placement/throw/collision; threshold click, preview, manual snap/down-drag/cancel/disable/hide/close; four edges at two scales, actual ±45 probes and manual 180 inversion; dead zone/range/no_mirror.',
                  'assertions': 'Only manual drag attaches. Normal automatic bounds/offset/angle. Cursor preserves body position and produces expected actual rendered image, not merely facing field.',
                  'reset': 'Close temporary AppShell; restore original OS pointer; no installed app/config or media modifications.',
                  'checks': rows, 'errors': errors, 'exit_status': exit_status,
                  'evidence_valid': exit_status == 0, 'in_progress': exit_status is None}
        (args.output_dir / f'{args.label}.json').write_text(json.dumps(record, ensure_ascii=False, indent=2))
        return record

    def check(name, action):
        try:
            result = action() or {}
            rows.append({'case': name, 'pass': True, **result})
        except Exception as exc:
            errors.append({'case': name, 'error': f'{type(exc).__name__}: {exc}', 'traceback': traceback.format_exc()})
            rows.append({'case': name, 'pass': False})
        persist()

    def settle():
        win._stop_physics()
        win._cancel_move()
        win._cancel_animation_gap()
        if win.movie.currentPixmap() is None:
            win.movie.start()
            wait_until(lambda: win.movie.currentPixmap() is not None)
        # Hold the decoded frame by pausing its Qt publication timer. stop()
        # clears the display slot, and jumpToFrame(0) needs an evictable cache.
        # The real reader/queue remains owned by AppShell and closes normally.
        win.movie._timer.stop()
        win._rebuild_frame()

    def central():
        win._top_flip.cancel('fixture-reset')
        win._edge_probe.cancel('fixture-reset', restore=False)
        win._reset_press_hold_state()
        win._top_flip.set_enabled(True)
        if config.get('edge_probe_enabled', False):
            config.set('edge_probe_enabled', False)
            config.save()
        win._edge_probe.set_enabled(False)
        settle()
        body = win._stable_body_local_rect()
        avail = win._screen_available().availableGeometry()
        win._move_window_towards(avail.center().x() - body.center().x(),
                                 avail.center().y() - body.center().y())
        return body, avail

    def attach():
        body, avail = central()
        x = avail.center().x() - body.center().x()
        drag_to(win, QPoint(x, avail.top() - body.top()))
        assert win._effects_current_angle() == 180
        assert getattr(win._top_flip, 'manually_attached', False)
        assert not getattr(win._top_flip, 'manual_drag_active', False)
        assert win._physics_mode is None
        return body, avail

    def automatic():
        body, avail = central()
        x = avail.center().x() - body.center().x()
        win._move_window_towards(x, avail.top() - body.top() - 150)
        assert win._effects_current_angle() == 0, 'Automatic placement inverted'
        assert win._virtual_pos().y() + body.top() == avail.top(), 'Automatic top bounds/offset changed'
        assert win._top_flip.top_offset_px(body.height()) == 0
        assert not getattr(win._top_flip, 'manually_attached', False)
        return {'angle': win._effects_current_angle(), 'virtual': list(win._virtual_pos().toTuple())}

    def click():
        body, avail = central()
        win._move_window_towards(win._virtual_pos().x(), avail.top() - body.top())
        point = win._virtual_pos() + body.center()
        mouse_event(win, QEvent.Type.MouseButtonPress, point)
        mouse_event(win, QEvent.Type.MouseMove, point + QPoint(1, 1))
        mouse_event(win, QEvent.Type.MouseButtonRelease, point + QPoint(1, 1))
        assert win._effects_current_angle() == 0, 'Click gained manual ceiling eligibility'
        assert not getattr(win._top_flip, 'manually_attached', False)

    def preview():
        body, avail = central()
        point = drag_to(win, QPoint(win._virtual_pos().x(), avail.top() - body.top() + 70), release=False)
        assert 0 < win._effects_current_angle() < 180
        assert getattr(win._top_flip, 'manual_drag_active', False)
        mouse_event(win, QEvent.Type.MouseButtonRelease, point)
        assert win._effects_current_angle() == 0, 'Release outside 40px snap retained preview'
        assert not getattr(win._top_flip, 'manually_attached', False)
        assert win._virtual_pos().y() + body.top() >= avail.top()

    def manual():
        body, avail = attach()
        actual_top = win._virtual_pos().y() + body.top()
        expected_top = win._top_flip.edge_y - round(body.height() * 0.5)
        assert abs(actual_top - expected_top) <= 1, (actual_top, expected_top, win.pos(), win._draw_delta)
        initial_position = win._virtual_pos()
        win._move_window_towards(initial_position.x(), initial_position.y())
        position = win._virtual_pos()
        native_settle = position - initial_position
        assert abs(native_settle.x()) <= 1 and abs(native_settle.y()) <= 1, native_settle
        placements = [list(position.toTuple())]
        for _ in range(20):
            win._move_window_towards(position.x(), position.y())
            placements.append(list(win._virtual_pos().toTuple()))
        assert win._virtual_pos() == position, (position, win._virtual_pos(), placements)
        assert not win._top_flip._timer.isActive()
        win.grab().save(str(args.output_dir / f'{args.label}-manual.png'))
        drag_to(win, QPoint(position.x(), avail.top() - body.top() + 220))
        assert win._effects_current_angle() == 0
        assert not getattr(win._top_flip, 'manually_attached', False)
        return {'initial_position': list(initial_position.toTuple()),
                'settled_position': list(position.toTuple()),
                'native_settle_delta': list(native_settle.toTuple()),
                'repeat_positions': placements}

    def snap_offset(drag_physics):
        body, avail = central()
        config.set('drag_physics', drag_physics)
        config.save()
        win.drag_physics = drag_physics
        try:
            target = QPoint(win._virtual_pos().x(), avail.top() - body.top() + 30)
            point = drag_to(win, target, release=False)
            if drag_physics:
                wait_until(lambda: abs(win._phys_pos[1] - target.y()) < 0.5,
                           timeout=10)
            preview_angle = win._effects_current_angle()
            assert 0 < preview_angle < 180
            assert win._top_flip.manual_drag_active
            mouse_event(win, QEvent.Type.MouseButtonRelease, point)
            assert win._top_flip.manually_attached
            assert not win._top_flip.manual_drag_active
            assert win._effects_current_angle() == 180
            assert win._physics_mode is None
            expected_y = win._top_flip.reference_limit() - win._top_flip.top_offset_px(body.height())
            actual_y = win._virtual_pos().y()
            assert abs(actual_y - expected_y) <= 1, (actual_y, expected_y, preview_angle)
            return {'drag_physics': drag_physics, 'target': list(target.toTuple()),
                    'preview_angle': preview_angle, 'release_angle': win._effects_current_angle(),
                    'actual_y': actual_y, 'expected_y': expected_y}
        finally:
            win._stop_physics()
            config.set('drag_physics', False)
            config.save()
            win.drag_physics = False

    def throw():
        body, avail = attach()
        win._enter_physics_mode('throw')
        assert win._effects_current_angle() == 0, 'Automatic flight retained ceiling pose'
        assert not getattr(win._top_flip, 'manually_attached', False)
        assert win._virtual_pos().y() + body.top() >= avail.top()
        win._move_window_towards(win._virtual_pos().x(), avail.top() - body.top() - 100)
        assert win._effects_current_angle() == 0
        assert win._virtual_pos().y() + body.top() == avail.top()
        win._stop_physics()

    def collision():
        body, avail = attach()
        xy = win._collision_clamp_pos(win._virtual_pos().x(), avail.top() - body.top() - 100)
        win._move_window_towards(*xy)
        assert win._effects_current_angle() == 0, 'Collision displacement retained ceiling pose'
        assert not getattr(win._top_flip, 'manually_attached', False)

    def cancel():
        body, avail = central()
        drag_to(win, QPoint(win._virtual_pos().x(), avail.top() - body.top() + 70), release=False)
        win._reset_press_hold_state()
        assert win._effects_current_angle() == 0
        assert not getattr(win._top_flip, 'manual_drag_active', False)
        assert not getattr(win._top_flip, 'manually_attached', False)

    def hidden():
        attach()
        win.hide()
        assert not win._top_flip._timer.isActive()
        assert not win._cursor_facing_timer.isActive()
        win.show()
        assert win._effects_current_angle() == 180
        assert getattr(win._top_flip, 'manually_attached', False)
        assert not getattr(win._top_flip, 'manual_drag_active', False)

    def disabled():
        body, avail = attach()
        win._top_flip.set_enabled(False)
        assert win._effects_current_angle() == 0
        assert win._virtual_pos().y() + body.top() >= avail.top()
        assert not getattr(win._top_flip, 'manually_attached', False)

    def cursor_case(label, offset, before='left', keep=False):
        settle()
        center = body_center(win)
        requested = center + offset
        # Clamp only vertical sample location into the real screen. The original
        # horizontal dx remains the acceptance input for edge and inverted poses.
        screen = win._screen_available().geometry()
        requested.setY(max(screen.top(), min(screen.bottom(), requested.y())))
        expected = before
        if not keep:
            screen_facing = 'right' if offset.x() > 0 else 'left'
            inverted = math.cos(math.radians(win._effects_current_angle())) < 0
            expected = ('left' if screen_facing == 'right' else 'right') if inverted else screen_facing
        win.facing = expected
        win._rebuild_frame()
        expected_render = image_digest(win)
        win.facing = before
        win._rebuild_frame()
        before_render = image_digest(win)
        position = win._virtual_pos()
        QCursor.setPos(requested)
        try:
            wait_until(lambda: QCursor.pos() == requested, timeout=3)
        except AssertionError as exc:
            actual_cursor = QCursor.pos()
            raise AssertionError(('OS pointer placement', requested, actual_cursor,
                                  actual_cursor - requested)) from exc
        timer = QTimer()
        samples = []
        timer.setInterval(catalog.CURSOR_POLL_MS)
        timer.timeout.connect(lambda: samples.append(win.facing))
        timer.start()
        wait_until(lambda: len(samples) >= 3, timeout=5)
        timer.stop()
        actual_render = image_digest(win)
        win.grab().save(str(args.output_dir / f'{args.label}-{label}.png'))
        assert win._virtual_pos() == position, 'Cursor moved the body'
        assert win.facing == expected, (label, center, requested, win.facing, expected)
        assert actual_render == expected_render, 'Actual rendered direction disagreed with expected mirror/rotation'
        if not keep and expected != before and win.anim not in win.lib.no_mirror:
            assert actual_render != before_render, 'Facing changed but rendered image did not'
        return {'center': list(center.toTuple()), 'cursor': list(requested.toTuple()),
                'angle': win._effects_current_angle(), 'scale': win.scale,
                'draw_delta': list(win._draw_delta.toTuple()), 'facing': win.facing,
                'render_hash': actual_render, 'expected_render_hash': expected_render}

    persist()
    try:
        wait_until(lambda: win._frame_pixmap is not None and not win._frame_pixmap.isNull(), timeout=20)
        if args.section in ('all', 'ceiling'):
            for name, action in (('automatic-ceiling', automatic), ('click-no-eligibility', click),
                                 ('preview-release-outside-snap', preview), ('manual-snap-and-down', manual),
                                 ('snap-offset-plain-drag', lambda: snap_offset(False)),
                                 ('snap-offset-physics-drag', lambda: snap_offset(True)),
                                 ('flight-detaches', throw), ('collision-detaches', collision),
                                 ('cancel-drag-clears-preview', cancel), ('hide-resume-keeps-attachment', hidden),
                                 ('disable-restores-offset', disabled)):
                check(name, action)
        if args.section in ('all', 'cursor'):
            assert app.platformName() == 'cocoa', 'Native cursor acceptance requires Cocoa'
            for scale in (0.7, 1.3):
                central()
                win.change_scale(scale)
                body, avail = central()
                positions = {'left': QPoint(avail.left() - body.left(), avail.center().y() - body.center().y()),
                             'right': QPoint(avail.right() + 1 - body.right() - 1, avail.center().y() - body.center().y()),
                             'top': QPoint(avail.center().x() - body.center().x(), avail.top() - body.top()),
                             'bottom': QPoint(avail.center().x() - body.center().x(), avail.bottom() - body.bottom())}
                for edge, position in positions.items():
                    win._move_window_towards(position.x(), position.y())
                    offset = -70 if edge == 'right' else 70
                    check(f'cursor-{scale}-{edge}', lambda e=edge, o=offset: cursor_case(f'{scale}-{e}', QPoint(o, 0), before='left' if o > 0 else 'right'))
                central()
                check(f'cursor-{scale}-deadzone', lambda: cursor_case(f'{scale}-deadzone', QPoint(0, 0), keep=True))
                check(f'cursor-{scale}-outside', lambda: cursor_case(f'{scale}-outside', QPoint(0, 320), keep=True))
                attach()
                check(f'cursor-{scale}-inverted-left', lambda: cursor_case(f'{scale}-inverted-left', QPoint(-70, 0), before='left'))
                check(f'cursor-{scale}-inverted-right', lambda: cursor_case(f'{scale}-inverted-right', QPoint(70, 0), before='right'))
                for edge in ('left', 'right'):
                    body, avail = central()
                    config.set('edge_probe_enabled', True)
                    config.save()
                    win._edge_probe.set_enabled(True)
                    target = QPoint(avail.left() - body.left() if edge == 'left' else avail.right() - body.right(), avail.center().y() - body.center().y())
                    drag_to(win, target)
                    try:
                        wait_until(lambda: win._edge_probe.mode == 'PEEKING', timeout=5)
                    except AssertionError as exc:
                        raise AssertionError((edge, win._edge_probe.mode, win._edge_probe.enabled,
                                              win._edge_probe._hidden, win._virtual_pos(), body, avail)) from exc
                    offset = 70 if edge == 'left' else -70
                    check(f'cursor-{scale}-{edge}-probe', lambda e=edge, o=offset: cursor_case(f'{scale}-{e}-probe', QPoint(o, 0), before='left' if o > 0 else 'right'))
            central()
            mirrorless = next(iter(win.lib.no_mirror), None)
            if mirrorless is not None:
                win._switch(mirrorless)
                wait_until(lambda: win.anim == mirrorless and win._frame_pixmap is not None)
                check('cursor-no-mirror', lambda: cursor_case('no-mirror', QPoint(70, 0), before='left'))
            else:
                rows.append({'case': 'cursor-no-mirror', 'pass': True, 'note': 'Default character has no no_mirror animation'})
        win._top_flip.cancel('end')
        win.close()
        assert not getattr(win._top_flip, 'manually_attached', False)
        assert not getattr(win._top_flip, 'manual_drag_active', False)
        rows.append({'case': 'close-clears-state', 'pass': True})
    except Exception as exc:
        errors.append({'case': 'harness', 'error': f'{type(exc).__name__}: {exc}', 'traceback': traceback.format_exc()})
    finally:
        QCursor.setPos(original_cursor)
        win.close()
        QTimer.singleShot(0, app.quit)
        app.exec()  # Production aboutToQuit stops the real IPC worker before destruction.
    record = persist(int(bool(errors)))
    print(json.dumps(record, ensure_ascii=False))
    return record['exit_status']


if __name__ == '__main__':
    raise SystemExit(main())
