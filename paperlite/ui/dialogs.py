"""Dialogs: compress, signature pad, text entry."""

from __future__ import annotations

import os

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QSettings, QSize, Qt, QThread, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from paperlite.core import compress, pages
from paperlite.ui import theme


def _section(text: str) -> QLabel:
    lb = QLabel(text)
    lb.setObjectName("SectionLabel")
    return lb


def dialog_header(icon_name: str, title: str, subtitle: str, tint: str) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setSpacing(12)
    badge = QLabel()
    badge.setFixedSize(40, 40)
    badge.setAlignment(Qt.AlignCenter)
    badge.setStyleSheet(f"background:{tint};border-radius:10px;")
    badge.setPixmap(theme.pixmap(icon_name, "#FFFFFF", 22))
    row.addWidget(badge, alignment=Qt.AlignTop)
    col = QVBoxLayout()
    col.setSpacing(2)
    t = QLabel(title)
    t.setObjectName("PanelTitle")
    sub = QLabel(subtitle)
    sub.setObjectName("PanelHint")
    sub.setWordWrap(True)
    col.addWidget(t)
    col.addWidget(sub)
    row.addLayout(col, 1)
    return row


# --------------------------------------------------------------------------- compress


class CompressWorker(QThread):
    progress = Signal(int, str)  # index, filename
    finished_one = Signal(object)  # CompressResult or Exception
    done = Signal()

    def __init__(self, jobs: list[tuple[str, str]], preset: str):
        super().__init__()
        self.jobs, self.preset = jobs, preset

    def run(self):
        for i, (src, dst) in enumerate(self.jobs):
            self.progress.emit(i, os.path.basename(src))
            try:
                self.finished_one.emit(compress.compress_pdf(src, dst, self.preset))
            except Exception as e:  # report and carry on with the next file
                e.filename = src  # type: ignore[attr-defined]
                self.finished_one.emit(e)
        self.done.emit()


def compressed_name(path: str) -> str:
    root, ext = os.path.splitext(path)
    return f"{root}_compressed{ext or '.pdf'}"


