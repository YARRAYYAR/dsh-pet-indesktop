"""Local navigation channel between the pet and its isolated settings process."""
from __future__ import annotations

import hashlib
import json
import logging

from PySide6.QtCore import QObject, QTimer, Slot
from PySide6.QtNetwork import QLocalServer, QLocalSocket

log = logging.getLogger(__name__)
_PAGE_KEYS = {"codex"}


def page_key_from_argv(argv) -> str:
    try:
        index = argv.index("--settings-page")
    except ValueError:
        return ""
    if index + 1 >= len(argv):
        return ""
    page_key = str(argv[index + 1] or "").strip()
    return page_key if page_key in _PAGE_KEYS else ""


def endpoint(config) -> str:
    digest = hashlib.sha256(str(config.path.resolve()).encode()).hexdigest()[:16]
    return f"dsrp-nav-{digest}"


def select_settings_page(dialog, page_key: str, *, activate: bool = True) -> bool:
    """Select a page by a semantic dialog attribute, never by visible text."""
    if page_key not in _PAGE_KEYS:
        raise ValueError(f"不支持的设置页标识: {page_key}")
    target = getattr(dialog, "codex_page", None)
    pages = getattr(dialog, "pages", None)
    sidebar = getattr(dialog, "sidebar", None)
    if target is None or pages is None or sidebar is None:
        return False
    for index in range(pages.count()):
        page = pages.widget(index)
        if page is target or page.isAncestorOf(target):
            sidebar.setCurrentRow(index)
            if activate:
                if not dialog.isVisible():
                    dialog.show()
                dialog.raise_()
                dialog.activateWindow()
            return True
    return False


class SettingsProcessNavigationServer(QObject):
    """Accept page requests from the pet while one standalone settings window runs."""

    def __init__(self, config, dialog=None, parent=None):
        super().__init__(parent)
        config.dir.mkdir(parents=True, exist_ok=True)
        self._dialog = dialog
        self._pending_page_key = ""
        self._sockets = set()
        self._name = endpoint(config)
        self._server = QLocalServer(self)
        self._server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        if not self._server.listen(self._name):
            probe = QLocalSocket()
            probe.connectToServer(self._name)
            live = probe.waitForConnected(100)
            probe.abort()
            if not live:
                QLocalServer.removeServer(self._name)
            if live or not self._server.listen(self._name):
                raise RuntimeError(self._server.errorString())
        self._server.newConnection.connect(self._accept)

    def set_dialog(self, dialog, *, activate: bool = False) -> None:
        self._dialog = dialog
        if self._pending_page_key:
            page_key = self._pending_page_key
            self._pending_page_key = ""
            select_settings_page(dialog, page_key, activate=activate)

    def _accept(self) -> None:
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            socket.setReadBufferSize(65536)
            self._sockets.add(socket)
            socket.readyRead.connect(self._read)
            socket.disconnected.connect(self._discard)

    @Slot()
    def _discard(self) -> None:
        socket = self.sender()
        self._sockets.discard(socket)
        socket.deleteLater()

    @Slot()
    def _read(self) -> None:
        socket = self.sender()
        if not socket.canReadLine():
            if socket.bytesAvailable() >= 65536:
                socket.disconnectFromServer()
            return
        try:
            request = json.loads(bytes(socket.readLine()))
            if not isinstance(request, dict) or request.get("command") != "navigate":
                raise ValueError("无效的设置页导航命令")
            page_key = request.get("page_key")
            if not isinstance(page_key, str) or page_key not in _PAGE_KEYS:
                raise ValueError("无效的设置页标识")
            if self._dialog is None:
                self._pending_page_key = page_key
            elif not select_settings_page(self._dialog, page_key):
                raise ValueError(f"设置页暂不可用: {page_key}")
            response = {"ok": True}
        except (ValueError, UnicodeDecodeError) as exc:
            response = {"ok": False, "error": str(exc)}
        except Exception:
            log.exception("处理设置页导航请求失败")
            response = {"ok": False, "error": "设置页导航失败"}
        socket.write(json.dumps(response, ensure_ascii=False).encode() + b"\n")
        socket.disconnectFromServer()

    def close(self) -> None:
        self._server.close()
        for socket in tuple(self._sockets):
            # Closing must not run the disconnected slot while scheduling the
            # same socket for deferred deletion.
            socket.blockSignals(True)
            socket.abort()
            socket.deleteLater()
        self._sockets.clear()
        QLocalServer.removeServer(self._name)


