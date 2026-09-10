"""Two-pane action library, shared by settings and the standalone editor."""
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QHBoxLayout, QListWidget, QListWidgetItem, QLineEdit, QMessageBox,
    QSplitter, QVBoxLayout, QWidget,
)
from .playlist import read_playlist, write_playlist
from .ui_style import apply_style, button, label


class ActionLibraryWidget(QWidget):
    previewRequested = Signal(str)

    def __init__(self, names, selected, parent=None, *, allow_exchange=False, favorites=()):
        super().__init__(parent)
        self._names = list(dict.fromkeys(names))
        self._favorites = set(favorites)
        self._preview_name = None
        self._icons = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        self.search = QLineEdit()
        self.search.setPlaceholderText('搜索动作名称…')
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName('搜索全部动作')
        self.filter = QComboBox()
        self.filter.addItems(['全部动作', '收藏动作'])
        toolbar = QHBoxLayout()
        toolbar.addWidget(self.search, 1)
        toolbar.addWidget(self.filter)
        if allow_exchange:
            toolbar.addWidget(button('导入', self.import_playlist))
            toolbar.addWidget(button('导出', self.export_playlist))
        layout.addLayout(toolbar)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(12)
        left, right = QWidget(), QWidget()
        left_layout, right_layout = QVBoxLayout(left), QVBoxLayout(right)
        for column in (left_layout, right_layout):
            column.setContentsMargins(0, 0, 0, 0)
            column.setSpacing(8)
        self.catalog_title = label('全部动作', 'sectionTitle')
        left_layout.addWidget(self.catalog_title)
        self.catalog_list = QListWidget()
        self.catalog_list.setAccessibleName('全部动作')
        self.catalog_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.catalog_list.setIconSize(QSize(36, 36))
        for name in self._names:
            item = QListWidgetItem(name, self.catalog_list)
            item.setToolTip(name)
        left_layout.addWidget(self.catalog_list, 1)
        left_buttons = QHBoxLayout()
        self.preview_button = button('预览动作', self.preview_current)
        self.add = button('加入列表 →', self.add_selected, primary=True)
        self.preview_button.setEnabled(False)
        self.add.setEnabled(False)
        left_buttons.addWidget(self.preview_button)
        left_buttons.addWidget(self.add)
        left_layout.addLayout(left_buttons)
        self.playlist_title = label('播放列表 · 0', 'sectionTitle')
        right_layout.addWidget(self.playlist_title)
        self.list_widget = QListWidget()
        self.list_widget.setAccessibleName('已选动作顺序')
        self.list_widget.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.list_widget.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        right_layout.addWidget(self.list_widget, 1)
        controls = QHBoxLayout()
        self.up = button('上移', lambda: self.move_current(-1))
        self.down = button('下移', lambda: self.move_current(1))
        self.remove = button('移除', self.remove_current)
        self.sort_name = button('按名称', lambda: self.list_widget.sortItems())
        for control in (self.up, self.down, self.remove, self.sort_name):
            controls.addWidget(control)
        right_layout.addLayout(controls)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setChildrenCollapsible(False)
        splitter.setSizes([360, 320])
        layout.addWidget(splitter, 1)
        self.status = label('')
        layout.addWidget(self.status)
        self.search.textChanged.connect(self.filter_actions)
        self.filter.currentIndexChanged.connect(self.filter_actions)
        self.catalog_list.itemSelectionChanged.connect(self._catalog_selection)
        self.catalog_list.itemDoubleClicked.connect(lambda _: self.add_selected())
        self.list_widget.currentItemChanged.connect(self._playlist_selection)
        self.list_widget.model().rowsMoved.connect(self.update_status)
        self._populate(selected)

    def _populate(self, selected):
        self.list_widget.clear()
        for name in dict.fromkeys(selected):
            if name in self._names:
                self._append(name)
        self.filter_actions()

    def _append(self, name):
        item = QListWidgetItem(name, self.list_widget)
        item.setToolTip(name)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsDropEnabled)
        if name in self._icons:
            item.setIcon(self._icons[name])

    def selected_names(self):
        return [self.list_widget.item(i).text() for i in range(self.list_widget.count())]

    def filter_actions(self):
        query = self.search.text().strip().casefold()
        favorites_only = self.filter.currentIndex() == 1
        for i in range(self.catalog_list.count()):
            item = self.catalog_list.item(i)
            item.setHidden(query not in item.text().casefold() or (favorites_only and item.text() not in self._favorites))
        self._catalog_selection()
        self.update_status()

    def _catalog_selection(self):
        items = [item for item in self.catalog_list.selectedItems() if not item.isHidden()]
        self.add.setEnabled(bool(items))
        self._preview_name = items[0].text() if items else None
        self.preview_button.setEnabled(bool(self._preview_name))

    def _playlist_selection(self):
        item = self.list_widget.currentItem()
        if item is not None:
            self._preview_name = item.text()
            self.preview_button.setEnabled(True)
        self.update_status()

    def add_selected(self):
        existing = set(self.selected_names())
        for item in self.catalog_list.selectedItems():
            if not item.isHidden() and item.text() not in existing:
                self._append(item.text())
                existing.add(item.text())
        self.update_status()

    def remove_current(self):
        row = self.list_widget.currentRow()
        if row >= 0:
            self.list_widget.takeItem(row)
        self.update_status()

    def move_current(self, offset):
        row = self.list_widget.currentRow()
        target = row + offset
        if row < 0 or not 0 <= target < self.list_widget.count():
            return
        item = self.list_widget.takeItem(row)
        self.list_widget.insertItem(target, item)
        self.list_widget.setCurrentItem(item)
        self.update_status()

    def update_status(self):
        visible = sum(not self.catalog_list.item(i).isHidden() for i in range(self.catalog_list.count()))
        count = self.list_widget.count()
        row = self.list_widget.currentRow()
        self.catalog_title.setText(f'全部动作 · {visible} / {len(self._names)}')
        self.playlist_title.setText(f'播放列表 · {count}')
        self.up.setEnabled(row > 0)
        self.down.setEnabled(0 <= row < count - 1)
        self.remove.setEnabled(row >= 0)
        self.sort_name.setEnabled(count > 1)
        self.status.setText('没有匹配动作，试试其他关键词。' if not visible else
            '从左侧加入动作；右侧拖动排序，搜索时也能调整。' if not count else
            f'已选 {count} 个动作 · 拖动右侧列表调整播放顺序')

    def preview_current(self):
        if self._preview_name:
            self.previewRequested.emit(self._preview_name)

    def set_thumbnail(self, name, pixmap):
        if pixmap.isNull() or name not in self._names:
            return
        self._icons[name] = QIcon(pixmap.scaled(36, 36, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation))
        if len(self._icons) > 16:
            del self._icons[next(iter(self._icons))]
        for listing in (self.catalog_list, self.list_widget):
            for i in range(listing.count()):
                item = listing.item(i)
                item.setIcon(self._icons.get(item.text(), QIcon()))

    def import_playlist(self):
        path, _ = QFileDialog.getOpenFileName(self, '导入播放列表', '', '播放列表 (*.json)')
        if not path:
            return
        try:
            selected, missing = read_playlist(path, self._names)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, '无法导入', str(exc))
            return
        self._populate(selected)
        message = f'已载入 {len(selected)} 个动作，保存后应用。'
        if missing:
            message += f' 跳过 {len(missing)} 个缺失动作：' + '、'.join(name[:50] for name in missing[:3])
            if len(missing) > 3:
                message += '…'
        self.status.setText(message)

    def export_playlist(self):
        path, _ = QFileDialog.getSaveFileName(self, '导出播放列表', '桌宠播放列表.json', '播放列表 (*.json)')
        if not path:
            return
        try:
            write_playlist(path, self.selected_names())
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, '无法导出', str(exc))
            return
        self.status.setText(f'已导出 {self.list_widget.count()} 个动作的顺序；不包含视频。')


