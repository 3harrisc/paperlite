"""Editing scanned pages, including handwriting.

A scanned page is a single picture, so there's no text to edit. We do what
Acrobat does:

* **Recognise text (OCR)** with the Tesseract engine built into PyMuPDF, so a
  click on a printed word knows the word and its exact box.
* **Replace**: the pixels under the old word are really removed (not just
  covered), the area is filled with the sampled *paper* colour, and the new
  text is drawn in the sampled *ink* colour at the same height.
* **Erase / move / copy** any area. This works for anything on the page:
  handwriting, stamps, signatures, printed text.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

import pymupdf


def tessdata_dir() -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    return os.path.join(base, "assets", "tessdata")


@dataclass
class OcrWord:
    text: str
    rect: pymupdf.Rect  # unrotated page coordinates
    line_id: tuple[int, int]


def is_scanned(page: pymupdf.Page) -> bool:
    """True when the page is mostly a picture with little or no real text."""
    if len(page.get_text("text").strip()) > 20:
        return False
    area = abs(page.rect)
    covered = sum(abs(r & page.rect) for img in page.get_images(full=True) for r in page.get_image_rects(img[0]))
    return covered > 0.5 * area


def ocr_words(page: pymupdf.Page, dpi: int = 300, language: str = "eng") -> list[OcrWord]:
    tp = page.get_textpage_ocr(tessdata=tessdata_dir(), language=language, dpi=dpi, full=True)
    words = []
    for x0, y0, x1, y1, text, block, line, _ in page.get_text("words", textpage=tp):
        if text.strip():
            words.append(OcrWord(text, pymupdf.Rect(x0, y0, x1, y1), (block, line)))
    return words


def word_at(words: list[OcrWord], point: pymupdf.Point, slack: float = 2) -> OcrWord | None:
    for w in words:
        if (w.rect + (-slack, -slack, slack, slack)).contains(point):
            return w
    return None


def line_metrics(page: pymupdf.Page, words: list[OcrWord], word: OcrWord) -> tuple[float, float]:
    """Font size and baseline y for ``word``, measured from the scan's pixels.

    OCR gives one box for the whole line, from the tallest letter to the lowest
    descender. We find the baseline as the last pixel row where most letters
    still have ink, then size = (baseline - top of line) / 0.72, because capitals
    and ascenders are about 0.72 em tall in common fonts.
    """
    line = [w for w in words if w.line_id == word.line_id] or [word]
    box = pymupdf.Rect(line[0].rect)
    for w in line[1:]:
        box |= w.rect
    pix = page.get_pixmap(clip=box, dpi=200, alpha=False, colorspace=pymupdf.csGRAY)
    s, w, h = pix.samples, pix.width, pix.height
    if not h:
        return max(4.0, box.height), box.y1
    rows = [sum(1 for x in range(w) if s[y * pix.stride + x] < 128) for y in range(h)]
    peak = max(rows) or 1
    base_row = max(y for y in range(h) if rows[y] >= 0.25 * peak)
    top_row = min(y for y in range(h) if rows[y] > 0)
    to_pt = box.height / h
    baseline = box.y0 + (base_row + 1) * to_pt
    top = box.y0 + top_row * to_pt
    return max(4.0, (baseline - top) / 0.72), baseline


# ------------------------------------------------------------------ colours


def _pixels(page: pymupdf.Page, rect: pymupdf.Rect, dpi: int = 100):
    pix = page.get_pixmap(clip=rect, dpi=dpi, alpha=False, colorspace=pymupdf.csRGB)
    s, n = pix.samples, pix.n
    return [(s[i], s[i + 1], s[i + 2]) for i in range(0, len(s) - n + 1, n)], pix


def _median(colors):
    if not colors:
        return (1.0, 1.0, 1.0)
    return tuple(sorted(c[k] for c in colors)[len(colors) // 2] / 255 for k in range(3))


def sample_colors(page: pymupdf.Page, rect: pymupdf.Rect) -> tuple[tuple, tuple]:
    """Return (paper colour, ink colour) around/inside ``rect`` as 0-1 RGB tuples."""
    rect = pymupdf.Rect(rect) & page.mediabox
    pad = max(3.0, rect.height * 0.35)
    ring = (pymupdf.Rect(rect) + (-pad, -pad, pad, pad)) & page.mediabox
    outside, pix = _pixels(page, ring)
    # keep only pixels outside the inner rect, and drop the darkest (other text)
    sx, sy = pix.width / ring.width, pix.height / ring.height
    ix0, iy0 = (rect.x0 - ring.x0) * sx, (rect.y0 - ring.y0) * sy
    ix1, iy1 = (rect.x1 - ring.x0) * sx, (rect.y1 - ring.y0) * sy
    ring_px = [c for k, c in enumerate(outside)
               if not (ix0 <= k % pix.width <= ix1 and iy0 <= k // pix.width <= iy1)]
    ring_px.sort(key=sum)
    paper = _median(ring_px[len(ring_px) // 3:] or ring_px)

    inside, _ = _pixels(page, rect, dpi=150)
    inside.sort(key=sum)
    darkest = inside[: max(1, len(inside) // 12)]
    ink = tuple(sum(c[k] for c in darkest) / len(darkest) / 255 for k in range(3))
    if sum(paper) - sum(ink) < 0.6:  # not enough contrast: fall back to near-black
        ink = (0.1, 0.1, 0.12)
    return paper, ink


# ------------------------------------------------------------------ edits


def erase_area(page: pymupdf.Page, rect: pymupdf.Rect, color: tuple | None = None) -> tuple:
    """Remove everything inside ``rect`` (image pixels, text, drawings) and paint
    it in the paper colour. Returns the colour used."""
    rect = pymupdf.Rect(rect) & page.mediabox
    if color is None:
        color, _ = sample_colors(page, rect)
    page.add_redact_annot(rect, fill=color, cross_out=False)
    page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_PIXELS, graphics=pymupdf.PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED,
                          text=pymupdf.PDF_REDACT_TEXT_REMOVE)
    # pixels cleared by redaction are filled white; paint the paper colour over them
    if color != (1, 1, 1) and color != (1.0, 1.0, 1.0):
        page.draw_rect(rect, color=None, fill=color, overlay=True)
    return color


def replace_text(page: pymupdf.Page, rect: pymupdf.Rect, new_text: str, fontname: str = "helv",
                 fontsize: float | None = None, baseline_y: float | None = None) -> None:
    """Replace whatever is inside ``rect`` with ``new_text`` that matches the scan.

    Pass ``fontsize``/``baseline_y`` from :func:`line_metrics` when you have them.
    """
    rect = pymupdf.Rect(rect)
    paper, ink = sample_colors(page, rect)
    pad = rect.height * 0.12
    erase_area(page, rect + (-pad, -pad, pad, pad), paper)
    if not new_text:
        return
    size = fontsize or _fit_size(rect, new_text, fontname)
    # sit the text on the same baseline as the original (descender ~ 22% of the box)
    baseline = pymupdf.Point(rect.x0, baseline_y if baseline_y is not None else rect.y1 - rect.height * 0.2)
    page.insert_text(baseline, new_text, fontname=fontname, fontsize=size, color=ink)


def _fit_size(rect: pymupdf.Rect, text: str, fontname: str) -> float:
    """Font size whose capital/x-height matches the scanned text box."""
    size = rect.height * 0.95
    font = pymupdf.Font(fontname)
    width = font.text_length(text, fontsize=size)
    # don't let replacement run far past the original area
    if width > rect.width * 1.6 and len(text) > 1:
        size *= rect.width * 1.6 / width
    return max(4.0, size)


def grab_area(page: pymupdf.Page, rect: pymupdf.Rect, dpi: int = 300) -> bytes:
    """Picture of an area, as PNG, for moving or copying it."""
    return page.get_pixmap(clip=rect, dpi=dpi, alpha=False).tobytes("png")


def place_area(page: pymupdf.Page, png: bytes, rect: pymupdf.Rect) -> None:
    page.insert_image(rect, stream=png, keep_proportion=True, overlay=True)


def move_area(page: pymupdf.Page, src: pymupdf.Rect, dst_top_left: pymupdf.Point,
              target: pymupdf.Page | None = None) -> None:
    png = grab_area(page, src)
    erase_area(page, src)
    dst = pymupdf.Rect(dst_top_left, dst_top_left + (src.width, src.height))
    place_area(target or page, png, dst)
