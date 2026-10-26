"""Run under xvfb-run: the real Application watches for a drag started in another window, a Shift tap opens the
Convert wheel, a drop on the PNG segment converts the dragged photo, and the result appears next to it."""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
home = tempfile.mkdtemp()
os.environ["MANGOSTEEN_HOME"] = home
os.environ["XDG_DATA_HOME"] = os.path.join(home, "data")
os.environ["XDG_CONFIG_HOME"] = os.path.join(home, "config")
os.environ["QT_QPA_PLATFORM"] = "xcb"

from PySide6.QtCore import QMimeData, QObject, Qt, QTimer, QUrl, Slot  # noqa: E402
from PySide6.QtGui import QDrag  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from mangosteen.app import Application  # noqa: E402
from mangosteen.ui.wheel import DIAMETER  # noqa: E402

work = Path(tempfile.mkdtemp())
sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_fixtures  # noqa: E402

photo = Path(make_fixtures.photo(str(work / "holiday photo.jpg")))
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


from mangosteen.core.settings import Settings  # noqa: E402

settings = Settings()
settings.welcome_shown = True  # the welcome window would cover the drag source
settings.save()
qapp = QApplication([])
app = Application(qapp)
assert app.start(), "could not start"
assert app.drag_available, "the drag monitor did not start"
source = Source("drag me")
source.setGeometry(40, 40, 240, 160)
source.show()


class Driver(QObject):
    @Slot()
    def step1(self):
        xdo("mousemove", "100", "100")
        xdo("mousedown", "1")

    @Slot()
    def step2(self):
        for _ in range(8):
            xdo("mousemove_relative", "--", "12", "6")

    @Slot()
    def step3(self):
        # Held as long as a person would: the monitor polls the modifiers, an instant tap falls between polls.
        xdo("keydown", "shift", "sleep", "0.15", "keyup", "shift")

    @Slot()
    def step4(self):
        g = app.wheel.widget.geometry()
        log.append(f"monitor alive={app.monitor._thread.is_alive()} running={app.monitor.running}")
        log.append(f"wheel visible={app.wheel.is_visible} items={[i.title for i in app.wheel.widget.items]}")
        x, y = g.x() + DIAMETER // 2, g.y() + DIAMETER // 2 - 112
        for i in range(5, -1, -1):
            xdo("mousemove", str(x), str(y + i * 4))

    @Slot()
    def step5(self):
        xdo("mouseup", "1")

    @Slot()
    def finish(self):
        qapp.quit()


driver = Driver()
for delay, name in ((400, "step1"), (900, "step2"), (1800, "step3"), (2700, "step4"), (3400, "step5"), (7000, "finish")):
    QTimer.singleShot(delay, getattr(driver, name))
qapp.exec()
app.monitor.stop()
print("\n".join(log)); print(open(os.path.join(home, "mangosteen.log")).read() if os.path.exists(os.path.join(home, "mangosteen.log")) else "no log")
outputs = sorted(p.name for p in work.iterdir())
print("files:", outputs)
history = [(e.title, [os.path.basename(o) for o in e.outputs]) for e in app.history.entries]
print("history:", history)
ok = "holiday photo.png" in outputs and history and history[0][1] == ["holiday photo.png"]
print("OK" if ok else "FAILED")
sys.exit(0 if ok else 1)