class ActionSetDialog(QDialog):
    def __init__(self, title, names, selected, parent=None, *, allow_exchange=False):
        super().__init__(parent)
        self._original_playback = None
        self._did_preview = False
        if parent is not None and hasattr(parent, '_switch'):
            self._original_playback = (parent.anim, parent._paused, parent.isVisible(), parent._suspended)
        self.setWindowTitle(title)
        self.setMinimumSize(740, 480)
        self.resize(860, 570)
        apply_style(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(14)
        layout.addWidget(label(title, 'title'))
        self.editor = ActionLibraryWidget(names, selected, self, allow_exchange=allow_exchange,
            favorites=getattr(parent, 'favorites', ()))
        layout.addWidget(self.editor, 1)
        if parent is not None and hasattr(parent, '_switch'):
            self.editor.previewRequested.connect(self._preview)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('保存列表')
        buttons.button(QDialogButtonBox.StandardButton.Ok).setObjectName('primary')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _preview(self, name):
        pet = self.parentWidget()
        self._did_preview = True
        pet.show()
        pet.resume_animation()
        pet.set_paused(False)
        pet._switch(name)

    def reject(self):
        if self._did_preview and self._original_playback is not None:
            pet = self.parentWidget()
            anim, paused, visible, suspended = self._original_playback
            pet._switch(anim)
            pet.set_paused(paused)
            if suspended:
                pet.suspend_animation()
            if not visible:
                pet.hide()
        super().reject()

    def selected_names(self):
        return self.editor.selected_names()
