"""User preferences, kept in ~/.config/mangosteen/settings.json."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields

from . import log, loc, paths

MODIFIER_CHOICES = ("shift", "ctrl", "alt", "super", "none")


@dataclass
class ConversionOptions:
    """Quality settings the conversions use."""

    jpeg_quality: float = 0.85
    heic_quality: float = 0.8
    avif_quality: float = 0.7
    webp_quality: int = 80
    preserve_metadata: bool = True
    # Resolution used when rendering PDF pages to images.
    pdf_render_dpi: int = 300

    def quality(self, fmt) -> float | None:  # noqa: ANN001 - a FileFormat; avoids an import cycle
        from .file_format import FileFormat

        return {
            FileFormat.JPG: self.jpeg_quality,
            FileFormat.HEIC: self.heic_quality,
            FileFormat.AVIF: self.avif_quality,
            FileFormat.WEBP: self.webp_quality / 100,
        }.get(fmt)


@dataclass
class Settings:
    # "system", "en", "es" or "ru".
    language: str = "system"
    welcome_shown: bool = False
    convert_modifier: str = "shift"
    tools_modifier: str = "ctrl"
    actions_modifier: str = "alt"
    # Show the result in the file manager when a job ends.
    reveal_results: bool = False
    jpeg_quality: float = 0.85
    heic_quality: float = 0.8
    avif_quality: float = 0.7
    webp_quality: int = 80
    preserve_metadata: bool = True
    # "auto" picks the desktop's terminal; otherwise a command such as "kitty" or "gnome-terminal".
    terminal: str = "auto"
    # Dragging out of Float moves the original instead of copying it.
    float_moves_files: bool = False
    # The tab the Crop window opens on: "crop" or "size".
    crop_tab: str = "crop"
    # "Mangosteen" in the file manager's right-click menu.
    file_manager_menu: bool = True
    # Watch for drags with the wheel keys (X11 only; Wayland has no way to see a drag in another app).
    watch_drags: bool = True
    extra: dict = field(default_factory=dict)

    @classmethod
    def load(cls) -> Settings:
        try:
            data = json.loads(paths.settings_file().read_text(encoding="utf-8"))
            known = {f.name for f in fields(cls)}
            settings = cls(**{k: v for k, v in data.items() if k in known})
            for key in ("convert_modifier", "tools_modifier", "actions_modifier"):
                if getattr(settings, key) not in MODIFIER_CHOICES:
                    setattr(settings, key, getattr(cls(), key))
            return settings
        except (OSError, ValueError, TypeError):
            return cls()

    def save(self) -> None:
        try:
            paths.config_dir().mkdir(parents=True, exist_ok=True)
            paths.settings_file().write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")
        except OSError as error:
            log.error("settings", error)

    @property
    def effective_language(self) -> str:
        return loc.system_language() if self.language == "system" else self.language

    @property
    def conversion_options(self) -> ConversionOptions:
        return ConversionOptions(
            jpeg_quality=self.jpeg_quality,
            heic_quality=self.heic_quality,
            avif_quality=self.avif_quality,
            webp_quality=self.webp_quality,
            preserve_metadata=self.preserve_metadata,
        )

    def wheel_for_modifier(self, modifier: str):  # noqa: ANN201
        """The wheel opened by tapping `modifier`; the first matching wheel wins if two share a key."""
        from .wheel_catalog import WheelKind

        for kind, choice in (
            (WheelKind.CONVERT, self.convert_modifier),
            (WheelKind.TOOLS, self.tools_modifier),
            (WheelKind.ACTIONS, self.actions_modifier),
        ):
            if choice == modifier:
                return kind
        return None

    def modifier_for(self, kind) -> str:  # noqa: ANN001
        from .wheel_catalog import WheelKind

        return {
            WheelKind.CONVERT: self.convert_modifier,
            WheelKind.TOOLS: self.tools_modifier,
            WheelKind.ACTIONS: self.actions_modifier,
        }[kind]
