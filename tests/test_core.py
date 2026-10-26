import json
import os

from mangosteen.core import format_catalog, history, loc, output_naming, wheel_catalog
from mangosteen.core.file_format import Category, FileFormat, detect
from mangosteen.core.settings import Settings
from mangosteen.core.wheel_catalog import WheelKind

F = FileFormat


def test_detect_by_name():
    assert detect("/a/b/Photo.JPEG") is F.JPG
    assert detect("x.tif") is F.TIFF
    assert detect("archive.tar.gz") is F.TGZ
    assert detect("archive.TGZ") is F.TGZ
    assert detect("notes.markdown") is F.MD
    assert detect("noextension") is None
    assert detect("/folder.with.dots/") is None
    assert F.TGZ.extension == "tar.gz"
    assert F.WEBP.display_name == "WebP"
    assert F.MP3.category is Category.AUDIO
    assert F.SVG.category is Category.IMAGE and not F.SVG.is_raster_image


def test_unique_names(work):
    folder = str(work)
    assert output_naming.unique_path(folder, "photo", "png") == os.path.join(folder, "photo.png")
    (work / "photo.png").write_bytes(b"x")
    (work / "photo 2.png").write_bytes(b"x")
    assert output_naming.unique_path(folder, "photo", "png") == os.path.join(folder, "photo 3.png")
    assert output_naming.unique_path(folder, "dir", "") == os.path.join(folder, "dir")


def test_base_name_and_parts():
    assert output_naming.base_name("/x/archive.tar.gz") == "archive"
    assert output_naming.base_name("/x/photo.final.jpg") == "photo.final"
    assert output_naming.part_number(2, 12) == "03"
    assert output_naming.part_number(0, 5) == "1"


def test_write_atomically_never_overwrites_and_cleans_up(work):
    folder = str(work)
    (work / "out.txt").write_text("original")

    def produce(path):
        with open(path, "w") as stream:
            stream.write("new")

    result = output_naming.write_atomically(folder, "out", "txt", produce)
    assert result == os.path.join(folder, "out 2.txt")
    assert (work / "out.txt").read_text() == "original"
    assert sorted(os.listdir(folder)) == ["out 2.txt", "out.txt"]

    def fail(path):
        with open(path, "w") as stream:
            stream.write("partial")
        raise RuntimeError("boom")

    try:
        output_naming.write_atomically(folder, "bad", "txt", fail)
    except RuntimeError:
        pass
    assert sorted(os.listdir(folder)) == ["out 2.txt", "out.txt"]


def test_write_atomically_folders(work):
    def produce(path):
        os.mkdir(path)
        with open(os.path.join(path, "a.txt"), "w") as stream:
            stream.write("a")

    first = output_naming.write_atomically(str(work), "pages", "", produce)
    second = output_naming.write_atomically(str(work), "pages", "", produce)
    assert os.path.basename(first) == "pages" and os.path.basename(second) == "pages 2"
    assert os.listdir(first) == ["a.txt"]


def test_catalog_single_kind(work):
    photo = work / "a.jpg"
    photo.write_bytes(b"x")
    targets = format_catalog.targets([str(photo)])
    assert F.JPG not in targets and F.PNG in targets and F.PDF in targets
    assert targets[0] is F.PNG


def test_catalog_mixed_offers_only_common_targets(work):
    a, b, doc = work / "a.png", work / "b.jpg", work / "c.md"
    for p in (a, b, doc):
        p.write_bytes(b"x")
    # Two photos: PNG is offered because the PNG already is one (skipped), the JPG converts.
    two = format_catalog.targets([str(a), str(b)])
    assert F.PNG in two and F.JPG in two
    # A photo and a Markdown file share only PDF (both can become one).
    mixed = format_catalog.targets([str(a), str(doc)])
    assert mixed == [F.PDF]


