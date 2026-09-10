"""Playlist round trips, editor transactions and filtered selection regressions."""

import json
import os
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QApplication, QDialog, QMenu

from pet.action_dialog import ActionSetDialog
from pet.config import Config
from pet.playlist import MAX_PLAYLIST_BYTES, read_playlist, write_playlist
from pet.settings_dialog import SettingsDialog
from tests import test_media_runtime as media_tests


@pytest.fixture(scope='module', autouse=True)
def app():
    instance = QApplication.instance() or QApplication([])
    yield instance


def test_playlist_round_trip_preserves_unicode_order_and_removes_duplicates(tmp_path):
    path = tmp_path / '播放列表.json'
    write_playlist(path, ['转向', '待机', '转向'])
    assert read_playlist(path, ['待机', '转向']) == (['转向', '待机'], [])
    write_playlist(path, [])
    assert read_playlist(path, ['待机']) == ([], [])


@pytest.mark.parametrize('payload', [
    [], {'format': 'other'},
    {'format': 'dsh-pet-playlist', 'version': True, 'actions': []},
    {'format': 'dsh-pet-playlist', 'version': 2, 'actions': []},
    {'format': 'dsh-pet-playlist', 'version': 1, 'actions': [42]},
    {'format': 'dsh-pet-playlist', 'version': 1, 'actions': ['']},
])
def test_invalid_schema_is_rejected(tmp_path, payload):
    path = tmp_path / 'bad.json'
    path.write_text(json.dumps(payload), encoding='utf-8')
    with pytest.raises(ValueError):
        read_playlist(path, ['待机'])


def test_import_limits_size_and_handles_unavailable_names(tmp_path):
    path = tmp_path / 'playlist.json'
    write_playlist(path, ['../outside.webm', '待机'])
    assert read_playlist(path, ['待机']) == (['待机'], ['../outside.webm'])
    with pytest.raises(ValueError, match='没有文件中的动作'):
        read_playlist(path, ['转向'])
    path.write_bytes(b' ' * (MAX_PLAYLIST_BYTES + 1))
    with pytest.raises(ValueError, match='1 MB'):
        read_playlist(path, ['待机'])
    path.write_bytes(b'\xff')
    with pytest.raises(ValueError, match='UTF-8'):
        read_playlist(path, ['待机'])


def test_editor_keeps_saved_order_and_hidden_selections():
    dialog = ActionSetDialog('列表', ['alpha', 'beta', 'gamma'], ['gamma', 'alpha'])
    try:
        assert dialog.selected_names() == ['gamma', 'alpha']
        editor = dialog.editor
        editor.search.setText(' ALPHA ')
        assert editor.catalog_list.item(1).isHidden()
        assert not editor.list_widget.item(0).isHidden()
        assert dialog.selected_names() == ['gamma', 'alpha']
        editor.list_widget.setCurrentRow(1)
        editor.move_current(-1)
        assert dialog.selected_names() == ['alpha', 'gamma']
        editor.search.clear()
        editor.catalog_list.setCurrentRow(1)
        editor.add_selected()
        editor.add_selected()
        editor.sort_name.click()
        assert dialog.selected_names() == ['alpha', 'beta', 'gamma']
    finally:
        dialog.close()


def test_native_model_move_preserves_checks_and_order():
    dialog = ActionSetDialog('列表', ['alpha', 'beta', 'gamma'], ['alpha', 'beta', 'gamma'])
    try:
        model = dialog.editor.list_widget.model()
        assert model.moveRow(model.index(-1, -1), 2, model.index(-1, -1), 0)
        assert dialog.selected_names() == ['gamma', 'alpha', 'beta']
    finally:
        dialog.close()


def test_import_export_operate_on_draft_and_invalid_import_keeps_it(tmp_path):
    path = tmp_path / 'playlist.json'
    write_playlist(path, ['gamma', 'missing', 'alpha'])
    original = ['alpha']
    dialog = ActionSetDialog('列表', ['alpha', 'beta', 'gamma'], original, allow_exchange=True)
    try:
        with patch('pet.action_dialog.QFileDialog.getOpenFileName', return_value=(str(path), '')):
            dialog.editor.import_playlist()
        assert dialog.selected_names() == ['gamma', 'alpha']
        assert 'missing' in dialog.editor.status.text()
        assert original == ['alpha']
        export = tmp_path / 'export.json'
        dialog.editor.search.setText('gamma')
        with patch('pet.action_dialog.QFileDialog.getSaveFileName', return_value=(str(export), '')):
            dialog.editor.export_playlist()
        assert read_playlist(export, ['alpha', 'gamma'])[0] == ['gamma', 'alpha']
        path.write_text('{broken', encoding='utf-8')
        with patch('pet.action_dialog.QFileDialog.getOpenFileName', return_value=(str(path), '')), \
                patch('pet.action_dialog.QMessageBox.warning') as warning:
            dialog.editor.import_playlist()
            warning.assert_called_once()
        assert dialog.selected_names() == ['gamma', 'alpha']
        dialog.reject()
        assert original == ['alpha']
    finally:
        dialog.close()


