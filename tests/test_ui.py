"""Headless smoke test of the main window: open, fill, sign, edit, undo, save, compress."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pymupdf
import pytest
from PySide6.QtCore import QPointF, QSettings
from PySide6.QtWidgets import QApplication

from paperlite.ui import dialogs, main_window
from paperlite.ui.main_window import MainWindow


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    a.setOrganizationName("PaperLiteTest")
    a.setApplicationName("PaperLiteTest")
    QSettings().clear()
    return a


@pytest.fixture
def form_pdf(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 300), "Amount due: 100", fontsize=12)
    w = pymupdf.Widget()
    w.field_name, w.field_type, w.rect = "name", pymupdf.PDF_WIDGET_TYPE_TEXT, pymupdf.Rect(72, 72, 300, 92)
    page.add_widget(w)
    path = str(tmp_path / "form.pdf")
    doc.save(path)
    return path


class FakeDialog:
    """Stands in for a modal text dialog and returns a fixed answer."""

    answer = ("", None)

    def __init__(self, *a, **k):
        pass

    def exec(self):
        return True

    def value(self):
        return FakeDialog.answer


def test_window_workflow(app, form_pdf, tmp_path, monkeypatch):
    monkeypatch.setattr(main_window, "TextEntryDialog", FakeDialog)
    win = MainWindow()
    win.show()
    win.open_file(form_pdf)
    app.processEvents()
    assert win.doc.page_count == 1 and len(win.view.pages) == 1
    win.view.pages[0].grab()  # forces a render

    # fill a form field by clicking it
    FakeDialog.answer = ("Jane Doe", None)
    win.view.pageClicked.emit(0, QPointF(100, 80))
    assert win.doc[0].first_widget.field_value == "Jane Doe"

    # add free text
    win.set_mode(main_window.MODE_TEXT)
    FakeDialog.answer = ("Hello there", 11)
    win.view.pageClicked.emit(0, QPointF(72, 400))
    assert "Hello there" in win.doc[0].get_text()

    # tick + signature (pre-saved typed signature)
    QSettings().setValue("sign/signature", dialogs.image_to_png(dialogs.typed_signature("Jane")))
    win.set_mode(main_window.MODE_CHECK)
    win.view.pageClicked.emit(0, QPointF(80, 500))
    win.set_mode(main_window.MODE_SIGN)
    win.view.pageClicked.emit(0, QPointF(72, 600))
    assert win.doc[0].get_images()

    # edit existing text, then undo it
    win.set_mode(main_window.MODE_EDIT)
    FakeDialog.answer = ("Amount due: 250", None)
    win.view.pageClicked.emit(0, QPointF(90, 296))
    assert "250" in win.doc[0].get_text()
    if win.undo_ok:
        win.undo()
        assert "Amount due: 100" in win.doc[0].get_text()
        win.redo()
        assert "250" in win.doc[0].get_text()

    # save over the open file
    assert win.dirty
    assert win.save()
    assert not win.dirty
    re = pymupdf.open(form_pdf)
    assert "Hello there" in re[0].get_text() and "250" in re[0].get_text()
    assert re[0].first_widget.field_value == "Jane Doe"
    win.dirty = False
    win.close()


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