class CompressDialog(QDialog):
    """Compress one or more PDFs. Originals are never overwritten unless asked."""

    def __init__(self, parent=None, files: list[str] | None = None):
        super().__init__(parent)
        self.setWindowTitle("Compress PDF")
        self.setMinimumWidth(520)
        self.results: list = []
        self.worker: CompressWorker | None = None
        settings = QSettings()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(8)
        lay.addLayout(dialog_header("minimize-2", "Compress PDF", "Make files smaller. Scanned documents usually shrink the most.", theme.BRAND))
        lay.addSpacing(6)
        lay.addWidget(_section("FILES"))
        self.file_list = QListWidget()
        self.file_list.setMaximumHeight(96)
        lay.addWidget(self.file_list)
        row = QHBoxLayout()
        add_btn = QPushButton("Add files…")
        add_btn.setIcon(theme.icon("file-plus", theme.TEXT, size=16))
        add_btn.clicked.connect(self._add_files)
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self.file_list.clear)
        row.addWidget(add_btn)
        row.addWidget(clear_btn)
        row.addStretch()
        lay.addLayout(row)

        lay.addSpacing(6)
        lay.addWidget(_section("COMPRESSION LEVEL"))
        self.group = QButtonGroup(self)
        current = settings.value("compress/preset", compress.DEFAULT_PRESET)
        for p in compress.PRESETS.values():
            rb = QRadioButton(p.label.replace("&", "&&"))
            rb.setProperty("preset", p.key)
            rb.setChecked(p.key == current)
            rb.setStyleSheet("font-weight:600")
            self.group.addButton(rb)
            lay.addWidget(rb)
            hint = QLabel(p.description)
            hint.setObjectName("PanelHint")
            hint.setContentsMargins(26, 0, 0, 6)
            lay.addWidget(hint)

        self.overwrite = QCheckBox("Replace the original files (otherwise saves as “name_compressed.pdf”)")
        self.overwrite.setChecked(settings.value("compress/overwrite", False, type=bool))
        lay.addWidget(self.overwrite)

        self.progress = QProgressBar()
        self.progress.hide()
        lay.addWidget(self.progress)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.status)

        self.buttons = QDialogButtonBox()
        self.go_btn = self.buttons.addButton("Compress", QDialogButtonBox.AcceptRole)
        self.go_btn.setProperty("kind", "primary")
        self.close_btn = self.buttons.addButton(QDialogButtonBox.Close)
        self.go_btn.clicked.connect(self._start)
        self.close_btn.clicked.connect(self.reject)
        lay.addWidget(self.buttons)

        for f in files or []:
            self._add_path(f)

    def _add_path(self, path: str):
        it = QListWidgetItem(theme.icon("file-text", theme.TEXT_MUTED, size=16), os.path.basename(path))
        it.setData(Qt.UserRole, path)
        it.setToolTip(path)
        self.file_list.addItem(it)

    def _add_files(self):
        start = QSettings().value("lastDir", "")
        paths, _ = QFileDialog.getOpenFileNames(self, "Choose PDFs to compress", start, "PDF files (*.pdf)")
        for p in paths:
            self._add_path(p)

    def selected_preset(self) -> str:
        return self.group.checkedButton().property("preset")

    def _start(self):
        files = [self.file_list.item(i).data(Qt.UserRole) for i in range(self.file_list.count())]
        if not files:
            self.status.setText("Add at least one PDF first.")
            return
        s = QSettings()
        s.setValue("compress/preset", self.selected_preset())
        s.setValue("compress/overwrite", self.overwrite.isChecked())
        jobs = [(f, f if self.overwrite.isChecked() else compressed_name(f)) for f in files]
        self.results = []
        self.progress.setRange(0, len(jobs))
        self.progress.setValue(0)
        self.progress.show()
        self.go_btn.setEnabled(False)
        self.worker = CompressWorker(jobs, self.selected_preset())
        self.worker.progress.connect(lambda i, name: self.status.setText(f"Compressing {name}…"))
        self.worker.finished_one.connect(self._one_done)
        self.worker.done.connect(self._all_done)
        self.worker.start()

    def _one_done(self, r):
        self.results.append(r)
        self.progress.setValue(len(self.results))

    def _all_done(self):
        lines, total_before, total_after = [], 0, 0
        for r in self.results:
            if isinstance(r, Exception):
                lines.append(f"❌ {os.path.basename(r.filename)}: {r}")
                continue
            total_before += r.original_bytes
            total_after += r.compressed_bytes
            name = os.path.basename(r.output_path)
            if r.kept_original:
                lines.append(f"• {name}: already small ({compress.human_size(r.original_bytes)}), left unchanged")
            else:
                lines.append(
                    f"✅ {name}: {compress.human_size(r.original_bytes)} → "
                    f"{compress.human_size(r.compressed_bytes)} ({r.saved_percent:.0f}% smaller)"
                )
        if len(self.results) > 1 and total_before:
            lines.append(
                f"<b>Total: {compress.human_size(total_before)} → {compress.human_size(total_after)} "
                f"({100 * (total_before - total_after) / total_before:.0f}% smaller)</b>"
            )
        self.status.setText("<br>".join(lines))
        self.go_btn.setEnabled(True)
        self.go_btn.setText("Compress again")

    def reject(self):
        if self.worker and self.worker.isRunning():
            return  # don't close mid-write
        super().reject()


# --------------------------------------------------------------------------- signature


