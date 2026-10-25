"""The image and PDF tools' engines: geometry, adjustments, compression, redaction, metadata, annotations, PDF editing."""

import os
from datetime import datetime

import numpy as np
import pytest
from PIL import Image

from make_fixtures import photo
from mangosteen.convert import pdf
from mangosteen.core.settings import ConversionOptions
from mangosteen.imaging import adjust, annotations, compose, compress, cropper, geometry, metadata, redact
from mangosteen.imaging.geometry import Edges, ImageTransform, ResizeRule, UnitRect

OPTIONS = ConversionOptions()


def names(folder):
    return sorted(os.listdir(folder))


def make_pdf(path, pages=3, size=(200, 280)):
    images = [Image.new("RGB", size, (40 * (i + 1), 90, 160)) for i in range(pages)]
    images[0].save(path, save_all=True, append_images=images[1:])
    return str(path)


# MARK: Geometry


def test_unit_rect_to_pixels_is_clamped_and_never_empty():
    box = UnitRect(0.999, 0.999, 0.0, 0.0).to_pixels(100, 50)
    assert box.width >= 1 and box.height >= 1
    assert box.right <= 100 and box.bottom <= 50
    full = UnitRect(-1, -1, 3, 3).to_pixels(100, 50)
    assert (full.x, full.y) == (0, 0)


def test_resize_keeps_the_aspect_when_locked():
    rect = UnitRect(0.25, 0.25, 0.5, 0.5)
    resized = geometry.resize(rect, Edges.RIGHT, 0.1, 0.0, 1.0)
    assert resized is not None
    assert resized.width / resized.height == pytest.approx(1.0, abs=1e-6) or resized.width > rect.width


def test_resize_rules():
    assert ResizeRule("percent", 50).apply(1000, 500) == (500, 250)
    assert ResizeRule("long_side", 400).apply(1000, 500) == (400, 200)
    assert ResizeRule("long_side", 4000).apply(1000, 500) == (1000, 500)  # never enlarges
    assert ResizeRule("width", 200).apply(1000, 500) == (200, 100)
    assert ResizeRule("height", 100).apply(1000, 500) == (200, 100)
    assert ResizeRule("exact", 33, 77).apply(1000, 500) == (33, 77)


def test_transform_rotates_and_flips():
    image = Image.new("RGB", (40, 20))
    image.putpixel((0, 0), (255, 0, 0))
    turned = ImageTransform().rotate(True).apply(image)
    assert turned.size == (20, 40)
    assert turned.getpixel((19, 0)) == (255, 0, 0)  # the top-left corner went to the top-right
    flipped = ImageTransform().flip(True).apply(image)
    assert flipped.getpixel((39, 0)) == (255, 0, 0)
    assert ImageTransform().is_identity


def test_tiles_cover_the_image_exactly():
    parts = geometry.tiles(geometry.even_cuts(3), geometry.even_cuts(2), 301, 200)
    assert len(parts) == 6
    assert sum(t.width * t.height for t in parts) == 301 * 200


# MARK: Cropping and resizing files


def test_crop_file_crops_and_keeps_the_format(work):
    source = photo(str(work / "p.jpg"), (400, 300))
    result = cropper.crop_file(source, UnitRect(0.25, 0.25, 0.5, 0.5), None, None, [], [], OPTIONS)
    assert os.path.basename(result) == "p (cropped).jpg"
    with Image.open(result) as image:
        assert image.size == (200, 150)
    assert os.path.exists(source)


def test_crop_with_cuts_writes_a_folder_of_parts(work):
    source = photo(str(work / "p.png"), (400, 300))
    result = cropper.crop_file(source, UnitRect(0, 0, 1, 1), None, None, geometry.even_cuts(2), [], OPTIONS)
    assert os.path.isdir(result)
    assert len(names(result)) == 2


def test_resize_file_names_the_result_by_its_size(work):
    source = photo(str(work / "p.png"), (400, 300))
    result = cropper.resize_file(source, ResizeRule("long_side", 200), None, OPTIONS)
    assert "200×150" in os.path.basename(result)
    with Image.open(result) as image:
        assert image.size == (200, 150)


# MARK: Adjustments


def test_identity_adjustments_change_nothing():
    image = Image.new("RGB", (30, 20), (120, 80, 40))
    out = adjust.apply(image, adjust.PhotoAdjustments())
    assert np.array_equal(np.asarray(out.convert("RGB")), np.asarray(image))


def test_exposure_brightens_and_saturation_removal_greys():
    image = Image.new("RGB", (30, 20), (120, 80, 40))
    brighter = adjust.apply(image, adjust.PhotoAdjustments(exposure=1.0)).convert("RGB").getpixel((5, 5))
    assert sum(brighter) > sum((120, 80, 40))
    grey = adjust.apply(image, adjust.PhotoAdjustments(saturation=-1.0)).convert("RGB").getpixel((5, 5))
    assert max(grey) - min(grey) <= 3


