"""Run under a real X server (xvfb-run): a Qt window starts a file drag, xdotool taps Shift mid-drag, the wheel must
appear under the pointer, and a drop on its first segment must select it. Exit code 0 means it all happened."""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
os.environ.setdefault("MANGOSTEEN_HOME", tempfile.mkdtemp())
os.environ["QT_QPA_PLATFORM"] = "xcb"

from PySide6.QtCore import QMimeData, QPoint, Qt, QTimer, QUrl  # noqa: E402
from PySide6.QtGui import QDrag  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from mangosteen.core import wheel_catalog  # noqa: E402
from mangosteen.core.wheel_catalog import WheelKind  # noqa: E402
from mangosteen.platform.drag_monitor import DragMonitor, nudge  # noqa: E402
from mangosteen.ui import brand  # noqa: E402
from mangosteen.ui.wheel import DIAMETER, WheelController  # noqa: E402

work = Path(tempfile.mkdtemp())
photo = work / "photo with space.jpg"
photo.write_bytes(b"x")
log: list[str] = []


def xdo(*args: str) -> None:
    subprocess.run(["xdotool", *args], check=True)


class Source(QLabel):
    def mouseMoveEvent(self, event):  # noqa: N802
        if event.buttons() & Qt.MouseButton.LeftButton:
            mime = QMimeData()
            mime.setUrls([QUrl.fromLocalFile(str(photo))])
            drag = QDrag(self)
            drag.setMimeData(mime)
            drag.exec(Qt.DropAction.CopyAction)
            log.append("drag finished")


app = QApplication([])
brand.apply_palette(app)
chosen: list = []
wheel = WheelController(lambda item, paths: (chosen.append((item.id, paths)), QTimer.singleShot(200, app.quit)),
                        wheel_catalog.items)
monitor = DragMonitor()
started: list = []
monitor.drag_started.connect(lambda paths: (started.append(paths), log.append(f"drag_started {paths}")))
monitor.modifier_tapped.connect(lambda name, paths: (
    log.append(f"tap {name}"),
    wheel.show(WheelKind.CONVERT, paths or None)))
wheel.on_shown_without_files = lambda: QTimer.singleShot(30, lambda: log.append(f"nudge {nudge()}"))
monitor.drag_ended.connect(lambda: (log.append("drag_ended"), wheel.drag_ended()))
if not monitor.start():
    print("monitor did not start")
    sys.exit(2)

source = Source("drag me")
source.setGeometry(40, 40, 240, 160)
source.show()


def step1():
    xdo("mousemove", "100", "100")
    xdo("mousedown", "1")


def step2():
    for dx in range(1, 8):
        xdo("mousemove_relative", "--", "12", "6")


def step3():
    # Held as long as a person would: the monitor polls the modifiers, an instant tap falls between polls.
    xdo("keydown", "shift", "sleep", "0.15", "keyup", "shift")


def step4():
    geometry = wheel.widget.geometry()
    log.append(f"wheel visible={wheel.is_visible} at {geometry.x()},{geometry.y()}")
    # The first segment is at 12 o'clock.
    target_x = geometry.x() + DIAMETER // 2
    target_y = geometry.y() + DIAMETER // 2 - 112
    for i in range(1, 6):
        xdo("mousemove", str(target_x), str(target_y + (5 - i) * 4))
    xdo("mousemove", str(target_x), str(target_y))


def step5():
    xdo("mouseup", "1")


def timeout():
    print("TIMEOUT", log)
    app.exit(3)


QTimer.singleShot(400, step1)
QTimer.singleShot(900, step2)
QTimer.singleShot(1800, step3)
QTimer.singleShot(2600, step4)
QTimer.singleShot(3300, step5)
QTimer.singleShot(9000, timeout)
code = app.exec()
monitor.stop()
print("\n".join(log))
print("chosen:", chosen)
ok = code == 0 and chosen and chosen[0][0] == "convert.png" and chosen[0][1] == [str(photo)] and started
print("OK" if ok else "FAILED")
sys.exit(0 if ok else 1)