def test_window_commit_and_cancel_preserve_playback_order(tmp_path):
    harness = media_tests.MediaRuntimeTests()
    with harness.interaction_window() as window:
        with patch.object(window.lib, 'names', return_value=['idle', 'beta']), \
                patch('pet.window.ActionSetDialog') as editor:
            dialog = editor.return_value
            dialog.DialogCode = QDialog.DialogCode
            dialog.exec.return_value = QDialog.DialogCode.Accepted
            dialog.selected_names.return_value = ['beta', 'idle']
            window._edit_action_set('playlist', '播放列表')
            assert window.playlist == ['beta', 'idle']
            assert Config(base=window.cfg.dir.parent).get('playlist') == ['beta', 'idle']
            window._playlist_index = -1
            with patch.object(window, '_switch') as switch:
                window._play_next_playlist()
                window._play_next_playlist()
                assert [call.args[0] for call in switch.call_args_list] == ['beta', 'idle']
            dialog.exec.return_value = QDialog.DialogCode.Rejected
            dialog.selected_names.return_value = []
            window._edit_action_set('playlist', '播放列表')
            assert window.playlist == ['beta', 'idle']


def test_settings_search_includes_all_categories():
    harness = media_tests.MediaRuntimeTests()
    with harness.interaction_window() as window:
        with patch.object(window.lib, 'names', return_value=['待机', '转向', '动作Beta']):
            dialog = SettingsDialog(window)
            try:
                editor = dialog.library
                visible = lambda: [editor.catalog_list.item(i).text() for i in range(editor.catalog_list.count()) if not editor.catalog_list.item(i).isHidden()]
                editor.search.setText('转向')
                assert visible() == ['转向']
                editor.search.setText(' BETA ')
                assert visible() == ['动作Beta']
                editor.search.setText('没有')
                with patch.object(window, '_switch') as switch:
                    editor.preview_current()
                    switch.assert_not_called()
                editor.search.clear()
                assert len(visible()) == 3
            finally:
                dialog.reject()


def test_closed_editors_do_not_accumulate_on_pet_window():
    harness = media_tests.MediaRuntimeTests()
    with harness.interaction_window() as window:
        with patch.object(SettingsDialog, 'exec', return_value=QDialog.DialogCode.Rejected), \
                patch.object(ActionSetDialog, 'exec', return_value=QDialog.DialogCode.Rejected):
            for _ in range(3):
                window.open_settings()
                window._edit_action_set('playlist', '列表')
        QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert not window.findChildren(SettingsDialog)
        assert not window.findChildren(ActionSetDialog)


def test_settings_previews_do_not_save_and_cancel_restores_pause():
    harness = media_tests.MediaRuntimeTests()
    with harness.interaction_window() as window:
        menu = QMenu(window)
        action = window.add_bubble_toggle(menu)
        original = dict(window.cfg.data)
        dialog = SettingsDialog(window)
        with patch.object(window.cfg, 'save') as save:
            dialog.bubble.setChecked(not window.bubble_enabled)
            dialog.sound.setChecked(not window.sound_enabled)
            dialog.volume.setValue(17)
            dialog.pause_button.click()
            assert window._paused
            assert action.isChecked() == dialog.bubble.isChecked()
            dialog.reject()
            save.assert_not_called()
        assert window.cfg.data == original
        assert window._duck_sound.volume == original['volume']
        assert window.bubble_enabled == original['bubble_enabled']
        assert not window._paused


@pytest.mark.parametrize('standalone', [False, True])
def test_cancel_action_preview_restores_hidden_suspended_pet(standalone):
    harness = media_tests.MediaRuntimeTests()
    with harness.interaction_window() as window:
        window.set_paused(True)
        window.suspend_animation()
        window.hide()
        original = window.anim
        if standalone:
            dialog = ActionSetDialog('列表', list(window.lib.names()), [], window)
            dialog._preview(original)
        else:
            dialog = SettingsDialog(window)
            dialog.preview_action(original)
        assert window.isVisible() and not window._suspended and not window._paused
        dialog.reject()
        assert not window.isVisible() and window._suspended and window._paused
        assert window.anim == original
