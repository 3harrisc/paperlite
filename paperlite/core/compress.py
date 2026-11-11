"""PDF compression, aimed at large scanned documents.

Scanned PDFs are big because every page is a full-resolution photo of paper,
usually 300-600 DPI and often stored with weak or no compression. Most of the
size saving comes from three things:

1. Downsampling: any image above ``dpi_threshold`` is resampled to ``dpi_target``.
2. Re-encoding: colour and greyscale images are re-encoded as JPEG at ``quality``.
3. Clean-up: unused objects are removed, streams are deflated and objects are
   packed into object streams.

Black-and-white (1-bit) scans are already small, so they are left alone unless
they are above the DPI threshold.

The presets below are the source of truth for both the Windows app and the
planned Mac app. To get the same results in Swift/PDFKit, use the same DPI and
JPEG quality numbers.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass, field

import pymupdf


@dataclass(frozen=True)
class Preset:
    key: str
    label: str
    description: str
    dpi_threshold: int  # images above this effective DPI get downsampled
    dpi_target: int  # ...to this DPI
    quality: int  # JPEG quality, 0-100
    grayscale: bool = False


PRESETS: dict[str, Preset] = {
    p.key: p
    for p in [
        Preset("high", "High quality", "Print-ready. Smaller file, hard to tell apart from the original.", 225, 200, 85),
        Preset("standard", "Standard (recommended)", "Good for email and archiving. Text stays sharp.", 165, 150, 70),
        Preset("small", "Smallest file", "Good for on-screen reading. Photos lose some detail.", 110, 96, 55),
        Preset("small_gray", "Smallest, black & white", "Converts pages to greyscale. Best for text-only scans.", 110, 96, 55, grayscale=True),
    ]
}
DEFAULT_PRESET = "standard"


@dataclass
class CompressResult:
    input_path: str
    output_path: str
    original_bytes: int
    compressed_bytes: int
    kept_original: bool = False  # True when compressing didn't make the file smaller
    notes: list[str] = field(default_factory=list)

    @property
    def saved_bytes(self) -> int:
        return self.original_bytes - self.compressed_bytes

    @property
    def saved_percent(self) -> float:
        if not self.original_bytes:
            return 0.0
        return 100.0 * self.saved_bytes / self.original_bytes


def human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{n} B"


def compress_pdf(
    input_path: str,
    output_path: str,
    preset: str | Preset = DEFAULT_PRESET,
    password: str | None = None,
) -> CompressResult:
    """Compress ``input_path`` into ``output_path``.

    ``output_path`` may be the same as ``input_path``. If compression would make
    the file bigger, the original is copied unchanged and ``kept_original`` is set.
    """
    p = PRESETS[preset] if isinstance(preset, str) else preset
    original = os.path.getsize(input_path)
    notes: list[str] = []

    doc = pymupdf.open(input_path)
    try:
        if doc.needs_pass and not doc.authenticate(password or ""):
            raise PermissionError("This PDF is password protected. Enter the password to compress it.")

        doc.rewrite_images(
            dpi_threshold=p.dpi_threshold,
            dpi_target=p.dpi_target,
            quality=p.quality,
            lossy=True,
            lossless=True,
            bitonal=True,
            color=True,
            gray=True,
            set_to_gray=p.grayscale,
        )
        try:
            doc.subset_fonts()
        except Exception:  # font subsetting is a bonus; never fail the job over it
            notes.append("Fonts could not be subset.")

        out_dir = os.path.dirname(os.path.abspath(output_path)) or "."
        fd, tmp = tempfile.mkstemp(suffix=".pdf", dir=out_dir)
        os.close(fd)
        try:
            doc.save(
                tmp,
                garbage=4,
                deflate=True,
                deflate_images=True,
                deflate_fonts=True,
                clean=True,
                use_objstms=1,
            )
        except Exception:
            os.remove(tmp)
            raise
    finally:
        doc.close()

    new_size = os.path.getsize(tmp)
    if new_size >= original:
        os.remove(tmp)
        if os.path.abspath(input_path) != os.path.abspath(output_path):
            shutil.copyfile(input_path, output_path)
        notes.append("This file is already well compressed, so it was left as it was.")
        return CompressResult(input_path, output_path, original, original, True, notes)

    os.replace(tmp, output_path)
    return CompressResult(input_path, output_path, original, new_size, False, notes)
