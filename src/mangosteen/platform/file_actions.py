"""Actions that work on any file or folder (the Actions wheel), and the small desktop services around them:
opening a file or folder, revealing it in the file manager, the trash."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import time
import urllib.parse
from datetime import datetime

from ..core import log, output_naming


def _uris(paths: list[str]) -> list[str]:
    return ["file://" + urllib.parse.quote(os.path.abspath(p)) for p in paths]


def copy_files(paths: list[str]) -> None:
    """Puts the files themselves on the clipboard, ready to paste in a file manager or a mail. GNOME and KDE file
    managers each look for their own format next to the standard URI list."""
    from PySide6.QtCore import QByteArray, QMimeData, QUrl
    from PySide6.QtGui import QGuiApplication

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(os.path.abspath(p)) for p in paths])
    gnome = "copy\n" + "\n".join(_uris(paths))
    mime.setData("x-special/gnome-copied-files", QByteArray(gnome.encode("utf-8")))
    mime.setData("application/x-kde-cutselection", QByteArray(b"0"))
    mime.setText("\n".join(paths))
    QGuiApplication.clipboard().setMimeData(mime)


def copy_paths(paths: list[str]) -> None:
    """One full path per line."""
    from PySide6.QtGui import QGuiApplication

    QGuiApplication.clipboard().setText("\n".join(os.path.abspath(p) for p in paths))


def move(paths: list[str], destination: str) -> tuple[list[str], list[str]]:
    """Moves the items into `destination`; a name that is taken gets a number. Returns (moved, failed messages)."""
    moved: list[str] = []
    failed: list[str] = []
    destination = os.path.abspath(destination)
    for path in paths:
        source = os.path.abspath(path.rstrip("/\\"))
        if os.path.dirname(source) == destination.rstrip("/"):
            continue
        try:
            is_folder = os.path.isdir(source)
            if is_folder and (destination + os.sep).startswith(source + os.sep):
                raise OSError("A folder cannot be moved into itself.")
            name = os.path.basename(source)
            stem, extension = (name, "") if is_folder else os.path.splitext(name)
            target = output_naming.unique_path(destination, stem, extension.lstrip("."))
            shutil.move(source, target)
            moved.append(target)
        except OSError as error:
            failed.append(f"{os.path.basename(source)}: {error}")
            log.error(f"move {source}", error)
    return moved, failed


_TERMINALS = [
    # (program, arguments that open it in a folder; {dir} is replaced)
    ("kitty", ["-d", "{dir}"]),
    ("wezterm", ["start", "--cwd", "{dir}"]),
    ("alacritty", ["--working-directory", "{dir}"]),
    ("foot", ["-D", "{dir}"]),
    ("tilix", ["-w", "{dir}"]),
    ("gnome-terminal", ["--working-directory={dir}"]),
    ("kgx", ["--working-directory={dir}"]),
    ("konsole", ["--workdir", "{dir}"]),
    ("xfce4-terminal", ["--working-directory={dir}"]),
    ("mate-terminal", ["--working-directory={dir}"]),
    ("lxterminal", ["--working-directory={dir}"]),
    ("terminator", ["--working-directory={dir}"]),
    ("qterminal", ["-w", "{dir}"]),
    ("xterm", None),
]


def open_terminal(paths: list[str], terminal: str = "auto") -> None:
    """Opens each folder (or a file's folder) in a terminal: the one chosen in Settings, otherwise the desktop's."""
    folders: list[str] = []
    for path in paths:
        absolute = os.path.abspath(path.rstrip("/\\"))
        folder = absolute if os.path.isdir(absolute) else os.path.dirname(absolute)
        if folder not in folders:
            folders.append(folder)
    for folder in folders:
        command = _terminal_command(terminal, folder)
        if command is None:
            raise OSError("No terminal program was found. Choose one in Settings.")
        subprocess.Popen(command, cwd=folder, start_new_session=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _terminal_command(choice: str, folder: str) -> list[str] | None:
    if choice and choice != "auto":
        parts = shlex.split(choice)
        known = dict(_TERMINALS).get(os.path.basename(parts[0]))
        if known:
            return [*parts, *(a.replace("{dir}", folder) for a in known)]
        return parts  # the working directory is set by cwd
    preferred = os.environ.get("TERMINAL")
    names = ([preferred] if preferred else []) + [name for name, _ in _TERMINALS]
    for name in names:
        program = shutil.which(name) if name else None
        if program is None:
            continue
        known = dict(_TERMINALS).get(os.path.basename(program))
        if known:
            return [program, *(a.replace("{dir}", folder) for a in known)]
        return [program]
    fallback = shutil.which("x-terminal-emulator")
    return [fallback] if fallback else None


def open_path(path: str) -> None:
    """Opens a file or folder with the desktop's default program."""
    subprocess.Popen(["xdg-open", path], start_new_session=True, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def reveal(path: str) -> None:
    """Shows the item selected in the file manager (through the FileManager1 service when there is one)."""
    absolute = os.path.abspath(path.rstrip("/\\"))
    try:
        from PySide6.QtDBus import QDBusConnection, QDBusInterface

        bus = QDBusConnection.sessionBus()
        if bus.isConnected():
            interface = QDBusInterface("org.freedesktop.FileManager1", "/org/freedesktop/FileManager1",
                                       "org.freedesktop.FileManager1", bus)
            if interface.isValid():
                reply = interface.call("ShowItems", _uris([absolute]), "")
                if reply.errorMessage() == "":
                    return
    except Exception as error:  # noqa: BLE001
        log.write(f"reveal through D-Bus failed: {error}")
    open_path(os.path.dirname(absolute))


def trash(path: str) -> bool:
    """Moves a file or folder to the trash (never deleting it for good). Returns True on success."""
    absolute = os.path.abspath(path.rstrip("/\\"))
    gio = shutil.which("gio")
    if gio:
        if subprocess.run([gio, "trash", absolute], capture_output=True).returncode == 0:
            return True
    return _trash_by_hand(absolute)


def _trash_by_hand(path: str) -> bool:
    """The freedesktop.org trash in the home folder: the file moves to Trash/files, with a .trashinfo next to it."""
    data = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    files, info = os.path.join(data, "Trash", "files"), os.path.join(data, "Trash", "info")
    try:
        os.makedirs(files, exist_ok=True)
        os.makedirs(info, exist_ok=True)
        name = os.path.basename(path)
        stem, extension = os.path.splitext(name)
        target = output_naming.unique_path(files, stem, extension.lstrip("."))
        shutil.move(path, target)
        with open(os.path.join(info, os.path.basename(target) + ".trashinfo"), "w", encoding="utf-8") as stream:
            stream.write("[Trash Info]\nPath=" + urllib.parse.quote(path) + "\nDeletionDate="
                         + datetime.now().strftime("%Y-%m-%dT%H:%M:%S") + "\n")
        return True
    except OSError as error:
        log.error("trash", error)
        return False


__all__ = ["copy_files", "copy_paths", "move", "open_terminal", "open_path", "reveal", "trash", "time"]
