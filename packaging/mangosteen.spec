# PyInstaller spec: a one-folder bundle of Mangosteen, used by build-appimage.sh and build-deb.sh.
#   pyinstaller --noconfirm --distpath dist --workpath build packaging/mangosteen.spec
from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None

hidden = collect_submodules("mangosteen")  # the tool windows are imported by name at run time
datas = [("../src/mangosteen/strings/*.json", "mangosteen/strings"), ("../src/mangosteen/assets/*", "mangosteen/assets")]
binaries = []
for package in ("pypdfium2", "pypdfium2_raw", "pillow_heif"):
    try:
        d, b, h = collect_all(package)
    except Exception:  # an optional package that is not installed
        continue
    datas += d
    binaries += b
    hidden += h

# Qt parts the app never uses; leaving them out keeps the bundle a few hundred megabytes smaller.
excludes = [
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick", "PySide6.QtQuick", "PySide6.QtQml",
    "PySide6.Qt3DCore", "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtBluetooth", "PySide6.QtNfc",
    "PySide6.QtSensors", "PySide6.QtSerialPort", "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtDesigner",
    "PySide6.QtHelp", "PySide6.QtTest", "PySide6.QtSql", "PySide6.QtNetworkAuth", "PySide6.QtRemoteObjects",
    "PySide6.QtScxml", "PySide6.QtSpatialAudio", "PySide6.QtTextToSpeech", "PySide6.QtWebChannel", "PySide6.QtWebSockets",
    "tkinter", "matplotlib", "scipy",
]

a = Analysis(["entry.py"], pathex=["../src"], binaries=binaries, datas=datas, hiddenimports=hidden,
             excludes=excludes, noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="mangosteen", console=False, debug=False, strip=False, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="mangosteen")
