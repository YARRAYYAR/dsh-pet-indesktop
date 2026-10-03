import json
import os
import sys

from PySide6.QtCore import QAbstractAnimation, QProcess
from PySide6.QtWidgets import QLabel, QPushButton


def test_commands_cross_process_and_are_instance_isolated(qtbot, tmp_path):
    from pet.config import Config
    from pet.settings_commands import SettingsCommandClient

    script = '''
import sys
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from pet.config import Config
from pet.settings_commands import SettingsCommandServer
app = QApplication([])
config = Config(sys.argv[1], instance_id='slot-3')
def handle(command, args):
    if command == 'list_actions':
        return {'actions': [{'name': '待机', 'category': 'idle'}], 'current': '待机'}
    if command == 'watch_actions':
        QTimer.singleShot(100, lambda: server.publish_action('挥手'))
        return {'current': '待机'}
    if command == 'quit':
        QTimer.singleShot(100, app.quit)
        return {}
    raise ValueError('未知命令')
server = SettingsCommandServer(config, handle, app)
app.aboutToQuit.connect(server.close)
print('ready', flush=True)
sys.exit(app.exec())
'''
    process = QProcess()
    process.start(sys.executable, ['-c', script, str(tmp_path)])
    output = bytearray()

    def ready():
        output.extend(bytes(process.readAllStandardOutput()))
        return b'ready' in output

    try:
        qtbot.waitUntil(ready, timeout=15000)
        client = SettingsCommandClient(Config(tmp_path, instance_id='slot-3'))
        responses = []
        client.request('list_actions', {}, responses.append)
        qtbot.waitUntil(lambda: bool(responses), timeout=5000)
        assert responses[-1]['data']['current'] == '待机'
        other = SettingsCommandClient(Config(tmp_path, instance_id='slot-4'))
        other.request('list_actions', {}, responses.append)
        qtbot.waitUntil(lambda: len(responses) == 2, timeout=5000)
        assert not responses[-1]['ok']
        updates = []
        watch = client.request('watch_actions', {}, updates.append)
        qtbot.waitUntil(lambda: len(updates) == 2, timeout=5000)
        assert [update['data']['current'] for update in updates] == ['待机', '挥手']
        client.cancel(watch)
        client.request('quit', {}, responses.append)
        qtbot.waitUntil(lambda: process.state() == QProcess.ProcessState.NotRunning,
                        timeout=5000)
        assert process.exitCode() == 0
        client.close()
        other.close()
    finally:
        if process.state() != QProcess.ProcessState.NotRunning:
            process.kill()
            process.waitForFinished(5000)


def test_brand_navigation_and_native_minimum_size(qtbot, tmp_path, monkeypatch):
    from pet.config import Config
    from pet.modern_settings_dialog import ModernSettingsDialog
    from pet import autostart

    monkeypatch.setattr(autostart, 'is_enabled', lambda: False)
    dialog = ModernSettingsDialog(Config(tmp_path), include_ai=False, standalone=True)
    qtbot.addWidget(dialog)
    dialog.resize(720, 500)
    dialog.show()
    assert 'seeky· pet' in dialog.windowTitle()
    assert '文件识别' not in [dialog.sidebar.item(i).text() for i in range(dialog.sidebar.count())]
    assert dialog.property('settingsDark') is True
    assert not dialog.windowIcon().isNull()
    assert dialog.findChildren(QLabel, 'pageDescription')
    pet_row = next(i for i in range(dialog.sidebar.count())
                   if dialog.sidebar.item(i).text() == '桌宠')
    dialog.sidebar.setCurrentRow(pet_row)
    children = dialog.findChildren(QPushButton, 'sidebarSubtask')
    assert {'常用控制', '动作库'} <= {button.text() for button in children}
    assert all(button.icon().isNull() for button in children)
    assert dialog.quit_button.isVisible()
    assert dialog.quit_button.geometry().bottom() < dialog.height()
    dialog.resize(1000, 680)
    next(button for button in children if button.text() == '动作库').click()
    from pet.settings_actions import ActionLibrary
    from PySide6.QtCore import QPoint
    library = dialog.findChild(ActionLibrary)
    qtbot.waitUntil(lambda: library.play.mapTo(dialog, QPoint(0, 0)).y() < dialog.height())
    assert library.list.maximumHeight() == 260


def test_switch_animation_stops_and_can_reverse(qtbot):
    from pet.settings_widgets import ToggleSwitch

    switch = ToggleSwitch()
    qtbot.addWidget(switch)
    switch.show()
    switch.setChecked(True)
    switch.setChecked(False)
    qtbot.waitUntil(lambda: switch._motion.state() == QAbstractAnimation.State.Stopped)
    assert switch._progress == 0.0
    switch.setChecked(True)
    qtbot.waitUntil(lambda: switch._motion.state() == QAbstractAnimation.State.Stopped)
    assert switch._progress == 1.0


def test_removed_island_does_not_return_from_legacy_config(qtbot, tmp_path):
    from pet.app import AppShell
    from pet.config import Config
    from pet.modern_settings_dialog import ModernSettingsDialog
    from pet.settings_widgets import SettingRow
    from PySide6.QtWidgets import QApplication

    config = Config(tmp_path)
    config.set('dynamic_island', {'enabled': True})
    shell = AppShell(QApplication.instance(), config, enable_chat=False)
    shell._sync_dynamic_island()
    assert shell.island is None
    assert shell.island_collision is None
    dialog = ModernSettingsDialog(config, include_ai=False, standalone=True)
    qtbot.addWidget(dialog)
    assert '桌面组件' not in [dialog.sidebar.item(i).text()
                         for i in range(dialog.sidebar.count())]
    assert not any(row.objectName().startswith('settingRow_dynamic_island')
                   or row.objectName() == 'settingRow_spawn_inherit_dynamic_island'
                   for row in dialog.findChildren(SettingRow))
    dialog._write_config()
    assert config.get('dynamic_island')['enabled'] is False


def test_inflight_music_bridge_survives_deleted_window(qtbot):
    import shiboken6
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QWidget
    from pet.context_menus import shared

    pet = QWidget()
    notices = []
    pet.show_bubble = lambda *args, **kwargs: notices.append(args)
    bridge = shared._music_launch_bridge(pet)
    pet.deleteLater()
    QCoreApplication.sendPostedEvents(pet, QEvent.Type.DeferredDelete)
    assert shiboken6.isValid(bridge)
    bridge.notice.emit('播放器路径不可用')
    assert not notices
    bridge._worker_done.emit()
    assert bridge not in shared._LAUNCH_BRIDGES


def test_app_icon_has_macos_rounded_corners(qtbot):
    from pet.branding import brand_icon
    image = brand_icon().pixmap(128, 128).toImage()
    assert image.pixelColor(0, 0).alpha() == 0
    assert image.pixelColor(64, 64).alpha() == 255
