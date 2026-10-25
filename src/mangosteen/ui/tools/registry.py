"""Which tool id opens which window."""

from __future__ import annotations

from collections.abc import Callable

# tool id -> factory(paths, context) returning a window; filled by the tool modules as they are imported.
_FACTORIES: dict[str, Callable] = {}


def register(tool_id: str):  # noqa: ANN201
    def decorator(factory: Callable) -> Callable:
        _FACTORIES[tool_id] = factory
        return factory

    return decorator


def create(tool_id: str, paths: list[str], context):  # noqa: ANN001, ANN201
    """The window for a tool, or None when there is no such tool."""
    _load_all()
    factory = _FACTORIES.get(tool_id)
    return factory(paths, context) if factory else None


_loaded = False


def _load_all() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    import importlib

    for name in _MODULES:
        try:
            importlib.import_module(f"mangosteen.ui.tools.{name}")
        except ModuleNotFoundError as error:
            if error.name != f"mangosteen.ui.tools.{name}":
                raise


# Tool modules, imported on first use so that starting the app stays quick.
_MODULES: list[str] = ["compress_tool", "crop_tool", "editor_tool", "annotate_tool", "background_tool", "collage_tool", "hide_tool", "metadata_tool", "remove_background_tool", "pdf_tools", "media_tools", "audio_tools", "video_tools"]
