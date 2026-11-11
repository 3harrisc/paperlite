"""Main window: viewer, thumbnails, Fill & Sign tools, text editing, compression."""

from __future__ import annotations

import os
import shutil
import tempfile

import pymupdf
from PySide6.QtCore import QPoint, QPointF, QRectF, QSettings, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QIcon, QImage, QKeySequence, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from paperlite import __version__
from paperlite.core import compress, forms, textedit
from paperlite.ui.dialogs import CompressDialog, SignatureDialog, TextEntryDialog, saved_signature

APP_NAME = "PaperLite PDF"

MODE_VIEW, MODE_TEXT, MODE_CHECK, MODE_SIGN, MODE_INITIALS, MODE_EDIT = "view", "text", "check", "sign", "initials", "edit"
MODE_HINTS = {
    MODE_VIEW: "Click form fields to fill them in.",
    MODE_TEXT: "Click anywhere on the page to type text.",
    MODE_CHECK: "Click to place a tick ✓.",
    MODE_SIGN: "Click where your signature should go.",
    MODE_INITIALS: "Click where your initials should go.",
    MODE_EDIT: "Click a line of text to change it.",
}


class PageWidget(QWidget):
    def __init__(self, viewer: "PageView", index: int):
        super().__init__()
        self.viewer, self.index = viewer, index
        self._cache: QImage | None = None
        self._cache_key = None
        self.setMouseTracking(True)
        self.resize_to_zoom()

    def page_rect(self):
        return self.viewer.doc[self.index].rect

    def resize_to_zoom(self):
        r = self.page_rect()
        z = self.viewer.zoom
        self.setFixedSize(int(r.width * z), int(r.height * z))

    def invalidate(self):
        self._cache = None
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), Qt.white)
        dpr = self.devicePixelRatioF()
        key = (self.viewer.zoom, dpr, self.viewer.revision)
        if self._cache is None or self._cache_key != key:
            page = self.viewer.doc[self.index]
            pix = page.get_pixmap(matrix=pymupdf.Matrix(self.viewer.zoom * dpr, self.viewer.zoom * dpr), annots=True)
            img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888).copy()
            img.setDevicePixelRatio(dpr)
            self._cache, self._cache_key = img, key
        p.drawImage(0, 0, self._cache)
        if self.viewer.mode == MODE_VIEW:
            # light blue tint over form fields, like most readers do
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(80, 140, 255, 35))
            page = self.viewer.doc[self.index]
            z = self.viewer.zoom
            for w in page.widgets() or []:
                r = w.rect * page.rotation_matrix
                p.drawRect(QRectF(r.x0 * z, r.y0 * z, r.width * z, r.height * z))

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            z = self.viewer.zoom
            self.viewer.pageClicked.emit(self.index, QPointF(e.position().x() / z, e.position().y() / z))

    def mouseMoveEvent(self, e):
        self.setCursor(Qt.ArrowCursor if self.viewer.mode == MODE_VIEW else Qt.CrossCursor)