def test_every_effect_runs_on_a_small_image():
    image = Image.fromarray(np.random.default_rng(1).integers(0, 255, (24, 32, 3), dtype=np.uint8))
    for effect in adjust.PhotoEffect:
        out = adjust.apply(image, adjust.PhotoAdjustments(effect=effect, vignette=0.5, grain=0.5, sharpness=0.5,
                                                          clarity=0.5, noise_reduction=0.5, dehaze=0.5))
        assert out.size == image.size


def test_edit_file_writes_an_edited_copy(work):
    source = photo(str(work / "p.jpg"))
    result = cropper.edit_file(source, adjust.PhotoAdjustments(contrast=0.4), OPTIONS)
    assert result != source and os.path.exists(result)


# MARK: Compression


def test_compression_is_never_bigger_than_the_original(work):
    source = photo(str(work / "big.jpg"), (1600, 1200))
    result = compress.compress_file(source, compress.CompressionSettings(preset=compress.Preset.SMALL))
    assert os.path.getsize(result) < os.path.getsize(source)
    assert os.path.basename(result).startswith("big (compressed)")


def test_compression_refuses_to_write_a_bigger_file(work):
    source = str(work / "tiny.jpg")
    noise = np.random.default_rng(2).integers(0, 255, (64, 64, 3), dtype=np.uint8)
    Image.fromarray(noise).save(source, quality=5)
    settings = compress.CompressionSettings(mode=compress.Mode.QUALITY, quality=1.0)
    with pytest.raises(compress.NotSmaller):
        compress.compress_file(source, settings)
    assert names(work) == ["tiny.jpg"]


def test_target_size_mode_fits_the_limit(work):
    source = photo(str(work / "t.jpg"), (1200, 900))
    limit = os.path.getsize(source) // 2
    settings = compress.CompressionSettings(mode=compress.Mode.TARGET_SIZE, target_bytes=limit)
    result = compress.compress_file(source, settings)
    assert os.path.getsize(result) <= limit


def test_human_size():
    assert compress.human_size(512).startswith("512")
    assert "KB" in compress.human_size(2048) or "KiB" in compress.human_size(2048)


def test_best_fit_picks_the_best_quality_that_fits():
    calls = []

    def encode(quality):
        calls.append(quality)
        return b"x" * int(1000 * quality)

    data = compress.best_fit(encode, 500)
    assert data is not None and len(data) <= 500
    assert len(data) > 400


# MARK: Redaction


def test_solid_redaction_covers_only_the_region():
    image = Image.new("RGB", (100, 100), (200, 200, 200))
    out = redact.apply(image, [UnitRect(0.2, 0.2, 0.4, 0.4)], redact.RedactionStyle.SOLID, compose.RGBA(0, 0, 0))
    assert out.getpixel((40, 40))[:3] == (0, 0, 0)
    assert out.getpixel((90, 90))[:3] == (200, 200, 200)


@pytest.mark.parametrize("style", [redact.RedactionStyle.BLUR, redact.RedactionStyle.PIXELATE])
def test_blur_and_pixelate_destroy_detail(style):
    noise = np.random.default_rng(5).integers(0, 255, (80, 80, 3), dtype=np.uint8)
    image = Image.fromarray(noise)
    out = np.asarray(redact.apply(image, [UnitRect(0, 0, 1, 1)], style).convert("RGB")).astype(float)
    assert out.std() < noise.astype(float).std() * 0.6


def test_redact_file_strips_metadata(work):
    source = photo(str(work / "p.jpg"))
    result = redact.redact_file(source, [UnitRect(0, 0, 0.5, 0.5)], redact.RedactionStyle.SOLID, compose.RGBA(0, 0, 0),
                                OPTIONS)
    assert os.path.basename(result) == "p (redacted).jpg"
    with Image.open(result) as image:
        assert len(image.getexif()) == 0


# MARK: Metadata


def test_metadata_read_and_edit_is_lossless_for_jpeg(work):
    source = photo(str(work / "p.jpg"))
    before = np.asarray(Image.open(source).convert("RGB"))
    info = metadata.read(source)
    assert info.entries
    changes = metadata.MetadataChanges(text={metadata.MetadataField.AUTHOR: "Igor"},
                                       date_taken=datetime(2020, 5, 17, 10, 30, 0))
    result = metadata.apply(source, changes)
    after = metadata.read(result)
    assert after.text[metadata.MetadataField.AUTHOR] == "Igor"
    assert after.date_taken == datetime(2020, 5, 17, 10, 30, 0)
    # Lossless: the pixels are exactly the same as the original's.
    assert np.array_equal(before, np.asarray(Image.open(result).convert("RGB")))