def test_catalog_unknown_files_are_ignored_and_folders_archive(work):
    folder = work / "stuff"
    folder.mkdir()
    unknown = work / "x.unknownext"
    unknown.write_bytes(b"x")
    assert format_catalog.targets([str(unknown)]) == []
    assert format_catalog.targets([str(folder)]) == [F.ZIP, F.TAR, F.TGZ]
    assert format_catalog.targets([str(folder), str(unknown)]) == [F.ZIP, F.TAR, F.TGZ]


def test_split_for_pdf(work):
    names = ["a.png", "b.jpg", "c.docx"]
    paths = [str(work / n) for n in names]
    pages, separate = format_catalog.split_for_pdf(paths)
    assert pages == paths[:2] and separate == [paths[2]]
    pages, separate = format_catalog.split_for_pdf(paths[:1] + paths[2:])
    assert pages == [] and separate == paths[:1] + paths[2:]


def test_wheel_tools_for_images_and_pdfs(work):
    img, pdf1, pdf2 = work / "a.png", work / "a.pdf", work / "b.pdf"
    for p in (img, pdf1, pdf2):
        p.write_bytes(b"x")
    ids = [i.id for i in wheel_catalog.items(WheelKind.TOOLS, [str(img)])]
    assert ids[:4] == ["tool.compress", "tool.crop", "tool.edit", "tool.annotate"]
    assert "tool.collage" not in ids and "tool.mergePDF" not in ids
    ids = [i.id for i in wheel_catalog.items(WheelKind.TOOLS, [str(pdf1), str(pdf2)])]
    assert "tool.mergePDF" in ids and "tool.splitPDF" in ids and "tool.organizePDF" in ids
    ids = [i.id for i in wheel_catalog.items(WheelKind.TOOLS, [str(img), str(pdf1)])]
    assert ids == ["tool.compressAll", "tool.metadata", "tool.recognizeText", "tool.archive"]


def test_wheel_actions():
    ids = [i.id for i in wheel_catalog.items(WheelKind.ACTIONS, ["/x"])]
    assert ids == ["action.float", "action.copy", "action.move", "action.copyPath", "action.terminal"]


def test_loc_counts():
    loc.set_language("ru")
    assert [loc.count(n, "file") for n in (1, 2, 5, 11, 21, 22, 25)] == [
        "1 файл", "2 файла", "5 файлов", "11 файлов", "21 файл", "22 файла", "25 файлов"]
    loc.set_language("es")
    assert loc.count(1, "file") == "1 archivo" and loc.count(3, "file") == "3 archivos"
    loc.set_language("en")
    assert loc.count(1, "file") == "1 file" and loc.count(0, "file") == "0 files"


def test_loc_lookup_and_context_keys():
    loc.set_language("ru")
    assert loc.L("Convert") == "Конвертация"
    assert loc.L("A string nobody translated") == "A string nobody translated"
    loc.set_language("en")
    assert loc.L("Crop|tab") == "Crop"
    assert loc.fmt("{0} of {1}", 2, 5) == "2 of 5"


def test_translation_tables_cover_each_other():
    ru, es = loc.load("ru"), loc.load("es")
    assert set(ru) == set(es)
    assert all(ru.values()) and all(es.values())


def test_settings_roundtrip_and_validation(tmp_path):
    settings = Settings()
    settings.language = "ru"
    settings.jpeg_quality = 0.5
    settings.save()
    loaded = Settings.load()
    assert loaded.language == "ru" and loaded.jpeg_quality == 0.5
    from mangosteen.core import paths

    data = json.loads(paths.settings_file().read_text())
    data["convert_modifier"] = "bogus"
    data["unknown_key"] = 1
    paths.settings_file().write_text(json.dumps(data))
    assert Settings.load().convert_modifier == "shift"
    assert loaded.wheel_for_modifier("ctrl") is WheelKind.TOOLS
    assert loaded.wheel_for_modifier("super") is None


