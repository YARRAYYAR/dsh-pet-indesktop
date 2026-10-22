"""Native Codex connection, usage, and task controls."""
from datetime import datetime, timezone

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .codex_link import open_codex
from .context_menus.icons import vector_widget_icon
from .settings_widgets import ModernSelect, ResponsiveActionRow, SettingRow, SettingsSection, ToggleSwitch

STATES = {
    'working': '正在工作',
    'question': '等你回答',
    'complete': '本轮已完成',
    'idle': '空闲',
    'disconnected': '未连接',
    'unavailable': '等待本地会话',
    'error': '任务出错',
}


def _token_count(value):
    return f'{value:,}' if type(value) is int and value >= 0 else None


def _quota_summary(limits):
    windows = limits.get('windows') if isinstance(limits, dict) else None
    if not windows:
        return '暂无额度数据'
    summaries = []
    for window in windows:
        if not isinstance(window, dict):
            continue
        duration = window.get('window_minutes')
        used = window.get('used_percent')
        if type(duration) is not int or not isinstance(used, (int, float)):
            continue
        used_text = f'{used:.0f}%' if float(used).is_integer() else f'{used:.1f}%'
        summary = f'{duration} 分钟 · 已用 {used_text}'
        reset_at = window.get('reset_at')
        if type(reset_at) is int:
            try:
                reset = datetime.fromtimestamp(reset_at, timezone.utc)
            except (OSError, OverflowError, ValueError):
                summary += ' · 重置时间不可用'
            else:
                summary += f' · 重置 {reset:%Y-%m-%d %H:%M} UTC'
        summaries.append(summary)
    return '；'.join(summaries) if summaries else '暂无额度数据'


