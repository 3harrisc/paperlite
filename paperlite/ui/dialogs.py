"""Dialogs: compress, signature pad, text entry."""

from __future__ import annotations

import os

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QSettings, Qt, QThread, Signal
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
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from paperlite.core import compress


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
        lay.addWidget(QLabel("<b>Files</b>"))
        self.file_list = QListWidget()
        self.file_list.setMaximumHeight(110)
        lay.addWidget(self.file_list)
        row = QHBoxLayout()
        add_btn = QPushButton("Add files…")
        add_btn.clicked.connect(self._add_files)
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self.file_list.clear)
        row.addWidget(add_btn)
        row.addWidget(clear_btn)
        row.addStretch()
        lay.addLayout(row)

        lay.addWidget(QLabel("<b>Compression level</b>"))
        self.group = QButtonGroup(self)
        current = settings.value("compress/preset", compress.DEFAULT_PRESET)
        for p in compress.PRESETS.values():
            rb = QRadioButton(p.label)
            rb.setProperty("preset", p.key)
            rb.setChecked(p.key == current)
            self.group.addButton(rb)
            lay.addWidget(rb)
            hint = QLabel(f"<span style='color:gray'>{p.description}</span>")
            hint.setContentsMargins(24, 0, 0, 4)
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
        self.close_btn = self.buttons.addButton(QDialogButtonBox.Close)
        self.go_btn.clicked.connect(self._start)
        self.close_btn.clicked.connect(self.reject)
        lay.addWidget(self.buttons)

        for f in files or []:
            self.file_list.addItem(f)

    def _add_files(self):
        start = QSettings().value("lastDir", "")
        paths, _ = QFileDialog.getOpenFileNames(self, "Choose PDFs to compress", start, "PDF files (*.pdf)")
        for p in paths:
            self.file_list.addItem(p)

    def selected_preset(self) -> str:
        return self.group.checkedButton().property("preset")

    def _start(self):
        files = [self.file_list.item(i).text() for i in range(self.file_list.count())]
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
        self.preview = QLabel()
        self.preview.setMinimumHeight(90)
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setStyleSheet("background:white;border:1px solid #ddd")
        self.typed.textChanged.connect(self._update_preview)
        tl.addWidget(self.typed)
        tl.addWidget(self.preview)
        self.tabs.addTab(type_tab, "Type")
        self.tabs.addTab(draw_tab, "Draw")
        lay.addWidget(self.tabs)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
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
