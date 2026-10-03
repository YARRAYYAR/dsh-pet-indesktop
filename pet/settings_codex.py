"""Native connection card backed by the pet's instance control channel."""
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from .codex_link import open_codex
from .context_menus.icons import vector_widget_icon
from .settings_widgets import SettingRow, SettingsSection, ToggleSwitch
from .settings_task_appearance import TaskAppearanceEditor

STATES = {'working': '正在工作', 'question': '等你回答', 'complete': '本轮已完成',
          'idle': '空闲', 'disconnected': '未连接', 'unavailable': '等待本地会话'}


class CodexConnectionPage(QWidget):
    def __init__(self, config, client, parent=None):
        super().__init__(parent)
        self.config = config
        self.client = client
        self._session_id = ''
        self._requesting = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        self.enabled = ToggleSwitch(self)
        self.enabled.setChecked(bool(config.get('codex_link_enabled', False)))
        self.enabled.setAccessibleName('连接 Codex 工作状态')
        self.enabled.toggled.connect(self._set_enabled)
        row = SettingRow('codex_link', 'Codex', '让桌宠显示工作状态、提问和本轮完成消息。', self.enabled)
        layout.addWidget(SettingsSection('本地连接', [row], self))
        status_card = QFrame(self)
        status_card.setObjectName('settingsCard')
        status_layout = QVBoxLayout(status_card)
        status_layout.setContentsMargins(16, 14, 16, 14)
        heading = QHBoxLayout()
        self.status = QLabel('未连接', self)
        self.status.setObjectName('settingLabel')
        heading.addWidget(self.status, 1)
        self.open_button = QPushButton('打开 Codex', self)
        self.open_button.setIcon(vector_widget_icon(self, 'harness', 16))
        self.open_button.clicked.connect(self._open)
        heading.addWidget(self.open_button)
        status_layout.addLayout(heading)
        self.message = QLabel('开启连接后，跟随最近活跃的本地 Codex 会话。', self)
        self.message.setWordWrap(True)
        self.message.setObjectName('settingHint')
        status_layout.addWidget(self.message)
        layout.addWidget(status_card)
        note = QLabel('问题请在 Codex 中回答。连接仅在本机读取状态，不需要 API 密钥。桌宠隐藏后，消息可在这里查看。', self)
        note.setObjectName('settingHint')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.appearance_editor = TaskAppearanceEditor(config, self)
        layout.addWidget(self.appearance_editor)
        layout.addStretch(1)
        self.timer = QTimer(self)
        self.timer.setInterval(1500)
        self.timer.timeout.connect(self.refresh)

    def _set_enabled(self, enabled):
        self.config.reload()
        self.config.set('codex_link_enabled', enabled)
        if not self.config.save():
            self.enabled.blockSignals(True)
            self.enabled.setChecked(not enabled)
            self.enabled.blockSignals(False)
            self.config.set('codex_link_enabled', not enabled)
            self.status.setText('保存失败：请检查配置目录是否可写')
            return
        self.status.setText('正在连接…' if enabled else '未连接')
        self.refresh()

    def _open(self):
        if not open_codex(self._session_id):
            self.status.setText('无法打开 Codex，请确认已经安装桌面应用')

    def refresh(self):
        if self._requesting:
            return
        self._requesting = True
        self.client.request('codex_status', {}, self._receive)

    def _receive(self, response):
        self._requesting = False
        if not response['ok']:
            self.status.setText(response['error'])
            return
        data = response['data']
        self._session_id = data['session_id']
        self.status.setText('Codex · ' + STATES.get(data['state'], '等待状态'))
        project = data.get('project')
        text = data.get('text') or ('等待 Codex 的下一条状态消息。' if data['enabled'] else '开启连接后，跟随最近活跃的本地 Codex 会话。')
        self.message.setText((f'{project}\n' if project else '') + text)

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()
        self.timer.start()

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)
