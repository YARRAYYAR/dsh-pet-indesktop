"""Retired controls must not become floating children over the original UI."""
from PySide6.QtWidgets import QPushButton


def test_companion_has_no_floating_music_controls(qtbot, tmp_path, monkeypatch):
    from pet import autostart
    from pet.config import Config
    from pet.modern_settings_dialog import ModernSettingsDialog

    monkeypatch.setattr(autostart, 'is_enabled', lambda: False)
    dialog = ModernSettingsDialog(Config(tmp_path), companion_mode=True, standalone=True)
    qtbot.addWidget(dialog)
    dialog.resize(1100, 760)
    dialog.show()
    qtbot.waitExposed(dialog)
    assert not any(button.isVisible() for button in dialog.findChildren(QPushButton, 'musicPlayerDetectButton'))
    assert [dialog.sidebar.item(i).text() for i in range(dialog.sidebar.count())] == [
        '常规', '桌宠', '互动', '菜单', '连接',
    ]
