"""Identity and navigation chrome, separate from persistent settings owners."""
import logging
import weakref

import shiboken6
from PySide6.QtCore import QAbstractAnimation, QSize, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from .branding import NAME, DISPLAY_VERSION, brand_icon
from .context_menus.icons import vector_widget_icon
from .settings_widgets import SettingsTabContainer
from .settings_navigation import NavigationDelegate, NavigationSelectionPill, SidebarNavigationButton
from .ui_motion import StateTransition

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
    row.setContentsMargins(4, 4, 0, 8)
    row.setSpacing(10)
    logo = QLabel(header)
    pixmap = brand_icon().pixmap(QSize(28, 28), dialog.devicePixelRatioF())
    logo.setPixmap(pixmap)
    logo.setObjectName('brandLogo')
    logo.setFixedSize(28, 28)
    title = QLabel(NAME, header)
    title.setObjectName('brandTitle')
    row.addWidget(logo)
    row.addWidget(title, 1)
    layout.addWidget(header)


def add_footer(dialog, layout):
    # Keep the old attribute as an alias for callers, with only one live action.
    dialog.quit_button = dialog.save_exit_button
    dialog.quit_button.clicked.disconnect()
    dialog.quit_button.setText('退出软件')
    dialog.quit_button.setObjectName('quitApplication')
    dialog.quit_button.setIcon(vector_widget_icon(dialog, 'power', 18))
    dialog.quit_button.setAccessibleName('保存设置并退出软件')
    dialog.quit_button.setAccessibleDescription('保存成功后退出所有桌宠；关闭设置窗口可用 Esc。')
    dialog.quit_button.setAutoDefault(False)
    dialog.quit_button.clicked.connect(lambda: _quit(dialog))
    layout.addWidget(dialog.quit_button)
    dialog.footer_status = QLabel(dialog)
    dialog.footer_status.setObjectName('footerStatus')
    dialog.footer_status.setWordWrap(True)
    dialog.footer_status.hide()
    layout.addWidget(dialog.footer_status)
    version = QLabel(f'{NAME}  {DISPLAY_VERSION}', dialog)
    version.setObjectName('brandVersion')
    layout.addWidget(version)


def save_before_close(dialog):
    """All finish paths retain the form when persistence or applying fails."""
    try:
        if not dialog._write_config():
            dialog.footer_status.setText('保存失败，请修正问题后重试。')
            dialog.footer_status.show()
            return False
        dialog._apply_autostart()
    except Exception as error:
        logging.exception('保存并应用设置失败')
        dialog.footer_status.setText(f'保存失败：{error}')
        dialog.footer_status.show()
        return False
    dialog.footer_status.hide()
    return True


def _quit(dialog):
    if getattr(dialog, '_quit_request_pending', False):
        return
    dialog._quit_request_pending = True
    dialog.quit_button.setEnabled(False)
    if not save_before_close(dialog):
        dialog._quit_request_pending = False
        dialog.quit_button.setEnabled(True)
        return
    reference = weakref.ref(dialog)

    def finished(response):
        host = reference()
        if host is None or not shiboken6.isValid(host):
            return  # App shutdown disposed the form before the transport reply.
        host._quit_request_pending = False
        host.quit_button.setEnabled(True)
        if response['ok']:
            host._saved_via_button = True
            host.accept()
        else:
            host.footer_status.setText(response['error'])
            host.footer_status.show()

    try:
        dialog.command_client.request('quit', {}, finished)
    except Exception as error:
        logging.exception('请求退出软件失败')
        finished({'ok': False, 'error': f'连接失败：{error}'})


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
        if selected and not pane.visited:
            pane.visited = True
            pane.expanded = pane.children is not None
        _disclose_domain(dialog, item, pane)
    dialog.sidebar.doItemsLayout()
    if not hasattr(dialog, '_navigation_pill'):
        dialog._navigation_pill = NavigationSelectionPill(dialog.sidebar)
    dialog._navigation_pill.reposition()
    _tab_order(dialog)


def _disclose_domain(dialog, item, pane):
    expanded = pane.expanded and pane.heading._selected
    if pane.children is not None:
        pane.children.setVisible(expanded)
        pane.disclosure.blockSignals(True)
        pane.disclosure.setChecked(pane.expanded)
        pane.disclosure.blockSignals(False)
        pane.disclosure.setAccessibleName(f'{item.text()}：{"收起" if pane.expanded else "展开"}子页面')
    pane.layout().invalidate()
    pane.layout().activate()
    item.setSizeHint(QSize(0, pane.sizeHint().height() if expanded else pane.heading.sizeHint().height()))
    dialog.sidebar.doItemsLayout()


def _visible_navigation(dialog):
    buttons = []
    for index in range(dialog.sidebar.count()):
        pane = dialog.sidebar.itemWidget(dialog.sidebar.item(index))
        if pane is None:
            continue
        buttons.append(pane.heading)
        if pane.disclosure is not None:
            buttons.append(pane.disclosure)
        if pane.children is not None and pane.children.isVisible():
            buttons.extend(pane.children.findChildren(SidebarNavigationButton))
    return buttons


