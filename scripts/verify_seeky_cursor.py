"""Native Cocoa E2E for cursor-facing direction, dead zone and range."""
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6 import __version__ as qt_version
from PySide6.QtCore import QPoint, QTimer, Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from pet import catalog
from pet.app import AppShell
from pet.config import Config


def main():
    output = ROOT / 'docs/evidence/seeky4-quality/cursor-facing.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    assert app.platformName() == 'cocoa'
    original_cursor = QCursor.pos()
    config = Config(Path(tempfile.mkdtemp(prefix='seeky-cursor-')))
    config.data.update({'no_move': True, 'facing': 'right', 'mouse_through': True,
                        'idle_low_fps_enabled': False, 'self_talk_enabled': False,
                        'codex_link_enabled': False, 'harness_autostart': False,
                        'top_flip_enabled': False, 'click_sound_enabled': False})
    config.save()
    shell = AppShell(app, config, enable_chat=False)
    shell.start()
    pet = shell.win
    pet.setWindowFlag(Qt.WindowType.WindowTransparentForInput, True)
    pet.show()
    screen = app.primaryScreen().geometry()
    center = screen.center()
    pet.move(center.x() - pet.width() // 2, center.y() - pet.height() // 2)

    panel = QWidget()
    panel.setWindowTitle('seeky· pet 鼠标朝向验收')
    panel.setFixedSize(900, 150)
    panel.move(center.x() - 450, center.y() - 75)
    layout = QVBoxLayout(panel)
    status = QLabel('正在自动移动系统指针测试桌宠朝向，完成后会恢复指针位置。', panel)
    layout.addWidget(status)
    results, errors = [], []
    cases = (
        ('范围外左', -320, 'right', None),
        ('左侧', -140, 'right', 'left'),
        ('死区', 0, 'left', None),
        ('右侧', 140, 'left', 'right'),
        ('范围外右', 320, 'left', None),
    )
    case_index = 0

    def persist(exit_status=None):
        record = {'command': [sys.executable, str(Path(__file__).resolve())],
                  'cwd': str(Path.cwd()),
                  'setup': 'Fresh temporary config; real Cocoa AppShell; cursor-transparent native pet window',
                  'inputs': 'Five QCursor.setPos OS pointer moves relative to the pet center: -320,-140,0,+140,+320 px; the original global position is restored at completion',
                  'assertions': f'{catalog.CURSOR_POLL_MS}ms mouse polling; radius {catalog.CURSOR_REACTION_RADIUS} logical pixels; horizontal dead zone {catalog.CURSOR_DEAD_ZONE}; left/right update facing, center/outside preserve facing',
                  'reset': 'Temporary config; AppShell pet window closes; original global cursor position restored; no user preferences written',
                  'qt_version': qt_version,
                  'checks': results, 'errors': errors,
                  'evidence_valid': False if exit_status is None else not errors,
                  'exit_status': exit_status,
                  'in_progress': exit_status is None}
        output.write_text(json.dumps(record, ensure_ascii=False, indent=2))
        return record

    persist()

    def start_next_sample():
        nonlocal case_index
        if case_index == len(cases):
            QTimer.singleShot(200, finish)
            return
        name, offset, initial_facing, target = cases[case_index]
        case_index += 1
        center_x = round(pet.x() + pet._w / 2)
        center_y = round(pet.y() + pet._h / 2)
        requested_cursor = QPoint(center_x + offset, center_y)
        pet.facing = initial_facing
        pet._rebuild_frame()
        QCursor.setPos(requested_cursor)
        # macOS applies a cursor warp after the current event turn; sample it
        # after yielding so we do not mistake the previous point for this one.
        QTimer.singleShot(80, lambda: sample_input(
            name, offset, target, initial_facing, requested_cursor,
        ))

    def sample_input(name, offset, target, initial_facing, requested_cursor):
        cursor = QCursor.pos()
        QTimer.singleShot(
            catalog.CURSOR_POLL_MS * 3,
            lambda: finish_sample(name, offset, cursor, target,
                                  initial_facing, requested_cursor),
        )

    def finish_sample(name, offset, cursor, target, before, requested_cursor):
        actual = pet.facing
        expected = before if target is None else target
        pointer_moved = cursor == requested_cursor
        passed = pointer_moved and actual == expected
        row = {'input': name, 'cursor': [cursor.x(), cursor.y()],
               'requested_cursor': [requested_cursor.x(), requested_cursor.y()],
               'offset_from_pet_center': offset,
               'window_center': [pet.x() + pet._w/2, pet.y() + pet._h/2],
               'requested_facing': target, 'before': before, 'actual': actual,
               'expected': expected, 'cursor_moved': pointer_moved, 'pass': passed}
        results.append(row)
        if not passed:
            errors.append(row)
        status.setText(f"{name}: cursor={cursor.x()},{cursor.y()}  朝向={actual}  "
                       f"{'通过' if passed else '失败，期望 ' + (expected or '保持当前方向')}")
        persist()
        QTimer.singleShot(80, start_next_sample)

    def finish():
        if len(results) != len(cases):
            errors.append(f"expected {len(cases)} pointer positions, observed {len(results)}")
        record = persist(int(bool(errors)))
        shell.win.close()
        panel.close()
        QCursor.setPos(original_cursor)
        print(json.dumps(record, ensure_ascii=False))
        app.quit()
    panel.show()
    panel.raise_()
    pet.raise_()
    QTimer.singleShot(600, start_next_sample)
    QTimer.singleShot(15000, finish)
    app.exec()
    return int(bool(errors))


if __name__ == '__main__':
    sys.exit(main())
