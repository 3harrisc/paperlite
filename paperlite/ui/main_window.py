"""Main window: app bar, tool rail, side panels, viewer, organise view, updates."""

from __future__ import annotations

import os
import shutil
import tempfile
import time

import pymupdf
from PySide6.QtCore import QDate, QLocale, QPoint, QSettings, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QCursor, QDesktopServices, QIcon, QImage, QKeySequence, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from paperlite import UPDATE_REPO, __version__
from paperlite.core import compress, forms, pages, scanedit, textedit, updater
from paperlite.core.history import History
from paperlite.ui import theme
from paperlite.ui.convert_dialog import ConvertDialog
from paperlite.ui.dialogs import CombineDialog, CompressDialog, PagesDialog, SignatureDialog, saved_signature
from paperlite.ui.panels import EditPanel, FillSignPanel, OrganiseView, ThumbsPanel, WelcomePage, thumb_card
from paperlite.ui.viewer import PageView
from paperlite.ui.widgets import RailButton, Spinner, Toast, button, label, tool_button

APP_NAME = "PaperLite PDF"
FILL_TOOLS = {"view", "text", "tick", "cross", "date", "sign", "initials"}
EDIT_TOOLS = {"edit", "text", "area", "erase"}


def _hex(rgb) -> str:
    return "#%02x%02x%02x" % tuple(int(max(0, min(1, c)) * 255) for c in rgb)


class UpdateChecker(QThread):
    found = Signal(object)  # updater.Update or None
    failed = Signal(str)

    def run(self):
        try:
            self.found.emit(updater.check(UPDATE_REPO, __version__))
        except Exception as e:
            self.failed.emit(str(e))


