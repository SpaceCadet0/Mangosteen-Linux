"""The command line: `mangosteen` starts the app; the other forms talk to the running one or work on their own."""

from __future__ import annotations

import argparse
import os
import sys

from . import __version__


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mangosteen", description="Zero-click file converter and toolbox.",
        epilog="Without options Mangosteen starts in the tray (or, when it is running, opens its menu).")
    parser.add_argument("--wheel", choices=["convert", "tools", "actions"], metavar="KIND",
                        help="open the convert, tools or actions wheel for FILES at the pointer")
    parser.add_argument("--tool", metavar="ID", help="open a tool window (for example tool.crop) for FILES")
    parser.add_argument("--convert", metavar="FORMAT",
                        help="convert FILES to FORMAT right here, without the app (png, pdf, mp3…)")
    parser.add_argument("--formats", action="store_true", help="list the formats FILES can be converted to")
    parser.add_argument("--snapshot", nargs=2, metavar=("TOOL", "OUTPUT"),
                        help="render a tool window or wheel for FILES into a PNG image and exit")
    parser.add_argument("--settings", action="store_true", help="open Settings")
    parser.add_argument("--welcome", action="store_true", help="open the welcome window")
    parser.add_argument("--no-drag", action="store_true", help="do not watch for drags in other windows")
    parser.add_argument("--quit", action="store_true", help="quit the running Mangosteen")
    parser.add_argument("--version", action="version", version=f"Mangosteen {__version__}")
    parser.add_argument("files", nargs="*", metavar="FILES")
    return parser


def _absolute(files: list[str]) -> list[str]:
    return [os.path.abspath(f) for f in files]


def _convert_here(format_name: str, files: list[str]) -> int:
    from .convert import converter
    from .core import loc
    from .core.file_format import FileFormat
    from .core.settings import Settings

    settings = Settings.load()
    loc.set_language(settings.effective_language)
    wanted = format_name.lower().lstrip(".")
    target = next((f for f in FileFormat if f.value == wanted or f.extension == wanted), None)
    if target is None:
        print(f"mangosteen: unknown format “{format_name}”", file=sys.stderr)
        return 2
    status = 0
    for path in files:
        try:
            result = converter.convert(path, target, settings.conversion_options)
            print(result if result else f"{path}: already {target.display_name}")
        except Exception as error:  # noqa: BLE001
            print(f"mangosteen: {converter.describe_error(error, os.path.basename(path))}", file=sys.stderr)
            status = 1
    return status


def _list_formats(files: list[str]) -> int:
    from .core import format_catalog

    targets = format_catalog.targets(files)
    print(" ".join(t.extension for t in targets) if targets else "(nothing)")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    files = _absolute(args.files)

    if args.convert:
        return _convert_here(args.convert, files)
    if args.formats:
        return _list_formats(files)

    from . import ipc

    message: dict | None = None
    if args.quit:
        message = {"cmd": "quit"}
    elif args.wheel:
        message = {"cmd": "wheel", "kind": args.wheel, "files": files}
    elif args.tool:
        message = {"cmd": "tool", "tool": args.tool, "files": files}
    elif args.settings:
        message = {"cmd": "settings"}
    elif args.welcome:
        message = {"cmd": "welcome"}
    elif not args.snapshot:
        message = {"cmd": "menu"}

    if message is not None and not args.snapshot:
        # Hand the request to the running instance, if there is one. The application object is the real one: a
        # QCoreApplication made just for this would stay alive and could not be replaced by a QApplication later.
        _qt_application()
        if ipc.send(message):
            return 0
        if args.quit:
            return 0

    return run(args, files, message)


def _qt_application():  # noqa: ANN202
    """The QApplication, created on first use (the platform is chosen first)."""
    if os.environ.get("XDG_SESSION_TYPE") == "wayland" and os.environ.get("DISPLAY") \
            and "QT_QPA_PLATFORM" not in os.environ:
        # XWayland gives windows a real position (a native Wayland window cannot be placed at the pointer).
        os.environ["QT_QPA_PLATFORM"] = "xcb"
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication(sys.argv[:1])


def run(args, files: list[str], message: dict | None) -> int:  # noqa: ANN001
    """Starts the Qt application: the tray app, or a one-off snapshot."""
    qapp = _qt_application()
    if args.snapshot:
        from .ui import snapshot

        return snapshot.run(qapp, args.snapshot[0], args.snapshot[1], files)

    from .app import Application

    application = Application(qapp, watch_drags=not args.no_drag)
    if not application.start():
        return 0  # another instance won the race
    if message and message.get("cmd") not in ("menu", "quit"):
        application.handle_message(message)
    code = qapp.exec()
    from .ui import teardown

    teardown.delete_windows(qapp)
    return code


if __name__ == "__main__":
    sys.exit(main())
