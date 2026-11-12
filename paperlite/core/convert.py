"""Convert a PDF to Word (.docx) or Excel (.xlsx).

Word: pdf2docx rebuilds paragraphs, fonts, images and tables from the PDF's
own layout. Excel: PyMuPDF finds the tables (``page.find_tables()``) and each
one becomes a worksheet. A page with no table still gives a sheet: its text
lines, split into columns where there are wide gaps.

Scanned pages have no text to convert, so they are read first with the
Tesseract OCR built into PyMuPDF (the same engine as scan editing). The
recognised words are written onto a clean page as real text, at the place and
size they were on the scan, and that page is converted instead. In Word that
gives editable text rather than a picture of the page.

The rules below (sheet names, which cells become numbers, the summary wording)
are shared with the Mac app; keep the two the same.
"""

from __future__ import annotations

import logging
import os
import re
import statistics
import tempfile
import warnings
from dataclasses import dataclass, field
from typing import Callable

import pymupdf

from paperlite.core.scanedit import is_scanned, tessdata_dir

Progress = Callable[[int, int, str], None]  # (step, total steps, message)

WORD, EXCEL = "word", "excel"
EXTENSIONS = {WORD: ".docx", EXCEL: ".xlsx"}


class PasswordError(PermissionError):
    """The PDF needs a password, or the one given is wrong."""


@dataclass
class ConvertResult:
    output_path: str
    pages_converted: int
    tables_found: int = 0  # Excel only
    ocr_pages: list[int] = field(default_factory=list)  # 1-based page numbers read with OCR
    warnings: list[str] = field(default_factory=list)


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def summary(r: ConvertResult) -> str:
    """One line for the user, e.g. "Saved Report.docx — 3 pages, 1 scanned page read with OCR"."""
    name = os.path.basename(r.output_path)
    if r.output_path.lower().endswith(".xlsx"):
        what = _plural(r.tables_found, "table") if r.tables_found else "no tables found, so the text was laid out in columns"
    else:
        what = _plural(r.pages_converted, "page")
    if r.ocr_pages:
        what += f", {_plural(len(r.ocr_pages), 'scanned page')} read with OCR"
    return f"Saved {name} — {what}"


def output_name(path: str, kind: str) -> str:
    return os.path.splitext(path)[0] + EXTENSIONS[kind]


# ------------------------------------------------------------------ shared helpers


def _open(input_path: str, password: str | None) -> pymupdf.Document:
    try:
        doc = pymupdf.open(input_path)
    except Exception as e:
        raise ValueError(f"This file couldn't be opened as a PDF ({e}).") from e
    if doc.needs_pass and not doc.authenticate(password or ""):
        doc.close()
        if password:
            raise PasswordError("That password isn't right.")
        raise PasswordError("This PDF is password protected. Enter the password to convert it.")
    return doc


def _save_via_temp(output_path: str, write: Callable[[str], None]) -> None:
    """Write to a temp file next to the output, then swap it in, so a failed
    conversion never leaves half a file (or wipes the previous one)."""
    out_dir = os.path.dirname(os.path.abspath(output_path)) or "."
    fd, tmp = tempfile.mkstemp(suffix=os.path.splitext(output_path)[1], dir=out_dir)
    os.close(fd)
    try:
        write(tmp)
        os.replace(tmp, output_path)
    except PermissionError as e:
        raise OSError(f"Couldn't save {os.path.basename(output_path)}. If it's open in Word or Excel, "
                      "close it and try again.") from e
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


@dataclass
class _Item:  # a word, or a run of words, with its box
    x0: float
    x1: float
    y0: float
    y1: float
    text: str
    size: float = 0.0
    baseline: float = 0.0


def _rows(items: list[_Item]) -> list[list[_Item]]:
    """Group items into visual lines (top to bottom), each sorted left to right."""
    rows: list[list[_Item]] = []
    for it in sorted(items, key=lambda i: ((i.y0 + i.y1) / 2, i.x0)):
        mid = (it.y0 + it.y1) / 2
        if rows:
            last = rows[-1]
            ref = statistics.median((i.y0 + i.y1) / 2 for i in last)
            h = statistics.median(i.y1 - i.y0 for i in last)
            if abs(mid - ref) <= 0.5 * max(h, it.y1 - it.y0):
                last.append(it)
                continue
        rows.append([it])
    return [sorted(r, key=lambda i: i.x0) for r in rows]


