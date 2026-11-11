"""Organise pages: reorder, rotate, delete, insert, combine, extract, split, export as images."""

from __future__ import annotations

import os

import pymupdf


def reorder(doc: pymupdf.Document, order: list[int]) -> None:
    """Put pages in ``order`` (a list of current page indexes)."""
    if sorted(order) != list(range(doc.page_count)):
        raise ValueError("order must list every page exactly once")
    doc.select(order)


def rotate(doc: pymupdf.Document, indexes: list[int], degrees: int) -> None:
    for i in indexes:
        page = doc[i]
        page.set_rotation((page.rotation + degrees) % 360)


def delete(doc: pymupdf.Document, indexes: list[int]) -> None:
    if len(set(indexes)) >= doc.page_count:
        raise ValueError("A PDF must keep at least one page.")
    doc.delete_pages(sorted(set(indexes)))


def insert_blank(doc: pymupdf.Document, at: int) -> None:
    ref = doc[min(max(at - 1, 0), doc.page_count - 1)].rect if doc.page_count else pymupdf.paper_rect("a4")
    doc.new_page(pno=at, width=ref.width, height=ref.height)


def insert_file(doc: pymupdf.Document, path: str, at: int, password: str | None = None) -> int:
    """Insert every page of ``path`` before page ``at``. Returns how many pages were added."""
    src = _open(path, password)
    try:
        n = src.page_count
        doc.insert_pdf(src, start_at=at)
        return n
    finally:
        src.close()


def _open(path: str, password: str | None = None) -> pymupdf.Document:
    src = pymupdf.open(path)
    if not src.is_pdf:  # images etc. get converted to a PDF page
        pdf = pymupdf.open("pdf", src.convert_to_pdf())
        src.close()
        src = pdf
    if src.needs_pass and not src.authenticate(password or ""):
        src.close()
        raise PermissionError(f"{os.path.basename(path)} is password protected.")
    return src


def combine(paths: list[str], output_path: str) -> int:
    """Join several PDFs (or images) into one file. Returns the page count."""
    out = pymupdf.open()
    try:
        for p in paths:
            src = _open(p)
            out.insert_pdf(src)
            src.close()
        out.save(output_path, garbage=3, deflate=True)
        return out.page_count
    finally:
        out.close()


def extract(doc: pymupdf.Document, indexes: list[int], output_path: str) -> None:
    """Save the chosen pages (in the given order) as a new PDF."""
    out = pymupdf.open()
    try:
        for i in indexes:
            out.insert_pdf(doc, from_page=i, to_page=i)
        out.save(output_path, garbage=3, deflate=True)
    finally:
        out.close()


def parse_ranges(text: str, page_count: int) -> list[int]:
    """Turn '1-3, 5, 8-' into zero-based indexes. Raises ValueError on bad input."""
    result: list[int] = []
    for part in text.replace(" ", "").split(","):
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            start = int(a) if a else 1
            end = int(b) if b else page_count
        else:
            start = end = int(part)
        if not (1 <= start <= page_count and 1 <= end <= page_count):
            raise ValueError(f"Page numbers must be between 1 and {page_count}.")
        step = 1 if end >= start else -1
        result.extend(i - 1 for i in range(start, end + step, step))
    if not result:
        raise ValueError("Enter at least one page number.")
    return result


def split(doc: pymupdf.Document, every: int, folder: str, base_name: str) -> list[str]:
    """Split into files of ``every`` pages each. Returns the files written."""
    files = []
    for n, start in enumerate(range(0, doc.page_count, every), 1):
        end = min(start + every, doc.page_count) - 1
        name = f"{base_name} - pages {start + 1}-{end + 1}.pdf" if end > start else f"{base_name} - page {start + 1}.pdf"
        path = os.path.join(folder, name)
        extract(doc, list(range(start, end + 1)), path)
        files.append(path)
    return files


def export_images(doc: pymupdf.Document, indexes: list[int], folder: str, base_name: str,
                  fmt: str = "png", dpi: int = 150) -> list[str]:
    """Save pages as PNG or JPG images. Returns the files written."""
    fmt = fmt.lower().replace("jpeg", "jpg")
    files = []
    for i in indexes:
        pix = doc[i].get_pixmap(dpi=dpi, alpha=False)
        path = os.path.join(folder, f"{base_name} - page {i + 1}.{fmt}")
        if fmt == "jpg":
            pix.save(path, jpg_quality=90)
        else:
            pix.save(path)
        files.append(path)
    return files
