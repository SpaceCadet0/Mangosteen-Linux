"""Run under a real X server (xvfb-run) with GTK 3 for the system Python (python3-gi, gir1.2-gtk-3.0): a GTK window,
like Nautilus, Nemo, Thunar or PCManFM, drags 60 files and answers the first request for its list with only 58, as a
file manager that has not finished writing the list does. The drag monitor must have all 60 by the key tap."""

import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
os.environ.setdefault("MANGOSTEEN_HOME", tempfile.mkdtemp())
os.environ["QT_QPA_PLATFORM"] = "xcb"

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from mangosteen.platform.drag_monitor import DragMonitor  # noqa: E402

SOURCE = textwrap.dedent('''
    import sys, tempfile
    from pathlib import Path
    import gi
    gi.require_version("Gtk", "3.0"); gi.require_version("Gdk", "3.0")
    from gi.repository import Gdk, Gtk
    work = Path(tempfile.mkdtemp())
    uris = []
    for i in range(60):
        f = work / f"photo {i:02d}.jpg"
        f.write_bytes(b"x")
        uris.append(f.as_uri())
    asked = [0]
    def get(widget, context, data, info, time):
        asked[0] += 1
        data.set_uris(uris if asked[0] > 1 else uris[:58])
    window = Gtk.Window()
    window.move(0, 0)
    window.set_default_size(300, 220)
    box = Gtk.EventBox()
    box.add(Gtk.Label(label="drag me"))
    window.add(box)
    box.drag_source_set(Gdk.ModifierType.BUTTON1_MASK, [Gtk.TargetEntry.new("text/uri-list", 0, 0)], Gdk.DragAction.COPY)
    box.connect("drag-data-get", get)
    box.connect("drag-end", lambda *a: Gtk.main_quit())
    window.show_all()
    print("ready", flush=True)
    Gtk.main()
''')


def xdo(*args: str) -> None:
    subprocess.run(["xdotool", *args], check=True)


python = os.environ.get("GTK_PYTHON", "/usr/bin/python3")
source = subprocess.Popen([python, "-c", SOURCE], stdout=subprocess.PIPE, text=True)
if source.stdout.readline().strip() != "ready":
    print("the GTK source did not start")
    sys.exit(2)

app = QApplication([])
log: list[str] = []
monitor = DragMonitor()
monitor.drag_started.connect(lambda paths: log.append(f"start {len(paths)}"))
monitor.modifier_tapped.connect(lambda name, paths: log.append(f"tap {len(paths)}"))
monitor.drag_ended.connect(lambda: (log.append("end"), QTimer.singleShot(200, app.quit)))
if not monitor.start():
    print("monitor did not start")
    sys.exit(2)

QTimer.singleShot(600, lambda: (xdo("mousemove", "100", "100"), xdo("mousedown", "1")))
QTimer.singleShot(1100, lambda: [xdo("mousemove_relative", "--", "12", "6") for _ in range(8)])
QTimer.singleShot(1900, lambda: xdo("keydown", "shift", "sleep", "0.15", "keyup", "shift"))
QTimer.singleShot(2700, lambda: xdo("mouseup", "1"))
QTimer.singleShot(9000, app.quit)
app.exec()
monitor.stop()
source.kill()
print(log)
ok = "tap 60" in log
print("OK" if ok else "FAILED")
sys.exit(0 if ok else 1)
