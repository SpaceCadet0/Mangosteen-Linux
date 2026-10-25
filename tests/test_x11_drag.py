"""The real thing on a real X server: a drag in another window, a modifier tap, the wheel, a drop."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

needs_x = pytest.mark.skipif(not (shutil.which("xvfb-run") and shutil.which("xdotool")),
                             reason="xvfb-run and xdotool are needed")


@needs_x
def test_drag_tap_wheel_drop_on_x11():
    script = Path(__file__).with_name("xvfb_drag_scenario.py")
    result = subprocess.run(["xvfb-run", "-a", "-s", "-screen 0 1280x800x24", sys.executable, str(script)],
                            capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK" in result.stdout


@needs_x
def test_application_converts_a_dragged_photo_on_x11():
    """The whole app: the drag monitor, the wheel, the job queue, the history."""
    script = Path(__file__).with_name("xvfb_app_scenario.py")
    result = subprocess.run(["xvfb-run", "-a", "-s", "-screen 0 1280x800x24", sys.executable, str(script)],
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK" in result.stdout
