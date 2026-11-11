"""Basic text editing: replace a line of existing text.

PDFs don't store paragraphs, only positioned runs of glyphs ("spans"). Like
most lightweight editors, we edit one span at a time: the old text is removed
with a redaction and the new text is written in the same place, at the same
size and colour. The original font is reused when it is embedded in full;
otherwise a close standard font (Helvetica/Times/Courier) is used.
"""

from __future__ import annotations

from dataclasses import dataclass

import pymupdf


@dataclass
class TextSpan:
    text: str
    rect: pymupdf.Rect
    origin: pymupdf.Point
    size: float
    color: tuple[float, float, float]
    font: str
    flags: int


def _srgb(c: int) -> tuple[float, float, float]:
    return ((c >> 16) & 255) / 255, ((c >> 8) & 255) / 255, (c & 255) / 255


def span_at(page: pymupdf.Page, point: pymupdf.Point) -> TextSpan | None:
    """Return the text span under ``point`` (PDF coordinates), or None."""
    data = page.get_text("dict", flags=pymupdf.TEXTFLAGS_TEXT)
    for block in data["blocks"]:
        for line in block.get("lines", []):
            for s in line["spans"]:
                r = pymupdf.Rect(s["bbox"])
                if r.contains(point) and s["text"].strip():
                    return TextSpan(s["text"], r, pymupdf.Point(s["origin"]), s["size"], _srgb(s["color"]), s["font"], s["flags"])
    return None


def _base14_for(span: TextSpan) -> str:
    name = span.font.lower()
    bold = bool(span.flags & 16) or "bold" in name
    italic = bool(span.flags & 2) or "italic" in name or "oblique" in name
    if span.flags & 8 or "courier" in name or "mono" in name:
        family = "cour"
    elif span.flags & 4 or "times" in name or ("serif" in name and "sans" not in name):
        family = "tiro"
    else:
        family = "helv"
    suffix = {(False, False): "", (True, False): "bo", (False, True): "it", (True, True): "bi"}[(bold, italic)]
    if family == "helv":
        return {"": "helv", "bo": "hebo", "it": "heit", "bi": "hebi"}[suffix]
    if family == "cour":
        return {"": "cour", "bo": "cobo", "it": "coit", "bi": "cobi"}[suffix]
    return {"": "tiro", "bo": "tibo", "it": "tiit", "bi": "tibi"}[suffix]


def replace_span(page: pymupdf.Page, span: TextSpan, new_text: str) -> None:
    """Replace ``span`` with ``new_text``, keeping position, size and colour."""
    page.add_redact_annot(span.rect, fill=False)
    page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE, graphics=pymupdf.PDF_REDACT_LINE_ART_NONE)
    if new_text:
        page.insert_text(span.origin, new_text, fontsize=span.size, fontname=_base14_for(span), color=span.color)
