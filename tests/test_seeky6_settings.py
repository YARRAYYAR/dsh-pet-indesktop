"""Public Qt regressions written before the seeky.6 UI implementation.

Native E2E covers the normal command server. A controllable client is needed
here for late replies, duplicate presses and hide/cancel races: a real local
server replies too quickly to exercise those orderings deterministically.
Failure matrix: refresh resets selection/scroll; pending requests can repeat;
play replies can claim playback before watch; hide/delete leaves callbacks;
failed request cannot retry; navigation destroys focus; hidden/reduced-motion
widgets continue animation; a delayed initial watch snapshot can pretend an
old same-name action is a newly started replay. Expected: preserve, suppress, watch owns current,
cancel all, retry, reuse, and stop/snap respectively.
"""
import pytest
from PySide6.QtCore import QAbstractAnimation, QEvent, Qt, QVariantAnimation
from PySide6.QtWidgets import QApplication, QPushButton


class ControlledClient:
    def __init__(self):
        self.calls = []
        self.cancelled = []

    def request(self, command, args, callback):
        token = object()
        self.calls.append((command, args, callback, token))
        return token

    def cancel(self, token):
        self.cancelled.append(token)

    def reply(self, command, data=None, error=None):
        call = next(call for call in reversed(self.calls) if call[0] == command)
        call[2]({'ok': False, 'error': error} if error else {'ok': True, 'data': data})


def actions():
    return {'actions': [{'name': f'动作{index:03}', 'category': 'idle'} for index in range(60)],
            'current': '动作000'}


def open_library(qtbot, *, register=True):
    from pet.settings_actions import ActionLibrary
    client = ControlledClient()
    library = ActionLibrary(client)
    if register:
        qtbot.addWidget(library)
    library.resize(480, 460)
    library.show()
    client.reply('list_actions', actions())
    client.reply('watch_actions', {'current': '动作000'})
    return library, client


def test_refresh_preserves_visible_selection_and_scroll(qtbot):
    library, client = open_library(qtbot)
    library.list.setCurrentRow(35)
    library.list.scrollToItem(library.list.currentItem())
    scroll = library.list.verticalScrollBar().value()
    library.refresh.click()
    client.reply('list_actions', actions())
    assert library.list.currentItem().data(Qt.ItemDataRole.UserRole) == '动作035'
    assert library.list.verticalScrollBar().value() == scroll


def test_pending_blocks_repeat_and_watch_is_playback_truth(qtbot):
    library, client = open_library(qtbot)
    library.list.setCurrentRow(3)
    library.play.click()
    assert '请求中' in library.status.text()
    library.list.setCurrentRow(4)
    library.list.itemActivated.emit(library.list.currentItem())
    assert len([call for call in client.calls if call[0] == 'play_action']) == 1
    client.reply('play_action', {'requested': '动作003', 'current': '动作003'})
    assert '正在播放' not in library.list.item(3).text()
    assert '当前播放' not in library.list.item(3).text()
    assert '动作004' in library.status.text()  # selected is distinct from queued
    assert '已排队' in library.list.item(3).text()
    client.reply('watch_actions', {'current': '动作003'})
    assert '正在播放' in library.list.item(3).text()
    assert '已排队' not in library.list.item(3).text()


def test_pending_failure_retries_and_hidden_callbacks_are_ignored(qtbot):
    library, client = open_library(qtbot)
    library.play.click()
    client.reply('play_action', error='桌宠暂时没有响应，请重试')
    assert library.play.isEnabled()
    assert '没有响应' in library.status.text()
    library.play.click()
    library.refresh.click()
    pending = [next(call[3] for call in reversed(client.calls) if call[0] == command)
               for command in ('play_action', 'list_actions', 'watch_actions')]
    before = library.list.currentItem().text()
    library.hide()
    assert all(token in client.cancelled for token in pending)
    client.reply('watch_actions', {'current': '动作001'})
    client.reply('play_action', {'requested': '动作000', 'current': '动作000'})
    assert library.list.currentItem().text() == before