class CodexConnectionPage(QWidget):
    def __init__(self, config, client, parent=None):
        super().__init__(parent)
        self.config = config
        self.client = client
        self._session_id = ''
        self._turn_id = ''
        self._generation = 0
        self._requesting = False
        self._updating_sessions = False
        self._busy_commands = set()
        self._request_cards = {}
        self._control_data = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        self.enabled = ToggleSwitch(self)
        self.enabled.setChecked(bool(config.get('codex_link_enabled', False)))
        self.enabled.setAccessibleName('连接 Codex 工作状态')
        self.enabled.setAccessibleDescription('允许桌宠读取本机 Codex 会话并执行你提交的任务操作。')
        self.enabled.toggled.connect(self._set_enabled)
        connection_row = SettingRow(
            'codex_link', 'Codex 连接', '读取本机 Codex 会话状态、任务进度和额度信息。', self.enabled
        )
        status_control = QWidget(self)
        status_layout = QVBoxLayout(status_control)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(6)
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
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        self.message.setObjectName('settingHint')
        status_layout.addWidget(self.message)
        self.source_note = QLabel('桌面会话只读；选择桌宠任务后可在这里发送消息和回答问题。', self)
        self.source_note.setWordWrap(True)
        self.source_note.setObjectName('settingHint')
        status_layout.addWidget(self.source_note)
        status_row = SettingRow(
            'codex_status', '连接状态', '查看当前 Codex 会话状态。', status_control, stacked=True
        )
        layout.addWidget(SettingsSection('本地连接', [connection_row, status_row], self))

        self.sessions = ModernSelect(self, width=280)
        self.sessions.setAccessibleName('选择 Codex 对话')
        self.sessions.setAccessibleDescription('桌面已有对话只读；桌宠创建的任务可在此继续交互。')
        self.sessions.currentIndexChanged.connect(self._select_session)
        session_row = SettingRow('codex_session', '当前对话', '选择桌面会话查看状态，或切换到桌宠任务继续交互。', self.sessions)
        layout.addWidget(SettingsSection('对话', [session_row], self))

        self.usage_text = QLabel('暂无 token 统计', self)
        self.usage_text.setObjectName('settingLabel')
        self.usage_text.setWordWrap(True)
        self.quota_text = QLabel('暂无额度数据', self)
        self.quota_text.setObjectName('settingLabel')
        self.quota_text.setWordWrap(True)
        layout.addWidget(SettingsSection('用量', [
            SettingRow('codex_usage', 'Token', '当前选中会话报告的累计量与最近一次响应。', self.usage_text),
            SettingRow('codex_quota', '额度窗口', '按 Codex 本机报告的窗口周期显示。', self.quota_text),
        ], self))

        workspace_control = QWidget(self)
        workspace_row = QHBoxLayout(workspace_control)
        workspace_row.setContentsMargins(0, 0, 0, 0)
        workspace_row.setSpacing(6)
        self.workspace = QLineEdit(self)
        self.workspace.setObjectName('codexWorkspace')
        self.workspace.setPlaceholderText('新任务使用的本地项目绝对路径')
        self.workspace.setAccessibleName('Codex 新任务项目目录')
        self.workspace_button = QPushButton('选择目录…', self)
        self.workspace_button.clicked.connect(self._choose_workspace)
        workspace_control.setAccessibleName('Codex 新任务项目目录')
        workspace_row.addWidget(self.workspace, 1)
        workspace_row.addWidget(self.workspace_button)
        workspace_setting = SettingRow(
            'codex_workspace', '项目目录', '新任务使用的本地项目绝对路径。', workspace_control
        )

        self.composer = QPlainTextEdit(self)
        self.composer.setObjectName('codexComposer')
        self.composer.setPlaceholderText('输入新任务，或向当前 Codex 任务发送消息')
        self.composer.setAccessibleName('Codex 任务消息')
        self.composer.setMaximumHeight(120)
        message_setting = SettingRow(
            'codex_task_message', '任务消息', '输入新任务，或向当前桌宠任务发送消息。', self.composer, stacked=True
        )
        self.connect_button = QPushButton('连接本机 Codex', self)
        self.connect_button.clicked.connect(lambda: self._command('codex_connect', {}, 'connect'))
        self.stop_button = QPushButton('停止任务', self)
        self.stop_button.clicked.connect(self._interrupt)
        self.new_button = QPushButton('新建任务', self)
        self.new_button.clicked.connect(self._new_task)
        self.send_button = QPushButton('发送消息', self)
        self.send_button.setIcon(vector_widget_icon(self, 'send', 16))
        self.send_button.clicked.connect(self._send_message)
        actions = ResponsiveActionRow(
            self.connect_button, [self.stop_button, self.new_button, self.send_button], self
        )
        self.command_status = QLabel('', self)
        self.command_status.setWordWrap(True)
        self.command_status.setObjectName('settingHint')
        self.command_status.hide()
        action_control = QWidget(self)
        action_layout = QVBoxLayout(action_control)
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(6)
        action_layout.addWidget(actions)
        action_layout.addWidget(self.command_status)
        action_setting = SettingRow(
            'codex_task_actions', '操作', '连接、本轮停止、新建任务或发送消息。', action_control
        )
        layout.addWidget(SettingsSection(
            '任务交互', [workspace_setting, message_setting, action_setting], self
        ))

        self.requests_heading = QLabel('待处理请求', self)
        self.requests_heading.setObjectName('sectionTitle')
        self.requests_heading.hide()
        layout.addWidget(self.requests_heading)
        self.requests_host = QWidget(self)
        self.requests_layout = QVBoxLayout(self.requests_host)
        self.requests_layout.setContentsMargins(0, 0, 0, 0)
        self.requests_layout.setSpacing(10)
        self.requests_host.hide()
        layout.addWidget(self.requests_host)

        layout.addStretch(1)

        self.timer = QTimer(self)
        self.timer.setInterval(1500)
        self.timer.timeout.connect(self.refresh)

    @staticmethod
    def _card(parent=None):
        card = QFrame(parent)
        card.setObjectName('settingsCard')
        return card

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

    def _choose_workspace(self):
        path = QFileDialog.getExistingDirectory(self, '选择 Codex 项目目录', self.workspace.text())
        if path:
            self.workspace.setText(path)

    def refresh(self):
        if self._requesting:
            return
        self._requesting = True
        self.client.request('codex_status', {}, self._receive)

    def _receive(self, response):
        self._requesting = False
        if not response.get('ok'):
            self.status.setText(response.get('error') or '无法读取 Codex 状态')
            return
        data = response.get('data')
        if not isinstance(data, dict):
            self.status.setText('Codex 返回了无效状态')
            return
        self._session_id = str(data.get('session_id') or '')
        self._turn_id = str(data.get('turn_id') or '')
        self._generation = data.get('generation', 0) if type(data.get('generation', 0)) is int else 0
        state = data.get('state', '')
        self.status.setText('Codex · ' + STATES.get(state, '等待状态'))
        project = data.get('project')
        text = data.get('text') or ('等待 Codex 的下一条状态消息。' if data.get('enabled') else '开启连接后，跟随最近活跃的本地 Codex 会话。')
        self.message.setText((f'{project}\n' if project else '') + str(text))
        readonly = data.get('source') == 'desktop_readonly'
        self.source_note.setText(
            '当前为桌面会话，只读；切换到桌宠任务后可发送消息、回答问题和处理审批。'
            if readonly else '问题和审批可在这里处理；连接只访问本机 Codex，不需要 API 密钥。'
        )
        self._update_sessions(data)
        self._update_usage(data)
        self._update_controls(data)
        self._render_requests(data.get('questions'), can_reply=bool(data.get('can_reply')))

    def _update_sessions(self, data):
        sessions = data.get('sessions')
        if not isinstance(sessions, list):
            sessions = []
        selected = str(data.get('selected_session_id') or '')
        entries = [('', '跟随最近活跃对话')]
        for item in sessions:
            if not isinstance(item, dict) or not isinstance(item.get('id'), str):
                continue
            session_id = item['id']
            label = str(item.get('project') or session_id)
            if item.get('source') == 'pet_session':
                label += ' · 桌宠任务'
            entries.append((session_id, label))
        if selected and not any(session_id == selected for session_id, _ in entries):
            entries.append((selected, str(data.get('project') or selected)))
        self._updating_sessions = True
        self.sessions.blockSignals(True)
        self.sessions.clear()
        for session_id, label in entries:
            self.sessions.addItem(label, session_id)
        self.sessions.setCurrentData(selected)
        self.sessions.blockSignals(False)
        self._updating_sessions = False

    def _select_session(self, _index):
        if self._updating_sessions:
            return
        session_id = str(self.sessions.currentData() or '')
        self._command('codex_select', {'session_id': session_id}, 'select')

    def _update_usage(self, data):
        usage = data.get('usage') if isinstance(data.get('usage'), dict) else None
        total = (usage or {}).get('total') if usage else None
        last = (usage or {}).get('last') if usage else None
        total_count = _token_count((total or {}).get('total_tokens')) if isinstance(total, dict) else None
        last_count = _token_count((last or {}).get('total_tokens')) if isinstance(last, dict) else None
        if total_count is None and last_count is None:
            self.usage_text.setText('暂无 token 统计')
        else:
            items = []
            if total_count is not None:
                items.append(f'累计 {total_count} tokens')
            if last_count is not None:
                items.append(f'最近 {last_count} tokens')
            self.usage_text.setText(' · '.join(items))
        self.quota_text.setText(_quota_summary(data.get('limits')))

    def _update_controls(self, data):
        self._control_data = data
        connected = bool(data.get('enabled'))
        can_send = bool(data.get('can_send'))
        can_interrupt = bool(data.get('can_interrupt'))
        busy = bool(self._busy_commands)
        self.connect_button.setEnabled(connected and data.get('connection') != 'ready' and not busy)
        self.new_button.setEnabled(connected and not busy and bool(self.workspace.text().strip()))
        self.send_button.setEnabled(connected and can_send and not busy)
        self.stop_button.setEnabled(connected and can_interrupt and not busy)
        self.sessions.setEnabled(connected and len(data.get('sessions') or []) > 1)
        for request_key, card in self._request_cards.items():
            can_reply = bool(data.get('can_reply'))
            for button in card.findChildren(QPushButton):
                button.setEnabled(can_reply and not busy and not card._codex_sending
                                  and request_key not in self._busy_commands)

    def _command(self, command, args, key, on_success=None):
        if key in self._busy_commands:
            return
        self._busy_commands.add(key)
        self.command_status.hide()
        self._update_busy_controls()

        def received(response):
            self._busy_commands.discard(key)
            if not response.get('ok'):
                self.command_status.setText(response.get('error') or 'Codex 命令未完成')
                self.command_status.show()
            else:
                self.command_status.setText('')
                self.command_status.hide()
                if on_success is not None:
                    on_success()
            self._update_busy_controls()

        self.client.request(command, args, received)

    def _update_busy_controls(self):
        self._update_controls(self._control_data)

    def _new_task(self):
        text = self.composer.toPlainText().strip()
        if not text:
            self.command_status.setText('请输入任务内容。')
            self.command_status.show()
            return
        draft = self.composer.toPlainText()
        self._command('codex_new_task', {'text': text, 'cwd': self.workspace.text().strip()}, 'new',
                      on_success=lambda: self.composer.clear() if self.composer.toPlainText() == draft else None)

    def _send_message(self):
        text = self.composer.toPlainText().strip()
        if not text:
            self.command_status.setText('请输入消息内容。')
            self.command_status.show()
            return
        draft = self.composer.toPlainText()
        args = {'session_id': self._session_id, 'turn_id': self._turn_id, 'text': text}
        self._command('codex_send', args, 'send',
                      on_success=lambda: self.composer.clear() if self.composer.toPlainText() == draft else None)

    def _interrupt(self):
        self._command('codex_interrupt', {'session_id': self._session_id, 'turn_id': self._turn_id}, 'interrupt')

    def _render_requests(self, requests, *, can_reply):
        items = requests if isinstance(requests, list) else []
        active = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            kind = item.get('kind', 'question' if isinstance(item.get('questions'), list) else None)
            if kind not in {'question', 'command_approval', 'file_approval'}:
                continue
            request_id = item.get('request_id')
            if isinstance(request_id, bool) or not isinstance(request_id, (str, int)) or request_id == '':
                continue
            context = {'session_id': item.get('session_id', self._session_id),
                       'turn_id': item.get('turn_id', self._turn_id),
                       'generation': item.get('generation', self._generation), 'request_id': request_id}
            # JSON-RPC int/string IDs are distinct and can recur after reconnect.
            request_key = (context['session_id'], context['turn_id'], context['generation'],
                           type(request_id), request_id, bool(can_reply))
            active.add(request_key)
            card = self._request_cards.get(request_key)
            if card is None:
                card = self._build_request_card(request_key, context, {**item, 'kind': kind}, can_reply=can_reply)
                self._request_cards[request_key] = card
                self.requests_layout.addWidget(card)
            sending = bool(item.get('sending'))
            card._codex_sending = sending
            for button in card.findChildren(QPushButton):
                button.setEnabled(can_reply and not sending and not self._busy_commands)
        for request_key in tuple(self._request_cards):
            if request_key not in active:
                card = self._request_cards.pop(request_key)
                self.requests_layout.removeWidget(card)
                card.hide()
                card.setParent(None)
                card.deleteLater()
        visible = bool(active)
        self.requests_heading.setVisible(visible)
        self.requests_host.setVisible(visible)

    def _build_request_card(self, request_key, context, item, *, can_reply):
        request_id = context['request_id']
        card = self._card(self.requests_host)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)
        if item.get('kind') == 'question':
            layout.addWidget(self._request_heading(item, 'Codex 有问题需要回答'))
            if not can_reply:
                note = QLabel('此会话为只读，请在 Codex 桌面应用中回答。', card)
                note.setObjectName('settingHint')
                note.setWordWrap(True)
                layout.addWidget(note)
                for question in item.get('questions') or []:
                    if isinstance(question, dict):
                        prompt = QLabel(str(question.get('question') or question.get('header') or ''), card)
                        prompt.setObjectName('codexQuestionText')
                        prompt.setWordWrap(True)
                        prompt.setTextFormat(Qt.TextFormat.PlainText)
                        layout.addWidget(prompt)
                return card
            controls = []
            for question in item.get('questions') or []:
                if not isinstance(question, dict) or not isinstance(question.get('id'), str):
                    continue
                question_id = question['id']
                prompt = QLabel(str(question.get('question') or question.get('header') or ''), card)
                prompt.setObjectName('codexQuestionText')
                prompt.setWordWrap(True)
                prompt.setTextFormat(Qt.TextFormat.PlainText)
                layout.addWidget(prompt)
                options = question.get('options')
                buttons = []
                answer = None
                if isinstance(options, list) and options and not question.get('isSecret'):
                    group = QButtonGroup(card)
                    group.setExclusive(True)
                    option_layout = QVBoxLayout()
                    for index, option in enumerate(options):
                        if not isinstance(option, dict):
                            continue
                        label = str(option.get('label') or '')
                        button = QPushButton(label, card)
                        button.setObjectName(f'codexOption_{question_id}_{index}')
                        button.setCheckable(True)
                        button.setAccessibleDescription(str(option.get('description') or label))
                        group.addButton(button)
                        buttons.append(button)
                        option_layout.addWidget(button)
                    layout.addLayout(option_layout)
                    if question.get('isOther'):
                        answer = QLineEdit(card)
                        answer.setObjectName(f'codexAnswer_{question_id}')
                        answer.setPlaceholderText('其他回答')
                        answer.setAccessibleName(f'{question.get("header") or "问题"}的其他回答')
                        layout.addWidget(answer)
                else:
                    answer = QLineEdit(card)
                    answer.setObjectName(f'codexAnswer_{question_id}')
                    answer.setAccessibleName(str(question.get('header') or 'Codex 问题回答'))
                    if question.get('isSecret'):
                        answer.setEchoMode(QLineEdit.EchoMode.Password)
                    layout.addWidget(answer)
                controls.append((question_id, answer, buttons))
            submit = QPushButton('提交回答', card)
            submit.setObjectName(f'codexSubmit_{request_id}')
            submit.setIcon(vector_widget_icon(self, 'send', 16))
            submit.clicked.connect(lambda _checked=False, key=request_key, ctx=context, refs=controls:
                                   self._submit_answer(key, ctx, refs))
            layout.addWidget(submit)
            card._codex_answer_controls = controls
        else:
            layout.addWidget(self._request_heading(item, '需要你确认操作'))
            summary = QLabel(str(item.get('summary') or 'Codex 请求了一项操作。'), card)
            summary.setObjectName('codexQuestionText')
            summary.setWordWrap(True)
            summary.setTextFormat(Qt.TextFormat.PlainText)
            layout.addWidget(summary)
            if not can_reply:
                note = QLabel('此会话为只读，请在 Codex 桌面应用中处理。', card)
                note.setObjectName('settingHint')
                note.setWordWrap(True)
                layout.addWidget(note)
                return card
            actions = QHBoxLayout()
            actions.addStretch(1)
            for decision, label in (('decline', '拒绝'), ('accept', '允许')):
                button = QPushButton(label, card)
                button.setObjectName(f'codexApproval_{decision}_{request_id}')
                button.clicked.connect(lambda _checked=False, key=request_key, ctx=context, choice=decision:
                                       self._approve(key, ctx, choice))
                actions.addWidget(button)
            layout.addLayout(actions)
        return card

    def _request_heading(self, item, fallback):
        heading = QLabel(str(item.get('title') or item.get('header') or fallback), self)
        heading.setObjectName('settingLabel')
        heading.setWordWrap(True)
        heading.setTextFormat(Qt.TextFormat.PlainText)
        return heading

    def _submit_answer(self, request_key, context, controls):
        answers = {}
        for question_id, answer, buttons in controls:
            if buttons:
                selected = next((button.text() for button in buttons if button.isChecked()), '')
                other = answer.text().strip() if answer is not None else ''
                value = other or selected
            else:
                value = answer.text().strip() if answer is not None else ''
            if not value:
                self.command_status.setText('请回答每一个问题。')
                self.command_status.show()
                return
            answers[question_id] = {'answers': [value]}
        self._command('codex_answer', {**context, 'answers': answers}, request_key)

    def _approve(self, request_key, context, decision):
        self._command('codex_approve', {**context, 'decision': decision}, request_key)

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()
        self.timer.start()

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)
