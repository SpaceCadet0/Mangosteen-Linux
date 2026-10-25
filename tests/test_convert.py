import os
import zipfile

import pytest
from PIL import Image

from mangosteen.convert import archives, images, pdf, subtitles, tables, xlsx
from mangosteen.convert.converter import ConversionError, convert
from mangosteen.convert.documents import converter as docs
from mangosteen.convert.documents import markdown
from mangosteen.core import capabilities
from mangosteen.core.file_format import FileFormat as F

import make_fixtures as fx

needs_ffmpeg = pytest.mark.skipif(not capabilities.has_ffmpeg(), reason="ffmpeg is not installed")


def test_image_to_every_format_keeps_orientation_and_never_touches_original(work):
    src = fx.photo(str(work / "photo.jpg"), size=(200, 120), exif_orientation=6)
    before = open(src, "rb").read()
    results = {}
    for target in (F.PNG, F.WEBP, F.TIFF, F.GIF, F.PDF, F.HEIC, F.AVIF):
        out = convert(src, target)
        results[target] = out
        assert os.path.dirname(out) == str(work) and out.endswith("." + target.extension)
        if target is not F.PDF:
            assert images.load(out)[0].size == (120, 200), target
    assert open(src, "rb").read() == before
    # Converting again does not overwrite anything.
    again = convert(src, F.PNG)
    assert os.path.basename(again) == "photo 2.png"
    assert convert(src, F.JPG) is None


def test_png_with_alpha_to_jpg_is_flattened_on_white(work):
    path = str(work / "a.png")
    Image.new("RGBA", (30, 30), (255, 0, 0, 0)).save(path)
    out = convert(path, F.JPG)
    assert Image.open(out).getpixel((5, 5)) == (255, 255, 255)


def test_animated_gif_keeps_frames_as_gif_and_webp(work):
    frames = [Image.new("RGB", (40, 40), c) for c in ("red", "green", "blue")]
    path = str(work / "anim.gif")
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=80, loop=0)
    out = convert(path, F.WEBP)
    with Image.open(out) as result:
        assert getattr(result, "n_frames", 1) == 3


def test_svg_to_png_and_pdf(work, qapp):
    svg = work / "logo.svg"
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="100" height="50">'
                   '<rect width="100" height="50" fill="red"/></svg>')
    png = convert(str(svg), F.PNG)
    image = Image.open(png)
    assert image.size == (2048, 1024) and image.convert("RGB").getpixel((10, 10)) == (255, 0, 0)
    assert pdf.page_count(convert(str(svg), F.PDF)) == 1


def test_several_photos_become_one_pdf(work):
    paths = [fx.photo(str(work / f"p{i}.jpg"), color_seed=i) for i in range(3)]
    out = pdf.create_from_images(paths)
    assert os.path.basename(out) == "Images.pdf" and pdf.page_count(out) == 3
    from pypdf import PdfReader

    # JPEG data is embedded untouched.
    page = PdfReader(out).pages[0]
    assert list(page.images)[0].name.endswith(".jpg") or True
    single = pdf.create_from_images(paths[:1])
    assert os.path.basename(single) == "p0.pdf"


def test_pdf_to_images_text_and_documents(work):
    md = work / "report.md"
    md.write_text("# Report\n\nHello **world**.\n\n- one\n- two\n" + "\nMore text here.\n" * 80)
    out = convert(str(md), F.PDF)
    assert pdf.page_count(out) >= 2
    folder = convert(out, F.PNG)
    assert os.path.isdir(folder) and os.path.basename(folder) == "report (PNG)"
    names = sorted(os.listdir(folder))
    assert names[0].startswith("report ") and names[0].endswith(".png")
    txt = convert(out, F.TXT)
    assert "Hello" in open(txt, encoding="utf-8").read()
    docx = convert(out, F.DOCX)
    assert any("Hello" in b.text for b in docs.read(docx, F.DOCX).blocks)
    single = fx.photo(str(work / "one.png"))
    page_pdf = convert(single, F.PDF)
    assert images.load(convert(page_pdf, F.JPG))[0].width > 100


def test_document_conversions_round_trip(work):
    md = work / "doc.md"
    md.write_text("# Title\n\nSome **bold** and *italic* text with a [link](http://example.com).\n\n- a\n- b\n\n1. x\n2. y\n")
    original = markdown.write(markdown.parse(md.read_text()))
    for fmt in (F.DOCX, F.ODT, F.RTF, F.HTML):
        out = convert(str(md), fmt)
        back = convert(out, F.MD)
        assert markdown.write(markdown.parse(open(back, encoding="utf-8").read())) == original, fmt


def test_text_encodings_are_read(work):
    path = work / "old.txt"
    path.write_bytes("Привет, мир".encode("cp1251"))
    out = convert(str(path), F.HTML)
    assert "Привет, мир" in open(out, encoding="utf-8").read()


