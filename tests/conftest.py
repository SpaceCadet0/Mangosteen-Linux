import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Settings, history and log go to a throw-away folder; English is the language."""
    monkeypatch.setenv("MANGOSTEEN_HOME", str(tmp_path / "mangosteen-home"))
    from mangosteen.core import loc

    loc.set_language("en")
    yield
    loc.set_language("en")


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(["mangosteen-tests"])
    yield app


@pytest.fixture
def work(tmp_path):
    folder = tmp_path / "work"
    folder.mkdir()
    return folder
