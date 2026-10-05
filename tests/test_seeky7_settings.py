"""seeky.7 public Qt acceptance, authored before implementation.

Most paths use actual widgets/events and an isolated Config. OS motion preference
is injected to avoid changing user accessibility. Unexpected Config exceptions
and delayed/raising quit transport are injected because a real local server does
not reliably hold acknowledgement/duplicate-click ordering. Failure outcomes:
X/Esc/quit save false or raising -> remain open, never quit; pending -> one request;
failed/raising transport -> enabled retry plus footer error; success -> saved close.
"""
import json

import pytest
from PySide6.QtCore import QAbstractAnimation, QEvent, Qt, QVariantAnimation
from PySide6.QtWidgets import QApplication, QPushButton

from tests.test_seeky6_settings import ControlledClient as _ControlledClient


class ControlledClient(_ControlledClient):
    def close(self):
        pass


def open_dialog(qtbot, tmp_path, monkeypatch):
    from pet import autostart
    from pet.config import Config
    from pet.modern_settings_dialog import ModernSettingsDialog
    monkeypatch.setattr(autostart, 'is_enabled', lambda: False)
    config = Config(tmp_path)
    config.save()
    dialog = ModernSettingsDialog(config, include_ai=False, standalone=True)
    dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.activateWindow()
    qtbot.waitUntil(lambda: QApplication.activeWindow() is dialog)
    return dialog


def pane_for(dialog, title):
    for index in range(dialog.sidebar.count()):
        if dialog.sidebar.item(index).text() == title:
            return dialog.sidebar.itemWidget(dialog.sidebar.item(index))
    raise AssertionError(title)


def test_compact_tokens_and_metric_growth(qtbot, tmp_path, monkeypatch):
    dialog = open_dialog(qtbot, tmp_path, monkeypatch)
    sidebar = dialog.sidebar.parentWidget()
    assert sidebar.width() == 200
    assert sidebar.layout().contentsMargins().top() == 12
    assert sidebar.layout().spacing() == 6
    assert dialog.findChild(type(dialog.search_status), 'brandLogo').size().width() == 28
    pane = pane_for(dialog, '桌宠')
    pane.heading.click()
    qtbot.waitUntil(lambda: pane.heading.height() == 32)
    assert pane.children.findChild(QPushButton).height() == 28
    assert pane.children.layout().contentsMargins().left() == 20
    assert dialog.search_edit.height() == 32
    font = dialog.font()
    font.setPixelSize(30)
    dialog.setStyleSheet('')
    dialog.setFont(font)
    qtbot.waitUntil(lambda: pane.heading.height() >= pane.heading.fontMetrics().height() + 8)


def test_label_and_arrow_disclosure_independent_and_reuse_pages(qtbot, tmp_path, monkeypatch):
    dialog = open_dialog(qtbot, tmp_path, monkeypatch)
    pane = pane_for(dialog, '桌宠')
    page_ids = [id(dialog.pages.widget(i)) for i in range(dialog.pages.count())]
    pane_ids = [id(dialog.sidebar.itemWidget(dialog.sidebar.item(i))) for i in range(dialog.sidebar.count())]
    pane.heading.click()
    assert pane.children.isVisible()
    action = next(button for button in pane.children.findChildren(QPushButton) if button.text() == '动作库')
    action.click()
    pane.heading.click()
    assert pane.children.isVisible() and dialog.pet_tabs.currentKey() == 'actions'
    pane.disclosure.click()
    assert not pane.children.isVisible()
    pane.heading.click()
    assert not pane.children.isVisible()
    pane_for(dialog, '菜单').heading.click()
    pane.heading.click()
    assert not pane.children.isVisible() and dialog.pet_tabs.currentKey() == 'actions'
    assert page_ids == [id(dialog.pages.widget(i)) for i in range(dialog.pages.count())]
    assert pane_ids == [id(dialog.sidebar.itemWidget(dialog.sidebar.item(i))) for i in range(dialog.sidebar.count())]


def test_keyboard_visual_order_disclose_activate_and_focus_modality(qtbot, tmp_path, monkeypatch):
    dialog = open_dialog(qtbot, tmp_path, monkeypatch)
    pane = pane_for(dialog, '桌宠')
    qtbot.mouseClick(pane.heading, Qt.MouseButton.LeftButton)
    assert pane.heading.hasFocus() and not pane.heading.property('keyboardFocus')
    qtbot.keyClick(pane.heading, Qt.Key.Key_Left)
    assert not pane.children.isVisible()
    qtbot.keyClick(pane.heading, Qt.Key.Key_Right)
    assert pane.children.isVisible() and pane.heading.property('keyboardFocus')
    qtbot.keyClick(pane.heading, Qt.Key.Key_Down)
    assert QApplication.focusWidget() is pane.disclosure
    qtbot.keyClick(pane.disclosure, Qt.Key.Key_Tab)
    child = pane.children.findChildren(QPushButton)[0]
    assert QApplication.focusWidget() is child
    qtbot.keyClick(child, Qt.Key.Key_Down)
    next_child = pane.children.findChildren(QPushButton)[1]
    assert QApplication.focusWidget() is next_child
    qtbot.keyClick(next_child, Qt.Key.Key_Return)
    assert next_child.isChecked()