def _tab_order(dialog):
    buttons = [dialog.search_edit, *_visible_navigation(dialog), dialog.quit_button]
    for before, after in zip(buttons, buttons[1:]):
        QWidget.setTabOrder(before, after)


def _navigation_key(dialog, item, pane, button, key):
    if key in (Qt.Key.Key_Left, Qt.Key.Key_Right) and pane.children is not None:
        pane.expanded = key == Qt.Key.Key_Right
        if not pane.expanded and pane.children.isAncestorOf(button):
            pane.heading.setFocus(Qt.FocusReason.TabFocusReason)
        _disclose_domain(dialog, item, pane)
        dialog._navigation_pill.reposition(animate=False)
        _tab_order(dialog)
        return True
    if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
        buttons = _visible_navigation(dialog)
        index = buttons.index(button)
        target = max(0, min(len(buttons) - 1, index + (-1 if key == Qt.Key.Key_Up else 1)))
        focused = buttons[target]
        focused.setFocus(Qt.FocusReason.TabFocusReason)
        for row in range(dialog.sidebar.count()):
            target_item = dialog.sidebar.item(row)
            target_pane = dialog.sidebar.itemWidget(target_item)
            if target_pane is not None and target_pane.isAncestorOf(focused):
                dialog.sidebar.scrollToItem(target_item)
                break
        return True
    return False


def _domain_navigation_row(dialog, item, index):
    pane = QFrame(dialog.sidebar)
    layout = QVBoxLayout(pane)
    layout.setContentsMargins(10, 0, 6, 0)
    layout.setSpacing(2)
    heading = SidebarNavigationButton(item.text(), pane)
    settings_icon = {'常规': 'settings-gear', '桌宠': 'settings-face',
                     '互动': 'settings-click', '菜单': 'settings-menu',
                     '连接': 'settings-link', '自动化与联动': 'settings-workflow',
                     '语音': 'settings-speaker'}.get(item.text())
    heading.setIcon(vector_widget_icon(dialog, settings_icon, 18) if settings_icon else item.icon())
    heading.setObjectName('sidebarDomainHeading')
    heading.setIconSize(QSize(18, 18))
    header = QHBoxLayout()
    header.setContentsMargins(0, 0, 0, 0)
    header.setSpacing(0)
    header.addWidget(heading, 1)
    layout.addLayout(header)
    pane.heading = heading
    pane.children = None
    pane.disclosure = None
    pane.expanded = False
    pane.visited = False
    heading.setAccessibleName(item.text())
    heading.setToolTip(item.text())
    heading._keyboard_handler = lambda button, key: _navigation_key(dialog, item, pane, button, key)
    heading.metricsChanged.connect(lambda: _disclose_domain(dialog, item, pane))
    tabs = dialog.pages.widget(index).findChildren(SettingsTabContainer)
    if tabs:
        tasks = tabs[0]
        tasks.tab_bar.hide()
        arrow = SidebarNavigationButton('', pane, disclosure=True)
        pane.disclosure = arrow
        arrow.setObjectName('sidebarDisclosure')
        arrow.setCheckable(True)
        arrow.setFixedWidth(24)
        arrow._keyboard_handler = heading._keyboard_handler
        header.addWidget(arrow)
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
            tasks._buttons[task_index].toggled.connect(lambda checked: transition_page(dialog) if checked else None)
            button.setAccessibleName(f'{item.text()}：{title}')
            button._keyboard_handler = heading._keyboard_handler
            button.metricsChanged.connect(lambda: _disclose_domain(dialog, item, pane))
            child_layout.addWidget(button)
        def disclose(expanded):
            pane.expanded = expanded
            pane.visited = True
            _disclose_domain(dialog, item, pane)
            dialog._navigation_pill.reposition(animate=False)
            _tab_order(dialog)
        arrow.toggled.connect(disclose)
        children.hide()
    heading.clicked.connect(lambda _checked=False: dialog.sidebar.setCurrentRow(index))
    return pane


def transition_page(dialog):
    """A short fade has one dialog owner; settled effects bypass compositing."""
    if not hasattr(dialog, '_page_transition'):
        def advance(value):
            page = dialog.pages.currentWidget()
            if page is not None:
                effect = page.graphicsEffect()
                if effect is None:
                    effect = QGraphicsOpacityEffect(page)
                    page.setGraphicsEffect(effect)
                effect.setEnabled(value < 1)
                effect.setOpacity(value)
        dialog._page_transition = StateTransition(dialog, 120, advance, 1.0)
    previous = getattr(dialog, '_transition_page', None)
    current = dialog.pages.currentWidget()
    if previous is not current and previous is not None and previous.graphicsEffect() is not None:
        previous.graphicsEffect().setEnabled(False)
        previous.graphicsEffect().setOpacity(1.0)
    dialog._transition_page = current
    active = dialog._page_transition.state() == QAbstractAnimation.State.Running
    if not active:
        dialog._page_transition.snap(.90)
    dialog._page_transition.move_to(1.0)


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