def test_history_prunes_missing_files(work):
    file = work / "history.json"
    h = history.ResultHistory.load(file)
    a, b = work / "a.txt", work / "b.txt"
    a.write_text("a")
    b.write_text("b")
    h.add("Convert", [str(a)])
    h.add("Tools", [str(b)])
    assert [e.title for e in h.live()] == ["Tools", "Convert"]
    b.unlink()
    assert [e.title for e in h.live()] == ["Convert"]
    assert [e.title for e in history.ResultHistory.load(file).entries] == ["Convert"]
    for i in range(30):
        h.add(f"job {i}", [str(a)])
    assert len(h.entries) == history.KEPT and len(h.live()) == history.SHOWN


def test_first_launch_with_a_tool_starts_the_real_application(tmp_path):
    """`mangosteen --tool …` as the first launch used to create a QCoreApplication for the hand-over check and then
    fail on QApplication methods; the application must start, and a second launch must hand over and quit it."""
    import subprocess
    import sys
    import time

    from PIL import Image

    picture = tmp_path / "t.png"
    Image.new("RGB", (40, 30), "purple").save(picture)
    environment = dict(os.environ, QT_QPA_PLATFORM="offscreen", MANGOSTEEN_HOME=str(tmp_path / "home"))
    first = subprocess.Popen([sys.executable, "-m", "mangosteen", "--tool", "tool.crop", str(picture)], env=environment,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 60
        while first.poll() is None and time.monotonic() < deadline:  # a cold start can take a while
            time.sleep(1.5)
            subprocess.run([sys.executable, "-m", "mangosteen", "--quit"], env=environment, timeout=30, check=True)
        assert first.returncode == 0, first.stderr.read().decode()[-600:]
    finally:
        if first.poll() is None:
            first.kill()


def test_drags_are_only_watched_in_a_real_x11_session(monkeypatch):
    from mangosteen.platform import x11

    for name in ("DISPLAY", "XDG_SESSION_TYPE", "WAYLAND_DISPLAY", "MANGOSTEEN_WATCH_DRAGS_ON_WAYLAND"):
        monkeypatch.delenv(name, raising=False)
    assert not x11.can_watch_drags()                      # no display at all
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    assert x11.can_watch_drags()                          # a real X11 session
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    assert not x11.can_watch_drags()                      # XWayland inside Wayland: leave drags alone
    monkeypatch.setenv("MANGOSTEEN_WATCH_DRAGS_ON_WAYLAND", "1")
    assert x11.can_watch_drags()                          # unless asked to


def test_float_shows_thumbnails(qapp, tmp_path):
    """Thumbnails are made on a worker pool; they used to be handed over with a timer on that thread, which never
    fired, so the shelf showed only icons."""
    import time

    import pillow_heif
    from PIL import Image
    from PySide6.QtWidgets import QApplication

    from mangosteen.ui.float_shelf import FloatShelf

    pillow_heif.register_heif_opener()
    paths = [tmp_path / "a.png", tmp_path / "b.heic"]
    for path in paths:
        Image.new("RGB", (120, 80), "purple").save(path)
    shelf = FloatShelf()
    shelf.add([str(p) for p in paths])
    deadline = time.monotonic() + 10

    def thumbnails():
        from mangosteen.ui.float_shelf import _Row

        return [row for row in shelf.findChildren(_Row) if row.picture.pixmap() is not None
                and not row.picture.pixmap().isNull() and row.picture.pixmap().width() > 30]
    while len(thumbnails()) < 2 and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.02)
    assert len(thumbnails()) == 2
    shelf.close()
    shelf.deleteLater()


def test_float_names_home_folders_with_a_tilde(monkeypatch):
    from mangosteen.ui.float_shelf import folder_label

    monkeypatch.setenv("HOME", "/home/anna")
    assert folder_label("/home/anna/Pictures") == "~/Pictures"
    assert folder_label("/home/anna") == "~"
    assert folder_label("/home/annabel/x") == "/home/annabel/x"
    assert folder_label("/tmp") == "/tmp"