class SignaturePad(QWidget):
    """Draw a signature with the mouse, pen or touch."""

    def __init__(self):
        super().__init__()
        self.setMinimumSize(460, 160)
        self.setAttribute(Qt.WA_StaticContents)
        self.strokes: list[list[QPointF]] = []

    def clear(self):
        self.strokes = []
        self.update()

    def mousePressEvent(self, e):
        self.strokes.append([e.position()])
        self.update()

    def mouseMoveEvent(self, e):
        if self.strokes and e.buttons() & Qt.LeftButton:
            self.strokes[-1].append(e.position())
            self.update()

    def _paint_strokes(self, p: QPainter, scale: float = 1.0):
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(10, 20, 80), 2.6 * scale, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        for s in self.strokes:
            path = QPainterPath(s[0] * scale)
            if len(s) == 1:
                path.lineTo(s[0] * scale + QPointF(0.1, 0.1))
            for pt in s[1:]:
                path.lineTo(pt * scale)
            p.drawPath(path)

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), Qt.white)
        p.setPen(QPen(QColor(200, 200, 200), 1, Qt.DashLine))
        y = int(self.height() * 0.75)
        p.drawLine(20, y, self.width() - 20, y)
        self._paint_strokes(p)

    def to_image(self) -> QImage | None:
        if not self.strokes:
            return None
        scale = 3.0  # render at 3x so it prints crisply
        img = QImage(int(self.width() * scale), int(self.height() * scale), QImage.Format_ARGB32)
        img.fill(Qt.transparent)
        p = QPainter(img)
        self._paint_strokes(p, scale)
        p.end()
        return crop_transparent(img)


def crop_transparent(img: QImage) -> QImage:
    w, h = img.width(), img.height()
    xs, ys = [], []
    for y in range(0, h, 2):
        for x in range(0, w, 2):
            if img.pixelColor(x, y).alpha():
                xs.append(x)
                ys.append(y)
    if not xs:
        return img
    pad = 8
    return img.copy(max(0, min(xs) - pad), max(0, min(ys) - pad), min(w, max(xs) + pad) - max(0, min(xs) - pad), min(h, max(ys) + pad) - max(0, min(ys) - pad))


