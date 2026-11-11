import os
import random

import pymupdf
import pytest

from paperlite.core import compress, forms, textedit


def make_scanned_pdf(path, pages=3, dpi=300):
    """Build a PDF that looks like a scanner made it: one big lossless image per page."""
    src = pymupdf.open()
    out = pymupdf.open()
    rnd = random.Random(1)
    for i in range(pages):
        p = src.new_page()
        p.insert_text((72, 100), f"Invoice page {i + 1}", fontsize=24)
        for line in range(30):
            p.insert_text((72, 140 + line * 20), "Lorem ipsum dolor sit amet " * 3, fontsize=10)
        pix = p.get_pixmap(dpi=dpi)
        # scanner noise so it isn't a perfectly flat image
        for _ in range(4000):
            x, y = rnd.randrange(pix.width), rnd.randrange(pix.height)
            pix.set_pixel(x, y, (rnd.randrange(200, 256),) * 3)
        page = out.new_page(width=p.rect.width, height=p.rect.height)
        page.insert_image(page.rect, stream=pix.tobytes("png"))
    out.save(path)


@pytest.fixture
def scanned(tmp_path):
    path = tmp_path / "scan.pdf"
    make_scanned_pdf(str(path))
    return str(path)


@pytest.mark.parametrize("preset", list(compress.PRESETS))
def test_compress_makes_scans_much_smaller(scanned, tmp_path, preset):
    out = str(tmp_path / f"out_{preset}.pdf")
    r = compress.compress_pdf(scanned, out, preset)
    assert not r.kept_original
    assert r.compressed_bytes == os.path.getsize(out)
    assert r.saved_percent > 50, f"{preset}: only saved {r.saved_percent:.0f}%"
    doc = pymupdf.open(out)
    assert doc.page_count == 3
    assert doc[0].get_pixmap(dpi=30)  # still renders


def test_compress_never_grows_file(tmp_path):
    path = str(tmp_path / "tiny.pdf")
    d = pymupdf.open()
    d.new_page().insert_text((72, 72), "hello")
    d.save(path, garbage=4, deflate=True, use_objstms=1)
    out = str(tmp_path / "out.pdf")
    r = compress.compress_pdf(path, out)
    assert os.path.getsize(out) <= os.path.getsize(path)
    assert r.compressed_bytes <= r.original_bytes


def test_compress_in_place(scanned):
    before = os.path.getsize(scanned)
    compress.compress_pdf(scanned, scanned, "small")
    assert os.path.getsize(scanned) < before


def test_fill_form_and_sign(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page()
    w = pymupdf.Widget()
    w.field_name, w.field_type, w.rect = "name", pymupdf.PDF_WIDGET_TYPE_TEXT, pymupdf.Rect(72, 72, 300, 92)
    page.add_widget(w)
    cb = pymupdf.Widget()
    cb.field_name, cb.field_type, cb.rect = "agree", pymupdf.PDF_WIDGET_TYPE_CHECKBOX, pymupdf.Rect(72, 110, 86, 124)
    page.add_widget(cb)

    forms.set_widget_value(forms.widget_at(page, pymupdf.Point(100, 80)), "Jane Doe")
    assert forms.toggle_widget(forms.widget_at(page, pymupdf.Point(78, 116))) is True
    forms.add_text(page, pymupdf.Point(72, 200), "Signed in London")
    forms.add_checkmark(page, pymupdf.Point(80, 250))
    sig = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, 10), True)
    sig.clear_with(0)
    forms.add_signature(page, pymupdf.Rect(72, 300, 272, 350), sig.tobytes("png"))

    out = str(tmp_path / "filled.pdf")
    doc.save(out)
    re = pymupdf.open(out)
    vals = {w.field_name: w.field_value for w in re[0].widgets()}
    assert vals["name"] == "Jane Doe"
    assert vals["agree"] not in ("Off", False)
    assert "Signed in London" in re[0].get_text()
    assert re[0].get_images()


def test_replace_text(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 100), "Total: 100.00", fontsize=14)
    page.insert_text((72, 140), "Keep this line", fontsize=14)
    span = textedit.span_at(page, pymupdf.Point(90, 96))
    assert span and span.text == "Total: 100.00"
    textedit.replace_span(page, span, "Total: 250.00")
    text = page.get_text()
    assert "250.00" in text and "100.00" not in text
    assert "Keep this line" in text
