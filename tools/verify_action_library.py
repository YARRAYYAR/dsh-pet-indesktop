"""Finite native-window check using real assets and an isolated configuration."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from pet.action_dialog import ActionSetDialog
from pet.app import PetApp
from pet.config import Config
from pet.playlist import read_playlist, write_playlist
from pet.settings_dialog import SettingsDialog


def main():
    output = ROOT / 'verification'
    output.mkdir(exist_ok=True)
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    errors = []
    sys.excepthook = lambda kind, value, tb: errors.append(f'{kind.__name__}: {value}')
    with tempfile.TemporaryDirectory(prefix='pet-action-check-') as base:
        config = Config(base=base)
        config.data.update(sound_enabled=False, proactive_greetings=False)
        controller = PetApp(app, config)
        with patch.object(controller.hotkeys, 'start'):
            controller.start()
        window = controller.win
        names = list(window.lib.names())
        selected = names[:3][::-1]
        editor = ActionSetDialog('编辑播放列表', names, selected, window, allow_exchange=True)
        editor.show()
        settings = SettingsDialog(window)
        checks = []

        def inspect_editor():
            try:
                assert editor.selected_names() == selected
                assert editor.isVisible()
                assert editor.height() <= app.primaryScreen().availableGeometry().height()
                editor.grab().save(str(output / 'action-library-native.png'))
                editor.editor.search.setText(selected[0])
                assert editor.selected_names() == selected
                path = Path(base) / 'playlist.json'
                write_playlist(path, editor.selected_names())
                assert read_playlist(path, names)[0] == selected
                checks.append('native editor visible; saved order, search and JSON round trip passed')
                editor.hide()
                settings.show()
            except Exception as exc:
                errors.append(repr(exc))

        def inspect_settings():
            try:
                assert settings.isVisible()
                assert settings.height() <= app.primaryScreen().availableGeometry().height()
                settings.library.search.setText(selected[0])
                assert not settings.library.catalog_list.item(names.index(selected[0])).isHidden()
                settings.grab().save(str(output / 'action-settings-native.png'))
                assert window.movie.currentFrame() is not None
                checks.append('scrollable settings visible; all-category search and real WebM frame passed')
                toggle = next(action for action in controller.tray.contextMenu().actions()
                    if action.text() == '显示对话框（气泡）')
                before = dict(config.data)
                settings.bubble.setChecked(False)
                settings.sound.setChecked(True)
                settings.volume.setValue(19)
                assert config.data == before, 'Preview must not change saved config through tray signals'
                settings.reject()
                assert window.bubble_enabled == before['bubble_enabled']
                assert window.sound_enabled == before['sound_enabled']
                settings.show()
                toggle.trigger()
                assert not window._bubble_visible and not settings.bubble.isChecked()
                assert Config(base=base).get('bubble_enabled') is False
                toggle.trigger()
                assert window._bubble_visible and settings.bubble.isChecked()
                checks.append('tray bubble toggle syncs settings and persists; hide/show passed')
                for index, title in enumerate(['home', 'library', 'interaction', 'sound', 'settings']):
                    settings.navigation.setCurrentRow(index)
                    app.processEvents()
                    settings.grab().save(str(output / f'control-panel-{title}.png'))
                settings.resize(820, 550)
                settings.navigation.setCurrentRow(1)
                app.processEvents()
                settings.grab().save(str(output / 'control-panel-small.png'))
            except Exception as exc:
                errors.append(repr(exc))
            finally:
                editor.reject()
                settings.reject()
                controller.shutdown()
                app.quit()

        QTimer.singleShot(1800, inspect_editor)
        QTimer.singleShot(3200, inspect_settings)
        QTimer.singleShot(12000, app.quit)
        app.exec()
        report = {'platform': app.platformName(), 'actions': len(names), 'checks': checks, 'errors': errors}
        (output / 'action-library-native.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(json.dumps(report, ensure_ascii=False))
        return int(bool(errors) or len(checks) != 3)


if __name__ == '__main__':
    raise SystemExit(main())
