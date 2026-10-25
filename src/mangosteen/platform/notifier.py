"""Desktop notifications through the freedesktop.org Notifications service, falling back to the tray icon's balloon."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from ..core import log

_SERVICE = "org.freedesktop.Notifications"
_PATH = "/org/freedesktop/Notifications"


class Notifier(QObject):
    # Emitted with the path attached to a notification the user clicked.
    clicked = Signal(str)

    def __init__(self, tray=None) -> None:  # noqa: ANN001 - a QSystemTrayIcon, for the fallback
        super().__init__()
        self._tray = tray
        self._reveal: dict[int, str] = {}
        self._bus = None
        self._fallback_path: str | None = None
        try:
            from PySide6.QtDBus import QDBusConnection

            bus = QDBusConnection.sessionBus()
            if bus.isConnected():
                self._bus = bus
                bus.connect(_SERVICE, _PATH, _SERVICE, "ActionInvoked", self, "on_action(uint,QString)")
                bus.connect(_SERVICE, _PATH, _SERVICE, "NotificationClosed", self, "on_closed(uint,uint)")
        except Exception as error:  # noqa: BLE001
            log.write(f"no D-Bus for notifications: {error}")
        if tray is not None:
            tray.messageClicked.connect(self._balloon_clicked)

    def notify(self, title: str, message: str = "", error: bool = False, reveal: str | None = None) -> None:
        log.write(f"notify: {title} | {message}")
        if self._bus is not None and self._send(title, message, error, reveal):
            return
        self._fallback_path = reveal
        if self._tray is not None and self._tray.isVisible():
            from PySide6.QtWidgets import QSystemTrayIcon

            icon = QSystemTrayIcon.MessageIcon.Warning if error else QSystemTrayIcon.MessageIcon.Information
            self._tray.showMessage(title, message, icon, 6000)

    def _send(self, title: str, message: str, error: bool, reveal: str | None) -> bool:
        from PySide6.QtDBus import QDBusMessage

        call = QDBusMessage.createMethodCall(_SERVICE, _PATH, _SERVICE, "Notify")
        actions = ["default", "Show"] if reveal else []
        hints = {"urgency": 2 if error else 1, "desktop-entry": "mangosteen"}
        call.setArguments(["Mangosteen", 0, "mangosteen", title, message, actions, hints, 8000])
        reply = self._bus.call(call, timeout=500)  # type: ignore[union-attr]
        if reply.type() != QDBusMessage.MessageType.ReplyMessage or not reply.arguments():
            return False
        try:
            identifier = int(reply.arguments()[0])
        except (TypeError, ValueError):
            return False
        if reveal:
            self._reveal[identifier] = reveal
            while len(self._reveal) > 20:
                self._reveal.pop(next(iter(self._reveal)))
        return True

    @Slot(int, str)
    def on_action(self, identifier: int, action: str) -> None:
        path = self._reveal.pop(identifier, None)
        if path and action == "default":
            self.clicked.emit(path)

    @Slot(int, int)
    def on_closed(self, identifier: int, _reason: int) -> None:
        self._reveal.pop(identifier, None)

    def _balloon_clicked(self) -> None:
        if self._fallback_path:
            self.clicked.emit(self._fallback_path)
