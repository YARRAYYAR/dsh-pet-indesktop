"""Action commands and observable playback, separate from persistent settings."""
from functools import partial
import weakref

import shiboken6
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from .settings_widgets import ModernSelect, ResponsiveActionRow
from .context_menus.icons import vector_widget_icon

CATEGORY_NAMES = {'idle': '待机', 'turn': '转向', 'idle_turn': '待机与转向',
                  'move': '移动', 'click': '点击回应', 'drag': '拖拽',
                  'random': '日常动作', 'events': '事件动作'}


def _cancel_requests(client, requests, *_args):
    # The destroyed connection holds the registry, never the QWidget itself.
    for token in tuple(requests.values()):
        client.cancel(token)
    requests.clear()


class ActionLibrary(QWidget):
    def __init__(self, client, parent=None):
        super().__init__(parent)
        self.client = client
        self._actions = []
        self._current = ''
        self._queued = ''
        self._pending = ''
        self._error = ''
        self._requests = {}
        self._generation = 0
        self._watch_seen = False
        self._watch_serial = 0
        self._play_watch_serial = 0
        self.destroyed.connect(partial(_cancel_requests, client, self._requests))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        hint = QLabel('选择动作后点击播放；桌宠当前动作结束后会继续原有活动。', self)
        hint.setObjectName('settingHint')
        hint.setWordWrap(True)
        hint.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        layout.addWidget(hint)
        self.search = QLineEdit(self)
        self.search.setPlaceholderText('搜索动作…')
        self.search.setAccessibleName('搜索动作')
        self.category = ModernSelect(self, width=140)
        self.category.setAccessibleName('动作分类')
        self.category.addItem('全部分类', '')
        filters = ResponsiveActionRow(self.search, [self.category], self)
        filters.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        layout.addWidget(filters)
        self.list = QListWidget(self)
        self.list.setObjectName('actionLibraryList')
        self.list.setAccessibleName('可播放动作')
        self.list.setMinimumHeight(220)
        self.list.setMaximumHeight(260)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(self.list)
        self.status = QLabel('打开动作库时读取桌宠动作。', self)
        self.status.setObjectName('settingHint')
        self.status.setWordWrap(True)
        self.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.refresh = QPushButton('刷新', self)
        self.refresh.setAccessibleName('刷新动作库')
        self.play = QPushButton('播放所选动作', self)
        self.play.setObjectName('actionPrimary')
        self.play.setAccessibleName('在桌宠窗口播放所选动作')
        self.play.setEnabled(False)
        footer = ResponsiveActionRow(self.status, [self.refresh, self.play], self)
        footer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        layout.addWidget(footer)
        self.search.textChanged.connect(self._filter)
        self.category.currentIndexChanged.connect(self._filter)
        self.list.currentItemChanged.connect(self._selection_changed)
        self.list.itemActivated.connect(lambda _item: self._play())
        self.play.clicked.connect(self._play)
        self.refresh.clicked.connect(self.reload)

    def _request(self, command, args, handler):
        generation = self._generation
        owner = weakref.ref(self)
        completed = False

        def received(response):
            nonlocal completed
            widget = owner()
            if widget is None or not shiboken6.isValid(widget) or widget._generation != generation:
                return
            if command != 'watch_actions' or not response['ok']:
                completed = True
                widget._requests.pop(command, None)
            getattr(widget, handler)(response)

        token = self.client.request(command, args, received)
        if not completed:
            self._requests[command] = token

    def showEvent(self, event):
        super().showEvent(event)
        self._generation += 1
        self._watch_seen = False
        self.reload()

    def hideEvent(self, event):
        self._generation += 1
        _cancel_requests(self.client, self._requests)
        self._pending = ''
        self._queued = ''
        self.play.setText('播放所选动作')
        self.refresh.setEnabled(True)
        self._selection_changed()
        super().hideEvent(event)

    def _current_changed(self, response):
        if not response['ok']:
            self._error = response['error']
            self._current = ''
            self._queued = ''
            self._watch_seen = False
            self._update_items()
            self._update_status()
            return
        name = response['data']['current']
        # The first watch response is a snapshot. If its name matches the
        # existing list snapshot, it cannot confirm a newly started replay.
        playback_event = self._watch_seen or name != self._current
        self._watch_seen = True
        if playback_event:
            self._watch_serial += 1
        self._current = name
        if playback_event and self._queued == self._current:
            self._queued = ''
        self._update_items()
        self._update_status()

    def reload(self):
        if 'list_actions' in self._requests:
            return
        self._error = ''
        self.refresh.setEnabled(False)
        self.status.setText('正在读取动作…')
        self._request('list_actions', {}, '_receive')
        if 'watch_actions' not in self._requests:
            self._request('watch_actions', {}, '_current_changed')

    def _receive(self, response):
        self.refresh.setEnabled(True)
        if not response['ok']:
            self._error = response['error']
            self._update_status()
            return
        data = response['data']
        self._actions = data['actions']
        # A list snapshot may arrive after a watch update. Only the watch owns
        # current playback once connected; play acknowledgements never own it.
        if not self._watch_seen:
            self._current = data['current']
        category = self.category.currentData()
        self.category.blockSignals(True)
        self.category.clear()
        self.category.addItem('全部分类', '')
        for value in sorted({item['category'] for item in self._actions}):
            self.category.addItem(CATEGORY_NAMES.get(value, value or '其他'), value)
        self.category.setCurrentData(category or '')
        self.category.blockSignals(False)
        self._filter()

    def _item_text(self, name, category):
        label = CATEGORY_NAMES.get(category, category or '其他')
        suffix = ' · 正在播放' if name == self._current else ''
        if name == self._queued:
            suffix += ' · 已排队'
        if name == self._pending:
            suffix += ' · 请求中'
        return f'{name}   ·   {label}{suffix}'

    def _update_items(self):
        categories = {action['name']: action['category'] for action in self._actions}
        for index in range(self.list.count()):
            item = self.list.item(index)
            name = item.data(Qt.ItemDataRole.UserRole)
            item.setText(self._item_text(name, categories.get(name, '')))
            item.setToolTip(item.text())
            item.setData(Qt.ItemDataRole.AccessibleDescriptionRole, item.text())

    def _filter(self, *_args):
        selected = self.list.currentItem()
        selected_name = selected.data(Qt.ItemDataRole.UserRole) if selected else None
        scroll = self.list.verticalScrollBar().value()
        self.list.blockSignals(True)
        self.list.clear()
        query = self.search.text().strip().casefold()
        category = self.category.currentData()
        restored = None
        for action in self._actions:
            if category and category != action['category']:
                continue
            if query and query not in action['name'].casefold():
                continue
            item = QListWidgetItem(vector_widget_icon(self, 'play', 18),
                                   self._item_text(action['name'], action['category']))
            item.setData(Qt.ItemDataRole.UserRole, action['name'])
            item.setToolTip(item.text())
            item.setData(Qt.ItemDataRole.AccessibleDescriptionRole, item.text())
            self.list.addItem(item)
            if action['name'] == selected_name:
                restored = item
        if restored is not None:
            self.list.setCurrentItem(restored)
            # clear() invalidates the item layout and scrollbar range. Rebuild
            # it before restoring the old position instead of clamping to zero.
            self.list.doItemsLayout()
            self.list.verticalScrollBar().setValue(scroll)
        elif self.list.count():
            self.list.setCurrentRow(0)
        self.list.blockSignals(False)
        self._selection_changed()

    def _selection_changed(self, *_args):
        self.play.setEnabled(self.list.currentItem() is not None and not self._pending)
        self._update_status()

    def _update_status(self):
        parts = [f'{self.list.count()} 个动作']
        item = self.list.currentItem()
        if item:
            parts.append(f'已选：{item.data(Qt.ItemDataRole.UserRole)}')
        if self._pending:
            parts.append(f'请求中：{self._pending}')
        elif self._queued:
            parts.append(f'已排队：{self._queued}')
        if self._current:
            parts.append(f'正在播放：{self._current}')
        if self._error:
            parts.append(self._error)
        self.status.setText(' · '.join(parts))
        self.status.setAccessibleDescription(self.status.text())

    def _play(self):
        item = self.list.currentItem()
        if item is None or self._pending:
            return
        self._pending = item.data(Qt.ItemDataRole.UserRole)
        self._play_watch_serial = self._watch_serial
        self._error = ''
        self.play.setText('正在请求…')
        self.play.setEnabled(False)
        self._update_items()
        self._update_status()
        self._request('play_action', {'name': self._pending}, '_played')

    def _played(self, response):
        self._pending = ''
        self.play.setText('播放所选动作')
        if not response['ok']:
            self._error = response['error']
        else:
            requested = response['data']['requested']
            # Play and watch use separate sockets, so a new playback event can
            # precede its acknowledgement. A matching old name alone does not
            # mean a same-name replay has started.
            started = self._watch_serial > self._play_watch_serial and self._current == requested
            self._queued = '' if started else requested
        self._update_items()
        self._selection_changed()
