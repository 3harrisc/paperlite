"""Convert dialog: PDF to Word (.docx) or Excel (.xlsx)."""

from __future__ import annotations

import html
import os

from PySide6.QtCore import QSettings, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
)

from paperlite.core import convert
from paperlite.ui import theme
from paperlite.ui.dialogs import _section, dialog_header

FORMATS = [
    (convert.WORD, "Word (.docx)", "Editable text, keeps the layout as closely as possible.", "Word documents (*.docx)"),
    (convert.EXCEL, "Excel (.xlsx)", "Tables from the PDF, one sheet per table.", "Excel workbooks (*.xlsx)"),
]


class ConvertWorker(QThread):
    progress = Signal(int, int, str)  # step, total, message
    finished_one = Signal(object)  # ConvertResult or Exception

    def __init__(self, kind: str, src: str, dst: str, password: str | None):
        super().__init__()
        self.kind, self.src, self.dst, self.password = kind, src, dst, password

    def run(self):
        try:
            r = convert.convert(self.kind, self.src, self.dst, self.password,
                                lambda i, n, msg: self.progress.emit(i, n, msg))
        except Exception as e:  # shown to the user in the dialog
            r = e
        self.finished_one.emit(r)


def error_text(e: Exception) -> str:
    """Plain-English reason. Our own errors already are; anything else isn't."""
    if isinstance(e, (ValueError, PermissionError, OSError)) and str(e):
        return str(e)
    return f"Something went wrong while converting this PDF. ({type(e).__name__}: {e})"


class ConvertDialog(QDialog):
    """Convert one PDF. The result is saved next to it unless the user picks elsewhere."""

    def __init__(self, parent=None, path: str | None = None, kind: str | None = None):
        super().__init__(parent)
        self.setWindowTitle("Convert PDF")
        self.setMinimumWidth(520)
        self.path = path
        self.result = None
        self.password: str | None = None
        self.worker: ConvertWorker | None = None
        kind = kind or QSettings().value("convert/kind", convert.WORD)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(8)
        lay.addLayout(dialog_header("arrow-right-left", "Convert PDF",
                                    "Turn a PDF into a file you can edit in Word or Excel.", theme.ACCENT))
        lay.addSpacing(6)
        lay.addWidget(_section("FILE"))
        row = QHBoxLayout()
        self.file_label = QLabel()
        self.file_label.setObjectName("PanelHint")
        choose = QPushButton("Choose…")
        choose.setIcon(theme.icon("folder-open", theme.TEXT, size=16))
        choose.clicked.connect(self._choose)
        row.addWidget(self.file_label, 1)
        row.addWidget(choose)
        lay.addLayout(row)

        lay.addSpacing(6)
        lay.addWidget(_section("CONVERT TO"))
        self.group = QButtonGroup(self)
        for key, label, description, _ in FORMATS:
            rb = QRadioButton(label)
            rb.setProperty("kind", key)
            rb.setChecked(key == kind)
            rb.setStyleSheet("font-weight:600")
            self.group.addButton(rb)
            lay.addWidget(rb)
            hint = QLabel(description)
            hint.setObjectName("PanelHint")
            hint.setContentsMargins(26, 0, 0, 6)
            lay.addWidget(hint)

        self.progress = QProgressBar()
        self.progress.hide()
        lay.addWidget(self.progress)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.RichText)  # set as escaped HTML
        self.status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.status)

        self.buttons = QDialogButtonBox()
        self.open_btn = self.buttons.addButton("Open", QDialogButtonBox.ActionRole)
        self.open_btn.hide()
        self.go_btn = self.buttons.addButton("Convert", QDialogButtonBox.AcceptRole)
        self.go_btn.setProperty("kind", "primary")
        self.close_btn = self.buttons.addButton(QDialogButtonBox.Close)
        self.open_btn.clicked.connect(self.open_result)
        self.go_btn.clicked.connect(lambda: self._start())
        self.close_btn.clicked.connect(self.reject)
        lay.addWidget(self.buttons)
        self._show_file()

    def selected_kind(self) -> str:
        return self.group.checkedButton().property("kind")

    def _show_file(self):
        self.file_label.setText(os.path.basename(self.path) if self.path else "No PDF chosen yet")
        self.file_label.setToolTip(self.path or "")

    def _choose(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose a PDF to convert", QSettings().value("lastDir", ""),
                                              "PDF files (*.pdf)")
        if path:
            self.path, self.password = path, None
            self._show_file()

    def _start(self, output: str | None = None):
        if not self.path:
            self.status.setText("Choose a PDF first.")
            return
        kind = self.selected_kind()
        QSettings().setValue("convert/kind", kind)
        if output is None:
            filt = next(f for k, *_, f in FORMATS if k == kind)
            output, _ = QFileDialog.getSaveFileName(self, "Save as", convert.output_name(self.path, kind), filt)
            if not output:
                return
            if not output.lower().endswith(convert.EXTENSIONS[kind]):
                output += convert.EXTENSIONS[kind]
        self.result = None
        self.open_btn.hide()
        self.progress.setRange(0, 0)  # busy until the first step is reported
        self.progress.show()
        self.go_btn.setEnabled(False)
        self.status.setText(html.escape(f"Converting {os.path.basename(self.path)}…"))
        self.worker = ConvertWorker(kind, self.path, output, self.password)
        self.worker.progress.connect(self._step)
        self.worker.finished_one.connect(self._done)
        self.worker.start()

    def _step(self, i: int, n: int, message: str):
        self.progress.setRange(0, max(1, n))
        self.progress.setValue(i)
        self.status.setText(html.escape(message))

    def _done(self, r):
        output = self.worker.dst
        self.progress.hide()
        self.go_btn.setEnabled(True)
        if isinstance(r, convert.PasswordError):
            pw, ok = QInputDialog.getText(self, "Convert PDF", f"{r}\nPassword:", QLineEdit.Password)
            self.status.clear()
            if ok:
                self.password = pw
                self._start(output)
            return
        if isinstance(r, Exception):
            self.status.setText(html.escape(f"❌ Couldn't convert {os.path.basename(self.path)}: {error_text(r)}"))
            return
        self.result = r
        lines = [f"✓ {html.escape(convert.summary(r))}"] + [f"• {html.escape(w)}" for w in r.warnings]
        self.status.setText("<br>".join(lines))
        self.open_btn.show()
        self.open_btn.setProperty("kind", "primary")
        self.go_btn.setProperty("kind", None)
        self.go_btn.setText("Convert again")
        for b in (self.open_btn, self.go_btn):  # restyle now that Open is the main action
            b.style().unpolish(b)
            b.style().polish(b)
            b.updateGeometry()

    def open_result(self):
        if self.result:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.result.output_path))

    def reject(self):
        if self.worker and self.worker.isRunning():
            return  # don't close mid-write
        super().reject()