class PageView(QScrollArea):
    pageChanged = Signal(int)
    pageClicked = Signal(int, QPointF)  # page index, point in page (display) coordinates

    def __init__(self):
        super().__init__()
        self.doc: pymupdf.Document | None = None
        self.zoom = 1.25
        self.mode = MODE_VIEW
        self.revision = 0
        self.pages: list[PageWidget] = []
        self.setWidgetResizable(True)
        self.setAlignment(Qt.AlignHCenter)
        self.setStyleSheet("QScrollArea{background:#525659;border:none}")
        self.verticalScrollBar().valueChanged.connect(self._emit_page)

    def set_document(self, doc):
        self.doc = doc
        self.revision += 1
        container = QWidget()
        container.setStyleSheet("background:#525659")
        lay = QVBoxLayout(container)
        lay.setSpacing(12)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setAlignment(Qt.AlignHCenter)
        self.pages = []
        if doc:
            for i in range(doc.page_count):
                w = PageWidget(self, i)
                self.pages.append(w)
                lay.addWidget(w, alignment=Qt.AlignHCenter)
        self.setWidget(container)

    def refresh(self, index: int | None = None):
        self.revision += 1
        targets = self.pages if index is None else [self.pages[index]]
        for w in targets:
            w.invalidate()

    def set_zoom(self, z: float):
        if not self.doc:
            return
        cur = self.current_page()
        self.zoom = max(0.25, min(5.0, z))
        for w in self.pages:
            w.resize_to_zoom()
        QTimer.singleShot(0, lambda: self.go_to(cur))

    def fit_width(self):
        if self.doc and self.doc.page_count:
            avail = self.viewport().width() - 60
            self.set_zoom(avail / self.doc[0].rect.width)

    def current_page(self) -> int:
        y = self.verticalScrollBar().value() + self.viewport().height() // 3
        for w in self.pages:
            if w.y() + w.height() >= y:
                return w.index
        return max(0, len(self.pages) - 1)

    def go_to(self, i: int):
        if 0 <= i < len(self.pages):
            self.verticalScrollBar().setValue(self.pages[i].y() - 10)

    def _emit_page(self):
        if self.pages:
            self.pageChanged.emit(self.current_page())

    def wheelEvent(self, e):
        if e.modifiers() & Qt.ControlModifier:
            self.set_zoom(self.zoom * (1.1 if e.angleDelta().y() > 0 else 1 / 1.1))
        else:
            super().wheelEvent(e)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.doc: pymupdf.Document | None = None
        self.path: str | None = None
        self.dirty = False
        self.undo_ok = False
        self.setAcceptDrops(True)
        self.resize(1200, 850)

        self.view = PageView()
        self.view.pageChanged.connect(self._on_page_changed)
        self.view.pageClicked.connect(self.on_page_click)
        self.thumbs = QListWidget()
        self.thumbs.setViewMode(QListWidget.IconMode)
        self.thumbs.setFlow(QListWidget.TopToBottom)
        self.thumbs.setWrapping(False)
        self.thumbs.setIconSize(QSize(120, 160))
        self.thumbs.setFixedWidth(170)
        self.thumbs.setSpacing(6)
        self.thumbs.setStyleSheet("QListWidget{background:#e9e9e9;border:none}")
        self.thumbs.currentRowChanged.connect(self.view.go_to)
        split = QSplitter()
        split.addWidget(self.thumbs)
        split.addWidget(self.view)
        split.setStretchFactor(1, 1)
        self.setCentralWidget(split)

        self.hint = QLabel()
        self.statusBar().addWidget(self.hint, 1)
        self.size_label = QLabel()
        self.statusBar().addPermanentWidget(self.size_label)

        self._build_actions()
        self.set_mode(MODE_VIEW)
        self._update_title()

    # ------------------------------------------------------------------ UI setup

    def _act(self, text, slot, shortcut=None, tip=None, checkable=False):
        a = QAction(text, self)
        if shortcut:
            a.setShortcut(shortcut)
        if tip:
            a.setToolTip(tip)
        a.setCheckable(checkable)
        a.triggered.connect(slot)
        return a

    def _build_actions(self):
        self.a_open = self._act("Open", self.open_dialog, QKeySequence.Open)
        self.a_save = self._act("Save", self.save, QKeySequence.Save)
        self.a_save_as = self._act("Save As…", self.save_as, QKeySequence.SaveAs)
        self.a_compress = self._act("Compress PDF", self.compress_current, "Ctrl+Shift+C", "Reduce the file size of this PDF")
        self.a_compress_many = self._act("Compress Files…", self.compress_files, tip="Compress several PDFs at once")
        self.a_print = self._act("Print", self.print_doc, QKeySequence.Print)
        self.a_undo = self._act("Undo", self.undo, QKeySequence.Undo)
        self.a_redo = self._act("Redo", self.redo, QKeySequence.Redo)
        self.a_zoom_in = self._act("Zoom In", lambda: self.view.set_zoom(self.view.zoom * 1.2), QKeySequence.ZoomIn)
        self.a_zoom_out = self._act("Zoom Out", lambda: self.view.set_zoom(self.view.zoom / 1.2), QKeySequence.ZoomOut)
        self.a_fit = self._act("Fit Width", self.view.fit_width, "Ctrl+0")
        self.a_rotate = self._act("Rotate Page", self.rotate_page, "Ctrl+R")
        self.a_delete_page = self._act("Delete Page", self.delete_page)
        self.a_about = self._act("About", self.about)

        self.mode_group = QActionGroup(self)
        self.mode_actions = {}
        for mode, label in [
            (MODE_VIEW, "Select"),
            (MODE_TEXT, "Add Text"),
            (MODE_CHECK, "✓ Tick"),
            (MODE_SIGN, "Sign"),
            (MODE_INITIALS, "Initials"),
            (MODE_EDIT, "Edit Text"),
        ]:
            a = self._act(label, lambda _=False, m=mode: self.set_mode(m), checkable=True, tip=MODE_HINTS[mode])
            self.mode_group.addAction(a)
            self.mode_actions[mode] = a

        m = self.menuBar().addMenu("&File")
        for a in (self.a_open, self.a_save, self.a_save_as, None, self.a_compress, self.a_compress_many, None, self.a_print):
            m.addSeparator() if a is None else m.addAction(a)
        m.addSeparator()
        m.addAction(self._act("Exit", self.close, QKeySequence.Quit))
        m = self.menuBar().addMenu("&Edit")
        for a in (self.a_undo, self.a_redo, None, self.a_rotate, self.a_delete_page):
            m.addSeparator() if a is None else m.addAction(a)
        m = self.menuBar().addMenu("&View")
        for a in (self.a_zoom_in, self.a_zoom_out, self.a_fit):
            m.addAction(a)
        m = self.menuBar().addMenu("Fill && &Sign")
        for mode in (MODE_VIEW, MODE_TEXT, MODE_CHECK, MODE_SIGN, MODE_INITIALS, MODE_EDIT):
            m.addAction(self.mode_actions[mode])
        m.addSeparator()
        m.addAction(self._act("Change signature…", lambda: self._new_signature("signature")))
        m.addAction(self._act("Change initials…", lambda: self._new_signature("initials")))
        self.menuBar().addMenu("&Help").addAction(self.a_about)

        tb = QToolBar("Main")
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.addToolBar(tb)
        tb.addAction(self.a_open)
        tb.addAction(self.a_save)
        tb.addAction(self.a_print)
        tb.addSeparator()
        tb.addAction(self.a_compress)
        tb.widgetForAction(self.a_compress).setStyleSheet("font-weight:bold;color:#b30b00")
        tb.addSeparator()
        for mode in (MODE_VIEW, MODE_TEXT, MODE_CHECK, MODE_SIGN, MODE_INITIALS, MODE_EDIT):
            tb.addAction(self.mode_actions[mode])
        tb.addSeparator()
        tb.addAction(self.a_undo)
        tb.addSeparator()
        tb.addAction(self.a_zoom_out)
        tb.addAction(self.a_zoom_in)
        tb.addAction(self.a_fit)
        tb.addSeparator()
        self.page_spin = QSpinBox()
        self.page_spin.setMinimum(1)
        self.page_spin.setPrefix("Page ")
        self.page_spin.valueChanged.connect(lambda v: self.view.go_to(v - 1))
        tb.addWidget(self.page_spin)
        self.page_total = QLabel()
        tb.addWidget(self.page_total)
        self._update_enabled()

    def _update_enabled(self):
        has = self.doc is not None
        for a in (self.a_save, self.a_save_as, self.a_compress, self.a_print, self.a_zoom_in, self.a_zoom_out,
                  self.a_fit, self.a_rotate, self.a_delete_page, *self.mode_actions.values()):
            a.setEnabled(has)
        self.a_undo.setEnabled(has and self.undo_ok and self.doc.journal_can_do()["undo"])
        self.a_redo.setEnabled(has and self.undo_ok and self.doc.journal_can_do()["redo"])
        self.page_spin.setEnabled(has)

    def set_mode(self, mode):
        self.view.mode = mode
        self.mode_actions[mode].setChecked(True)
        self.hint.setText(MODE_HINTS[mode])
        self.view.refresh()

    def _update_title(self):
        name = os.path.basename(self.path) if self.path else ""
        self.setWindowTitle(f"{'*' if self.dirty else ''}{name}{' - ' if name else ''}{APP_NAME}")
        if self.path and os.path.exists(self.path):
            self.size_label.setText(f"File size: {compress.human_size(os.path.getsize(self.path))}")
        else:
            self.size_label.setText("")

    # ------------------------------------------------------------------ open / save

    def open_dialog(self):
        if not self._maybe_save():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Open PDF", QSettings().value("lastDir", ""), "PDF files (*.pdf)")
        if path:
            self.open_file(path)

    def open_file(self, path: str):
        try:
            doc = pymupdf.open(path)
        except Exception as e:
            QMessageBox.critical(self, APP_NAME, f"Couldn't open this file:\n{e}")
            return
        if doc.needs_pass:
            from PySide6.QtWidgets import QInputDialog, QLineEdit

            pw, ok = QInputDialog.getText(self, APP_NAME, "This PDF is password protected. Password:", QLineEdit.Password)
            if not ok or not doc.authenticate(pw):
                QMessageBox.warning(self, APP_NAME, "Wrong password.")
                return
        if self.doc:
            self.doc.close()
        self.doc, self.path, self.dirty = doc, path, False
        try:
            doc.journal_enable()
            self.undo_ok = True
        except Exception:
            self.undo_ok = False
        QSettings().setValue("lastDir", os.path.dirname(path))
        self._load_view()

    def _load_view(self, keep_page: int = 0):
        self.view.set_document(self.doc)
        self.page_spin.setMaximum(max(1, self.doc.page_count))
        self.page_total.setText(f" of {self.doc.page_count}")
        self._build_thumbs()
        self._update_enabled()
        self._update_title()
        QTimer.singleShot(0, lambda: (self.view.fit_width() if keep_page == 0 else None, self.view.go_to(keep_page)))

    def _build_thumbs(self):
        self.thumbs.blockSignals(True)
        self.thumbs.clear()
        for i in range(self.doc.page_count):
            item = QListWidgetItem(str(i + 1))
            item.setTextAlignment(Qt.AlignHCenter)
            self.thumbs.addItem(item)
        self.thumbs.blockSignals(False)
        self._thumb_next = 0
        QTimer.singleShot(0, self._render_some_thumbs)

    def _render_some_thumbs(self):
        # render a few at a time so big scans don't freeze the window
        if not self.doc:
            return
        end = min(self._thumb_next + 4, self.doc.page_count)
        for i in range(self._thumb_next, end):
            self._render_thumb(i)
        self._thumb_next = end
        if end < self.doc.page_count:
            QTimer.singleShot(10, self._render_some_thumbs)

    def _render_thumb(self, i):
        if i >= self.thumbs.count():
            return
        page = self.doc[i]
        z = 160 / max(page.rect.height, 1)
        pix = page.get_pixmap(matrix=pymupdf.Matrix(z, z))
        img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888).copy()
        self.thumbs.item(i).setIcon(QIcon(QPixmap.fromImage(img)))

    def _write(self, target: str):
        """Save to ``target``; handles saving over the file that's open."""
        same = self.path and os.path.abspath(target) == os.path.abspath(self.path)
        if same and self.doc.can_save_incrementally():
            self.doc.save(target, incremental=True, encryption=pymupdf.PDF_ENCRYPT_KEEP)
            return
        fd, tmp = tempfile.mkstemp(suffix=".pdf", dir=os.path.dirname(os.path.abspath(target)))
        os.close(fd)
        self.doc.save(tmp, garbage=3, deflate=True)
        if same:
            page = self.view.current_page()
            self.doc.close()
            os.replace(tmp, target)
            self.doc = pymupdf.open(target)
            try:
                self.doc.journal_enable()
            except Exception:
                self.undo_ok = False
            self._load_view(page)
        else:
            shutil.move(tmp, target)

    def save(self):
        if not self.doc:
            return False
        try:
            self._write(self.path)
        except Exception as e:
            QMessageBox.critical(self, APP_NAME, f"Couldn't save:\n{e}\n\nTry File → Save As.")
            return False
        self.dirty = False
        self._update_title()
        return True

    def save_as(self):
        if not self.doc:
            return False
        path, _ = QFileDialog.getSaveFileName(self, "Save As", self.path or "", "PDF files (*.pdf)")
        if not path:
            return False
        try:
            self._write(path)
        except Exception as e:
            QMessageBox.critical(self, APP_NAME, f"Couldn't save:\n{e}")
            return False
        if os.path.abspath(path) != os.path.abspath(self.path or ""):
            self.open_file(path)
        self.dirty = False
        self._update_title()
        return True

    def _maybe_save(self) -> bool:
        if not self.dirty:
            return True
        r = QMessageBox.question(self, APP_NAME, "Save changes to this PDF?",
                                 QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if r == QMessageBox.Save:
            return self.save()
        return r == QMessageBox.Discard

    def closeEvent(self, e):
        if self._maybe_save():
            e.accept()
        else:
            e.ignore()

    def dragEnterEvent(self, e):
        if any(u.toLocalFile().lower().endswith(".pdf") for u in e.mimeData().urls()):
            e.acceptProposedAction()

    def dropEvent(self, e):
        pdfs = [u.toLocalFile() for u in e.mimeData().urls() if u.toLocalFile().lower().endswith(".pdf")]
        if len(pdfs) > 1:
            CompressDialog(self, pdfs).exec()
        elif pdfs and self._maybe_save():
            self.open_file(pdfs[0])

    # ------------------------------------------------------------------ compress

    def compress_current(self):
        if not self.doc:
            return
        if self.dirty:
            r = QMessageBox.question(self, APP_NAME, "Save your changes before compressing?",
                                     QMessageBox.Save | QMessageBox.Cancel)
            if r != QMessageBox.Save or not self.save():
                return
        dlg = CompressDialog(self, [self.path])
        dlg.exec()
        done = [r for r in dlg.results if not isinstance(r, Exception) and not r.kept_original]
        if done and os.path.abspath(done[-1].output_path) != os.path.abspath(self.path):
            if QMessageBox.question(self, APP_NAME, "Open the compressed file?") == QMessageBox.Yes:
                self.open_file(done[-1].output_path)
        elif done:  # replaced the original in place: reload it
            self.open_file(self.path)

    def compress_files(self):
        CompressDialog(self).exec()

    # ------------------------------------------------------------------ editing

    def _begin(self, name):
        if self.undo_ok:
            self.doc.journal_start_op(name)

    def _end(self, index):
        if self.undo_ok:
            self.doc.journal_stop_op()
        self.dirty = True
        self.view.refresh(index)
        self._render_thumb(index)
        self._update_title()
        self._update_enabled()

    def _on_page_changed(self, i):
        self.page_spin.blockSignals(True)
        self.page_spin.setValue(i + 1)
        self.page_spin.blockSignals(False)
        self.thumbs.blockSignals(True)
        self.thumbs.setCurrentRow(i)
        self.thumbs.blockSignals(False)

    def on_page_click(self, index: int, pt: QPointF):
        page = self.doc[index]
        shown = pymupdf.Point(pt.x(), pt.y())  # point as displayed (rotation applied)
        raw = shown * page.derotation_matrix  # point in the page's own coordinates
        mode = self.view.mode
        try:
            if mode == MODE_VIEW:
                self._click_form(index, page, raw)
            elif mode == MODE_TEXT:
                dlg = TextEntryDialog(self, "Add text", size=QSettings().value("fill/fontsize", 11, type=int))
                if dlg.exec():
                    text, size = dlg.value()
                    if text:
                        QSettings().setValue("fill/fontsize", size)
                        self._begin("Add text")
                        forms.add_text(page, raw, text, size)
                        self._end(index)
            elif mode == MODE_CHECK:
                self._begin("Tick")
                forms.add_checkmark(page, raw)
                self._end(index)
            elif mode in (MODE_SIGN, MODE_INITIALS):
                kind = "signature" if mode == MODE_SIGN else "initials"
                png = saved_signature(kind) or self._new_signature(kind)
                if png:
                    w, h = (180, 50) if kind == "signature" else (70, 35)
                    rect = pymupdf.Rect(raw.x, raw.y - h / 2, raw.x + w, raw.y + h / 2)
                    self._begin("Sign")
                    forms.add_signature(page, rect, png)
                    self._end(index)
            elif mode == MODE_EDIT:
                span = textedit.span_at(page, shown)
                if not span:
                    self.hint.setText("No editable text there. Scanned pages are pictures, so use Add Text instead.")
                    return
                dlg = TextEntryDialog(self, "Edit text", span.text)
                if dlg.exec():
                    new, _ = dlg.value()
                    if new != span.text:
                        self._begin("Edit text")
                        textedit.replace_span(page, span, new)
                        self._end(index)
        except Exception as e:
            if self.undo_ok:
                try:
                    self.doc.journal_stop_op()
                except Exception:
                    pass
            QMessageBox.warning(self, APP_NAME, f"That didn't work:\n{e}")

    def _click_form(self, index, page, raw):
        w = forms.widget_at(page, raw)
        if not w:
            return
        if w.field_type in forms.TOGGLE_TYPES:
            self._begin("Fill form")
            forms.toggle_widget(w)
            self._end(index)
        elif w.field_type in forms.TEXT_TYPES:
            dlg = TextEntryDialog(self, w.field_label or w.field_name or "Fill in", str(w.field_value or ""))
            if dlg.exec():
                self._begin("Fill form")
                forms.set_widget_value(w, dlg.value()[0])
                self._end(index)

    def _new_signature(self, kind):
        dlg = SignatureDialog(self, kind)
        if dlg.exec():
            return dlg.png
        return None

    def rotate_page(self):
        i = self.view.current_page()
        self._begin("Rotate")
        self.doc[i].set_rotation((self.doc[i].rotation + 90) % 360)
        self._end(i)
        self.view.pages[i].resize_to_zoom()

    def delete_page(self):
        if self.doc.page_count <= 1:
            return
        i = self.view.current_page()
        if QMessageBox.question(self, APP_NAME, f"Delete page {i + 1}?") != QMessageBox.Yes:
            return
        self._begin("Delete page")
        self.doc.delete_page(i)
        if self.undo_ok:
            self.doc.journal_stop_op()
        self.dirty = True
        self._load_view(min(i, self.doc.page_count - 1))

    def _journal_step(self, undo: bool):
        if not (self.doc and self.undo_ok):
            return
        can = self.doc.journal_can_do()
        if not can["undo" if undo else "redo"]:
            return
        count = self.doc.page_count
        self.doc.journal_undo() if undo else self.doc.journal_redo()
        self.dirty = True
        if self.doc.page_count != count:
            self._load_view(self.view.current_page())
        else:
            for w in self.view.pages:
                w.resize_to_zoom()
            self.view.refresh()
            for i in range(self.doc.page_count):
                self._render_thumb(i)
        self._update_title()
        self._update_enabled()

    def undo(self):
        self._journal_step(True)

    def redo(self):
        self._journal_step(False)

    # ------------------------------------------------------------------ misc

    def print_doc(self):
        from PySide6.QtPrintSupport import QPrintDialog, QPrinter

        printer = QPrinter(QPrinter.HighResolution)
        printer.setFromTo(1, self.doc.page_count)
        dlg = QPrintDialog(printer, self)
        if not dlg.exec():
            return
        first = max(1, printer.fromPage() or 1)
        last = min(self.doc.page_count, printer.toPage() or self.doc.page_count)
        painter = QPainter(printer)
        for n in range(first - 1, last):
            if n > first - 1:
                printer.newPage()
            page = self.doc[n]
            target = painter.viewport()
            zoom = min(target.width() / page.rect.width, target.height() / page.rect.height)
            zoom = min(zoom, 300 / 72)  # cap at 300 dpi
            pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
            img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888)
            scaled = img.scaled(target.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            painter.drawImage(QPoint(0, 0), scaled)
        painter.end()

    def about(self):
        QMessageBox.about(self, APP_NAME, f"<b>{APP_NAME}</b> {__version__}<br>View, compress, fill and sign PDFs.<br>"
                                          f"PDF engine: PyMuPDF {pymupdf.VersionBind}")