def _runs(row: list[_Item], gap_factor: float) -> list[_Item]:
    """Join neighbouring words on a line; a gap wider than ``gap_factor`` x line
    height starts a new run (a new column)."""
    out: list[_Item] = []
    for it in row:
        h = max(it.y1 - it.y0, 1.0)
        if out and it.x0 - out[-1].x1 <= gap_factor * h:
            prev = out[-1]
            out[-1] = _Item(prev.x0, max(prev.x1, it.x1), min(prev.y0, it.y0), max(prev.y1, it.y1),
                            f"{prev.text} {it.text}", prev.size, prev.baseline)
        else:
            out.append(it)
    return out


# ------------------------------------------------------------------ OCR


def _ocr_page(page: pymupdf.Page, dpi: int = 300) -> pymupdf.Document:
    """A one-page PDF holding the scan's text as real, visible text in the same
    places, without the picture. Empty when nothing could be read."""
    w, h = page.rect.width, page.rect.height
    # OCR a picture of the page as it is shown, so rotated scans come out right
    img = pymupdf.open()
    ip = img.new_page(width=w, height=h)
    ip.insert_image(ip.rect, pixmap=page.get_pixmap(dpi=dpi, alpha=False))
    tp = ip.get_textpage_ocr(tessdata=tessdata_dir(), language="eng", dpi=dpi, full=True)
    spans = []
    for block in ip.get_text("dict", textpage=tp)["blocks"]:
        for line in block.get("lines", []):
            for s in line["spans"]:
                if s["text"].strip():
                    x0, y0, x1, y1 = s["bbox"]
                    spans.append(_Item(x0, x1, y0, y1, s["text"].strip(), s["size"], s["origin"][1]))
    img.close()
    out = pymupdf.open()
    op = out.new_page(width=w, height=h)
    for row in _rows(spans):
        size = round(2 * statistics.median(i.size for i in row)) / 2 or 10
        baseline = statistics.median(i.baseline for i in row)
        for run in _runs(row, 0.6):
            op.insert_text((run.x0, baseline), run.text, fontsize=max(4.0, size), fontname="helv")
    return out


def _has_text(page: pymupdf.Page) -> bool:
    return bool(page.get_text("text").strip())


# ------------------------------------------------------------------ Word


def _load_pdf2docx():
    """Import pdf2docx without its side effects: it configures the root logger
    on import and warns about the old ``fitz`` name."""
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from docx import Document
        from pdf2docx import Converter
    for hd in root.handlers[:]:
        if hd not in handlers:
            root.removeHandler(hd)
    root.setLevel(level)
    return Converter, Document


def pdf_to_word(input_path: str, output_path: str, password: str | None = None,
                progress: Progress | None = None) -> ConvertResult:
    """Convert to an editable Word document, keeping the layout where possible."""
    Converter, Document = _load_pdf2docx()
    report = progress or (lambda *_: None)
    notes: list[str] = []
    doc = _open(input_path, password)
    try:
        n = doc.page_count
        if not n:
            raise ValueError("This PDF has no pages.")
        scanned = [i for i in range(n) if is_scanned(doc[i])]
        total, step = len(scanned) + n + 1, 0
        # a decrypted copy to work on; scanned pages are swapped for their OCR text
        work = pymupdf.open("pdf", doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_NONE))
    finally:
        doc.close()

    ocr_done: list[int] = []
    for i in scanned:
        step += 1
        report(step, total, f"Reading scanned page {i + 1} with OCR…")
        try:
            text_doc = _ocr_page(work[i])
        except Exception:
            notes.append(f"Page {i + 1} is a scan and its text couldn't be read, so it was kept as a picture.")
            continue
        if not _has_text(text_doc[0]):
            notes.append(f"Page {i + 1} is a scan with no readable text, so it was kept as a picture.")
            continue
        work.delete_page(i)
        work.insert_pdf(text_doc, start_at=i)
        text_doc.close()
        ocr_done.append(i + 1)

    conv = Converter(stream=work.tobytes())
    work.close()
    try:
        settings = conv.default_settings
        conv.load_pages()
        conv.parse_document(**settings)
        for page in conv.pages:
            step += 1
            report(step, total, f"Converting page {page.id + 1} of {n}…")
            try:
                page.parse(**settings)
            except Exception:
                notes.append(f"Page {page.id + 1} couldn't be converted and was left out.")
        parsed = [p for p in conv.pages if p.finalized]
        if not parsed:
            raise ValueError("Nothing in this PDF could be converted to Word.")
        report(total, total, "Saving…")
        docx, made = Document(), 0
        for page in parsed:
            try:
                page.make_docx(docx)
                made += 1
            except Exception:
                notes.append(f"Page {page.id + 1} couldn't be converted and was left out.")
        if not made:
            raise ValueError("Nothing in this PDF could be converted to Word.")
        _save_via_temp(output_path, docx.save)
    finally:
        conv.close()
    return ConvertResult(output_path, made, 0, ocr_done, notes)


