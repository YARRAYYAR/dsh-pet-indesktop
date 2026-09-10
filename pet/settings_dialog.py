"""Grouped desktop control panel with reversible previews and one media player."""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame,
    QHBoxLayout, QLabel, QListWidget, QScrollArea, QSlider, QSpinBox,
    QStackedWidget, QToolButton, QVBoxLayout, QWidget,
)
from . import catalog
from .action_dialog import ActionLibraryWidget
from .ui_style import apply_style, button, label


class SettingsDialog(QDialog):
    def __init__(self, pet):
        super().__init__(pet)
        self.pet = pet
        self.setWindowTitle('桌宠控制面板')
        self.setMinimumSize(820, 550)
        self.resize(1020, 680)
        apply_style(self)
        self._original = dict(scale=pet.scale, position=pet.pos(), volume=pet._duck_sound.volume,
            sound=pet.sound_enabled, bubble=pet.bubble_enabled, drag=pet.drag_physics,
            bounce_variant=pet._bounce_sound.variant,
            bubble_x=pet.bubble_offset_x, bubble_y=pet.bubble_offset_y,
            paused=pet._paused, anim=pet.anim, visible=pet.isVisible(), suspended=pet._suspended)
        self._did_preview_action = False
        self._preview_name = None
        self._preview_attempts = 0
        self._preview_timer = QTimer(self)
        self._preview_timer.setInterval(80)
        self._preview_timer.timeout.connect(self._capture_preview)
        self._size_timer = QTimer(self)
        self._size_timer.setSingleShot(True)
        self._size_timer.setInterval(60)
        self._size_timer.timeout.connect(self._preview_size)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 18, 14)
        body = QHBoxLayout()
        body.setSpacing(20)
        self.navigation = QListWidget()
        self.navigation.setObjectName('navigation')
        self.navigation.setAccessibleName('控制面板导航')
        self.navigation.setFixedWidth(144)
        self.navigation.addItems(['桌宠', '动作库', '互动', '声音', '设置'])
        body.addWidget(self.navigation)
        self.pages = QStackedWidget()
        body.addWidget(self.pages, 1)
        root.addLayout(body, 1)

        home = self._page('你的桌面小伙伴', '常用控制放在这里。修改可即时预览，取消会恢复。')
        hero_card, hero_layout = self._card(home, '正在陪伴你')
        hero_row = QHBoxLayout()
        self.hero = QLabel()
        self.hero.setObjectName('hero')
        self.hero.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hero.setMinimumSize(180, 150)
        self.hero.setPixmap(pet.icon_pixmap(210))
        hero_row.addWidget(self.hero)
        hero_text = QVBoxLayout()
        hero_text.addWidget(label(str(pet.cfg.get('character', '桌宠')), 'sectionTitle'))
        hero_text.addWidget(label(f'{len(list(pet.lib.names()))} 个动作 · 原视频画质'))
        self.pause_button = button('继续播放' if pet._paused else '暂停播放', pet.toggle_pause)
        pet.pausedChanged.connect(self._sync_pause)
        hero_text.addWidget(self.pause_button)
        hero_text.addStretch()
        hero_row.addLayout(hero_text, 1)
        hero_layout.addLayout(hero_row)
        _, quick = self._card(home, '常用开关')
        self.bubble = self._check('显示对话框（气泡）', pet.bubble_enabled)
        self.sound = self._check('开启互动音效', pet.sound_enabled)
        self.drag = self._check('原版回弹与抛掷', pet.drag_physics)
        for control in (self.bubble, self.sound, self.drag):
            quick.addWidget(control)
        _, size_layout = self._card(home, '桌宠大小')
        self.size = QSpinBox()
        self.size.setRange(160, 1280)
        self.size.setSuffix(' px')
        self.size.setValue(round(catalog.CANVAS_W * pet.scale))
        self.size.setAccessibleName('桌宠显示宽度')
        self.size_slider = QSlider(Qt.Orientation.Horizontal)
        self.size_slider.setRange(160, 1280)
        self.size_slider.setValue(self.size.value())
        self.size_slider.setAccessibleName('桌宠大小')
        size_row = QHBoxLayout()
        size_row.addWidget(self.size_slider, 1)
        size_row.addWidget(self.size)
        size_layout.addLayout(size_row)
        self.size_slider.valueChanged.connect(self.size.setValue)
        self.size.valueChanged.connect(self.size_slider.setValue)
        home.addStretch()

        actions = self._page('动作库', '左侧找动作，右侧安排顺序。预览只播放选中的一个动作。', scroll=False)
        self.library = ActionLibraryWidget(list(pet.lib.names()), pet.playlist, self,
            allow_exchange=True, favorites=pet.favorites)
        self.library.previewRequested.connect(self.preview_action)
        actions.addWidget(self.library, 1)
        mode_row = QHBoxLayout()
        mode_row.addWidget(label('播放方式', 'sectionTitle'))
        self.playlist_mode = QComboBox()
        for key, title in [('off', '跟随性格'), ('loop', '按列表顺序循环'), ('random', '从列表随机播放')]:
            self.playlist_mode.addItem(title, key)
        self.playlist_mode.setCurrentIndex(self.playlist_mode.findData(pet.playlist_mode))
        mode_row.addWidget(self.playlist_mode)
        mode_row.addStretch()
        actions.addLayout(mode_row)

        interactions = self._page('互动', '保留你喜欢的回弹手感，调整气泡和主动互动。')
        _, physical = self._card(interactions, '拖拽手感')
        physical.addWidget(self._mirror(self.drag, '启用原版来回回弹与抛掷'))
        physical.addWidget(label('第一下立即跟手；后续保留弹簧回弹。'))
        _, bubbles = self._card(interactions, '对话框')
        bubbles.addWidget(self._mirror(self.bubble, '显示气泡'))
        self.bubble_details = QWidget()
        details = QVBoxLayout(self.bubble_details)
        details.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        row.addWidget(button('预览气泡', self.preview_bubble))
        row.addWidget(button('收起预览', self.hide_preview_bubble))
        row.addStretch()
        details.addLayout(row)
        advanced_button = QToolButton()
        advanced_button.setText('调整位置')
        advanced_button.setCheckable(True)
        advanced_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        advanced_button.setArrowType(Qt.ArrowType.RightArrow)
        details.addWidget(advanced_button, alignment=Qt.AlignmentFlag.AlignLeft)
        advanced = QWidget()
        form = QFormLayout(advanced)
        form.setContentsMargins(0, 4, 0, 0)
        self.bubble_x, self.bubble_y = QSpinBox(), QSpinBox()
        for field, value in [(self.bubble_x, pet.bubble_offset_x), (self.bubble_y, pet.bubble_offset_y)]:
            field.setRange(-90, 90)
            field.setValue(value)
        form.addRow('左右位置', self.bubble_x)
        form.addRow('上下位置', self.bubble_y)
        self.bubble_data = label('')
        form.addRow(self.bubble_data)
        advanced.setVisible(False)
        advanced_button.toggled.connect(advanced.setVisible)
        advanced_button.toggled.connect(lambda on: advanced_button.setArrowType(Qt.ArrowType.DownArrow if on else Qt.ArrowType.RightArrow))
        details.addWidget(advanced)
        bubbles.addWidget(self.bubble_details)
        self.bubble_details.setVisible(self.bubble.isChecked())
        _, greetings = self._card(interactions, '主动互动')
        self.greetings = self._check('偶尔主动打招呼', pet.proactive_greetings)
        greetings.addWidget(self.greetings)
        interactions.addStretch()

        sounds = self._page('声音', '短促回弹音和点击音效，统一控制音量。')
        _, audio = self._card(sounds, '互动音效')
        audio.addWidget(self._mirror(self.sound, '开启声音'))
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(pet._duck_sound.volume)
        self.volume.setAccessibleName('互动音量')
        self.volume_label = label(f'{self.volume.value()}%', 'sectionTitle')
        volume_row = QHBoxLayout()
        volume_row.addWidget(self.volume, 1)
        volume_row.addWidget(self.volume_label)
        audio.addLayout(volume_row)
        self.bounce_variant = QComboBox()
        for key in pet._bounce_sound.VARIANTS:
            self.bounce_variant.addItem(pet._bounce_sound.VARIANT_LABELS[key], key)
        self.bounce_variant.setCurrentIndex(self.bounce_variant.findData(pet._bounce_sound.variant))
        self.bounce_variant.setAccessibleName('回弹音效种类')
        audio.addWidget(label('回弹音效'))
        audio.addWidget(self.bounce_variant)
        audio.addWidget(button('试听回弹音', pet._play_bounce_sound), alignment=Qt.AlignmentFlag.AlignLeft)
        audio.addWidget(label('拖动过程不发声，只在真正撞到边缘或地面时播放。'))
        sounds.addStretch()

        settings = self._page('设置', '调整性格与动作节奏。高级参数按需展开。')
        _, personality_layout = self._card(settings, '性格')
        self.personality = QComboBox()
        for key, profile in catalog.PERSONALITY_PRESETS.items():
            self.personality.addItem(profile['label'], key)
        self.personality.setCurrentIndex(self.personality.findData(pet.personality))
        self.description = label('')
        personality_layout.addWidget(self.personality)
        personality_layout.addWidget(self.description)
        self.personality.currentIndexChanged.connect(self.refresh_actions)
        self.refresh_actions()
        _, rhythm = self._card(settings, '动作节奏')
        form = QFormLayout()
        self.frequency = QSpinBox()
        self.frequency.setRange(0, 3600)
        self.frequency.setSpecialValueText('跟随性格')
        self.frequency.setSuffix(' 秒')
        self.frequency.setValue(pet.action_interval_seconds)
        form.addRow('动作最小间隔', self.frequency)
        self.delay = QSpinBox()
        self.delay.setRange(0, 60)
        self.delay.setSuffix(' 秒')
        self.delay.setValue(pet.action_switch_delay_ms // 1000)
        form.addRow('播完后等待', self.delay)
        rhythm.addLayout(form)
        rhythm.addWidget(label('当前动作自然播完再切换。间隔设为 0 时跟随性格安排。'))
        settings.addWidget(button('恢复全部默认设置', self.reset_fields), alignment=Qt.AlignmentFlag.AlignLeft)
        settings.addStretch()

        footer = QHBoxLayout()
        footer.addWidget(label('修改仅在保存后记住；取消恢复本次预览。'), 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText('保存设置')
        buttons.button(QDialogButtonBox.StandardButton.Save).setObjectName('primary')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        footer.addWidget(buttons)
        root.addLayout(footer)
        self.navigation.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.navigation.setCurrentRow(0)
        self.size.valueChanged.connect(lambda _: self._size_timer.start())
        self.volume.valueChanged.connect(self._preview_volume)
        self.sound.toggled.connect(lambda on: pet.set_sound_enabled(on, persist=False))
        self.bubble.toggled.connect(self._preview_bubble_enabled)
        pet.bubbleChanged.connect(self.bubble.setChecked)
        pet.soundChanged.connect(self.sound.setChecked)
        pet.bounceSoundVariantChanged.connect(
            lambda key: self.bounce_variant.setCurrentIndex(self.bounce_variant.findData(key))
        )
        self.bounce_variant.currentIndexChanged.connect(
            lambda _: pet.set_bounce_sound_variant(self.bounce_variant.currentData(), persist=False)
        )
        self.drag.toggled.connect(lambda on: pet.set_drag_physics(on, persist=False))
        self.bubble_x.valueChanged.connect(self.preview_bubble_position)
        self.bubble_y.valueChanged.connect(self.preview_bubble_position)
        self.update_bubble_data()

    def showEvent(self, event):
        super().showEvent(event)
        self._preview_name = self.pet.anim
        self._preview_attempts = 0
        self._preview_timer.start()

    def _page(self, title, subtitle, *, scroll=True):
        content = QWidget()
        content.setObjectName('panel')
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 8, 6, 4)
        layout.setSpacing(14)
        layout.addWidget(label(title, 'title'))
        layout.addWidget(label(subtitle))
        if scroll:
            area = QScrollArea()
            area.setWidgetResizable(True)
            area.setWidget(content)
            self.pages.addWidget(area)
        else:
            self.pages.addWidget(content)
        return layout

    def _card(self, layout, title):
        card = QFrame()
        card.setObjectName('card')
        body = QVBoxLayout(card)
        body.setContentsMargins(18, 14, 18, 16)
        body.setSpacing(10)
        body.addWidget(label(title, 'sectionTitle'))
        layout.addWidget(card)
        return card, body

    def _check(self, text, checked):
        result = QCheckBox(text)
        result.setChecked(checked)
        return result

    def _mirror(self, source, text):
        result = self._check(text, source.isChecked())
        result.toggled.connect(source.setChecked)
        source.toggled.connect(result.setChecked)
        return result

    def _sync_pause(self, paused):
        self.pause_button.setText('继续播放' if paused else '暂停播放')

    def refresh_actions(self):
        self.description.setText(catalog.PERSONALITY_DESCRIPTIONS[self.personality.currentData()])

    def _preview_size(self):
        self.pet.change_scale(self.size.value() / catalog.CANVAS_W, persist=False)

    def _preview_volume(self, value):
        self.volume_label.setText(f'{value}%')
        self.pet.set_volume(value, persist=False)

    def _preview_bubble_enabled(self, on):
        self.bubble_details.setVisible(on)
        self.pet.set_bubble_enabled(on, persist=False)

    def update_bubble_data(self):
        self.bubble_data.setText(f'偏移 {self.bubble_x.value():+d} / {self.bubble_y.value():+d}，随桌宠大小缩放')

    def preview_bubble_position(self):
        self.pet.set_bubble_position(self.bubble_x.value(), self.bubble_y.value())
        self.update_bubble_data()

    def preview_bubble(self):
        self.pet.preview_bubble(True)

    def hide_preview_bubble(self):
        self.pet.preview_bubble(False)

    def preview_action(self, name):
        if name not in self.pet.lib.names():
            return
        self._did_preview_action = True
        self._preview_name = name
        self._preview_attempts = 0
        self.pet.show()
        self.pet.resume_animation()
        self.pet.set_paused(False)
        self.pet._switch(name)
        self._preview_timer.start()

    def _capture_preview(self):
        self._preview_attempts += 1
        if not self.isVisible() or self._preview_attempts > 25 or self.pet.anim != self._preview_name:
            self._preview_timer.stop()
            return
        frame = self.pet.movie.currentFrame() if self.pet.movie else None
        if frame is not None:
            self.library.set_thumbnail(self._preview_name, QPixmap.fromImage(frame.image))
            self.hero.setPixmap(self.pet.icon_pixmap(210))
            self._preview_timer.stop()

    def reject(self):
        self._size_timer.stop()
        self._preview_timer.stop()
        old = self._original
        self.pet.preview_bubble(None)
        self.pet.set_bubble_position(old['bubble_x'], old['bubble_y'])
        self.pet.set_sound_enabled(old['sound'], persist=False)
        self.pet.set_bubble_enabled(old['bubble'], persist=False)
        self.pet.set_volume(old['volume'], persist=False)
        self.pet.set_bounce_sound_variant(old['bounce_variant'], persist=False)
        self.pet.set_drag_physics(old['drag'], persist=False)
        self.pet.change_scale(old['scale'], persist=False)
        self.pet.move(old['position'])
        if self._did_preview_action:
            self.pet._switch(old['anim'])
        self.pet.set_paused(old['paused'])
        if old['suspended']:
            self.pet.suspend_animation()
        if not old['visible']:
            self.pet.hide()
        super().reject()

    def reset_fields(self):
        self.sound.setChecked(True)
        self.bubble.setChecked(True)
        self.drag.setChecked(False)
        self.greetings.setChecked(True)
        self.bubble_x.setValue(0)
        self.bubble_y.setValue(0)
        self.volume.setValue(80)
        self.bounce_variant.setCurrentIndex(self.bounce_variant.findData('random'))
        self.personality.setCurrentIndex(self.personality.findData('lively'))
        self.size.setValue(round(catalog.CANVAS_W * catalog.DEFAULT_SCALE))
        self.delay.setValue(0)
        self.frequency.setValue(0)

    def save(self):
        self._size_timer.stop()
        self._preview_timer.stop()
        self.pet.preview_bubble(None)
        with self.pet.cfg.batch_save():
            self.pet.set_sound_enabled(self.sound.isChecked())
            self.pet.set_bubble_enabled(self.bubble.isChecked())
            self.pet.set_volume(self.volume.value())
            self.pet.set_bounce_sound_variant(self.bounce_variant.currentData())
            self.pet.set_drag_physics(self.drag.isChecked())
            self.pet.set_proactive_greetings(self.greetings.isChecked())
            self.pet.set_personality(self.personality.currentData())
            self.pet.change_scale(self.size.value() / catalog.CANVAS_W, persist=False)
            self.pet._save_position()
            self.pet.set_bubble_position(self.bubble_x.value(), self.bubble_y.value(), persist=True)
            self.pet.set_action_switch_delay(self.delay.value() * 1000)
            self.pet.set_action_interval(self.frequency.value())
            selected = self.library.selected_names()
            if selected != self.pet.playlist:
                self.pet._apply_action_set('playlist', selected)
            if self.playlist_mode.currentData() != self.pet.playlist_mode:
                self.pet.set_playlist_mode(self.playlist_mode.currentData())
        self.accept()
