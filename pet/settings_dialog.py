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
        self.bubble = QCheckBox('显示动态气泡')
        self.bubble.setChecked(pet.bubble_enabled)
        layout.addRow('互动', self.bubble)
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
        self.size_slider = QSlider(Qt.Orientation.Horizontal)
        self.size_slider.setRange(160, 1280)
        self.size_slider.setValue(self.size.value())
        self.size_slider.setStyleSheet('''
            QSlider::groove:horizontal { height: 24px; background: #e7e7e7; border-radius: 12px; }
            QSlider::sub-page:horizontal { background: #1677ed; border-radius: 12px; }
            QSlider::handle:horizontal { background: white; width: 28px; margin: -3px 0;
                border: 1px solid #c8c8c8; border-radius: 14px; }
        ''')
        self.size_slider.setMinimumHeight(38)
        self.size_slider.valueChanged.connect(self.size.setValue)
        self.size.valueChanged.connect(self.size_slider.setValue)
        layout.addRow('', self.size_slider)
        self.frequency = QSpinBox()
        self.frequency.setRange(0, 3600)
        self.frequency.setSpecialValueText('跟随当前模式')
        self.frequency.setSuffix(' 秒')
        self.frequency.setValue(pet.action_interval_seconds)
        layout.addRow('动作出现间隔', self.frequency)
        hint = QLabel('0 = 跟随模式；自定义为两次动作开始的最小间隔。\n当前动画播完再切换，等待期间播放待机。')
        hint.setWordWrap(True)
        layout.addRow('', hint)
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
        self.bubble.setChecked(True)
        self.volume.setValue(80)
        self.personality.setCurrentIndex(self.personality.findData('lively'))
        self.size.setValue(round(catalog.CANVAS_W * catalog.DEFAULT_SCALE))
        self.delay.setValue(0)
        self.frequency.setValue(0)

    def save(self) -> None:
        self.pet.set_sound_enabled(self.sound.isChecked())
        self.pet.set_bubble_enabled(self.bubble.isChecked())
        self.pet.set_volume(self.volume.value())
        self.pet.set_personality(self.personality.currentData())
        self.pet.change_scale(self.size.value() / catalog.CANVAS_W)
        self.pet.set_action_switch_delay(self.delay.value() * 1000)
        self.pet.set_action_interval(self.frequency.value())
        self.accept()
