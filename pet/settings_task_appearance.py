"""One owner for Codex task colors and size; preview uses the real renderer."""
from PySide6.QtCore import QRect
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QColorDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from .settings_widgets import BROWSER_CONTROL_SPEC, BrowserSpinBox, ModernSelect, SettingRow, SettingsSection
from .task_bubble import TaskSpeechBubble
from .task_bubble_style import DEFAULT_TASK_APPEARANCE, TASK_PRESETS, clean_task_appearance, valid_task_color


class TaskPreview(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.appearance = dict(DEFAULT_TASK_APPEARANCE)
        self.message_kind = '提问'
        self.bubble = TaskSpeechBubble(appearance_provider=lambda: self.appearance, embedded=True, parent=self)
        self.setMinimumHeight(160)
        self.setAccessibleName('Codex 任务框实时预览')

    def render(self):
        messages = {'工作': ('正在整理素材与界面，请稍候。', 'Codex · 正在工作'),
                    '提问': ('任务框现在是什么感觉？请在 Codex 中回答。', 'Codex · 需要你回答'),
                    '完成': ('本轮任务已完成，点击按钮查看结果。', 'Codex · 本轮完成')}
        text, subtitle = messages[self.message_kind]
        self.bubble.show_text(text, QRect(), sticky=True, subtitle=subtitle,
                              buttons=[('打开 Codex', lambda: None)] if self.message_kind != '工作' else None)
        for button in self.bubble._interactive_buttons:
            button.setEnabled(False)
            button.setToolTip('这里是预览；真实消息中的按钮会打开 Codex')
        self.setFixedHeight(self.bubble.height() + 20)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if event.oldSize().width() != event.size().width():
            self.render()


class TaskAppearanceEditor(QWidget):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self._saved = clean_task_appearance(config.get('codex_task_appearance'))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        self.presets = ModernSelect(self)
        for name in (*TASK_PRESETS, '自定义'):
            self.presets.addItem(name, name)
        self.presets.setAccessibleName('任务框配色预设')
        self.background, bg_control = self._color_control('taskBackground', '任务框背景颜色')
        self.accent, accent_control = self._color_control('taskAccent', '任务框边框颜色')
        self.scale = BrowserSpinBox(self)
        self.scale.setObjectName('taskScale')
        self.scale.setRange(80, 160)
        self.scale.setSuffix(' %')
        self.scale.setKeyboardTracking(False)
        self.scale.setAccessibleName('Codex 任务框大小百分比')
        rows = [SettingRow('codex_task_preset', '配色', '选择配色，再按喜好调整。', self.presets),
                SettingRow('codex_task_background', '背景颜色', '文字自动使用清晰的黑色或白色。', bg_control),
                SettingRow('codex_task_accent', '边框颜色', '同时用于任务框和操作按钮边缘。', accent_control),
                SettingRow('codex_task_scale', '任务框大小', '80–160%；文字与按钮一起缩放，高度随内容调整。', self.scale)]
        layout.addWidget(SettingsSection('任务框外观', rows, self))
        heading = QHBoxLayout()
        heading.addWidget(QLabel('实时预览', self), 1)
        self.kind = ModernSelect(self)
        for name in ('提问', '工作', '完成'):
            self.kind.addItem(name, name)
        self.kind.setAccessibleName('任务框预览消息类型')
        heading.addWidget(self.kind)
        self.reset_button = QPushButton('恢复默认', self)
        self.reset_button.setObjectName('taskReset')
        self.reset_button.setAutoDefault(False)
        heading.addWidget(self.reset_button)
        layout.addLayout(heading)
        self.preview = TaskPreview(self)
        layout.addWidget(self.preview)
        note = QLabel('调整时预览，结束编辑后保存并应用。预览不会产生真实任务或播放动作。', self)
        note.setObjectName('settingHint')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.error = QLabel(self)
        self.error.setWordWrap(True)
        self.error.setStyleSheet('color:#ff9f93; background:transparent;')
        self.error.hide()
        layout.addWidget(self.error)
        self._load(self._saved)
        self.presets.currentIndexChanged.connect(lambda _index: self._preset(self.presets.currentText()))
        for field in (self.background, self.accent):
            field.textChanged.connect(self._preview)
            field.editingFinished.connect(self._commit)
        self.scale.valueChanged.connect(self._preview)
        self.scale.editingFinished.connect(self._commit)
        self.kind.currentIndexChanged.connect(self._preview)
        self.reset_button.clicked.connect(self._reset)

    def _color_control(self, name, accessible):
        control = QWidget(self)
        # The row may be measured before inherited QSS polishes its children.
        # Reserve the shared field height so their borders stay inside the row.
        control.setMinimumHeight(BROWSER_CONTROL_SPEC["field_height"])
        row = QHBoxLayout(control)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        field = QLineEdit(control)
        field.setObjectName(name)
        field.setMaximumWidth(96)
        field.setAccessibleName(accessible + '，十六进制')
        field.setPlaceholderText('#1c1c1e')
        button = QPushButton('选色', control)
        button.setAutoDefault(False)
        button.setAccessibleName(accessible + '，打开颜色选择器')
        button.clicked.connect(lambda: self._choose(field, accessible))
        row.addWidget(field)
        row.addWidget(button)
        return field, control

    def _choose(self, field, title):
        color = QColorDialog.getColor(QColor(field.text()), self, title)
        if color.isValid():
            field.setText(color.name())
            self._commit()

    def _draft(self):
        if not all(valid_task_color(f.text()) for f in (self.background, self.accent)):
            return None
        return clean_task_appearance({'background': self.background.text(), 'accent': self.accent.text(), 'scale': self.scale.value()})

    def _load(self, value):
        widgets = (self.background, self.accent, self.scale, self.presets)
        for widget in widgets:
            widget.blockSignals(True)
        self.background.setText(value['background'])
        self.accent.setText(value['accent'])
        self.scale.setValue(value['scale'])
        self.presets.setCurrentData(next((name for name, p in TASK_PRESETS.items() if all(p[k] == value[k] for k in ('background', 'accent'))), '自定义'))
        for widget in widgets:
            widget.blockSignals(False)
        self._preview()

    def _preview(self, *_args):
        draft = self._draft()
        if draft is None:
            return
        self.preview.appearance = draft
        self.preview.message_kind = self.kind.currentText()
        self.preview.render()

    def _commit(self):
        draft = self._draft()
        if draft is None:
            self.error.setText('请输入 # 开头的 6 位颜色，例如 #1c1c1e。')
            self.error.show()
            return False
        if draft == self._saved:
            self.error.hide()
            return True
        self.config.reload()
        previous = clean_task_appearance(self.config.get('codex_task_appearance'))
        self.config.set('codex_task_appearance', draft)
        if not self.config.save():
            self.config.set('codex_task_appearance', previous)
            self._saved = previous
            self._load(previous)
            self.error.setText('保存失败：请检查配置目录是否可写。已恢复上次保存的外观。')
            self.error.show()
            return False
        self._saved = draft
        self._load(draft)
        self.error.hide()
        return True

    def _preset(self, name):
        if name in TASK_PRESETS:
            value = dict(TASK_PRESETS[name], scale=self.scale.value())
            self._load(value)
            self._commit()

    def _reset(self):
        self._load(dict(DEFAULT_TASK_APPEARANCE))
        self._commit()