def test_motion_retarget_bounce_once_fixed_hit_rect_and_hidden_stop(qtbot, tmp_path, monkeypatch):
    from pet import ui_motion
    monkeypatch.setattr(ui_motion, 'reduced_motion_requested', lambda: False)
    dialog = open_dialog(qtbot, tmp_path, monkeypatch)
    pane = pane_for(dialog, '桌宠')
    button = pane.heading
    geometry = button.geometry()
    QApplication.sendEvent(button, QEvent(QEvent.Type.Enter))
    qtbot.waitUntil(lambda: 0 < button._hover < 1)
    midpoint = button._hover
    QApplication.sendEvent(button, QEvent(QEvent.Type.Leave))
    assert button._fade.startValue() == midpoint
    qtbot.mousePress(button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: button._press > .1)
    assert button.geometry() == geometry and button._paint_scale < 1
    qtbot.mouseRelease(button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: button._icon_scale > 1)
    qtbot.waitUntil(lambda: button._icon_scale == 1)
    button.click()
    assert button._icon_bounce.state() == QAbstractAnimation.State.Stopped
    assert dialog._navigation_pill._motion.duration() == 160
    assert dialog._page_transition.duration() == 120
    QApplication.sendEvent(button, QEvent(QEvent.Type.Enter))
    dialog.hide()
    assert all(animation.state() == QAbstractAnimation.State.Stopped for animation in dialog.findChildren(QVariantAnimation))


def test_reduced_motion_final_state(qtbot, tmp_path, monkeypatch):
    from pet import ui_motion
    monkeypatch.setattr(ui_motion, 'reduced_motion_requested', lambda: True)
    dialog = open_dialog(qtbot, tmp_path, monkeypatch)
    button = pane_for(dialog, '桌宠').heading
    button.click()
    assert button._icon_scale == 1
    assert dialog.pages.currentWidget().graphicsEffect().opacity() == 1
    assert all(animation.state() == QAbstractAnimation.State.Stopped for animation in dialog.findChildren(QVariantAnimation))


@pytest.mark.parametrize('path', ('escape', 'close', 'quit'))
@pytest.mark.parametrize('result', ('false', 'raise'))
def test_save_failure_or_exception_never_closes_or_quits(qtbot, tmp_path, monkeypatch, path, result):
    dialog = open_dialog(qtbot, tmp_path, monkeypatch)
    client = ControlledClient()
    dialog.command_client = client
    def write():
        if result == 'raise':
            raise OSError('受控保存异常')
        return False
    monkeypatch.setattr(dialog, '_write_config', write)
    if path == 'escape':
        qtbot.keyClick(dialog, Qt.Key.Key_Escape)
    elif path == 'close':
        dialog.close()
    else:
        dialog.quit_button.click()
    assert dialog.isVisible()
    assert not client.calls
    assert dialog.quit_button.isEnabled()
    assert dialog.footer_status.isVisible()
    assert '保存' in dialog.footer_status.text()


def test_single_footer_quit_deduplicates_errors_retry_and_external_reload(qtbot, tmp_path, monkeypatch):
    dialog = open_dialog(qtbot, tmp_path, monkeypatch)
    client = ControlledClient()
    dialog.command_client = client
    assert dialog.quit_button.text() == '退出软件'
    assert dialog.save_exit_button is dialog.quit_button
    assert len([button for button in dialog.sidebar.parentWidget().findChildren(QPushButton) if button.isVisible() and '退出' in button.text()]) == 1
    external = json.loads(dialog.config.path.read_text()) if dialog.config.path.exists() else {}
    external['screen_name'] = '保留外部字段'
    dialog.config.path.write_text(json.dumps(external))
    dialog.no_move_check.setChecked(True)
    dialog.quit_button.click()
    assert not dialog.quit_button.isEnabled()
    dialog.quit_button.click()
    assert len(client.calls) == 1 and client.calls[0][0] == 'quit'
    saved = json.loads(dialog.config.path.read_text())
    assert saved['screen_name'] == '保留外部字段' and saved['no_move']
    client.reply('quit', error='连接失败，请重试')
    assert dialog.quit_button.isEnabled() and dialog.footer_status.isVisible()
    assert '连接失败' in dialog.footer_status.text()
    dialog.quit_button.click()
    client.reply('quit', {})
    assert not dialog.isVisible()


def test_raising_quit_transport_restores_retry(qtbot, tmp_path, monkeypatch):
    dialog = open_dialog(qtbot, tmp_path, monkeypatch)
    def request(*args):
        raise OSError('连接中断')
    monkeypatch.setattr(dialog.command_client, 'request', request)
    dialog.quit_button.click()
    assert dialog.isVisible() and dialog.quit_button.isEnabled()
    assert '连接中断' in dialog.footer_status.text()