def typed_signature(text: str) -> QImage:
    font = QFont()
    for fam in ("Segoe Script", "Lucida Handwriting", "Brush Script MT", "Snell Roundhand", "Bradley Hand", "Comic Sans MS"):
        font = QFont(fam)
        if font.exactMatch():
            break
    font.setPixelSize(120)
    font.setItalic(True)
    from PySide6.QtGui import QFontMetrics

    fm = QFontMetrics(font)
    w, h = fm.horizontalAdvance(text) + 40, fm.height() + 20
    img = QImage(max(w, 10), h, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setFont(font)
    p.setPen(QColor(10, 20, 80))
    p.drawText(20, fm.ascent() + 10, text)
    p.end()
    return img


def image_to_png(img: QImage) -> bytes:
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(ba)


class SignatureDialog(QDialog):
    """Create a signature (draw or type). It is remembered for next time."""

    def __init__(self, parent=None, kind: str = "signature"):
        super().__init__(parent)
        self.kind = kind
        self.setWindowTitle("Create signature" if kind == "signature" else "Create initials")
        self.png: bytes | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(12)
        lay.addLayout(dialog_header("signature", self.windowTitle(),
                                    "Type it or draw it with your mouse, pen or finger. It's saved on this computer for next time.",
                                    "#7C3AED"))
        self.tabs = QTabWidget()
        self.pad = SignaturePad()
        draw_tab = QWidget()
        dl = QVBoxLayout(draw_tab)
        dl.addWidget(self.pad)
        clear = QPushButton("Clear")
        clear.clicked.connect(self.pad.clear)
        dl.addWidget(clear, alignment=Qt.AlignRight)
        type_tab = QWidget()
        tl = QVBoxLayout(type_tab)
        self.typed = QLineEdit()
        self.typed.setPlaceholderText("Type your name")
        self.typed.setMinimumHeight(34)
        self.preview = QLabel()
        self.preview.setMinimumHeight(90)
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setStyleSheet(f"background:white;border:1px solid {theme.BORDER};border-radius:8px;")
        self.typed.textChanged.connect(self._update_preview)
        tl.addWidget(self.typed)
        tl.addWidget(self.preview)
        self.tabs.addTab(type_tab, "Type")
        self.tabs.addTab(draw_tab, "Draw")
        lay.addWidget(self.tabs)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Use this")
        bb.button(QDialogButtonBox.Ok).setProperty("kind", "primary")
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _update_preview(self, text):
        if text.strip():
            from PySide6.QtGui import QPixmap

            self.preview.setPixmap(QPixmap.fromImage(typed_signature(text)).scaledToHeight(70, Qt.SmoothTransformation))
        else:
            self.preview.clear()

    def _ok(self):
        if self.tabs.currentIndex() == 0:
            img = typed_signature(self.typed.text()) if self.typed.text().strip() else None
        else:
            img = self.pad.to_image()
        if img is None:
            return
        self.png = image_to_png(img)
        QSettings().setValue(f"sign/{self.kind}", QByteArray(self.png))
        self.accept()


def saved_signature(kind: str) -> bytes | None:
    v = QSettings().value(f"sign/{kind}")
    return bytes(v) if v else None


# --------------------------------------------------------------------------- text entry


class TextEntryDialog(QDialog):
    def __init__(self, parent, title: str, text: str = "", size: float | None = None):
        super().__init__(parent)
        self.setWindowTitle(title)
        lay = QVBoxLayout(self)
        self.edit = QLineEdit(text)
        self.edit.setMinimumWidth(380)
        self.edit.selectAll()
        lay.addWidget(self.edit)
        self.size = None
        if size is not None:
            row = QHBoxLayout()
            row.addWidget(QLabel("Font size:"))
            self.size = QSpinBox()
            self.size.setRange(4, 96)
            self.size.setValue(int(size))
            row.addWidget(self.size)
            row.addStretch()
            lay.addLayout(row)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def value(self) -> tuple[str, float | None]:
        return self.edit.text(), (self.size.value() if self.size else None)


# --------------------------------------------------------------------------- combine


class CombineDialog(QDialog):
    """Pick files, put them in order, join them into one PDF."""

    def __init__(self, parent=None, files: list[str] | None = None):
        super().__init__(parent)
        self.setWindowTitle("Combine files")
        self.setMinimumSize(560, 460)
        self.output: str | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(10)
        lay.addLayout(dialog_header("combine", "Combine files", "Join PDFs and images into one PDF. Drag to change the order.", "#D97706"))
        self.list = QListWidget()
        self.list.setDragDropMode(QListWidget.InternalMove)
        self.list.setSelectionMode(QListWidget.ExtendedSelection)
        self.list.setIconSize(QSize(18, 18))
        lay.addWidget(self.list, 1)
        row = QHBoxLayout()
        add = QPushButton("Add files…")
        add.setIcon(theme.icon("file-plus", theme.TEXT, size=16))
        add.clicked.connect(self._add)
        rem = QPushButton("Remove")
        rem.setIcon(theme.icon("trash-2", theme.TEXT, size=16))
        rem.clicked.connect(lambda: [self.list.takeItem(self.list.row(i)) for i in self.list.selectedItems()])
        row.addWidget(add)
        row.addWidget(rem)
        row.addStretch()
        self.info = QLabel()
        self.info.setObjectName("PanelHint")
        row.addWidget(self.info)
        lay.addLayout(row)
        bb = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.go = bb.addButton("Combine", QDialogButtonBox.AcceptRole)
        self.go.setProperty("kind", "primary")
        self.go.clicked.connect(self._combine)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.list.model().rowsInserted.connect(self._update)
        self.list.model().rowsRemoved.connect(self._update)
        for f in files or []:
            self.add_path(f)
        self._update()

    def add_path(self, path: str):
        it = QListWidgetItem(theme.icon("file-text", theme.TEXT_MUTED, size=18), os.path.basename(path))
        it.setData(Qt.UserRole, path)
        it.setToolTip(path)
        self.list.addItem(it)

    def paths(self) -> list[str]:
        return [self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())]

    def _update(self, *_):
        n = self.list.count()
        self.info.setText(f"{n} file{'s' if n != 1 else ''}")
        self.go.setEnabled(n >= 2)

    def _add(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Add files", QSettings().value("lastDir", ""),
                                                "PDFs and images (*.pdf *.png *.jpg *.jpeg *.tif *.tiff *.bmp)")
        for p in paths:
            self.add_path(p)

    def _combine(self):
        files = self.paths()
        first = files[0]
        suggested = os.path.join(os.path.dirname(first), "Combined.pdf")
        out, _ = QFileDialog.getSaveFileName(self, "Save combined PDF", suggested, "PDF files (*.pdf)")
        if not out:
            return
        try:
            pages.combine(files, out)
        except Exception as e:
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.warning(self, "Combine files", f"Couldn't combine the files:\n{e}")
            return
        self.output = out
        self.accept()


