"""The running application: wires the drag monitor, the wheel, the tray, the jobs and the tools together."""

from __future__ import annotations

import os

from PySide6.QtCore import QObject, QTimer, Slot
from PySide6.QtGui import QCursor, QGuiApplication
from PySide6.QtWidgets import QApplication, QFileDialog

from . import ipc
from .core import file_format, format_catalog, history, loc, log, paths, wheel_catalog
from .core.file_format import Category, FileFormat
from .core.loc import L, count, fmt
from .core.settings import Settings
from .core.wheel_catalog import WheelItem, WheelKind, wheel_title


class Application(QObject):
    def __init__(self, qapp: QApplication, watch_drags: bool = True) -> None:
        super().__init__()
        from .platform import file_actions
        from .ui import art, brand
        from .ui.float_shelf import FloatShelf
        from .ui.jobs import Jobs
        from .ui.tray import TrayController
        from .ui.wheel import WheelController
        from .platform.notifier import Notifier

        self.qapp = qapp
        self.actions = file_actions
        self.settings = Settings.load()
        loc.set_language(self.settings.effective_language)
        qapp.setApplicationName("Mangosteen")
        qapp.setDesktopFileName("mangosteen")
        qapp.setWindowIcon(art.app_icon())
        qapp.setQuitOnLastWindowClosed(False)
        brand.apply_palette(qapp)

        self.history = history.ResultHistory.load(paths.history_file())
        self.tray = TrayController(self.history)
        self.notifier = Notifier(self.tray.icon)
        self.jobs = Jobs(self.notify, self.history.add, self._results_ready)
        self.wheel = WheelController(self._perform_slot, wheel_catalog.items)
        self.shelf = FloatShelf(lambda: self.settings.float_moves_files)
        self.monitor = None
        self._watch_drags = watch_drags
        self._windows: dict[str, object] = {}
        self._tools: list[object] = []

        self.tray.choose_files.connect(self.choose_files)
        self.tray.toggle_shelf.connect(self.shelf.toggle)
        self.tray.open_settings.connect(self.show_settings)
        self.tray.open_welcome.connect(self.show_welcome)
        self.tray.open_about.connect(self.show_about)
        self.tray.check_updates.connect(self.show_updates)
        self.tray.open_log.connect(lambda: self.actions.open_path(str(paths.log_file())))
        self.tray.quit_requested.connect(self.quit)
        self.tray.reveal_result.connect(lambda entry: self.actions.reveal(entry.outputs[0]))
        self.tray.open_result.connect(lambda entry: [self.actions.open_path(p) for p in entry.outputs])
        self.tray.delete_result.connect(self._delete_result)
        self.tray.clear_history.connect(self.history.clear)
        self.notifier.clicked.connect(self.actions.reveal)
        self.wheel.on_shown_without_files = self._nudge_soon

        self.server = ipc.Server()
        self.server.received.connect(self.handle_message)

    # MARK: Start and stop

    def start(self) -> bool:
        """Becomes the running instance. False when another one is already running."""
        if not self.server.listen():
            return False
        from .platform import integration, x11

        self.tray.show()
        integration.install_icon()
        integration.install_launcher()
        integration.set_file_manager_menus(self.settings.file_manager_menu)
        if integration.autostart_enabled():
            integration.set_autostart(True)  # an updated AppImage may have a new file name
        self._start_monitor()
        log.write(f"started; tray available: {self.tray.available}; drag monitor: "
                  f"{self.monitor is not None and self.monitor.running}; X11: {x11.is_x11_session()}; Wayland: {x11.is_wayland_session()}")
        if not self.settings.welcome_shown:
            self.settings.welcome_shown = True
            self.settings.save()
            QTimer.singleShot(300, self.show_welcome)
        elif not self.tray.available:
            QTimer.singleShot(800, lambda: self.notify(
                L("Mangosteen is running"),
                L("There is no tray icon on this desktop. Start Mangosteen again from the applications menu to open "
                  "its menu.")))
        return True

    @property
    def drag_available(self) -> bool:
        return self.monitor is not None and self.monitor.running

    def _start_monitor(self) -> None:
        from .platform.drag_monitor import DragMonitor
        from .platform import x11

        if self.monitor is not None or not self._watch_drags or not self.settings.watch_drags:
            return
        if not x11.can_watch_drags():
            return
        monitor = DragMonitor()
        monitor.drag_started.connect(self._drag_started)
        monitor.modifier_tapped.connect(self._modifier_tapped)
        monitor.drag_ended.connect(self._drag_ended)
        if monitor.start():
            self.monitor = monitor

    def _stop_monitor(self) -> None:
        if self.monitor is not None:
            self.monitor.stop()
            self.monitor = None

    @Slot()
    def quit(self) -> None:
        log.write("quit")
        self._stop_monitor()
        self.wheel.hide()
        self.tray.hide()
        self.qapp.quit()

    # MARK: Requests from other launches

    @Slot(dict)
    def handle_message(self, message: dict) -> None:
        command = message.get("cmd")
        files = [p for p in message.get("files", []) if os.path.lexists(p)]
        if command == "wheel" and files:
            self.show_wheel(WheelKind(message.get("kind", "convert")), files)
        elif command == "menu":
            self.tray.popup_at_cursor()
        elif command == "settings":
            self.show_settings()
        elif command == "welcome":
            self.show_welcome()
        elif command == "tool" and files:
            self.open_tool(message.get("tool", ""), files)
        elif command == "quit":
            self.quit()

    # MARK: Drag monitor

    @Slot(list)
    def _drag_started(self, files: list) -> None:
        pass

    @Slot(str, list)
    def _modifier_tapped(self, modifier: str, files: list) -> None:
        kind = self.settings.wheel_for_modifier(modifier)
        if kind is None:
            return
        if self.wheel.is_visible and self.wheel.drag_mode:
            self.wheel.switch(kind)
            return
        self.show_wheel(kind, files or None, drag_mode=True)

    @Slot()
    def _drag_ended(self) -> None:
        self.wheel.drag_ended()

    def _nudge_soon(self) -> None:
        from .platform import drag_monitor

        QTimer.singleShot(25, drag_monitor.nudge)

    # MARK: Wheels

    def show_wheel(self, kind: WheelKind, files: list[str] | None, drag_mode: bool = False) -> None:
        """Opens the wheel at the pointer. `files` None means a drag whose files are not known yet."""
        if files is not None:
            log.write(f"wheel {kind.value}: {len(files)} files: "
                      f"{', '.join(i.title for i in wheel_catalog.items(kind, files))}")
        self.wheel.show(kind, files, drag_mode=drag_mode)

    def choose_files(self, kind: WheelKind) -> None:
        names, _ = QFileDialog.getOpenFileNames(None, f"Mangosteen: {wheel_title(kind)}")
        if names:
            log.write(f"chosen {len(names)} files for {kind.value}")
            QTimer.singleShot(0, lambda: self.show_wheel(kind, names))

    @Slot(object, list)
    def _perform_slot(self, item: WheelItem, files: list) -> None:
        self.perform(item, files)

    # MARK: Doing things

    def notify(self, title: str, message: str = "", error: bool = False, reveal: str | None = None) -> None:
        self.notifier.notify(title, message, error=error, reveal=reveal)

    def _results_ready(self, outputs: list[str]) -> None:
        if self.settings.reveal_results and outputs:
            self.actions.reveal(outputs[-1])

    def perform(self, item: WheelItem, files: list[str]) -> None:
        log.write(f"chose {item.id} for {len(files)} items")
        if not item.available:
            self.notify(item.title, item.hint, error=True)
            return
        try:
            if item.target is not None:
                self._convert(item.target, files)
                return
            self._perform_other(item, files)
        except Exception as error:  # noqa: BLE001 - shown, not lost
            log.error(item.id, error)
            self.notify(item.title, str(error), error=True)

    def _convert(self, target: FileFormat, files: list[str]) -> None:
        from .convert import converter, pdf

        options = self.settings.conversion_options
        # Items that cannot become the target (or already are it) are skipped, as the wheel promised.
        inputs = [p for p in files if (c := format_catalog.conversion(p))[0] is not target and target in c[1]]
        if target is FileFormat.PDF:
            # Several photos become one PDF, a page each; the rest is converted file by file.
            pages, separate = format_catalog.split_for_pdf(inputs)
            if pages:
                self.jobs.run_once(L("Creating PDF"), L("PDF created"), count(len(pages), "file"),
                                   lambda: pdf.create_from_images(pages))
                inputs = separate
                if not inputs:
                    return
        has_media = any((f := file_format.detect(p)) is not None and f.category.is_media for p in inputs)
        self.jobs.run_each(
            fmt("Converting to {0}", target.display_name), fmt("Converted to {0}", target.display_name), inputs,
            lambda path, token, progress: converter.convert(path, target, options, token, progress),
            max_concurrent=2 if has_media else 3)

    def _perform_other(self, item: WheelItem, files: list[str]) -> None:
        from .convert import archives, pdf

        action = item.id
        if action == "tool.extract":
            archive_files = [p for p in files if (f := file_format.detect(p)) and f.category is Category.ARCHIVE]
            self.jobs.run_each(L("Extracting"), L("Extracted"), archive_files,
                               lambda path, _t, _p: archives.extract_next_to_archive(path))
        elif action == "tool.archive":
            self.jobs.run_once(L("Archiving"), L("Archived"), count(len(files), "item"),
                               lambda: archives.add_to_archive(files))
        elif action == "tool.mergePDF":
            self.jobs.run_once(L("Merging PDFs"), L("PDFs merged"), count(len(files), "file"), lambda: pdf.merge(files))
        elif action == "tool.compressAll":
            self._compress_all(files)
        elif action == "tool.recognizeText":
            self._recognize_text(files)
        elif action == "action.float":
            self.shelf.add(files)
        elif action == "action.copy":
            self.actions.copy_files(files)
            name = os.path.basename(files[0]) if len(files) == 1 else count(len(files), "item")
            self.notify(L("Copied"), fmt("{0}: paste it in a folder or a message.", name))
        elif action == "action.copyPath":
            self.actions.copy_paths(files)
            self.notify(L("Path copied"), files[0] if len(files) == 1 else count(len(files), "path"))
        elif action == "action.move":
            self._move(files)
        elif action == "action.terminal":
            self.actions.open_terminal(files, self.settings.terminal)
        else:
            self.open_tool(action, files)

    def _compress_all(self, files: list[str]) -> None:
        """Each file is compressed in its own way, with the default settings."""
        from .imaging import compress
        from .mediatools import effects

        def work(path: str, token, progress) -> str:  # noqa: ANN001
            kind = file_format.detect(path)
            if kind is not None and kind.category.is_media:
                return effects.compress(path, None, progress, token)
            return compress.compress_file(path)

        has_media = any((k := file_format.detect(p)) is not None and k.category.is_media for p in files)
        self.jobs.run_each(L("Compressing"), L("Compressed"), files, work, max_concurrent=1 if has_media else 3)

    def _recognize_text(self, files: list[str]) -> None:
        from .imaging import ocr

        inputs = [p for p in files if ocr.accepts(p)]
        self.jobs.run_each(L("Recognizing text"), L("Text recognized"), inputs,
                           lambda path, token, progress: ocr.recognize_file(path, progress, token))

    def _move(self, files: list[str]) -> None:
        start = os.path.dirname(os.path.abspath(files[0].rstrip("/\\")))
        title = (fmt("Move “{0}” to", os.path.basename(files[0])) if len(files) == 1
                 else fmt("Move {0} to", count(len(files), "item")))
        destination = QFileDialog.getExistingDirectory(None, title, start)
        if not destination:
            return
        moved, failed = self.actions.move(files, destination)
        if failed:
            self.notify(fmt("{0} of {1} not moved", len(failed), len(moved) + len(failed)), "\n".join(failed[:3]),
                        error=True)
        elif moved:
            self.notify(L("Moved"), os.path.basename(moved[0]) if len(moved) == 1 else count(len(moved), "item"),
                        reveal=moved[-1])

    def _delete_result(self, entry) -> None:  # noqa: ANN001
        for path in entry.outputs:
            self.actions.trash(path)
        self.history.remove(entry)

    # MARK: Tools

    def open_tool(self, tool_id: str, files: list[str]) -> None:
        from .ui.tools import registry

        window = registry.create(tool_id, files, self)
        if window is None:
            self.notify(tool_id, L("Coming in a later version"))
            return
        self._tools = [w for w in self._tools if w.isVisible()]
        self._tools.append(window)
        window.present()

    # MARK: Windows

    def show_settings(self) -> None:
        from .ui.settings_window import SettingsWindow

        window = self._windows.get("settings")
        if window is None:
            window = SettingsWindow(self.settings, self._setting_changed, self.drag_available or self._can_watch(),
                                    True)
            self._windows["settings"] = window
        window.present()

    def _can_watch(self) -> bool:
        from .platform import x11

        return x11.can_watch_drags()

    def show_welcome(self) -> None:
        from .ui.welcome import WelcomeWindow

        keys = {kind: self.settings.modifier_for(kind) for kind in WheelKind}
        window = WelcomeWindow(keys, self.drag_available)
        self._windows["welcome"] = window
        window.present()

    def show_about(self) -> None:
        from .ui.about import AboutWindow

        window = self._windows.get("about")
        if window is None:
            window = AboutWindow()
            window.check_updates.connect(self.show_updates)
        self._windows["about"] = window
        window.present()

    def show_updates(self) -> None:
        from .ui.update_window import UpdateWindow

        window = self._windows.get("updates")
        if window is None:
            window = UpdateWindow()
            window.restart_requested.connect(self.restart)
        self._windows["updates"] = window
        window.present()

    @Slot(list)
    def restart(self, command: list) -> None:
        """Starts `command` once this process has exited, then quits."""
        from PySide6.QtCore import QProcess

        from .core import updates

        line = updates.restart_command([str(part) for part in command])
        log.write(f"restart: {command}")
        started, _pid = QProcess.startDetached(line[0], line[1:])
        if started:
            self.quit()

    def _setting_changed(self, name: str) -> None:
        from .platform import integration

        if name == "language":
            loc.set_language(self.settings.effective_language)
            self.tray.rebuild()
        elif name == "autostart":
            window = self._windows.get("settings")
            integration.set_autostart(bool(window.autostart.isChecked()) if window else False)
        elif name == "file_manager_menu":
            integration.set_file_manager_menus(self.settings.file_manager_menu)
        elif name == "watch_drags":
            if self.settings.watch_drags:
                self._start_monitor()
            else:
                self._stop_monitor()


__all__ = ["Application", "QCursor", "QGuiApplication"]