# ------------------------------------------------------------------ Excel

_BAD_SHEET_CHARS = re.compile(r"[\[\]:*?/\\]")
_NUMBER = re.compile(r"^(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?$|^\.\d+$")
_CURRENCY = "£$€"


def sheet_name(base: str, used: set[str]) -> str:
    """A valid, unique Excel sheet name: at most 31 characters, none of []:*?/\\,
    and "Page 3", "Page 3 (2)", "Page 3 (3)"… when one page has several tables."""
    base = _BAD_SHEET_CHARS.sub(" ", base).strip().strip("'")[:31].strip() or "Sheet"
    name, k = base, 2
    while name.lower() in used:
        suffix = f" ({k})"
        name = base[: 31 - len(suffix)].rstrip() + suffix
        k += 1
    used.add(name.lower())
    return name


def parse_number(text: str) -> tuple[int | float, str] | None:
    """The number in a cell and an Excel number format for it, or None to keep
    the cell as text.

    Numbers: ``1234``, ``1,234.50``, ``-12.5``, ``(45.00)`` (negative),
    ``£1,234.50`` / ``$12`` / ``12 €``, ``20%`` / ``5.5%`` (stored as 0.2 / 0.055).
    Kept as text: leading-zero codes (``00123``, ``07700 900123``), phone
    numbers, refs with letters (``AMM11280899``), dates, anything over 15 digits.
    """
    s = text.strip().replace("−", "-").replace(" ", " ")
    if not s or len(s) > 30 or "\n" in s:
        return None
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg, s = True, s[1:-1].strip()
    if s.startswith("-"):
        neg, s = True, s[1:].strip()
    cur = ""
    if s[:1] and s[0] in _CURRENCY:
        cur, s = s[0], s[1:].strip()
    elif s[-1:] and s[-1] in _CURRENCY:
        cur, s = s[-1], s[:-1].strip()
    if cur and s.startswith("-") and not neg:  # £-5
        neg, s = True, s[1:].strip()
    pct = s.endswith("%")
    if pct:
        if cur:
            return None
        s = s[:-1].strip()
    if not _NUMBER.match(s):
        return None
    whole = s.split(".")[0].replace(",", "")
    if len(whole) > 1 and whole.startswith("0"):
        return None  # a code, not a number
    if len(s.replace(",", "").replace(".", "").lstrip("0")) > 15:
        return None  # beyond Excel's precision: an account or card number
    decimals = len(s.split(".")[1]) if "." in s else 0
    plain = s.replace(",", "")
    value: int | float = float(plain) if decimals else int(plain)
    if neg:
        value = -value
    places = "." + "0" * decimals if decimals else ""
    if pct:
        return value / 100, f"0{places}%"
    if cur:
        return value, f'"{cur}"#,##0{places}'
    if "," in s:
        return value, f"#,##0{places}"
    return value, f"0{places}" if decimals else "General"


def _table_rows(page: pymupdf.Page, table) -> list[list[str]]:
    # read each cell's own box: table.extract() can split "1,234.50" across lines
    rows = []
    if table.header.external:
        rows.append([(c or "").strip() for c in table.header.names])
    for row in table.rows:
        rows.append(["" if c is None else page.get_textbox(pymupdf.Rect(c)).strip() for c in row.cells])
    return [r for r in rows if any(r)]


