# -*- coding: utf-8 -*-
"""按需创建的设置面板，不增加常驻计时器或播放器。"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QLabel, QPushButton, QSlider, QSpinBox,
)

from . import catalog


class SettingsDialog(QDialog):
    def __init__(self, pet) -> None:
        super().__init__(pet)
        self.pet = pet
        self.setWindowTitle('桌宠设置与动作预览')
        self.setMinimumWidth(420)
        layout = QFormLayout(self)
        self.sound = QCheckBox('开启声音')
        self.sound.setChecked(pet.sound_enabled)
        layout.addRow('声音', self.sound)
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(pet._duck_sound.volume)
        self.volume_label = QLabel()
        self.volume.valueChanged.connect(lambda value: self.volume_label.setText(f'{value}%'))
        self.volume_label.setText(f'{self.volume.value()}%')
        layout.addRow('音量', self.volume)
        layout.addRow('', self.volume_label)
        self.personality = QComboBox()
        for key, profile in catalog.PERSONALITY_PRESETS.items():
            self.personality.addItem(profile['label'], key)
        self.personality.setCurrentIndex(self.personality.findData(pet.personality))
        layout.addRow('性格', self.personality)
        self.description = QLabel()
        self.description.setWordWrap(True)
        layout.addRow('', self.description)
        self.size = QSpinBox()
        self.size.setRange(160, 1280)
        self.size.setSuffix(' px')
        self.size.setValue(round(catalog.CANVAS_W * pet.scale))
        layout.addRow('桌宠画布宽度', self.size)
        self.delay = QSpinBox()
        self.delay.setRange(0, 60)
        self.delay.setSuffix(' 秒')
        self.delay.setValue(pet.action_switch_delay_ms // 1000)
        layout.addRow('动作结束后等待', self.delay)
        self.actions = QComboBox()
        layout.addRow('动作预览', self.actions)
        preview = QPushButton('播放选中动作')
        preview.clicked.connect(self.preview)
        layout.addRow('', preview)
        self.personality.currentIndexChanged.connect(self.refresh_actions)
        self.refresh_actions()
        defaults = QPushButton('恢复本页默认值')
        defaults.clicked.connect(self.reset_fields)
        layout.addRow('', defaults)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText('保存')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def refresh_actions(self) -> None:
        key = self.personality.currentData()
        self.description.setText(catalog.PERSONALITY_DESCRIPTIONS[key])
        self.actions.clear()
        frequent = catalog.personality_frequent_actions(key, self.pet.acts, self.pet._action_tags)
        for name in catalog.personality_action_candidates(key, self.pet.acts, self.pet._action_tags):
            self.actions.addItem(f'★ {name}' if name in frequent else name, name)

    def preview(self) -> None:
        name = self.actions.currentData()
        if name:
            self.pet.show()
            self.pet.resume_animation()
            self.pet.set_paused(False)
            self.pet._switch(name)

    def reset_fields(self) -> None:
        self.sound.setChecked(True)
        self.volume.setValue(80)
        self.personality.setCurrentIndex(self.personality.findData('lively'))
        self.size.setValue(round(catalog.CANVAS_W * catalog.DEFAULT_SCALE))
        self.delay.setValue(0)

    def save(self) -> None:
        self.pet.set_sound_enabled(self.sound.isChecked())
        self.pet.set_volume(self.volume.value())
        self.pet.set_personality(self.personality.currentData())
        self.pet.change_scale(self.size.value() / catalog.CANVAS_W)
        self.pet.set_action_switch_delay(self.delay.value() * 1000)
        self.accept()
