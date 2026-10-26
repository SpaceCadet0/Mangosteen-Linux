"""One running Mangosteen per user: later launches (a file manager's menu entry, the launcher icon) hand their request
to it over a local socket and exit."""

from __future__ import annotations

import hashlib
import json
import os

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from .core import log


def server_name() -> str:
    """One name per user; with MANGOSTEEN_HOME (portable installs, tests) one per home folder, so they stay apart."""
    home = os.environ.get("MANGOSTEEN_HOME")
    suffix = "-" + hashlib.sha1(home.encode("utf-8")).hexdigest()[:10] if home else ""
    return f"mangosteen-{os.getuid()}{suffix}"


def send(message: dict, timeout_ms: int = 800) -> bool:
    """Delivers `message` to the running instance; False when there is none."""
    socket = QLocalSocket()
    socket.connectToServer(server_name())
    if not socket.waitForConnected(timeout_ms):
        return False
    socket.write(json.dumps(message).encode("utf-8") + b"\n")
    socket.flush()
    socket.waitForBytesWritten(timeout_ms)
    socket.disconnectFromServer()
    return True


class Server(QObject):
    received = Signal(dict)

    def __init__(self) -> None:
        super().__init__()
        self._server = QLocalServer(self)
        self._server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self._server.newConnection.connect(self._connection)
        self._buffers: dict[int, bytes] = {}

    def listen(self) -> bool:
        name = server_name()
        if self._server.listen(name):
            return True
        QLocalServer.removeServer(name)  # a stale socket from a crashed run
        return self._server.listen(name)

    def _connection(self) -> None:
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            socket.readyRead.connect(lambda s=socket: self._read(s))
            socket.disconnected.connect(lambda s=socket: self._read(s, final=True))

    def _read(self, socket: QLocalSocket, final: bool = False) -> None:
        key = id(socket)
        self._buffers[key] = self._buffers.get(key, b"") + bytes(socket.readAll())
        *lines, rest = self._buffers[key].split(b"\n")
        self._buffers[key] = rest
        if final and rest.strip():
            lines.append(rest)
            self._buffers[key] = b""
        for line in lines:
            if not line.strip():
                continue
            try:
                self.received.emit(json.loads(line.decode("utf-8")))
            except ValueError as error:
                log.error("ipc", error)
        if final:
            self._buffers.pop(key, None)
            socket.deleteLater()