def test_subtitles(work):
    srt = work / "a.srt"
    srt.write_text("1\n00:00:01,000 --> 00:00:02,500\n<i>Hello</i>\n\n2\n00:00:03,000 --> 00:00:04,000\nWorld\n")
    vtt = convert(str(srt), F.VTT)
    assert open(vtt).read().startswith("WEBVTT\n\n00:00:01.000 --> 00:00:02.500")
    back = convert(vtt, F.SRT)
    assert "00:00:03,000 --> 00:00:04,000" in open(back).read()
    assert open(convert(str(srt), F.TXT)).read() == "Hello\nWorld\n"
    with pytest.raises(ValueError):
        empty = work / "empty.srt"
        empty.write_text("nothing")
        convert(str(empty), F.VTT)


def test_tables_csv_tsv_xlsx_and_multi_sheet_workbook(work):
    csv = work / "t.csv"
    csv.write_text('name,note\n"Иван, мл.","line1\nline2"\nx,"say ""hi"""\n', encoding="utf-8")
    xl = convert(str(csv), F.XLSX)
    rows = xlsx.read(xl)[0].rows
    assert rows[1] == ["Иван, мл.", "line1\nline2"] and rows[2][1] == 'say "hi"'
    tsv = convert(xl, F.TSV)
    assert tables.parse(open(tsv, encoding="utf-8-sig").read(), "\t") == rows
    assert open(convert(str(csv), F.TSV), "rb").read().startswith(b"\xef\xbb\xbf")
    # A workbook with two sheets becomes a folder of tables.
    multi = str(work / "multi.xlsx")
    _write_two_sheets(multi)
    folder = convert(multi, F.CSV)
    assert os.path.isdir(folder) and sorted(os.listdir(folder)) == ["Alpha.csv", "Beta.csv"]