@pytest.mark.parametrize('watch_before_ack', (True, False))
def test_initial_watch_snapshot_does_not_complete_same_name_replay(qtbot, watch_before_ack):
    """Separate IPC sockets can deliver list, play, then initial watch late."""
    from pet.settings_actions import ActionLibrary
    client = ControlledClient()
    library = ActionLibrary(client)
    qtbot.addWidget(library)
    library.show()
    client.reply('list_actions', actions())
    library.play.click()  # replay the current action before watch connects
    if watch_before_ack:
        client.reply('watch_actions', {'current': '动作000'})  # old initial snapshot
    client.reply('play_action', {'requested': '动作000', 'current': '动作000'})
    if not watch_before_ack:
        client.reply('watch_actions', {'current': '动作000'})
    assert library._queued == '动作000'
    assert '正在播放' in library.list.item(0).text()
    assert '已排队' in library.list.item(0).text()
    client.reply('watch_actions', {'current': '动作000'})  # new actual playback
    assert library._queued == ''


def test_initial_watch_new_name_can_confirm_play_before_ack(qtbot):
    """A changed initial snapshot is still authoritative playback state."""
    from pet.settings_actions import ActionLibrary
    client = ControlledClient()
    library = ActionLibrary(client)
    qtbot.addWidget(library)
    library.show()
    client.reply('list_actions', actions())
    library.list.setCurrentRow(3)
    library.play.click()
    client.reply('watch_actions', {'current': '动作003'})
    client.reply('play_action', {'requested': '动作003', 'current': '动作003'})
    assert library._current == '动作003'
    assert library._queued == ''


def test_destroy_cancels_every_live_request(qtbot):
    import shiboken6
    library, client = open_library(qtbot, register=False)
    library.play.click()
    library.refresh.click()
    tokens = [next(call[3] for call in reversed(client.calls) if call[0] == command)
              for command in ('play_action', 'list_actions', 'watch_actions')]
    library.deleteLater()
    qtbot.waitUntil(lambda: not shiboken6.isValid(library))
    assert all(token in client.cancelled for token in tokens)


def test_sidebar_reuses_rows_and_keeps_focus(qtbot, tmp_path, monkeypatch):
    from pet import autostart
    from pet.config import Config
    from pet.modern_settings_dialog import ModernSettingsDialog
    monkeypatch.setattr(autostart, 'is_enabled', lambda: False)
    dialog = ModernSettingsDialog(Config(tmp_path), include_ai=False, standalone=True)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.activateWindow()
    qtbot.waitUntil(lambda: QApplication.activeWindow() is dialog)
    headings = dialog.findChildren(QPushButton, 'sidebarDomainHeading')
    target = next(button for button in headings if button.text().startswith('桌宠'))
    target.setFocus()
    target.click()
    assert QApplication.focusWidget() is target
    assert dialog.findChildren(QPushButton, 'sidebarDomainHeading') == headings
    assert dialog.sidebar.currentItem().text() == '桌宠'
    assert dialog.findChild(QPushButton, 'sidebarSubtask') is not None
    assert dialog.findChild(QPushButton, 'sidebarSubtask').icon().isNull()


def test_hidden_and_reduced_motion_snap_to_state(qtbot, monkeypatch):
    from pet import ui_motion
    from pet.settings_navigation import SidebarNavigationButton
    from pet.settings_widgets import ToggleSwitch
    monkeypatch.setattr(ui_motion, 'reduced_motion_requested', lambda: False)
    button = SidebarNavigationButton('桌宠')
    qtbot.addWidget(button)
    button.show()
    QApplication.sendEvent(button, QEvent(QEvent.Type.Enter))
    assert any(animation.state() == QAbstractAnimation.State.Running
               for animation in button.findChildren(QVariantAnimation))
    button.hide()
    assert all(animation.state() == QAbstractAnimation.State.Stopped
               for animation in button.findChildren(QVariantAnimation))
    monkeypatch.setattr(ui_motion, 'reduced_motion_requested', lambda: True)
    switch = ToggleSwitch()
    qtbot.addWidget(switch)
    switch.show()
    switch.setChecked(True)
    assert all(animation.state() == QAbstractAnimation.State.Stopped
               for animation in switch.findChildren(QVariantAnimation))
    assert switch.isChecked()