def _text_rows(page: pymupdf.Page) -> list[list[str]]:
    """The page's text lines, split into columns where words are far apart and
    lined up with the columns of the lines around them."""
    words = [_Item(x0, x1, y0, y1, t) for x0, y0, x1, y1, t, *_ in page.get_text("words") if t.strip()]
    lines = [_runs(r, 0.8) for r in _rows(words)]
    # column bands: merge the x-ranges of runs on lines that have more than one
    bands: list[list[float]] = []
    for x0, x1 in sorted((r.x0, r.x1) for line in lines if len(line) > 1 for r in line):
        if bands and x0 <= bands[-1][1]:
            bands[-1][1] = max(bands[-1][1], x1)
        else:
            bands.append([x0, x1])

    def column(run: _Item) -> int:
        for k, (b0, b1) in enumerate(bands):
            if run.x0 <= b1 and run.x1 >= b0:
                return k
        return max([k for k, (b0, _) in enumerate(bands) if b0 <= run.x0], default=0)

    out = []
    for line in lines:
        cells = [""] * max(1, len(bands))
        for run in line:
            k = column(run) if len(line) > 1 else 0
            cells[k] = f"{cells[k]} {run.text}".strip()
        while len(cells) > 1 and not cells[-1]:
            cells.pop()
        out.append(cells)
    return out


def _write_sheet(ws, rows: list[list[str]], header: bool) -> None:
    from openpyxl.styles import Alignment, Font
    from openpyxl.utils import get_column_letter

    widths: dict[int, int] = {}
    for r, row in enumerate(rows, start=1):
        for c, text in enumerate(row, start=1):
            if not text:
                continue
            cell = ws.cell(row=r, column=c)
            num = None if header and r == 1 else parse_number(text)
            if num is not None:
                cell.value, cell.number_format = num
            else:
                cell.value = text
                if "\n" in text:
                    cell.alignment = Alignment(wrap_text=True, vertical="top")
            if header and r == 1:
                cell.font = Font(bold=True)
            widths[c] = max(widths.get(c, 0), max(len(t) for t in text.split("\n")))
    for c, w in widths.items():
        ws.column_dimensions[get_column_letter(c)].width = min(60, max(8, w + 2))


def pdf_to_excel(input_path: str, output_path: str, password: str | None = None,
                 progress: Progress | None = None) -> ConvertResult:
    """Every table in the PDF on its own worksheet. Pages without a table give
    a sheet of their text, in columns."""
    from openpyxl import Workbook

    report = progress or (lambda *_: None)
    doc = _open(input_path, password)
    notes: list[str] = []
    ocr_done: list[int] = []
    sheets: list[tuple[str, list[list[str]], bool]] = []  # (name, rows, has header)
    used: set[str] = set()
    tables_found = pages_used = 0
    try:
        n = doc.page_count
        for i in range(n):
            report(i, n, f"Reading page {i + 1} of {n}…")
            page, text_doc = doc[i], None
            if is_scanned(page):
                report(i, n, f"Reading scanned page {i + 1} with OCR…")
                try:
                    text_doc = _ocr_page(page)
                except Exception:
                    notes.append(f"Page {i + 1} is a scan and its text couldn't be read.")
                    continue
                if not _has_text(text_doc[0]):
                    notes.append(f"Page {i + 1} is a scan with no readable text.")
                    continue
                page = text_doc[0]
                ocr_done.append(i + 1)
            # ruled tables only: the AI layout gate isn't shipped in the app, so don't use it here either
            tables = page.find_tables(use_layout=False).tables
            found = [rows for t in tables if (rows := _table_rows(page, t))]
            for rows in found:
                sheets.append((sheet_name(f"Page {i + 1}", used), rows, True))
            if found:
                tables_found += len(found)
                pages_used += 1
            elif rows := _text_rows(page):
                sheets.append((sheet_name(f"Page {i + 1}", used), rows, False))
                pages_used += 1
            if text_doc:
                text_doc.close()
    finally:
        doc.close()
    if not sheets:
        raise ValueError("No tables or text were found in this PDF, so there's nothing to put in a spreadsheet.")

    report(n, n, "Saving…")
    wb = Workbook()
    wb.remove(wb.active)
    for name, rows, header in sheets:
        _write_sheet(wb.create_sheet(name), rows, header)
    _save_via_temp(output_path, wb.save)
    return ConvertResult(output_path, pages_used, tables_found, ocr_done, notes)


def convert(kind: str, input_path: str, output_path: str, password: str | None = None,
            progress: Progress | None = None) -> ConvertResult:
    return (pdf_to_word if kind == WORD else pdf_to_excel)(input_path, output_path, password, progress)
