"""Small, event-driven local command seam for the isolated settings process."""
from __future__ import annotations

import hashlib
import json

from PySide6.QtCore import QObject, QLockFile, QTimer
from PySide6.QtNetwork import QLocalServer, QLocalSocket


def endpoint(config) -> str:
    digest = hashlib.sha256(str(config.path.resolve()).encode()).hexdigest()[:16]
    return f'dsrp-{digest}'


class SettingsCommandServer(QObject):
    def __init__(self, config, handler, parent=None):
        super().__init__(parent)
        config.dir.mkdir(parents=True, exist_ok=True)
        self._handler = handler
        self._lock = QLockFile(str(config.path.with_suffix('.control.lock')))
        self._server = QLocalServer(self)
        self._server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self._sockets = set()
        self._subscribers = set()
        if not self._lock.tryLock(0):
            raise RuntimeError('桌宠控制通道已被占用')
        name = endpoint(config)
        if not self._server.listen(name):
            probe = QLocalSocket()
            probe.connectToServer(name)
            live = probe.waitForConnected(100)
            probe.abort()
            if not live:
                QLocalServer.removeServer(name)
            if live or not self._server.listen(name):
                self._lock.unlock()
                raise RuntimeError(self._server.errorString())
        self._server.newConnection.connect(self._accept)

    def _accept(self):
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            socket.setReadBufferSize(65536)
            self._sockets.add(socket)
            socket.readyRead.connect(lambda socket=socket: self._read(socket))
            socket.disconnected.connect(lambda socket=socket: self._discard(socket))

    def _discard(self, socket):
        self._sockets.discard(socket)
        self._subscribers.discard(socket)
        socket.deleteLater()

    def _read(self, socket):
        if not socket.canReadLine():
            if socket.bytesAvailable() >= 65536:
                socket.disconnectFromServer()
            return
        try:
            request = json.loads(bytes(socket.readLine()))
            if not isinstance(request, dict):
                raise ValueError('无效的桌宠命令')
            command = request.get('command')
            data = self._handler(command, request.get('args', {}))
            response = {'ok': True, 'data': data}
        except (ValueError, KeyError) as exc:
            response = {'ok': False, 'error': str(exc)}
        socket.write(json.dumps(response, ensure_ascii=False).encode() + b'\n')
        if response['ok'] and command == 'watch_actions':
            self._subscribers.add(socket)
        else:
            socket.disconnectFromServer()  # Qt flushes the reply before closing.

    def publish_action(self, name):
        reply = json.dumps({'ok': True, 'data': {'current': name}}, ensure_ascii=False).encode() + b'\n'
        for socket in tuple(self._subscribers):
            socket.write(reply)

    def close(self):
        self._server.close()
        for socket in tuple(self._sockets):
            socket.abort()
            socket.deleteLater()
        self._sockets.clear()
        self._subscribers.clear()
        self._lock.unlock()


class SettingsCommandClient(QObject):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self._endpoint = endpoint(config)
        self._sockets = set()

    def request(self, command, args, callback):
        socket = QLocalSocket(self)
        timer = QTimer(socket)
        timer.setSingleShot(True)
        done = False

        def finish(response):
            nonlocal done
            if done:
                return
            done = True
            timer.stop()
            self._sockets.discard(socket)
            socket.abort()
            socket.deleteLater()
            callback(response)

        def read():
            while socket.canReadLine():
                try:
                    response = json.loads(bytes(socket.readLine()))
                except (ValueError, UnicodeDecodeError):
                    finish({'ok': False, 'error': '桌宠返回了无效响应'})
                    return
                if command == 'watch_actions' and response['ok']:
                    timer.stop()
                    callback(response)
                else:
                    finish(response)
                    return

        socket.connected.connect(lambda: socket.write(
            json.dumps({'command': command, 'args': args}, ensure_ascii=False).encode() + b'\n'))
        socket.readyRead.connect(read)
        socket.errorOccurred.connect(lambda _error: finish(
            {'ok': False, 'error': '无法连接桌宠，请确认 seeky· pet 正在运行'}))
        timer.timeout.connect(lambda: finish({'ok': False, 'error': '桌宠暂时没有响应，请重试'}))
        self._sockets.add(socket)
        timer.start(2000)
        socket.connectToServer(self._endpoint)
        return socket

    def cancel(self, socket):
        if socket not in self._sockets:
            return
        for timer in socket.findChildren(QTimer):
            timer.stop()
        socket.blockSignals(True)
        self._sockets.discard(socket)
        socket.abort()
        socket.deleteLater()

    def close(self):
        for socket in tuple(self._sockets):
            self.cancel(socket)
        self._sockets.clear()
