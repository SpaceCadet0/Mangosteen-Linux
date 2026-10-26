"""Settings: language, the wheel keys, behaviour, quality of conversions."""

from __future__ import annotations

import shutil

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                               QSlider, QVBoxLayout, QWidget)

from ..core.loc import L, LANGUAGES
from ..core.settings import Settings
from . import art, layoututil

_MODIFIERS = [("shift", "Shift"), ("ctrl", "Ctrl"), ("alt", "Alt"), ("super", "Super")]
_TERMINALS = ["kitty", "wezterm", "alacritty", "foot", "tilix", "gnome-terminal", "kgx", "konsole", "xfce4-terminal",
              "mate-terminal", "lxterminal", "terminator", "qterminal", "xterm"]


class SettingsWindow(QWidget):
    """Changes are applied as they are made; `changed(setting_name)` tells the app what to refresh."""

    def __init__(self, settings: Settings, changed=lambda _name: None, drag_available: bool = True,  # noqa: ANN001
                 menu_available: bool = True) -> None:
        super().__init__()
        self.settings = settings
        self._changed = changed
        self.setWindowTitle(L("Settings"))
        self.setWindowIcon(art.app_icon())
        root = QVBoxLayout(self)
        root.setSpacing(12)

        # General
        general = QGroupBox(L("General"))
        form = QFormLayout(general)
        self.language = QComboBox()
        self.language.addItem(L("Same as the system"), "system")
        for code, name in LANGUAGES:
            self.language.addItem(name, code)
        self.language.setCurrentIndex(max(0, self.language.findData(settings.language)))
        self.language.currentIndexChanged.connect(lambda: self._set("language", self.language.currentData()))
        form.addRow(L("Language"), self.language)
        self.autostart = QCheckBox(L("Start Mangosteen when I log in"))
        self.autostart.setChecked(_autostart_enabled())
        self.autostart.toggled.connect(lambda on: self._set("autostart", on, store=False))
        form.addRow(self.autostart)
        self.menu = QCheckBox(L("Show Mangosteen in the file manager's right-click menu"))
        self.menu.setChecked(settings.file_manager_menu)
        self.menu.setEnabled(menu_available)
        self.menu.toggled.connect(lambda on: self._set("file_manager_menu", on))
        form.addRow(self.menu)
        self.reveal = QCheckBox(L("Show results in the file manager"))
        self.reveal.setChecked(settings.reveal_results)
        self.reveal.toggled.connect(lambda on: self._set("reveal_results", on))
        form.addRow(self.reveal)
        root.addWidget(general)

        # The wheels
        wheels = QGroupBox(L("Wheels"))
        wform = QFormLayout(wheels)
        self.watch = QCheckBox(L("Open the wheel while I drag files"))
        self.watch.setChecked(settings.watch_drags and drag_available)
        self.watch.setEnabled(drag_available)
        self.watch.toggled.connect(lambda on: self._set("watch_drags", on))
        wform.addRow(self.watch)
        if not drag_available:
            note = QLabel(L("Not available here: this session does not let programs see drags in other windows "
                            "(Wayland). Use the file manager's right-click menu or the tray icon."))
            note.setWordWrap(True)
            note.setStyleSheet("color: gray;")
            wform.addRow(note)
        self._keys: dict[str, QComboBox] = {}
        for attribute, title in (("convert_modifier", L("Convert")), ("tools_modifier", L("Tools")),
                                 ("actions_modifier", L("Actions"))):
            combo = QComboBox()
            for value, name in _MODIFIERS:
                combo.addItem(name, value)
            combo.addItem(L("Off"), "none")
            combo.setCurrentIndex(max(0, combo.findData(getattr(settings, attribute))))
            combo.currentIndexChanged.connect(lambda _i, a=attribute, c=combo: self._set(a, c.currentData()))
            self._keys[attribute] = combo
            wform.addRow(title, combo)
        hint = QLabel(L("Start dragging a file, tap the key without letting go of the mouse, then drop the file "
                        "on a segment."))
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray;")
        wform.addRow(hint)
        root.addWidget(wheels)

        # Actions
        actions = QGroupBox(L("Actions"))
        aform = QFormLayout(actions)
        self.terminal = QComboBox()
        self.terminal.setEditable(True)
        self.terminal.addItem(L("Auto"), "auto")
        for name in _TERMINALS:
            if shutil.which(name):
                self.terminal.addItem(name, name)
        current = settings.terminal
        index = self.terminal.findData(current)
        if index >= 0:
            self.terminal.setCurrentIndex(index)
        else:
            self.terminal.setEditText(current)
        self.terminal.currentIndexChanged.connect(self._terminal_changed)
        edit = self.terminal.lineEdit()
        if edit is not None:
            edit.editingFinished.connect(self._terminal_edited)
        aform.addRow(L("Terminal"), self.terminal)
        self.float_moves = QCheckBox(L("Dragging out of Float moves the files"))
        self.float_moves.setChecked(settings.float_moves_files)
        self.float_moves.toggled.connect(lambda on: self._set("float_moves_files", on))
        aform.addRow(self.float_moves)
        root.addWidget(actions)

        # Quality
        quality = QGroupBox(L("Quality"))
        qform = QFormLayout(quality)
        self._sliders: dict[str, QSlider] = {}
        for attribute, title, scale in (("jpeg_quality", "JPG", 100), ("heic_quality", "HEIC", 100),
                                        ("avif_quality", "AVIF", 100), ("webp_quality", "WebP", 1)):
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(30, 100)
            value = getattr(settings, attribute)
            slider.setValue(int(round(value * scale)))
            label = QLabel(f"{slider.value()}")
            label.setMinimumWidth(28)
            slider.valueChanged.connect(lambda v, a=attribute, s=scale, lb=label: (lb.setText(str(v)),
                                                                                  self._set(a, v / s if s != 1 else v)))
            row = QHBoxLayout()
            row.addWidget(slider, 1)
            row.addWidget(label)
            holder = QWidget()
            holder.setLayout(row)
            row.setContentsMargins(0, 0, 0, 0)
            qform.addRow(title, holder)
            self._sliders[attribute] = slider
        self.metadata = QCheckBox(L("Keep metadata"))
        self.metadata.setChecked(settings.preserve_metadata)
        self.metadata.toggled.connect(lambda on: self._set("preserve_metadata", on))
        qform.addRow(self.metadata)
        root.addWidget(quality)
        root.addStretch(1)
        layoututil.fit(self, 500, fixed=False)

    def _terminal_changed(self) -> None:
        data = self.terminal.currentData()
        if data:
            self._set("terminal", data)

    def _terminal_edited(self) -> None:
        text = self.terminal.currentText().strip()
        self._set("terminal", "auto" if not text or text == L("Auto") else text)

    def _set(self, name: str, value, store: bool = True) -> None:  # noqa: ANN001
        if store:
            setattr(self.settings, name, value)
            self.settings.save()
        self._changed(name)

    def present(self) -> None:
        from . import screenfit

        screenfit.fit(self)
        self.show()
        self.raise_()
        self.activateWindow()


def _autostart_enabled() -> bool:
    from ..core import paths

    return paths.autostart_file().exists()


__all__ = ["SettingsWindow", "QLineEdit"]
