# -*- coding: utf-8 -*-
"""动作收藏夹/播放列表的轻量选择窗口。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)


class ActionSetDialog(QDialog):
    """用系统复选列表编辑一组动作，返回用户勾选的动作名。"""

    def __init__(
        self,
        title: str,
        names: list[str],
        selected: list[str],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(360, 480)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("勾选动作后点击“完成”；播放列表会按当前顺序循环或随机播放。"))

        self.list_widget = QListWidget(self)
        selected_set = set(selected)
        for name in names:
            item = QListWidgetItem(name, self.list_widget)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked
                if name in selected_set
                else Qt.CheckState.Unchecked
            )
        layout.addWidget(self.list_widget)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_names(self) -> list[str]:
        names: list[str] = []
        for index in range(self.list_widget.count()):
            item = self.list_widget.item(index)
            if item.checkState() == Qt.CheckState.Checked:
                names.append(item.text())
        return names
