"""Identity and navigation chrome, separate from persistent settings owners."""
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from .branding import NAME, DISPLAY_VERSION, brand_icon
from .context_menus.icons import vector_widget_icon
from .settings_widgets import SettingsTabContainer
from .settings_navigation import NavigationDelegate, SidebarNavigationButton

PAGE_DESCRIPTIONS = {
    '常规': '管理启动、窗口和桌面显示。',
    '通用': '管理启动、窗口和桌面显示。',
    '桌宠': '调整角色显示与活动，浏览完整动作库。',
    '互动': '设置点击回应、音效和自言自语。',
    '菜单': '编排右键菜单、快捷启动和外观。',
    '提醒': '管理报时、节日和待办提醒。',
    '通知': '设置事件通知与提示。',
    '连接': '管理桌宠与本地工具的连接。',
    '高级': '查看运行选项与高级设置。',
    '自动化与联动': '管理本地工具连接、报时和节日提醒。',
    '语音': '设置语音服务与播放。',
    '文件识别': '管理支持识别的文件类型和处理方式。',
}


def add_identity(dialog, layout):
    header = QWidget(dialog)
    row = QHBoxLayout(header)
    row.setContentsMargins(4, 12, 0, 16)
    row.setSpacing(10)
    logo = QLabel(header)
    pixmap = brand_icon().pixmap(36, 36)
    logo.setPixmap(pixmap)
    logo.setFixedSize(36, 36)
    title = QLabel(NAME, header)
    title.setObjectName('brandTitle')
    row.addWidget(logo)
    row.addWidget(title, 1)
    layout.addWidget(header)


def add_footer(dialog, layout):
    dialog.save_exit_button.setText('保存并关闭设置')
    dialog.save_exit_button.setAccessibleName('保存设置并关闭窗口')
    layout.addWidget(dialog.save_exit_button)
    dialog.quit_button = QPushButton(f'退出 {NAME}', dialog)
    dialog.quit_button.setObjectName('quitApplication')
    dialog.quit_button.setIcon(vector_widget_icon(dialog, 'power', 18))
    dialog.quit_button.setAccessibleName(f'退出 {NAME}')
    dialog.quit_button.setAutoDefault(False)
    dialog.quit_button.clicked.connect(lambda: _quit(dialog))
    layout.addWidget(dialog.quit_button)
    version = QLabel(f'{NAME}  {DISPLAY_VERSION}', dialog)
    version.setObjectName('brandVersion')
    layout.addWidget(version)


def _quit(dialog):
    if not dialog._write_config():
        return
    dialog.quit_button.setEnabled(False)

    def finished(response):
        dialog.quit_button.setEnabled(True)
        if response['ok']:
            dialog._saved_via_button = True
            dialog._apply_autostart()
            dialog.accept()
        else:
            dialog.search_status.setText(response['error'])
            dialog.search_status.show()

    dialog.command_client.request('quit', {}, finished)


def apply_dark_palette(dialog):
    palette = QPalette(dialog.palette())
    for role, value in ((QPalette.ColorRole.Window, '#141416'),
                        (QPalette.ColorRole.WindowText, '#f5f5f7'),
                        (QPalette.ColorRole.Base, '#1c1c1e'),
                        (QPalette.ColorRole.Text, '#f5f5f7'),
                        (QPalette.ColorRole.ButtonText, '#f5f5f7'),
                        (QPalette.ColorRole.Highlight, '#0a84ff')):
        palette.setColor(role, QColor(value))
    dialog.setPalette(palette)