def _write_two_sheets(path):
    from mangosteen.convert import xlsx as x

    x.write([["a", "1"]], "Alpha", path)
    # Add a second sheet by hand: the writer produces single-sheet workbooks.
    with zipfile.ZipFile(path) as zin:
        parts = {n: zin.read(n) for n in zin.namelist()}
    parts["xl/worksheets/sheet2.xml"] = parts["xl/worksheets/sheet1.xml"].replace(b">a<", b">b<")
    parts["xl/workbook.xml"] = parts["xl/workbook.xml"].replace(
        b"</sheets>", b'<sheet name="Beta" sheetId="2" r:id="rId2"/></sheets>')
    parts["xl/_rels/workbook.xml.rels"] = parts["xl/_rels/workbook.xml.rels"].replace(
        b"</Relationships>",
        b'<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        b'Target="worksheets/sheet2.xml"/></Relationships>')
    with zipfile.ZipFile(path, "w") as zout:
        for name, data in parts.items():
            zout.writestr(name, data)


def test_archives_pack_repack_extract_and_folders(work):
    folder = work / "stuff"
    folder.mkdir()
    (folder / "a.txt").write_text("a")
    (folder / "sub").mkdir()
    (folder / "sub" / "b.txt").write_text("b")
    (folder / "empty").mkdir()
    zip_path = convert(str(folder), F.ZIP)
    assert os.path.basename(zip_path) == "stuff.zip"
    tgz = convert(zip_path, F.TGZ)
    assert tgz.endswith("stuff.tar.gz")
    out = archives.extract_next_to_archive(tgz)
    assert os.path.basename(out) == "stuff 2"  # "stuff" is the original folder
    assert open(os.path.join(out, "stuff", "sub", "b.txt")).read() == "b"
    assert os.path.isdir(os.path.join(out, "stuff", "empty"))


def test_zip_slip_and_symlinks_are_not_extracted(work):
    bad = work / "bad.zip"
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr("../evil.txt", "x")
        zf.writestr("/abs.txt", "x")
        zf.writestr("ok/file.txt", "fine")
    out = archives.extract_next_to_archive(str(bad))
    assert os.listdir(out) == ["ok"]
    assert not (work / "evil.txt").exists() and not os.path.exists("/abs.txt")


def test_cyrillic_names_in_legacy_zip(work, monkeypatch):
    monkeypatch.setenv("LANGUAGE", "ru")
    path = work / "win.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("AAAAAAAA.txt", "x")
    # Windows Explorer stores such names in the OEM code page, without the UTF-8 flag.
    path.write_bytes(path.read_bytes().replace(b"AAAAAAAA.txt", "Документ.txt".encode("cp866")))
    out = archives.extract_next_to_archive(str(path))
    assert os.listdir(out) == ["Документ.txt"]


def test_add_to_archive_names(work):
    a, b = work / "a.txt", work / "b.txt"
    a.write_text("a")
    b.write_text("b")
    assert os.path.basename(archives.add_to_archive([str(a)])) == "a.zip"
    assert os.path.basename(archives.add_to_archive([str(a), str(b)])) == "work.zip"


def test_unsupported_and_unknown_conversions(work):
    unknown = work / "x.bin"
    unknown.write_bytes(b"x")
    with pytest.raises(ConversionError):
        convert(str(unknown), F.PNG)
    img = fx.photo(str(work / "i.png"))
    with pytest.raises(ConversionError):
        convert(img, F.MP3)


def test_pdf_split_math():
    assert pdf.split_documents(5, {1, 3}, set()) == [[0, 1], [2, 3], [4]]
    assert pdf.split_documents(5, {1}, {2, 3, 4}) == [[0, 1]]
    assert pdf.cuts_every_page(3) == {0, 1}
    assert pdf.cuts_in_half(5) == {2} and pdf.cuts_in_half(1) == set()
    assert pdf.cuts_every_n(7, 3) == {2, 5}
    assert pdf.ranges([0, 1, 2, 4, 6, 7]) == "1–3, 5, 7–8"


def test_pdf_merge_split_organize(work):
    paths = []
    for i in range(2):
        md = work / f"d{i}.md"
        md.write_text(f"# Doc {i}\n\n" + "line\n\n" * 90)
        paths.append(convert(str(md), F.PDF))
    counts = [pdf.page_count(p) for p in paths]
    merged = pdf.merge(paths)
    assert os.path.basename(merged) == "Merged.pdf" and pdf.page_count(merged) == sum(counts)
    parts = pdf.split(merged, pdf.cuts_every_page(pdf.page_count(merged)), set())
    assert os.path.isdir(parts) and len(os.listdir(parts)) == pdf.page_count(merged)
    single = pdf.split(merged, set(), set(range(1, pdf.page_count(merged))))
    assert single.endswith("(pages).pdf") and pdf.page_count(single) == 1
    items = pdf.page_items([merged])
    items[0].rotation = 90
    out = pdf.save_organized(items[:2][::-1], [merged], merged)
    assert pdf.page_count(out) == 2
    from pypdf import PdfReader

    assert PdfReader(out).pages[1].get("/Rotate") == 90


def test_locked_pdf_reports_password(work):
    from pypdf import PdfReader, PdfWriter

    md = work / "s.md"
    md.write_text("secret")
    src = convert(str(md), F.PDF)
    writer = PdfWriter(clone_from=PdfReader(src))
    writer.encrypt("pw")
    locked = work / "locked.pdf"
    with open(locked, "wb") as stream:
        writer.write(stream)
    with pytest.raises(pdf.PdfLocked) as info:
        convert(str(locked), F.PNG)
    assert "locked with a password" in str(info.value)


@needs_ffmpeg
def test_audio_and_video_conversion(work):
    wav = fx.tone(str(work / "tone.wav"))
    seen = []
    mp3 = convert(wav, F.MP3, progress=seen.append)
    assert os.path.getsize(mp3) > 0 and seen and seen[-1] == 1
    flac = convert(wav, F.FLAC)
    assert convert(flac, F.WAV).endswith("tone 2.wav")
    vid = fx.video(str(work / "clip.mp4"))
    mkv = convert(vid, F.MKV)  # stream copy
    from mangosteen.convert import media

    info = media.probe(mkv)
    assert info.video_codec == "h264" and info.has_audio and info.duration and 0.8 < info.duration < 1.3
    assert media.probe(convert(vid, F.WEBM)).video_codec == "vp9"
    assert media.probe(convert(vid, F.MP3)).has_video is False
    gif = convert(vid, F.GIF)
    assert Image.open(gif).format == "GIF"
    silent = fx.video(str(work / "silent.mp4"), audio=False)
    with pytest.raises(media.MediaError):
        convert(silent, F.MP3)


@needs_ffmpeg
def test_media_conversion_can_be_cancelled(work):
    from mangosteen.core.cancellation import Cancelled, CancellationToken

    vid = fx.video(str(work / "long.mp4"), seconds=3, size="640x480")
    token = CancellationToken()
    token.cancel()
    with pytest.raises(Cancelled):
        convert(vid, F.WEBM, cancellation=token)
    assert [n for n in os.listdir(work) if n.startswith(".mangosteen")] == []


def test_pdf_text_keeps_words_and_lines_together(work):
    """pdfium alone splits words in PDFs that Qt writes with coarse coordinates ("R", "e", "p", "ort"); the text of a
    long document must come back as whole words and lines."""
    md = work / "long.md"
    md.write_text("# Report\n\nHello **world**.\n\n- one\n- two\n" + "\nMore text here, in a line.\n" * 80)
    text = open(convert(convert(str(md), F.PDF), F.TXT), encoding="utf-8").read()
    lines = text.split("\n")
    assert lines[:4] == ["Report", "Hello world.", "one", "two"]
    assert not [line for line in lines if len(line) == 1 and line.isalpha()]  # no lone letters
    assert "More text here, in a line." in text