class SettingsProcessNavigationClient(QObject):
    """Retry briefly while a newly launched settings process starts listening."""

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self._endpoint = endpoint(config)
        self._page_key = ""
        self._attempts = 0
        self._socket = QLocalSocket(self)
        self._connect_timer = QTimer(self)
        self._connect_timer.setSingleShot(True)
        self._connect_timer.setInterval(300)
        self._retry_timer = QTimer(self)
        self._retry_timer.setSingleShot(True)
        self._retry_timer.setInterval(100)
        self._response_timer = QTimer(self)
        self._response_timer.setSingleShot(True)
        self._response_timer.setInterval(1200)
        self._socket.connected.connect(self._send)
        self._socket.readyRead.connect(self._receive)
        self._socket.errorOccurred.connect(self._failed)
        self._connect_timer.timeout.connect(self._connect_timed_out)
        self._retry_timer.timeout.connect(self._connect)
        self._response_timer.timeout.connect(self._response_timed_out)

    def navigate(self, page_key: str) -> None:
        if page_key not in _PAGE_KEYS:
            raise ValueError(f"不支持的设置页标识: {page_key}")
        self._abort_socket()
        self._connect_timer.stop()
        self._retry_timer.stop()
        self._response_timer.stop()
        self._page_key = page_key
        self._attempts = 0
        self._connect()

    def _connect(self) -> None:
        if not self._page_key:
            return
        if self._attempts >= 20:
            log.warning("独立设置进程导航通道未就绪，未能切换到 %s 页", self._page_key)
            self._finish()
            return
        self._attempts += 1
        self._abort_socket()
        self._socket.connectToServer(self._endpoint)
        self._connect_timer.start()

    def _send(self) -> None:
        self._connect_timer.stop()
        request = {"command": "navigate", "page_key": self._page_key}
        self._socket.write(json.dumps(request).encode() + b"\n")
        self._response_timer.start()

    def _receive(self) -> None:
        if not self._socket.canReadLine():
            return
        try:
            response = json.loads(bytes(self._socket.readLine()))
        except (ValueError, UnicodeDecodeError):
            log.warning("独立设置进程返回了无效导航响应")
            self._finish()
            return
        if not isinstance(response, dict) or not response.get("ok"):
            log.warning("独立设置进程未能切换页面: %s", response.get("error", "无效响应") if isinstance(response, dict) else "无效响应")
        self._finish()

    def _failed(self, _error) -> None:
        if not self._page_key:
            return
        self._connect_timer.stop()
        if self._attempts >= 20:
            log.warning("连接独立设置进程导航通道失败: %s", self._socket.errorString())
            self._finish()
        else:
            self._retry_timer.start()

    def _connect_timed_out(self) -> None:
        if self._socket.state() == QLocalSocket.LocalSocketState.ConnectedState:
            return
        self._abort_socket()
        self._failed(self._socket.error())

    def _response_timed_out(self) -> None:
        log.warning("等待独立设置进程导航响应超时")
        self._finish()

    def _abort_socket(self) -> None:
        self._socket.blockSignals(True)
        self._socket.abort()
        self._socket.blockSignals(False)

    def _finish(self) -> None:
        self._connect_timer.stop()
        self._retry_timer.stop()
        self._response_timer.stop()
        self._page_key = ""
        self._abort_socket()

    def close(self) -> None:
        self._finish()