# --------------------------------------------------------------------------- page ranges


class PagesDialog(QDialog):
    """Choose pages (and options) for Extract, Export images or Split."""

    def __init__(self, parent, mode: str, page_count: int, selected: list[int]):
        super().__init__(parent)
        self.mode, self.page_count = mode, page_count
        titles = {
            "extract": ("file-output", "Extract pages", "Save the chosen pages as a new PDF. The original isn't changed."),
            "export_images": ("image-down", "Export as images", "Save pages as picture files."),
            "split": ("scissors", "Split PDF", "Break this PDF into several smaller files."),
        }
        ic, title, sub = titles[mode]
        self.setWindowTitle(title)
        self.setMinimumWidth(440)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(8)
        lay.addLayout(dialog_header(ic, title, sub, "#0E9F6E"))
        lay.addSpacing(8)
        self.range = QLineEdit()
        self.every = QSpinBox()
        self.fmt = None
        self.dpi = None
        if mode == "split":
            lay.addWidget(_section("PAGES PER FILE"))
            self.every.setRange(1, max(1, page_count))
            self.every.setValue(1)
            lay.addWidget(self.every)
        else:
            lay.addWidget(_section("PAGES"))
            default = _ranges_text(selected) if selected else f"1-{page_count}"
            self.range.setText(default)
            self.range.setPlaceholderText("e.g. 1-3, 5, 8-")
            lay.addWidget(self.range)
            hint = QLabel(f"This PDF has {page_count} pages. Use commas and dashes, e.g. 1-3, 5.")
            hint.setObjectName("PanelHint")
            lay.addWidget(hint)
        if mode == "export_images":
            from PySide6.QtWidgets import QComboBox

            lay.addSpacing(6)
            lay.addWidget(_section("FORMAT"))
            row = QHBoxLayout()
            self.fmt = QComboBox()
            self.fmt.addItem("PNG (sharp, larger)", "png")
            self.fmt.addItem("JPG (photos, smaller)", "jpg")
            self.dpi = QComboBox()
            for d, t in ((96, "Screen – 96 DPI"), (150, "Standard – 150 DPI"), (300, "Print – 300 DPI")):
                self.dpi.addItem(t, d)
            self.dpi.setCurrentIndex(1)
            row.addWidget(self.fmt)
            row.addWidget(self.dpi)
            lay.addLayout(row)
        self.error = QLabel()
        self.error.setStyleSheet(f"color:{theme.BRAND}")
        lay.addWidget(self.error)
        bb = QDialogButtonBox(QDialogButtonBox.Cancel)
        ok = bb.addButton({"extract": "Extract", "export_images": "Export", "split": "Split"}[mode], QDialogButtonBox.AcceptRole)
        ok.setProperty("kind", "primary")
        ok.clicked.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def indexes(self) -> list[int]:
        return pages.parse_ranges(self.range.text(), self.page_count)

    def _ok(self):
        if self.mode != "split":
            try:
                self.indexes()
            except ValueError as e:
                self.error.setText(str(e))
                return
        self.accept()


def _ranges_text(idx: list[int]) -> str:
    idx = sorted(set(idx))
    parts, start, prev = [], None, None
    for i in idx + [None]:
        if start is None:
            start = prev = i
        elif i is not None and i == prev + 1:
            prev = i
        else:
            parts.append(f"{start + 1}" if start == prev else f"{start + 1}-{prev + 1}")
            start = prev = i
    return ", ".join(parts)
