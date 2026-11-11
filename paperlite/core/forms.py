"""Fill & Sign: form fields, free text, checkmarks and signatures."""

from __future__ import annotations

import pymupdf

TEXT_TYPES = {pymupdf.PDF_WIDGET_TYPE_TEXT, pymupdf.PDF_WIDGET_TYPE_COMBOBOX, pymupdf.PDF_WIDGET_TYPE_LISTBOX}
TOGGLE_TYPES = {pymupdf.PDF_WIDGET_TYPE_CHECKBOX, pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON}


def widget_at(page: pymupdf.Page, point: pymupdf.Point):
    """Return the form field under ``point`` (PDF coordinates), or None."""
    for w in page.widgets() or []:
        if w.rect.contains(point):
            return w
    return None


def set_widget_value(widget, value) -> None:
    if widget.field_type in TOGGLE_TYPES:
        widget.field_value = widget.on_state() if value else "Off"
    else:
        widget.field_value = str(value)
    widget.update()


def toggle_widget(widget) -> bool:
    """Flip a checkbox/radio button. Returns the new checked state."""
    checked = widget.field_value not in (False, "Off", "", None)
    set_widget_value(widget, not checked)
    return not checked


def add_text(page: pymupdf.Page, point: pymupdf.Point, text: str, fontsize: float = 11, color=(0, 0, 0)) -> None:
    """Type text anywhere on the page, like Fill & Sign's "Add text".

    ``point`` is the top-left corner of the text.
    """
    lines = text.splitlines() or [""]
    for i, line in enumerate(lines):
        baseline = pymupdf.Point(point.x, point.y + fontsize * (0.85 + 1.2 * i))
        page.insert_text(baseline, line, fontsize=fontsize, fontname="helv", color=color)


def add_checkmark(page: pymupdf.Page, point: pymupdf.Point, size: float = 12) -> None:
    """Draw a tick centred on ``point``."""
    x, y, s = point.x, point.y, size / 2
    shape = page.new_shape()
    shape.draw_polyline([(x - s, y), (x - s / 3, y + s * 0.7), (x + s, y - s * 0.8)])
    shape.finish(color=(0, 0, 0), width=max(1.2, size / 8), closePath=False, lineCap=1, lineJoin=1)
    shape.commit()


def add_signature(page: pymupdf.Page, rect: pymupdf.Rect, png_bytes: bytes) -> None:
    """Stamp a signature image (transparent PNG) into ``rect``, keeping its proportions.

    This is a visual signature, like Fill & Sign. It is not a certificate-based
    digital signature.
    """
    page.insert_image(rect, stream=png_bytes, keep_proportion=True, overlay=True)