def expand_domain_navigation(dialog, row):
    """Update stable row widgets so navigation preserves keyboard focus."""
    if not isinstance(dialog.sidebar.itemDelegate(), NavigationDelegate):
        dialog.sidebar.setItemDelegate(NavigationDelegate(dialog.sidebar))
    for index in range(dialog.sidebar.count()):
        item = dialog.sidebar.item(index)
        pane = dialog.sidebar.itemWidget(item)
        if pane is None:
            pane = _domain_navigation_row(dialog, item, index)
            dialog.sidebar.setItemWidget(item, pane)
        selected = index == row
        pane.heading.setSelected(selected)
        pane.setObjectName('expandedDomainNavigation' if selected else 'domainNavigation')
        pane.heading.blockSignals(True)
        pane.heading.setChecked(selected and pane.children is not None)
        pane.heading.blockSignals(False)
        _disclose_domain(item, pane, selected and pane.children is not None)


def _disclose_domain(item, pane, expanded):
    if pane.children is not None:
        pane.children.setVisible(expanded)
        suffix = ('  ⌄' if expanded else '  ›') if pane.heading._selected else ''
        pane.heading.setText(item.text() + suffix)
        pane.heading.setAccessibleName(f'{item.text()}：{"收起" if expanded else "展开"}子页面')
    else:
        pane.heading.setText(item.text())
        pane.heading.setAccessibleName(item.text())
    item.setSizeHint(QSize(0, pane.sizeHint().height() if expanded else 40))


def _domain_navigation_row(dialog, item, index):
    pane = QFrame(dialog.sidebar)
    layout = QVBoxLayout(pane)
    layout.setContentsMargins(10, 8, 6, 6)
    layout.setSpacing(2)
    heading = SidebarNavigationButton(item.text(), pane)
    settings_icon = {'常规': 'settings-gear', '桌宠': 'settings-paw',
                     '互动': 'settings-click', '菜单': 'settings-menu',
                     '连接': 'settings-link', '自动化与联动': 'settings-workflow',
                     '语音': 'settings-speaker'}.get(item.text())
    heading.setIcon(vector_widget_icon(dialog, settings_icon, 18) if settings_icon else item.icon())
    heading.setObjectName('sidebarDomainHeading')
    heading.setMinimumHeight(24)
    heading.setIconSize(QSize(18, 18))
    layout.addWidget(heading)
    pane.heading = heading
    pane.children = None
    tabs = dialog.pages.widget(index).findChildren(SettingsTabContainer)
    if tabs:
        tasks = tabs[0]
        tasks.tab_bar.hide()
        heading.setCheckable(True)
        children = QWidget(pane)
        pane.children = children
        child_layout = QVBoxLayout(children)
        child_layout.setContentsMargins(20, 0, 0, 0)
        child_layout.setSpacing(2)
        layout.addWidget(children)
        for task_index, (key, title) in enumerate(zip(tasks.keys(), tasks.labels())):
            button = SidebarNavigationButton(title, children, secondary=True)
            button.setObjectName('sidebarSubtask')
            button.setCheckable(True)
            button.setAutoExclusive(True)
            button.setChecked(tasks.currentKey() == key)
            button.clicked.connect(lambda _checked=False, key=key, tasks=tasks: tasks.setCurrentKey(key))
            tasks._buttons[task_index].toggled.connect(button.setChecked)
            button.setAccessibleName(f'{item.text()}：{title}')
            child_layout.addWidget(button)
        heading.toggled.connect(lambda expanded: _disclose_domain(item, pane, expanded)
                                if dialog.sidebar.currentRow() == index else None)
        children.hide()
    heading.clicked.connect(lambda _checked=False: dialog.sidebar.setCurrentRow(index))
    return pane


def page_heading(page, title, max_width):
    host = QWidget(page)
    host.setObjectName('pageHeader')
    host.setMaximumWidth(max_width)
    host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    layout = QVBoxLayout(host)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    heading = QLabel(title, host)
    heading.setObjectName('pageTitle')
    layout.addWidget(heading)
    description = QLabel(PAGE_DESCRIPTIONS.get(title, '管理此功能的设置。'), host)
    description.setObjectName('pageDescription')
    description.setWordWrap(True)
    layout.addWidget(description)
    return host