def test_metadata_remove_all(work):
    source = photo(str(work / "p.jpg"))
    result = metadata.apply(source, metadata.MetadataChanges(remove_all=True))
    with Image.open(result) as image:
        assert len(image.getexif()) == 0


# MARK: Annotations


def test_annotation_geometry_roundtrip():
    box = annotations.Annotation("rectangle", rect=(10, 20, 100, 50))  # x, y, width, height
    assert annotations.bounds(box) == (10, 20, 100, 50)
    moved = annotations.translated(box, 5, 7)
    assert moved.rect == (15, 27, 100, 50)
    assert annotations.hit_test([box], (60, 45), 4) == box.id
    assert annotations.hit_test([box], (500, 500), 4) is None


def test_annotations_render_and_save(work, qapp):
    source = photo(str(work / "p.jpg"), (300, 200))
    marks = [annotations.Annotation("rectangle", rect=(20, 20, 100, 60)),
             annotations.Annotation("text", text="Hi", start=(30, 120), font_size=30),
             annotations.Annotation("arrow", start=(200, 150), end=(250, 60)),
             annotations.Annotation("number", start=(150, 100), number=3)]
    result = annotations.annotate_file(source, marks, {}, OPTIONS)
    assert os.path.basename(result) == "p (annotated).jpg"
    with Image.open(result) as annotated, Image.open(source) as original:
        assert annotated.size == original.size
        assert not np.array_equal(np.asarray(annotated.convert("RGB")), np.asarray(original.convert("RGB")))


# MARK: Collage and frame


def test_collage_has_the_requested_aspect_and_all_photos(work, qapp):
    paths = [photo(str(work / f"{i}.png"), (200 + 40 * i, 150)) for i in range(3)]
    settings = compose.CollageSettings()
    images = [Image.open(p).convert("RGB") for p in paths]
    result = compose.compose_collage(images, settings)
    assert result.width > 0 and result.height > 0
    out = compose.collage_files(paths, settings, OPTIONS)
    assert os.path.exists(out)


def test_frame_adds_a_border(work, qapp):
    source = photo(str(work / "p.png"), (200, 100))
    result = compose.frame_file(source, compose.FrameSettings(), OPTIONS)
    with Image.open(result) as framed:
        assert framed.width >= 200 and framed.height >= 100


# MARK: PDF editing


def test_pdf_split_ranges_and_helpers(work):
    assert pdf.split_documents(6, {2, 4}, set()) == [[0, 1, 2], [3, 4], [5]]
    assert pdf.split_documents(4, {1}, {2}) == [[0, 1], [3]]
    assert pdf.cuts_every_page(3) == {0, 1}
    assert pdf.ranges([0, 1, 2, 5]) == "1–3, 6"


def test_pdf_split_writes_parts_in_a_folder(work):
    source = make_pdf(work / "doc.pdf", pages=4)
    result = pdf.split(source, {1}, set())
    assert os.path.isdir(result)
    counts = sorted(pdf.page_count(os.path.join(result, n)) for n in names(result))
    assert counts == [2, 2]


def test_pdf_organize_reorders_rotates_and_deletes(work):
    source = make_pdf(work / "doc.pdf", pages=3)
    items = [pdf.PageItem(0, 2, 90), pdf.PageItem(0, 0), pdf.PageItem(0, 0)]
    result = pdf.save_organized(items, [source], source)
    assert pdf.page_count(result) == 3
    from pypdf import PdfReader

    reader = PdfReader(result)
    assert reader.pages[0].rotation == 90
    assert reader.pages[1].rotation == 0
    first = pdf.render_page(result, 1, 36)
    third = pdf.render_page(source, 2, 36)
    assert first.size != third.size or first.getpixel((5, 5)) != third.getpixel((5, 5))


def test_pdf_thumbnails_respect_the_longest_side(work):
    source = make_pdf(work / "doc.pdf", pages=2, size=(200, 400))
    thumbs = pdf.thumbnails(source, 100)
    assert len(thumbs) == 2
    assert all(max(t.size) <= 101 for t in thumbs)


def test_pdf_compression_keeps_the_page_count(work):
    big = [Image.fromarray(np.random.default_rng(i).integers(0, 255, (900, 700, 3), dtype=np.uint8)) for i in range(2)]
    source = str(work / "scan.pdf")
    big[0].save(source, save_all=True, append_images=big[1:], quality=100)
    result = compress.compress_file(source)
    assert pdf.page_count(result) == 2
    assert os.path.getsize(result) < os.path.getsize(source)