class UpdateDownloader(QThread):
    progress = Signal(int, int)
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, update):
        super().__init__()
        self.update_info = update

    def run(self):
        try:
            self.done.emit(updater.download(self.update_info, lambda d, t: self.progress.emit(d, t)))
        except Exception as e:
            self.failed.emit(str(e))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.doc: pymupdf.Document | None = None
        self.path: str | None = None
        self.dirty = False
        self.history = History()
        self.section = "home"
        self.tool = "view"
        self.ocr_cache: dict[int, list[scanedit.OcrWord]] = {}
        self.span_cache: dict[int, list[textedit.TextSpan]] = {}
        self.clip = None  # (png, w, h, src_index, src_rect, is_move)
        self.pending_update = None
        self.setAcceptDrops(True)
        self.setMinimumSize(980, 640)
        self.resize(1320, 880)

        root = QWidget()
        rl = QVBoxLayout(root)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)
        rl.addWidget(self._build_app_bar())
        self.banner = self._build_update_banner()
        rl.addWidget(self.banner)
        body = QHBoxLayout()
        body.setSpacing(0)
        body.addWidget(self._build_rail())

        self.panel_stack = QStackedWidget()
        self.thumbs_panel = ThumbsPanel()
        self.fill_panel = FillSignPanel()
        self.edit_panel = EditPanel()
        for p in (self.thumbs_panel, self.fill_panel, self.edit_panel):
            self.panel_stack.addWidget(p)
        body.addWidget(self.panel_stack)

        self.main_stack = QStackedWidget()
        self.welcome = WelcomePage()
        self.view = PageView()
        self.organise = OrganiseView()
        for w in (self.welcome, self.view, self.organise):
            self.main_stack.addWidget(w)
        body.addWidget(self.main_stack, 1)
        rl.addLayout(body, 1)
        self.setCentralWidget(root)
        self.toast = Toast(self)

        self._wire()
        self._shortcuts()
        self.welcome.set_recent(self._recent())
        self._set_section("home")
        self._update_chrome()
        QTimer.singleShot(1500, self.check_updates_quietly)

    # ================================================================== layout

    def _build_app_bar(self):
        bar = QWidget()
        bar.setObjectName("AppBar")
        bar.setAttribute(Qt.WA_StyledBackground)
        bar.setFixedHeight(52)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(12, 0, 12, 0)
        lay.setSpacing(4)

        self.menu_btn = QToolButton()
        self.menu_btn.setIcon(QIcon(theme.logo_pixmap(26)))
        self.menu_btn.setIconSize(QSize(26, 26))
        self.menu_btn.setText("  PaperLite")
        self.menu_btn.setObjectName("AppTitle")
        self.menu_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.menu_btn.setPopupMode(QToolButton.InstantPopup)
        self.menu_btn.setCursor(Qt.PointingHandCursor)
        self.menu_btn.setStyleSheet("font-weight:600;font-size:10.5pt;padding:4px 8px;")
        lay.addWidget(self.menu_btn)

        sep = QWidget()
        sep.setFixedSize(1, 24)
        sep.setStyleSheet(f"background:{theme.BORDER}")
        lay.addSpacing(8)
        lay.addWidget(sep)
        lay.addSpacing(12)

        self.doc_icon = QLabel()
        self.doc_icon.setPixmap(theme.pixmap("file-text", theme.TEXT_MUTED, 18))
        self.doc_title = label("", "DocTitle")
        self.doc_size = label("", "Chip")
        self.doc_state = label("", "DocMeta")
        self.doc_size.setFixedHeight(22)
        self.doc_size.setAlignment(Qt.AlignCenter)
        for w in (self.doc_icon, self.doc_title, self.doc_size, self.doc_state):
            lay.addWidget(w)
        lay.addSpacing(4)
        lay.addStretch()

        self.b_open = tool_button("folder-open", "Open (Ctrl+O)")
        self.b_save = tool_button("save", "Save (Ctrl+S)")
        self.b_print = tool_button("printer", "Print (Ctrl+P)")
        self.b_undo = tool_button("undo-2", "Undo (Ctrl+Z)")
        self.b_redo = tool_button("redo-2", "Redo (Ctrl+Y)")
        for b in (self.b_open, self.b_save, self.b_print):
            lay.addWidget(b)
        sep2 = QWidget()
        sep2.setFixedSize(1, 22)
        sep2.setStyleSheet(f"background:{theme.BORDER}")
        lay.addSpacing(4)
        lay.addWidget(sep2)
        lay.addSpacing(4)
        lay.addWidget(self.b_undo)
        lay.addWidget(self.b_redo)
        lay.addSpacing(10)
        self.b_compress = button("Compress", "primary", "minimize-2")
        self.b_compress.setToolTip("Make this PDF smaller (Ctrl+Shift+C)")
        lay.addWidget(self.b_compress)
        return bar

    def _build_update_banner(self):
        b = QWidget()
        b.setObjectName("UpdateBanner")
        b.setAttribute(Qt.WA_StyledBackground)
        lay = QHBoxLayout(b)
        lay.setContentsMargins(16, 7, 12, 7)
        ic = QLabel()
        ic.setPixmap(theme.pixmap("download", theme.ACCENT, 18))
        self.banner_text = QLabel()
        self.banner_progress = QProgressBar()
        self.banner_progress.setFixedWidth(160)
        self.banner_progress.hide()
        self.banner_notes = button("What's new", "ghost")
        self.banner_install = button("Install update", "accent")
        self.banner_later = button("Later", "ghost")
        lay.addWidget(ic)
        lay.addWidget(self.banner_text)
        lay.addStretch()
        for w in (self.banner_progress, self.banner_notes, self.banner_install, self.banner_later):
            lay.addWidget(w)
        b.hide()
        return b

    def _build_rail(self):
        rail = QWidget()
        rail.setObjectName("ToolRail")
        rail.setAttribute(Qt.WA_StyledBackground)
        rail.setFixedWidth(80)
        lay = QVBoxLayout(rail)
        lay.setContentsMargins(6, 10, 6, 10)
        lay.setSpacing(4)
        self.rail_group = QButtonGroup(self)
        self.rail = {}
        for key, ic, text, tip in [
            ("home", "file-stack", "Home", "Start page and recent files"),
            ("view", "file-text", "View", "Read the document"),
            ("fill", "signature", "Fill && Sign", "Fill in forms and sign"),
            ("edit", "scan-text", "Edit", "Edit text, also on scans and handwriting"),
            ("organise", "layout-grid", "Organise", "Reorder, rotate, delete, extract and split pages"),
        ]:
            b = RailButton(ic, text, tip)
            self.rail_group.addButton(b)
            self.rail[key] = b
            lay.addWidget(b, alignment=Qt.AlignHCenter)
        sep = QWidget()
        sep.setFixedSize(40, 1)
        sep.setStyleSheet(f"background:{theme.BORDER}")
        lay.addSpacing(6)
        lay.addWidget(sep, alignment=Qt.AlignHCenter)
        lay.addSpacing(6)
        self.rail_compress = RailButton("minimize-2", "Compress", "Make PDFs smaller")
        self.rail_compress.setCheckable(False)
        self.rail_convert = RailButton("arrow-right-left", "Convert", "Turn a PDF into a Word or Excel file")
        self.rail_convert.setCheckable(False)
        self.rail_combine = RailButton("combine", "Combine", "Join files into one PDF")
        self.rail_combine.setCheckable(False)
        lay.addWidget(self.rail_compress, alignment=Qt.AlignHCenter)
        lay.addWidget(self.rail_convert, alignment=Qt.AlignHCenter)
        lay.addWidget(self.rail_combine, alignment=Qt.AlignHCenter)
        lay.addStretch()
        return rail

    def _wire(self):
        m = QMenu(self)
        m.addAction(theme.icon("folder-open", size=16), "Open…", self.open_dialog, QKeySequence.Open)
        self.recent_menu = m.addMenu(theme.icon("clock", size=16), "Open recent")
        self.recent_menu.aboutToShow.connect(self._fill_recent_menu)
        m.addSeparator()
        self.m_save = m.addAction(theme.icon("save", size=16), "Save", self.save)
        self.m_save_as = m.addAction("Save as…", self.save_as)
        self.m_print = m.addAction(theme.icon("printer", size=16), "Print…", self.print_doc)
        m.addSeparator()
        m.addAction(theme.icon("minimize-2", size=16), "Compress files…", lambda: CompressDialog(self).exec())
        m.addAction(theme.icon("arrow-right-left", size=16), "Convert to Word…", lambda: self.convert_current("word"))
        m.addAction("Convert to Excel…", lambda: self.convert_current("excel"))
        m.addAction(theme.icon("combine", size=16), "Combine files…", self.combine_files)
        m.addSeparator()
        m.addAction(theme.icon("download", size=16), "Check for updates…", self.check_updates_manually)
        m.addAction(theme.icon("info", size=16), f"About {APP_NAME}", self.about)
        m.addSeparator()
        m.addAction("Exit", self.close)
        self.menu_btn.setMenu(m)

        self.b_open.clicked.connect(self.open_dialog)
        self.b_save.clicked.connect(self.save)
        self.b_print.clicked.connect(self.print_doc)
        self.b_undo.clicked.connect(self.undo)
        self.b_redo.clicked.connect(self.redo)
        self.b_compress.clicked.connect(self.compress_current)
        self.rail_compress.clicked.connect(self.compress_current)
        self.rail_convert.clicked.connect(lambda: self.convert_current())
        self.rail_combine.clicked.connect(self.combine_files)
        for key, b in self.rail.items():
            b.clicked.connect(lambda _=False, k=key: self._set_section(k))

        self.welcome.openClicked.connect(self.open_dialog)
        self.welcome.recentChosen.connect(lambda p: self._maybe_save() and self.open_file(p))
        self.welcome.toolChosen.connect(self._welcome_tool)

        self.view.pageClicked.connect(self.on_page_click)
        self.view.areaSelected.connect(self.on_area)
        self.view.pageChanged.connect(self._page_changed)
        self.view.hover_provider = self._hover

        self.thumbs_panel.grid.currentRowChanged.connect(lambda r: r >= 0 and self.view.go_to(r))
        self.thumbs_panel.grid.orderChanged.connect(self.reorder)
        self.thumbs_panel.grid.setContextMenuPolicy(Qt.CustomContextMenu)
        self.thumbs_panel.grid.customContextMenuRequested.connect(self._thumb_menu)
        self.organise.grid.orderChanged.connect(self.reorder)
        self.organise.grid.itemDoubleClicked.connect(lambda it: (self._set_section("view"), self.view.go_to(self.organise.grid.row(it))))
        self.organise.action.connect(self.organise_action)

        self.fill_panel.toolChosen.connect(self.set_tool)
        self.edit_panel.toolChosen.connect(self.set_tool)
        self.fill_panel.sig.changeClicked.connect(lambda: self._new_signature("signature"))
        self.fill_panel.ini.changeClicked.connect(lambda: self._new_signature("initials"))
        self.fill_panel.sig.set_png(saved_signature("signature"))
        self.fill_panel.ini.set_png(saved_signature("initials"))

        self.banner_later.clicked.connect(self.banner.hide)
        self.banner_install.clicked.connect(self.install_update)
        self.banner_notes.clicked.connect(lambda: self.pending_update and QDesktopServices.openUrl(self.pending_update.page_url))

    def _shortcuts(self):
        def sc(keys, fn):
            a = QAction(self)
            a.setShortcuts(keys if isinstance(keys, list) else [keys])
            a.triggered.connect(fn)
            self.addAction(a)

        sc(QKeySequence.Open, self.open_dialog)
        sc(QKeySequence.Save, self.save)
        sc(QKeySequence.SaveAs, self.save_as)
        sc(QKeySequence.Print, self.print_doc)
        sc(QKeySequence.Undo, self.undo)
        sc([QKeySequence.Redo, QKeySequence("Ctrl+Y")], self.redo)
        sc([QKeySequence.ZoomIn, QKeySequence("Ctrl+=")], lambda: self.view.set_zoom(self.view.zoom * 1.2))
        sc(QKeySequence.ZoomOut, lambda: self.view.set_zoom(self.view.zoom / 1.2))
        sc(QKeySequence("Ctrl+0"), self.view.fit_width)
        sc(QKeySequence("Ctrl+Shift+C"), self.compress_current)
        sc(QKeySequence(Qt.Key_Escape), self._escape)

    # ================================================================== sections & tools

    def _set_section(self, key: str):
        if key != "home" and not self.doc:
            self.open_dialog()
            if not self.doc:
                self.rail[self.section].setChecked(True)
                return
        self.section = key
        self.rail[key].setChecked(True)
        if key == "home":
            self.welcome.set_recent(self._recent())
            self.main_stack.setCurrentWidget(self.welcome)
            self.panel_stack.hide()
        elif key == "organise":
            self.main_stack.setCurrentWidget(self.organise)
            self.panel_stack.hide()
            self.organise.grid.setFocus()
            self.organise._sel()
        else:
            self.main_stack.setCurrentWidget(self.view)
            self.panel_stack.show()
            panel = {"view": self.thumbs_panel, "fill": self.fill_panel, "edit": self.edit_panel}[key]
            self.panel_stack.setCurrentWidget(panel)
            self.panel_stack.setFixedWidth(panel.width())
            default = {"view": "view", "fill": "view", "edit": "edit"}[key]
            self.set_tool(self.tool if (key == "fill" and self.tool in FILL_TOOLS) or (key == "edit" and self.tool in EDIT_TOOLS) else default)

    def _welcome_tool(self, key: str):
        if key == "compress":
            self.compress_current()
        elif key == "combine":
            self.combine_files()
        else:
            self._set_section(key)

    def set_tool(self, tool: str):
        self.tool = tool
        self.view.set_tool(tool)
        self.fill_panel.select(tool if tool in FILL_TOOLS else None)
        self.edit_panel.select(tool if tool in EDIT_TOOLS else None)
        tips = {
            "view": "Click a blue form field to type in it, or tick a box.",
            "text": "Click on the page where the text should start, type, then press Enter.",
            "tick": "Click to place a tick.",
            "cross": "Click to place a cross.",
            "date": "Click to place today's date.",
            "sign": "Click where your signature should go.",
            "initials": "Click where your initials should go.",
            "edit": "Hover over text and click to change it. On scanned pages the text is read automatically first.",
            "area": "Drag a box around handwriting, a stamp, a number… then choose Replace, Erase, Move or Copy.",
            "erase": "Drag over anything you want gone. It's filled with the paper colour.",
            "place": "Click where it should go. Press Esc to cancel.",
        }
        tip = tips.get(tool, "")
        self.fill_panel.tip.setText(tip)
        self.edit_panel.tip.setText(tip)
        if tool == "edit":
            QTimer.singleShot(50, self._prepare_ocr_for_visible)

    def _escape(self):
        if self.tool == "place":
            self.clip = None
            self.view.place_size = None
            self.set_tool("area")
        elif self.section in ("fill", "edit") and self.tool not in ("view", "edit"):
            self.set_tool("view" if self.section == "fill" else "edit")

    # ================================================================== chrome

    def _update_chrome(self):
        has = self.doc is not None
        name = os.path.basename(self.path) if self.path else ""
        self.setWindowTitle(f"{'• ' if self.dirty else ''}{name}{' — ' if name else ''}{APP_NAME}")
        self.doc_icon.setVisible(has)
        self.doc_title.setText(name)
        if has and self.path and os.path.exists(self.path):
            n = self.doc.page_count
            self.doc_size.setText(f"{compress.human_size(os.path.getsize(self.path))} · {n} page{'s' if n != 1 else ''}")
            self.doc_size.show()
        else:
            self.doc_size.hide()
        self.doc_state.setText("Edited" if self.dirty else "")
        self.doc_state.setStyleSheet(f"color:{theme.BRAND};font-weight:600" if self.dirty else "")
        for w in (self.b_save, self.b_print, self.m_save, self.m_save_as, self.m_print):
            w.setEnabled(has)
        self.b_undo.setEnabled(has and self.history.can_undo())
        self.b_redo.setEnabled(has and self.history.can_redo())
        self.b_undo.setToolTip(f"Undo {self.history.undo_label()} (Ctrl+Z)" if self.history.can_undo() else "Undo (Ctrl+Z)")
        self.b_redo.setToolTip(f"Redo {self.history.redo_label()} (Ctrl+Y)" if self.history.can_redo() else "Redo (Ctrl+Y)")

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.toast.isVisible():
            self.toast._place()

    def notify(self, text: str, kind: str = "info", ms: int = 3200):
        self.toast.show_message(text, kind, ms)

    # ================================================================== open / save

    def _recent(self) -> list[str]:
        items = QSettings().value("recent", []) or []
        if isinstance(items, str):
            items = [items]
        return [p for p in items if os.path.exists(p)][:8]

    def _add_recent(self, path: str):
        items = [p for p in self._recent() if os.path.abspath(p) != os.path.abspath(path)]
        QSettings().setValue("recent", [path] + items[:9])

    def _fill_recent_menu(self):
        self.recent_menu.clear()
        for p in self._recent():
            self.recent_menu.addAction(os.path.basename(p), lambda p=p: self._maybe_save() and self.open_file(p))
        if self.recent_menu.isEmpty():
            self.recent_menu.addAction("No recent files").setEnabled(False)

    def open_dialog(self):
        if not self._maybe_save():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Open PDF", QSettings().value("lastDir", ""), "PDF files (*.pdf)")
        if path:
            self.open_file(path)

    def open_file(self, path: str) -> bool:
        try:
            doc = pymupdf.open(path)
        except Exception as e:
            QMessageBox.critical(self, APP_NAME, f"Couldn't open this file.\n\n{e}")
            return False
        if doc.needs_pass:
            pw, ok = QInputDialog.getText(self, APP_NAME, "This PDF is password protected.\nPassword:", QLineEdit.Password)
            if not ok or not doc.authenticate(pw):
                if ok:
                    QMessageBox.warning(self, APP_NAME, "That password isn't right.")
                return False
        if self.doc:
            self.doc.close()
        self.doc, self.path, self.dirty = doc, path, False
        self.history.clear()
        QSettings().setValue("lastDir", os.path.dirname(path))
        self._add_recent(path)
        self._reload(0, fit=True)
        if self.section in ("home",):
            self._set_section("view")
        else:
            self._set_section(self.section)
        return True

    def _reload(self, keep_page: int = 0, fit: bool = False):
        """Rebuild every view of the document (after open, undo, page changes)."""
        self.ocr_cache.clear()
        self.span_cache.clear()
        self.view.set_document(self.doc, keep_page)
        self._build_thumbs()
        self._update_chrome()
        if fit:
            QTimer.singleShot(0, self.view.fit_width)

    def _build_thumbs(self):
        for grid in (self.thumbs_panel.grid, self.organise.grid):
            grid.blockSignals(True)
            grid.clear()
            for i in range(self.doc.page_count):
                it = QListWidgetItem()
                it.setData(Qt.UserRole, i)
                it.setSizeHint(QSize(160, 196) if grid is self.thumbs_panel.grid else QSize(186, 266))
                grid.addItem(it)
            grid.blockSignals(False)
        self._thumb_next = 0
        self._thumb_gen = getattr(self, "_thumb_gen", 0) + 1
        gen = self._thumb_gen
        QTimer.singleShot(0, lambda: self._render_thumbs(gen))
        self.organise._sel()

    def _render_thumbs(self, gen):
        if gen != self._thumb_gen or not self.doc:
            return
        end = min(self._thumb_next + 3, self.doc.page_count)
        for i in range(self._thumb_next, end):
            self._render_thumb(i)
        self._thumb_next = end
        if end < self.doc.page_count:
            QTimer.singleShot(5, lambda: self._render_thumbs(gen))

    def _render_thumb(self, i):
        if not self.doc or i >= self.thumbs_panel.grid.count():
            return
        page = self.doc[i]
        for grid, size in ((self.thumbs_panel.grid, (150, 170)), (self.organise.grid, (170, 242))):
            pm = thumb_card(page, i + 1, *size)
            ic = QIcon(pm)
            ic.addPixmap(pm, QIcon.Selected)
            grid.item(i).setIcon(ic)

    def _write(self, target: str):
        same = self.path and os.path.abspath(target) == os.path.abspath(self.path)
        if same and self.doc.name and os.path.abspath(self.doc.name) == os.path.abspath(target) \
                and self.doc.can_save_incrementally():
            self.doc.save(target, incremental=True, encryption=pymupdf.PDF_ENCRYPT_KEEP)
            return
        fd, tmp = tempfile.mkstemp(suffix=".pdf", dir=os.path.dirname(os.path.abspath(target)))
        os.close(fd)
        try:
            self.doc.save(tmp, garbage=3, deflate=True)
        except Exception:
            os.remove(tmp)
            raise
        if same:
            page = self.view.current_page()
            self.doc.close()
            os.replace(tmp, target)
            self.doc = pymupdf.open(target)
            self._reload(page)
        else:
            shutil.move(tmp, target)

    def save(self) -> bool:
        if not self.doc:
            return False
        try:
            self._write(self.path)
        except Exception as e:
            QMessageBox.critical(self, APP_NAME, f"Couldn't save.\n\n{e}\n\nTry Save as… instead.")
            return False
        self.dirty = False
        self._update_chrome()
        self.notify("Saved", "success", 1800)
        return True

    def save_as(self) -> bool:
        if not self.doc:
            return False
        path, _ = QFileDialog.getSaveFileName(self, "Save as", self.path or "", "PDF files (*.pdf)")
        if not path:
            return False
        try:
            self._write(path)
        except Exception as e:
            QMessageBox.critical(self, APP_NAME, f"Couldn't save.\n\n{e}")
            return False
        if os.path.abspath(path) != os.path.abspath(self.path or ""):
            self.dirty = False
            self.open_file(path)
        self.dirty = False
        self._update_chrome()
        self.notify("Saved", "success", 1800)
        return True

    def _maybe_save(self) -> bool:
        if not self.dirty:
            return True
        box = QMessageBox(self)
        box.setWindowTitle(APP_NAME)
        box.setText(f"<b>Save changes to {os.path.basename(self.path)}?</b>")
        box.setInformativeText("Your changes will be lost if you don't save them.")
        box.setStandardButtons(QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        box.button(QMessageBox.Save).setProperty("kind", "primary")
        box.button(QMessageBox.Discard).setText("Don't save")
        r = box.exec()
        if r == QMessageBox.Save:
            return self.save()
        return r == QMessageBox.Discard

    def closeEvent(self, e):
        if self._maybe_save():
            for t in (getattr(self, "_checker", None), getattr(self, "_dl", None)):
                if t is not None and t.isRunning():
                    t.wait(3000)
            self.history.close()
            e.accept()
        else:
            e.ignore()

    def dragEnterEvent(self, e):
        if any(u.toLocalFile().lower().endswith(".pdf") for u in e.mimeData().urls()):
            e.acceptProposedAction()
            self.welcome.drop.set_hover(True)

    def dragLeaveEvent(self, e):
        self.welcome.drop.set_hover(False)

    def dropEvent(self, e):
        self.welcome.drop.set_hover(False)
        pdfs = [u.toLocalFile() for u in e.mimeData().urls() if u.toLocalFile().lower().endswith(".pdf")]
        if len(pdfs) > 1:
            self.combine_files(pdfs)
        elif pdfs and self._maybe_save():
            self.open_file(pdfs[0])

    # ================================================================== change tracking

    def change(self, label_: str, fn, index: int | None = None, structural: bool = False) -> bool:
        """Run an edit with an undo checkpoint and refresh what it touched."""
        self.history.checkpoint(self.doc, label_)
        try:
            fn()
        except Exception as e:
            self.history.drop_last()
            QMessageBox.warning(self, APP_NAME, f"That didn't work.\n\n{e}")
            return False
        self.dirty = True
        if structural or index is None:
            self._reload(min(self.view.current_page(), self.doc.page_count - 1))
        else:
            self.span_cache.pop(index, None)
            self.view.refresh(index)
            self._render_thumb(index)
        self._update_chrome()
        return True

    def undo(self):
        self._step(True)

    def redo(self):
        self._step(False)

    def _step(self, back: bool):
        if not self.doc or not (self.history.can_undo() if back else self.history.can_redo()):
            return
        label_ = self.history.undo_label() if back else self.history.redo_label()
        page = self.view.current_page()
        self.doc = self.history.undo(self.doc) if back else self.history.redo(self.doc)
        self.dirty = True
        self._reload(min(page, self.doc.page_count - 1))
        self.notify(f"{'Undid' if back else 'Redid'} {label_.lower()}", ms=1600)

    # ================================================================== hover & clicks

    def _spans(self, index):
        if index not in self.span_cache:
            self.span_cache[index] = textedit.all_spans(self.doc[index])
        return self.span_cache[index]

    def _hover(self, index: int, pt: pymupdf.Point):
        page = self.doc[index]
        if self.tool in FILL_TOOLS:
            w = forms.widget_at(page, pt)
            return w.rect if w else None
        if self.tool == "edit":
            s = textedit.span_at(page, pt, self._spans(index))
            if s:
                return s.rect
            w = scanedit.word_at(self.ocr_cache.get(index, []), pt)
            return w.rect if w else None
        return None

    def _ocr(self, index: int) -> list[scanedit.OcrWord]:
        if index not in self.ocr_cache:
            self.edit_panel.status.setText(f"Reading the text on page {index + 1}…")
            self.notify(f"Reading the scanned text on page {index + 1}…", "busy", 0)
            QApplication.setOverrideCursor(Qt.WaitCursor)
            QApplication.processEvents()
            try:
                self.ocr_cache[index] = scanedit.ocr_words(self.doc[index])
            except Exception as e:
                self.ocr_cache[index] = []
                self.notify(f"Couldn't read the text: {e}")
            finally:
                QApplication.restoreOverrideCursor()
            n = len(self.ocr_cache[index])
            self.edit_panel.status.setText(f"Page {index + 1} is a scan — {n} words recognised. Click one to change it.")
            self.notify(f"Page {index + 1}: {n} words recognised", "success", 2000)
        return self.ocr_cache[index]

    def _prepare_ocr_for_visible(self):
        if self.doc and self.tool == "edit" and self.section == "edit":
            i = self.view.current_page()
            if scanedit.is_scanned(self.doc[i]):
                self._ocr(i)
            else:
                self.edit_panel.status.setText("")

    def _page_changed(self, i):
        g = self.thumbs_panel.grid
        g.blockSignals(True)
        g.setCurrentRow(i)
        g.blockSignals(False)
        if self.tool == "edit" and i not in self.ocr_cache:
            QTimer.singleShot(400, lambda: self.view.current_page() == i and self._prepare_ocr_for_visible())

    def _font_choice(self) -> str | None:
        v = self.edit_panel.font.currentData()
        return None if v == "auto" else v

    def on_page_click(self, index: int, pt: pymupdf.Point):
        page = self.doc[index]
        tool = self.tool
        if tool in FILL_TOOLS:
            w = forms.widget_at(page, pt)
            if w is not None:
                return self._click_form(index, w)
        if tool == "view":
            return
        if tool == "text":
            size = QSettings().value("fill/fontsize", 11, type=float)
            rect = pymupdf.Rect(pt.x, pt.y, pt.x + 160, pt.y + size * 1.25)
            self.view.open_editor(index, rect, "", size,
                                  lambda t: t.strip() and self.change("Add text", lambda: forms.add_text(page, pt, t, size), index))
        elif tool in ("tick", "cross"):
            fn = forms.add_checkmark if tool == "tick" else forms.add_cross
            self.change("Tick" if tool == "tick" else "Cross", lambda: fn(page, pt), index)
        elif tool == "date":
            today = QLocale.system().toString(QDate.currentDate(), QLocale.ShortFormat)
            size = QSettings().value("fill/fontsize", 11, type=float)
            self.change("Add date", lambda: forms.add_text(page, pymupdf.Point(pt.x, pt.y - size * 0.6), today, size), index)
        elif tool in ("sign", "initials"):
            kind = "signature" if tool == "sign" else "initials"
            png = saved_signature(kind) or self._new_signature(kind)
            if png:
                img = QImage.fromData(png)
                w = 150 if kind == "signature" else 60
                h = min(w * img.height() / max(1, img.width()), 60 if kind == "signature" else 34)
                w = h * img.width() / max(1, img.height())
                rect = pymupdf.Rect(pt.x - w / 2, pt.y - h / 2, pt.x + w / 2, pt.y + h / 2)
                self.change("Sign" if kind == "signature" else "Initial", lambda: forms.add_signature(page, rect, png), index)
        elif tool == "edit":
            self._click_edit(index, page, pt)
        elif tool == "place" and self.clip:
            self._place_clip(index, pt)

    def _click_form(self, index, w):
        page = self.doc[index]
        if w.field_type in forms.TOGGLE_TYPES:
            self.change("Fill form", lambda: forms.toggle_widget(forms.widget_at(page, w.rect.tl + (1, 1))), index)
        elif w.field_type in forms.TEXT_TYPES:
            size = w.text_fontsize or max(8.0, w.rect.height * 0.62)
            rect = pymupdf.Rect(w.rect)

            def commit(t, rect=rect):
                widget = forms.widget_at(page, rect.tl + (1, 1))
                if widget is not None and t != str(widget.field_value or ""):
                    self.change("Fill form", lambda: forms.set_widget_value(widget, t), index)

            self.view.open_editor(index, rect, str(w.field_value or ""), size, commit)

    def _click_edit(self, index, page, pt):
        span = textedit.span_at(page, pt, self._spans(index))
        if span:
            def commit(t, span=span):
                if t != span.text:
                    self.change("Edit text", lambda: textedit.replace_span(page, span, t, self._font_choice()), index)
            self.view.open_editor(index, span.rect, span.text, span.size, commit,
                                  textedit.screen_family(span), _hex(span.color))
            return
        words = self._ocr(index) if scanedit.is_scanned(page) or index in self.ocr_cache else []
        word = scanedit.word_at(words, pt)
        if word is None:
            self.notify("No text found there. For handwriting, use Select area." if words or scanedit.is_scanned(page)
                        else "No text there. Use Add text to write something new.")
            return
        size, base = scanedit.line_metrics(page, words, word)
        _, ink = scanedit.sample_colors(page, word.rect)

        def commit_scan(t, word=word):
            if t == word.text:
                return
            font = self._font_choice() or "helv"
            if self.change("Edit text", lambda: scanedit.replace_text(page, word.rect, t, font, size, base), index):
                self.ocr_cache[index] = [w for w in self.ocr_cache.get(index, []) if w is not word]

        self.view.open_editor(index, word.rect, word.text, size, commit_scan, "Arial", _hex(ink))

    # ================================================================== area tools

    def on_area(self, index: int, rect: pymupdf.Rect, gpos: QPoint):
        page = self.doc[index]
        if self.tool == "erase":
            self.change("Erase", lambda: scanedit.erase_area(page, rect), index)
            self._forget_ocr(index, rect)
            return
        m = QMenu(self)
        a_rep = m.addAction(theme.icon("type", size=16), "Replace with text…")
        a_era = m.addAction(theme.icon("eraser", size=16), "Erase")
        m.addSeparator()
        a_mov = m.addAction(theme.icon("move", size=16), "Move")
        a_cop = m.addAction(theme.icon("copy", size=16), "Copy")
        chosen = m.exec(gpos)
        if chosen is a_era:
            self.change("Erase", lambda: scanedit.erase_area(page, rect), index)
            self._forget_ocr(index, rect)
        elif chosen is a_rep:
            words = [w for w in self.ocr_cache.get(index, []) if w.rect.intersects(rect)]
            if words:
                size, base = scanedit.line_metrics(page, self.ocr_cache[index], words[0])
            else:
                size, base = rect.height * 0.72, None
            _, ink = scanedit.sample_colors(page, rect)

            def commit(t):
                if t.strip():
                    font = self._font_choice() or "helv"
                    self.change("Replace", lambda: scanedit.replace_text(page, rect, t, font, size, base), index)
                    self._forget_ocr(index, rect)

            self.view.open_editor(index, rect, " ".join(w.text for w in words), size, commit, "Arial", _hex(ink))
        elif chosen in (a_mov, a_cop):
            png = scanedit.grab_area(page, rect)
            self.clip = (png, rect.width, rect.height, index, pymupdf.Rect(rect), chosen is a_mov)
            self.view.place_size = (rect.width, rect.height)
            self.set_tool("place")
            self.notify("Now click where it should go (Esc to cancel)", ms=2600)

    def _forget_ocr(self, index, rect):
        if index in self.ocr_cache:
            self.ocr_cache[index] = [w for w in self.ocr_cache[index] if not w.rect.intersects(rect)]

    def _place_clip(self, index, pt):
        png, w, h, src_i, src_rect, is_move = self.clip
        dst = pymupdf.Rect(pt.x, pt.y, pt.x + w, pt.y + h)

        def do():
            if is_move:
                scanedit.erase_area(self.doc[src_i], src_rect)
            scanedit.place_area(self.doc[index], png, dst)

        same = src_i == index
        if self.change("Move" if is_move else "Copy", do, index if same else None):
            if is_move:
                self._forget_ocr(src_i, src_rect)
        self.clip = None
        self.view.place_size = None
        self.set_tool("area")

    def _new_signature(self, kind):
        dlg = SignatureDialog(self, kind)
        if dlg.exec():
            (self.fill_panel.sig if kind == "signature" else self.fill_panel.ini).set_png(dlg.png)
            return dlg.png
        return None

    # ================================================================== pages

    def _selected_pages(self) -> list[int]:
        grid = self.organise.grid if self.section == "organise" else self.thumbs_panel.grid
        rows = grid.selected_rows()
        return rows or [self.view.current_page()]

    def reorder(self, order: list[int]):
        self.change("Reorder pages", lambda: pages.reorder(self.doc, order), structural=True)

    def organise_action(self, key: str):
        if key == "done":
            self._set_section("view")
            return
        sel = self._selected_pages()
        base = os.path.splitext(os.path.basename(self.path or "Document"))[0]
        if key in ("rotate_left", "rotate_right"):
            deg = 270 if key == "rotate_left" else 90
            if self.change("Rotate", lambda: pages.rotate(self.doc, sel, deg), structural=True):
                self._reselect(sel)
        elif key == "delete":
            if len(sel) >= self.doc.page_count:
                self.notify("A PDF needs at least one page.")
                return
            if self.change(f"Delete {len(sel)} page{'s' if len(sel) > 1 else ''}", lambda: pages.delete(self.doc, sel), structural=True):
                self.notify(f"Deleted {len(sel)} page{'s' if len(sel) > 1 else ''}", "success")
        elif key == "insert_blank":
            at = max(sel) + 1
            self.change("Insert blank page", lambda: pages.insert_blank(self.doc, at), structural=True)
        elif key == "insert_file":
            path, _ = QFileDialog.getOpenFileName(self, "Insert pages from", QSettings().value("lastDir", ""),
                                                  "PDFs and images (*.pdf *.png *.jpg *.jpeg *.tif *.tiff)")
            if path:
                at = max(sel) + 1
                added = []
                if self.change("Insert pages", lambda: added.append(pages.insert_file(self.doc, path, at)), structural=True):
                    self.notify(f"Inserted {added[0]} page{'s' if added[0] != 1 else ''}", "success")
        elif key in ("extract", "export_images", "split"):
            explicit = (self.organise.grid if self.section == "organise" else self.thumbs_panel.grid).selected_rows()
            dlg = PagesDialog(self, key, self.doc.page_count, explicit)
            if not dlg.exec():
                return
            try:
                if key == "extract":
                    out, _ = QFileDialog.getSaveFileName(self, "Save extracted pages",
                                                         os.path.join(os.path.dirname(self.path), f"{base} (extract).pdf"), "PDF files (*.pdf)")
                    if out:
                        pages.extract(self.doc, dlg.indexes(), out)
                        self._done_files([out])
                else:
                    folder = QFileDialog.getExistingDirectory(self, "Choose a folder", os.path.dirname(self.path))
                    if folder:
                        if key == "split":
                            files = pages.split(self.doc, dlg.every.value(), folder, base)
                        else:
                            files = pages.export_images(self.doc, dlg.indexes(), folder, base, dlg.fmt.currentData(), dlg.dpi.currentData())
                        self._done_files(files)
            except Exception as e:
                QMessageBox.warning(self, APP_NAME, f"That didn't work.\n\n{e}")

    def _done_files(self, files: list[str]):
        n = len(files)
        self.notify(f"Saved {n} file{'s' if n != 1 else ''} to {os.path.basename(os.path.dirname(files[0])) or files[0]}", "success", 4000)

    def _reselect(self, rows):
        g = self.organise.grid if self.section == "organise" else self.thumbs_panel.grid
        for r in rows:
            if r < g.count():
                g.item(r).setSelected(True)

    def _thumb_menu(self, pos):
        if not self.doc:
            return
        m = QMenu(self)
        for key, ic, text in [("rotate_left", "rotate-ccw", "Rotate left"), ("rotate_right", "rotate-cw", "Rotate right"),
                              (None, None, None), ("insert_file", "file-plus", "Insert pages from file…"),
                              ("insert_blank", "file-plus-2", "Insert blank page after"), (None, None, None),
                              ("extract", "file-output", "Extract…"), ("export_images", "image-down", "Export as images…"),
                              (None, None, None), ("delete", "trash-2", "Delete")]:
            if key is None:
                m.addSeparator()
            else:
                m.addAction(theme.icon(ic, size=16), text, lambda k=key: self.organise_action(k))
        m.exec(self.thumbs_panel.grid.mapToGlobal(pos))

    # ================================================================== compress / combine

    def compress_current(self):
        if not self.doc:
            CompressDialog(self).exec()
            return
        if self.dirty:
            r = QMessageBox.question(self, APP_NAME, "Save your changes before compressing?",
                                     QMessageBox.Save | QMessageBox.Cancel)
            if r != QMessageBox.Save or not self.save():
                return
        dlg = CompressDialog(self, [self.path])
        dlg.exec()
        done = [r for r in dlg.results if not isinstance(r, Exception) and not r.kept_original]
        if not done:
            return
        r = done[-1]
        if os.path.abspath(r.output_path) == os.path.abspath(self.path):
            self.open_file(self.path)
        else:
            box = QMessageBox(self)
            box.setWindowTitle(APP_NAME)
            box.setText(f"<b>{compress.human_size(r.original_bytes)} → {compress.human_size(r.compressed_bytes)}</b>")
            box.setInformativeText(f"Saved as {os.path.basename(r.output_path)}. Open the compressed copy?")
            box.setStandardButtons(QMessageBox.Open | QMessageBox.Close)
            box.button(QMessageBox.Open).setProperty("kind", "primary")
            if box.exec() == QMessageBox.Open:
                self.open_file(r.output_path)

    def convert_current(self, kind: str | None = None):
        """Convert the open PDF (as saved on disk) to Word or Excel; ask for one if none is open."""
        path = self.path
        if not self.doc:
            path, _ = QFileDialog.getOpenFileName(self, "Choose a PDF to convert", QSettings().value("lastDir", ""),
                                                  "PDF files (*.pdf)")
            if not path:
                return
        elif self.dirty:
            r = QMessageBox.question(self, APP_NAME, "Save your changes before converting?",
                                     QMessageBox.Save | QMessageBox.Cancel)
            if r != QMessageBox.Save or not self.save():
                return
        ConvertDialog(self, path, kind).exec()

    def combine_files(self, files=None):
        start = files if isinstance(files, list) else ([self.path] if self.path else [])
        dlg = CombineDialog(self, start)
        if dlg.exec() and dlg.output:
            self.notify(f"Combined into {os.path.basename(dlg.output)}", "success")
            if self._maybe_save():
                self.open_file(dlg.output)

    # ================================================================== updates

    def check_updates_quietly(self):
        if not UPDATE_REPO or os.environ.get("PAPERLITE_NO_UPDATE_CHECK"):
            return
        s = QSettings()
        if time.time() - s.value("update/last", 0, type=float) < 24 * 3600:
            return
        s.setValue("update/last", time.time())
        self._run_check(quiet=True)

    def check_updates_manually(self):
        if not UPDATE_REPO:
            self.notify("Update checks aren't set up in this build.")
            return
        self.notify("Checking for updates…", "busy", 0)
        self._run_check(quiet=False)

    def _run_check(self, quiet: bool):
        self._checker = UpdateChecker()
        self._checker.found.connect(lambda u: self._update_found(u, quiet))
        self._checker.failed.connect(lambda e: None if quiet else self.notify("Couldn't check for updates. Are you online?"))
        self._checker.start()

    def _update_found(self, u, quiet):
        if u is None:
            if not quiet:
                self.notify(f"You're up to date ({__version__})", "success")
            return
        self.toast.hide()
        self.pending_update = u
        self.banner_text.setText(f"<b>PaperLite {u.version}</b> is available. You have {__version__}.")
        self.banner_install.setEnabled(True)
        self.banner.show()

    def install_update(self):
        if not self.pending_update or not self._maybe_save():
            return
        self.banner_install.setEnabled(False)
        self.banner_progress.show()
        self.banner_text.setText(f"Downloading PaperLite {self.pending_update.version}…")
        self._dl = UpdateDownloader(self.pending_update)
        self._dl.progress.connect(lambda d, t: (self.banner_progress.setMaximum(t or 0), self.banner_progress.setValue(d)))
        self._dl.failed.connect(lambda e: (self.banner_text.setText(f"Download failed: {e}"), self.banner_install.setEnabled(True)))
        self._dl.done.connect(self._run_installer)
        self._dl.start()

    def _run_installer(self, path):
        try:
            updater.launch_installer(path)
        except Exception as e:
            self.banner_text.setText(str(e))
            return
        self.dirty = False
        self.history.close()
        QApplication.quit()

    # ================================================================== misc

    def print_doc(self):
        if not self.doc:
            return
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
            zoom = min(target.width() / page.rect.width, target.height() / page.rect.height, 300 / 72)
            pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
            img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888)
            painter.drawImage(QPoint(0, 0), img.scaled(target.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        painter.end()

    def about(self):
        QMessageBox.about(self, APP_NAME,
                          f"<h3>{APP_NAME}</h3><p>Version {__version__}</p>"
                          "<p>View, compress, fill, sign, edit and organise PDFs.</p>"
                          f"<p style='color:{theme.TEXT_MUTED}'>PDF engine: PyMuPDF {pymupdf.VersionBind} (AGPL). "
                          "Icons: Lucide (ISC).</p>")
