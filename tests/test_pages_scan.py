import os

import pymupdf
import pytest

from paperlite.core import history, pages, scanedit, updater


def make_doc(n, tag="P"):
    d = pymupdf.open()
    for i in range(n):
        d.new_page().insert_text((72, 72), f"{tag}{i + 1}")
    return d


def labels(doc):
    return [p.get_text().strip() for p in doc]


def save(doc, path):
    doc.save(path)
    return path


# ------------------------------------------------------------------ pages


def test_reorder_rotate_delete_blank():
    d = make_doc(4)
    pages.reorder(d, [3, 0, 2, 1])
    assert labels(d) == ["P4", "P1", "P3", "P2"]
    pages.rotate(d, [0, 1], 90)
    assert d[0].rotation == 90 and d[1].rotation == 90 and d[2].rotation == 0
    pages.delete(d, [1, 2])
    assert labels(d) == ["P4", "P2"]
    pages.insert_blank(d, 1)
    assert labels(d) == ["P4", "", "P2"]
    with pytest.raises(ValueError):
        pages.delete(d, [0, 1, 2])


def test_combine_insert_extract_split_export(tmp_path):
    a = save(make_doc(2, "A"), str(tmp_path / "a.pdf"))
    b = save(make_doc(3, "B"), str(tmp_path / "b.pdf"))
    out = str(tmp_path / "joined.pdf")
    assert pages.combine([a, b], out) == 5
    j = pymupdf.open(out)
    assert labels(j) == ["A1", "A2", "B1", "B2", "B3"]

    d = make_doc(2, "C")
    assert pages.insert_file(d, a, 1) == 2
    assert labels(d) == ["C1", "A1", "A2", "C2"]

    ex = str(tmp_path / "ex.pdf")
    pages.extract(j, [4, 0], ex)
    assert labels(pymupdf.open(ex)) == ["B3", "A1"]

    files = pages.split(j, 2, str(tmp_path), "joined")
    assert len(files) == 3 and all(os.path.exists(f) for f in files)
    assert labels(pymupdf.open(files[-1])) == ["B3"]

    imgs = pages.export_images(j, [0, 1], str(tmp_path), "joined", "jpg", 72)
    assert len(imgs) == 2 and imgs[0].endswith(".jpg") and os.path.getsize(imgs[0]) > 1000


def test_combine_accepts_images(tmp_path):
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 200, 300), False)
    pix.clear_with(200)
    png = str(tmp_path / "photo.png")
    pix.save(png)
    a = save(make_doc(1, "A"), str(tmp_path / "a.pdf"))
    out = str(tmp_path / "o.pdf")
    assert pages.combine([a, png], out) == 2


def test_parse_ranges():
    assert pages.parse_ranges("1-3, 5", 10) == [0, 1, 2, 4]
    assert pages.parse_ranges("8-", 10) == [7, 8, 9]
    assert pages.parse_ranges("3-1", 10) == [2, 1, 0]
    with pytest.raises(ValueError):
        pages.parse_ranges("0", 10)
    with pytest.raises(ValueError):
        pages.parse_ranges("", 10)


# ------------------------------------------------------------------ history


def test_history_undo_redo_page_ops():
    d = make_doc(3)
    h = history.History()
    h.checkpoint(d, "Delete")
    pages.delete(d, [0])
    h.checkpoint(d, "Insert")
    pages.insert_blank(d, 0)
    assert labels(d) == ["", "P2", "P3"]
    d = h.undo(d)
    assert labels(d) == ["P2", "P3"]
    d = h.undo(d)
    assert labels(d) == ["P1", "P2", "P3"]
    assert not h.can_undo()
    d = h.redo(d)
    assert labels(d) == ["P2", "P3"]
    h.close()


# ------------------------------------------------------------------ scans


def scanned_page(tmp_path, paper=(245, 240, 228)):
    """A 'scanned' page: text and a handwritten squiggle flattened into one image
    on slightly yellow paper."""
    src = pymupdf.open()
    p = src.new_page()
    p.draw_rect(p.rect, color=None, fill=tuple(c / 255 for c in paper))
    p.insert_text((72, 100), "Invoice total 1234 due today", fontsize=16, color=(0.15, 0.15, 0.2))
    p.draw_polyline([(80, 200), (100, 180), (120, 210), (140, 185), (160, 205)], color=(0.1, 0.1, 0.5), width=2)
    pix = p.get_pixmap(dpi=200)
    out = pymupdf.open()
    page = out.new_page(width=p.rect.width, height=p.rect.height)
    page.insert_image(page.rect, pixmap=pix)
    return out, page


def test_scan_detect_and_ocr(tmp_path):
    doc, page = scanned_page(tmp_path)
    assert scanned_page and scanedit.is_scanned(page)
    words = scanedit.ocr_words(page)
    texts = [w.text for w in words]
    assert "Invoice" in texts and "1234" in texts
    w = scanedit.word_at(words, pymupdf.Point(words[2].rect.x0 + 3, words[2].rect.y0 + 3))
    assert w.text == "1234"


def test_sample_colors_finds_paper_and_ink(tmp_path):
    doc, page = scanned_page(tmp_path)
    word = next(w for w in scanedit.ocr_words(page) if w.text == "1234")
    paper, ink = scanedit.sample_colors(page, word.rect)
    assert abs(paper[0] - 245 / 255) < 0.05 and abs(paper[2] - 228 / 255) < 0.05
    assert sum(ink) < 1.2  # dark


def test_replace_scanned_word_removes_old_pixels(tmp_path):
    doc, page = scanned_page(tmp_path)
    word = next(w for w in scanedit.ocr_words(page) if w.text == "1234")
    scanedit.replace_text(page, word.rect, "9876")
    # the new number is now real text, and OCR no longer sees the old one
    assert "9876" in page.get_text()
    path = str(tmp_path / "edited.pdf")
    doc.save(path)
    re = pymupdf.open(path)
    ocr = [w.text for w in scanedit.ocr_words(re[0])]
    assert "1234" not in ocr
    assert "Invoice" in ocr  # the rest of the line is untouched


def test_erase_and_move_handwriting(tmp_path):
    doc, page = scanned_page(tmp_path)
    squiggle = pymupdf.Rect(75, 175, 165, 215)

    def ink_pixels(rect):
        pix = page.get_pixmap(clip=rect, dpi=72)
        s = pix.samples
        return sum(1 for i in range(0, len(s), pix.n) if s[i] < 120)

    assert ink_pixels(squiggle) > 5
    scanedit.move_area(page, squiggle, pymupdf.Point(300, 400))
    assert ink_pixels(squiggle) == 0
    assert ink_pixels(pymupdf.Rect(300, 400, 390, 440)) > 5


# ------------------------------------------------------------------ updater


def test_version_compare():
    assert updater.is_newer("v0.3.0", "0.2.0")
    assert updater.is_newer("1.0", "0.9.9")
    assert not updater.is_newer("v0.2.0", "0.2.0")
    assert not updater.is_newer("0.1.9", "0.2.0")
    assert updater.check("", "0.1.0") is None
