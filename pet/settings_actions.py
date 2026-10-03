"""A static action browser; playback stays in the pet's existing player."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from .settings_widgets import ModernSelect
from .context_menus.icons import vector_widget_icon

CATEGORY_NAMES = {'idle': '待机', 'turn': '转向', 'idle_turn': '待机与转向',
                  'move': '移动', 'click': '点击回应', 'drag': '拖拽',
                  'random': '日常动作', 'events': '事件动作'}


class ActionLibrary(QWidget):
    def __init__(self, client, parent=None):
        super().__init__(parent)
        self.client = client
        self._actions = []
        self._current = ''
        self._watch = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        hint = QLabel('选择一个动作，让桌宠播放。动作结束后继续原有活动。', self)
        hint.setObjectName('settingHint')
        hint.setWordWrap(True)
        hint.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        layout.addWidget(hint)
        filters = QHBoxLayout()
        self.search = QLineEdit(self)
        self.search.setPlaceholderText('搜索动作…')
        self.search.setAccessibleName('搜索动作')
        self.category = ModernSelect(self, width=140)
        self.category.setAccessibleName('动作分类')
        self.category.addItem('全部分类', '')
        filters.addWidget(self.search, 1)
        filters.addWidget(self.category)
        layout.addLayout(filters)
        self.list = QListWidget(self)
        self.list.setObjectName('actionLibraryList')
        self.list.setAccessibleName('可播放动作')
        self.list.setMinimumHeight(220)
        self.list.setMaximumHeight(260)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(self.list)
        footer = QHBoxLayout()
        self.status = QLabel('打开动作库时读取桌宠动作。', self)
        self.status.setObjectName('settingHint')
        self.status.setWordWrap(True)
        self.refresh = QPushButton('刷新', self)
        self.play = QPushButton('播放所选动作', self)
        self.play.setObjectName('actionPrimary')
        self.play.setEnabled(False)
        footer.addWidget(self.status, 1)
        footer.addWidget(self.refresh)
        footer.addWidget(self.play)
        layout.addLayout(footer)
        self.search.textChanged.connect(self._filter)
        self.category.currentIndexChanged.connect(self._filter)
        self.list.currentItemChanged.connect(lambda *_: self.play.setEnabled(self.list.currentItem() is not None))
        self.list.itemActivated.connect(lambda _item: self._play())
        self.play.clicked.connect(self._play)
        self.refresh.clicked.connect(self.reload)

    def showEvent(self, event):
        super().showEvent(event)
        self.reload()
        self._watch = self.client.request('watch_actions', {}, self._current_changed)

    def hideEvent(self, event):
        if self._watch is not None:
            self.client.cancel(self._watch)
            self._watch = None
        super().hideEvent(event)

    def _current_changed(self, response):
        if response['ok']:
            self._current = response['data']['current']
            for index in range(self.list.count()):
                item = self.list.item(index)
                name = item.data(Qt.ItemDataRole.UserRole)
                category = next(action['category'] for action in self._actions if action['name'] == name)
                label = CATEGORY_NAMES.get(category, category or '其他')
                suffix = ' · 当前播放' if name == self._current else ''
                item.setText(f'{name}   ·   {label}{suffix}')

    def reload(self):
        self.status.setText('正在读取动作…')
        self.client.request('list_actions', {}, self._receive)

    def _receive(self, response):
        if not response['ok']:
            self.status.setText(response['error'])
            return
        data = response['data']
        self._actions = data['actions']
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

    def _filter(self, *_args):
        self.list.clear()
        query = self.search.text().strip().casefold()
        category = self.category.currentData()
        for action in self._actions:
            if category and category != action['category']:
                continue
            if query and query not in action['name'].casefold():
                continue
            label = CATEGORY_NAMES.get(action['category'], action['category'] or '其他')
            suffix = ' · 当前播放' if action['name'] == self._current else ''
            item = QListWidgetItem(vector_widget_icon(self, 'play', 18),
                                   f"{action['name']}   ·   {label}{suffix}")
            item.setData(Qt.ItemDataRole.UserRole, action['name'])
            item.setToolTip(item.text())
            self.list.addItem(item)
        self.status.setText(f'{self.list.count()} 个动作 · 在桌宠窗口播放')
        if self.list.count():
            self.list.setCurrentRow(0)

    def _play(self):
        item = self.list.currentItem()
        if item is None:
            return
        self.play.setEnabled(False)
        self.client.request('play_action', {'name': item.data(Qt.ItemDataRole.UserRole)}, self._played)

    def _played(self, response):
        self.play.setEnabled(self.list.currentItem() is not None)
        if not response['ok']:
            self.status.setText(response['error'])
            return
        data = response['data']
        self._current = data['current']
        self._filter()
        self.status.setText(f"已播放：{data['requested']}" if data['requested'] == data['current']
                            else f"已排队：{data['requested']} · 当前动作结束后播放")
