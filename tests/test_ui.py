"""Headless tests of the main window: open, fill, sign, edit (normal + scanned), organise, undo, save."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pymupdf
import pytest
from PySide6.QtCore import QPoint, QPointF, QSettings
from PySide6.QtWidgets import QApplication

from paperlite.ui import dialogs, theme
from paperlite.ui.main_window import MainWindow
from paperlite.ui.widgets import InlineEditor


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    a.setOrganizationName("PaperLiteTest")
    a.setApplicationName("PaperLiteTest")
    a.setStyleSheet(theme.stylesheet())
    QSettings().clear()
    return a


@pytest.fixture
def win(app):
    w = MainWindow()
    w.resize(1300, 900)
    w.show()
    yield w
    w.dirty = False
    w.close()


def type_into_editor(app, win, text):
    app.processEvents()
    eds = [e for e in win.view.findChildren(InlineEditor) if e.isVisible()]
    assert eds, "no inline editor opened"
    ed = eds[-1]
    ed.setText(text)
    ed.returnPressed.emit()
    app.processEvents()


@pytest.fixture
def form_pdf(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 300), "Amount due: 100", fontsize=12)
    w = pymupdf.Widget()
    w.field_name, w.field_type, w.rect = "name", pymupdf.PDF_WIDGET_TYPE_TEXT, pymupdf.Rect(72, 72, 300, 92)
    page.add_widget(w)
    doc.new_page().insert_text((72, 72), "Second page")
    path = str(tmp_path / "form.pdf")
    doc.save(path)
    return path


def test_fill_sign_edit_undo_save(app, win, form_pdf):
    assert win.open_file(form_pdf)
    assert win.section == "view" and len(win.view.pages) == 2
    win.view.pages[0].grab()

    win._set_section("fill")
    win.set_tool("view")
    win.view.pageClicked.emit(0, pymupdf.Point(100, 80))
    type_into_editor(app, win, "Jane Doe")
    assert win.doc[0].first_widget.field_value == "Jane Doe"

    win.set_tool("text")
    win.view.pageClicked.emit(0, pymupdf.Point(72, 400))
    type_into_editor(app, win, "Hello there")
    assert "Hello there" in win.doc[0].get_text()

    QSettings().setValue("sign/signature", dialogs.image_to_png(dialogs.typed_signature("Jane")))
    for tool, pt in (("tick", (80, 500)), ("cross", (100, 500)), ("date", (72, 540)), ("sign", (150, 620))):
        win.set_tool(tool)
        win.view.pageClicked.emit(0, pymupdf.Point(*pt))
    assert win.doc[0].get_images()

    win._set_section("edit")
    win.set_tool("edit")
    win.view.pageClicked.emit(0, pymupdf.Point(90, 296))
    type_into_editor(app, win, "Amount due: 250")
    assert "250" in win.doc[0].get_text()

    win.undo()
    assert "Amount due: 100" in win.doc[0].get_text()
    win.redo()
    assert "250" in win.doc[0].get_text()

    assert win.dirty and win.save() and not win.dirty
    re = pymupdf.open(form_pdf)
    assert "Hello there" in re[0].get_text() and "250" in re[0].get_text()
    assert re[0].first_widget.field_value == "Jane Doe"


def test_edit_scanned_page(app, win, tmp_path):
    from test_pages_scan import scanned_page

    doc, _ = scanned_page(tmp_path)
    path = str(tmp_path / "scan.pdf")
    doc.save(path)
    win.open_file(path)
    win._set_section("edit")
    win.set_tool("edit")
    words = win._ocr(0)
    target = next(w for w in words if w.text == "1234")
    assert win._hover(0, target.rect.tl + (2, 2)) == target.rect
    win.view.pageClicked.emit(0, target.rect.tl + (2, 2))
    type_into_editor(app, win, "5678")
    assert "5678" in win.doc[0].get_text()

    # erase the handwriting, then undo
    win.set_tool("erase")
    win.view.areaSelected.emit(0, pymupdf.Rect(75, 175, 165, 215), QPoint(0, 0))
    assert win.history.undo_label() == "Erase"
    win.undo()
    assert win.history.redo_label() == "Erase"


def test_organise_pages(app, win, tmp_path):
    d = pymupdf.open()
    for i in range(4):
        d.new_page().insert_text((72, 72), f"P{i + 1}")
    path = str(tmp_path / "four.pdf")
    d.save(path)
    extra = pymupdf.open()
    extra.new_page().insert_text((72, 72), "X1")
    extra_path = str(tmp_path / "extra.pdf")
    extra.save(extra_path)

    win.open_file(path)
    win._set_section("organise")
    labels = lambda: [p.get_text().strip() for p in win.doc]
    win.reorder([3, 2, 1, 0])
    assert labels() == ["P4", "P3", "P2", "P1"]
    assert win.organise.grid.count() == 4

    win.organise.grid.item(0).setSelected(True)
    win.organise_action("rotate_right")
    assert win.doc[0].rotation == 90

    win.organise.grid.clearSelection()
    win.organise.grid.item(1).setSelected(True)
    win.organise_action("delete")
    assert labels() == ["P4", "P2", "P1"]

    win.organise.grid.clearSelection()
    win.organise.grid.item(0).setSelected(True)
    win.organise_action("insert_blank")
    assert labels() == ["P4", "", "P2", "P1"]

    from paperlite.core import pages
    win.change("Insert pages", lambda: pages.insert_file(win.doc, extra_path, 0), structural=True)
    assert labels()[0] == "X1" and win.organise.grid.count() == 5

    for _ in range(5):
        win.undo()
    assert labels() == ["P1", "P2", "P3", "P4"]


def test_welcome_and_dialogs_render(app, win, tmp_path):
    assert win.section == "home"
    win.grab()
    dlg = dialogs.CombineDialog(win, [])
    assert not dlg.go.isEnabled()
    dlg.grab()
    dialogs.PagesDialog(win, "export_images", 10, [1, 2]).grab()
    dialogs.SignatureDialog(win).grab()


def test_signature_pad_draw(app):
    pad = dialogs.SignaturePad()
    pad.resize(460, 160)
    pad.strokes = [[QPointF(20, 80), QPointF(100, 40), QPointF(200, 100)]]
    img = pad.to_image()
    assert img is not None and img.width() > 50
    assert dialogs.image_to_png(img).startswith(b"\x89PNG")


def test_compress_dialog_runs(app, tmp_path):
    from test_core import make_scanned_pdf

    src = str(tmp_path / "scan.pdf")
    make_scanned_pdf(src, pages=1)
    dlg = dialogs.CompressDialog(None, [src])
    dlg._start()
    dlg.worker.wait(120_000)
    app.processEvents()
    assert len(dlg.results) == 1
    assert os.path.exists(dialogs.compressed_name(src))
    assert "smaller" in dlg.status.text()
