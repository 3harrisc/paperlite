"""Undo/redo by snapshot.

Before each change the whole document is written to a temporary file. Undo
reopens the previous snapshot. This works for every kind of edit (forms,
scans, page reordering, inserting files) and costs well under a second even
for large scans because snapshots are saved without compression.
"""

from __future__ import annotations

import os
import shutil
import tempfile

import pymupdf


class History:
    def __init__(self, limit: int = 30):
        self.limit = limit
        self.dir = tempfile.mkdtemp(prefix="paperlite-undo-")
        self.undo_stack: list[tuple[str, str]] = []  # (label, snapshot path)
        self.redo_stack: list[tuple[str, str]] = []
        self._n = 0

    def _snap(self, doc: pymupdf.Document) -> str:
        self._n += 1
        path = os.path.join(self.dir, f"{self._n}.pdf")
        doc.save(path, garbage=0, deflate=False, encryption=pymupdf.PDF_ENCRYPT_NONE)
        return path

    def checkpoint(self, doc: pymupdf.Document, label: str) -> None:
        """Call *before* changing ``doc``."""
        self.undo_stack.append((label, self._snap(doc)))
        for _, p in self.redo_stack:
            _remove(p)
        self.redo_stack.clear()
        while len(self.undo_stack) > self.limit:
            _remove(self.undo_stack.pop(0)[1])

    def drop_last(self) -> None:
        """Forget the last checkpoint (the change failed and nothing happened)."""
        if self.undo_stack:
            _remove(self.undo_stack.pop()[1])

    def can_undo(self) -> bool:
        return bool(self.undo_stack)

    def can_redo(self) -> bool:
        return bool(self.redo_stack)

    def undo_label(self) -> str:
        return self.undo_stack[-1][0] if self.undo_stack else ""

    def redo_label(self) -> str:
        return self.redo_stack[-1][0] if self.redo_stack else ""

    def undo(self, doc: pymupdf.Document) -> pymupdf.Document:
        label, path = self.undo_stack.pop()
        self.redo_stack.append((label, self._snap(doc)))
        return _load(path)

    def redo(self, doc: pymupdf.Document) -> pymupdf.Document:
        label, path = self.redo_stack.pop()
        self.undo_stack.append((label, self._snap(doc)))
        return _load(path)

    def clear(self) -> None:
        for _, p in self.undo_stack + self.redo_stack:
            _remove(p)
        self.undo_stack.clear()
        self.redo_stack.clear()

    def close(self) -> None:
        self.clear()
        shutil.rmtree(self.dir, ignore_errors=True)


def _load(path: str) -> pymupdf.Document:
    """Open a snapshot from memory so the temp file isn't kept locked (Windows)."""
    with open(path, "rb") as f:
        data = f.read()
    _remove(path)
    return pymupdf.open("pdf", data)


def _remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass  # Windows may still hold the file open; temp dir is cleaned on exit
