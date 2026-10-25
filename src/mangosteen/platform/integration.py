"""Fits Mangosteen into the desktop: the launcher entry, starting at login, and the file managers' right-click menus.

Everything is written under the user's home folder, so no administrator rights are needed, and removed again when
the setting is switched off."""

from __future__ import annotations

import os
import shlex
import stat
import sys
from pathlib import Path

from ..core import log, paths
from ..core.loc import L

# The file managers that can be extended with a plain file in the home folder. Thunar keeps its custom actions in a
# single XML file the user edits, so it is not touched (see the README for the snippet).
_APP_ID = "mangosteen"


def command() -> list[str]:
    """How to start Mangosteen: the AppImage or installed program when there is one, otherwise this interpreter."""
    appimage = os.environ.get("APPIMAGE")
    if appimage:
        return [appimage]
    from shutil import which

    installed = which("mangosteen")
    if installed:
        return [installed]
    return [sys.executable, "-m", "mangosteen"]


def _exec_line(*arguments: str) -> str:
    return " ".join(shlex.quote(part) for part in [*command(), *arguments])


def _data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def _config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")


def desktop_entry(autostart: bool = False) -> str:
    lines = [
        "[Desktop Entry]", "Type=Application", "Name=Mangosteen", "GenericName=File converter",
        "Comment=Zero-click file converter and toolbox", f"Exec={_exec_line()}", f"Icon={_icon_name()}",
        "Terminal=false", "Categories=Utility;", "StartupNotify=false", "StartupWMClass=mangosteen",
    ]
    if autostart:
        lines += ["X-GNOME-Autostart-enabled=true", "X-KDE-autostart-after=panel"]
    return "\n".join(lines) + "\n"


def _icon_name() -> str:
    """The themed icon when installed system-wide, otherwise the file written to the user's icon folder."""
    return str(_data_home() / "icons" / "hicolor" / "256x256" / "apps" / f"{_APP_ID}.png") \
        if (_data_home() / "icons" / "hicolor" / "256x256" / "apps" / f"{_APP_ID}.png").exists() else _APP_ID


def install_icon() -> None:
    """Writes the icon to the user's theme folder so launchers and notifications can show it."""
    try:
        from PySide6.QtWidgets import QApplication

        if QApplication.instance() is None:
            return
        from ..ui import art

        for size in (48, 128, 256):
            target = _data_home() / "icons" / "hicolor" / f"{size}x{size}" / "apps" / f"{_APP_ID}.png"
            target.parent.mkdir(parents=True, exist_ok=True)
            art.pixmap(size).save(str(target), "PNG")
    except OSError as error:
        log.error("install icon", error)


def install_launcher() -> None:
    """The entry in the applications menu."""
    target = _data_home() / "applications" / f"{_APP_ID}.desktop"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(desktop_entry(), encoding="utf-8")
    except OSError as error:
        log.error("install launcher", error)


def set_autostart(enabled: bool) -> None:
    target = paths.autostart_file()
    try:
        if enabled:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(desktop_entry(autostart=True) + "X-GNOME-Autostart-Delay=3\n", encoding="utf-8")
        elif target.exists():
            target.unlink()
    except OSError as error:
        log.error("autostart", error)


def autostart_enabled() -> bool:
    return paths.autostart_file().exists()


# MARK: File manager menus

_KINDS = [("convert", "Convert"), ("tools", "Tools"), ("actions", "Actions")]


def _kde_menu() -> str:
    actions = ";".join(f"Mangosteen{kind.title()}" for kind, _ in _KINDS)
    parts = ["[Desktop Entry]", "Type=Service", "ServiceTypes=KonqPopupMenu/Plugin",
             "MimeType=application/octet-stream;inode/directory;all/all;", f"Actions={actions}",
             "X-KDE-Submenu=Mangosteen", f"Icon={_icon_name()}", ""]
    for kind, title in _KINDS:
        parts += [f"[Desktop Action Mangosteen{kind.title()}]", f"Name={L(title)}", f"Icon={_icon_name()}",
                  f"Exec={_exec_line('--wheel', kind)} %F", ""]
    return "\n".join(parts)


def _nemo_action(kind: str, title: str) -> str:
    return "\n".join([
        "[Nemo Action]", f"Name=Mangosteen: {L(title)}", f"Comment={L(title)}", f"Exec={_exec_line('--wheel', kind)} %F",
        f"Icon-Name={_icon_name()}", "Selection=any", "Extensions=any;", ""])


def _script(kind: str) -> str:
    """A GNOME Files / Caja / Nemo script: the selection arrives in an environment variable, one path per line."""
    exec_line = _exec_line("--wheel", kind)
    return ("#!/bin/sh\n# Installed by Mangosteen\n"
            'paths="${NAUTILUS_SCRIPT_SELECTED_FILE_PATHS}${CAJA_SCRIPT_SELECTED_FILE_PATHS}'
            '${NEMO_SCRIPT_SELECTED_FILE_PATHS}"\n'
            f"printf '%s\\n' \"$paths\" | sed '/^$/d' | tr '\\n' '\\0' | exec xargs -0 -r {exec_line}\n")


def _desktop_actions_entry() -> str:
    """Desktop actions on the launcher entry, which PCManFM and other file managers list for a selected file."""
    return desktop_entry() + "Actions=" + ";".join(f"Mangosteen{k.title()}" for k, _ in _KINDS) + ";\n" + "".join(
        f"\n[Desktop Action Mangosteen{kind.title()}]\nName=Mangosteen: {L(title)}\n"
        f"Exec={_exec_line('--wheel', kind)} %F\n" for kind, title in _KINDS)


def set_file_manager_menus(enabled: bool) -> list[str]:
    """Installs or removes the right-click entries. Returns what was written (for the log)."""
    written: list[str] = []
    data, config = _data_home(), _config_home()
    files: dict[Path, str] = {
        data / "kio" / "servicemenus" / "mangosteen.desktop": _kde_menu(),
        data / "applications" / f"{_APP_ID}.desktop": _desktop_actions_entry(),
    }
    for kind, title in _KINDS:
        files[config / "nemo" / "actions" / f"mangosteen-{kind}.nemo_action"] = _nemo_action(kind, title)
    scripts: dict[Path, str] = {}
    for root in (data / "nautilus" / "scripts", config / "caja" / "scripts", data / "nemo" / "scripts"):
        for kind, title in _KINDS:
            scripts[root / f"Mangosteen - {L(title)}"] = _script(kind)
    for target, content in {**files, **scripts}.items():
        try:
            if enabled:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
                if target in scripts:
                    target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
                written.append(str(target))
            elif target.exists() and target.name != f"{_APP_ID}.desktop":
                target.unlink()
        except OSError as error:
            log.error(f"file manager menu {target}", error)
    if not enabled:
        # Take the actions out of the launcher entry but keep the entry.
        install_launcher()
        # Scripts named in another language are found by their content.
        for root in (data / "nautilus" / "scripts", config / "caja" / "scripts", data / "nemo" / "scripts"):
            if root.is_dir():
                for file in root.iterdir():
                    try:
                        if file.is_file() and "Installed by Mangosteen" in file.read_text(encoding="utf-8", errors="ignore"):
                            file.unlink()
                    except OSError:
                        pass
    return written
