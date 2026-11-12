import os

import docx
import openpyxl
import pymupdf
import pytest

from paperlite.core import convert
from paperlite.core.scanedit import tessdata_dir

HAS_TESSDATA = os.path.exists(os.path.join(tessdata_dir(), "eng.traineddata"))
needs_ocr = pytest.mark.skipif(not HAS_TESSDATA, reason="Tesseract language data (assets/tessdata) not available")

TABLE = [
    ["Code", "Item", "Price", "Qty", "VAT"],
    ["00123", "Kettle", "£1,234.50", "2", "20%"],
    ["AMM11280899", "Toaster", "$12", "10", "5.5%"],
]


def add_text_page(doc):
    p = doc.new_page()
    p.insert_text((72, 72), "Quarterly report", fontsize=18)
    p.insert_text((72, 100), "Sales went up this quarter thanks to the new kettles.", fontsize=11)
    return p


def draw_table(page, rows, top=140, xs=(72, 160, 300, 400, 460, 530)):
    y = top
    for r in rows:
        for i, c in enumerate(r):
            page.insert_text((xs[i] + 3, y + 14), c, fontsize=10)
        y += 20
    for yy in range(top, y + 1, 20):
        page.draw_line((xs[0], yy), (xs[len(rows[0])], yy))
    for xx in xs[: len(rows[0]) + 1]:
        page.draw_line((xx, top), (xx, y))


def add_scan_page(doc, text="Delivery receipt signed today"):
    """An image-only page, like a scanner makes, rendered from real text."""
    src = pymupdf.open()
    sp = src.new_page()
    sp.insert_text((72, 120), text, fontsize=24)
    page = doc.new_page()
    page.insert_image(page.rect, pixmap=sp.get_pixmap(dpi=200))
    return page


def save(doc, path, **kw):
    doc.save(str(path), **kw)
    return str(path)


@pytest.fixture
def table_pdf(tmp_path):
    doc = pymupdf.open()
    draw_table(doc.new_page(), TABLE)
    return save(doc, tmp_path / "Table.pdf")


# ------------------------------------------------------------------ rules


@pytest.mark.parametrize("text, value, fmt", [
    ("1234", 1234, "General"),
    ("1,234.50", 1234.5, "#,##0.00"),
    ("-12.5", -12.5, "0.0"),
    ("(45.00)", -45.0, "0.00"),
    ("£1,234.50", 1234.5, '"£"#,##0.00'),
    ("$12", 12, '"$"#,##0'),
    ("12 €", 12, '"€"#,##0'),
    ("-£5.00", -5.0, '"£"#,##0.00'),
    ("20%", 0.2, "0%"),
    ("5.5%", 0.055, "0.0%"),
    ("0.75", 0.75, "0.00"),
    ("0", 0, "General"),
])
def test_numbers(text, value, fmt):
    v, f = convert.parse_number(text)
    assert v == pytest.approx(value) and type(v) is type(value) and f == fmt


@pytest.mark.parametrize("text", [
    "00123", "07700 900123", "01452123456", "+44 1452 123456", "AMM11280899", "12/03/2026",
    "1.2.3", "12,34", "1234567890123456", "£5%", "", "Total", "1e5",
])
def test_kept_as_text(text):
    assert convert.parse_number(text) is None


def test_sheet_names():
    used = set()
    assert convert.sheet_name("Page 3", used) == "Page 3"
    assert convert.sheet_name("Page 3", used) == "Page 3 (2)"
    assert convert.sheet_name("page 3", used) == "page 3 (3)"  # Excel ignores case
    odd = convert.sheet_name("a[b]:c*d?e/f\\g" + "x" * 40, used)
    assert len(odd) <= 31 and not set(odd) & set("[]:*?/\\")
    assert len(convert.sheet_name("y" * 40, used)) == 31
    assert convert.sheet_name("y" * 40, used).endswith(" (2)")


def test_summary_wording():
    r = convert.ConvertResult("/x/Report.docx", 3, ocr_pages=[2])
    assert convert.summary(r) == "Saved Report.docx — 3 pages, 1 scanned page read with OCR"
    assert convert.summary(convert.ConvertResult("/x/Report.xlsx", 4, 4)) == "Saved Report.xlsx — 4 tables"
    assert convert.summary(convert.ConvertResult("/x/R.xlsx", 1, 1)) == "Saved R.xlsx — 1 table"
    assert convert.output_name("/x/Report.pdf", "excel") == "/x/Report.xlsx"


# ------------------------------------------------------------------ Word


def test_word_text_and_table(tmp_path):
    doc = pymupdf.open()
    add_text_page(doc)
    draw_table(doc.new_page(), TABLE)
    src = save(doc, tmp_path / "Report.pdf")
    out = str(tmp_path / "Report.docx")
    steps = []
    r = convert.pdf_to_word(src, out, progress=lambda i, n, m: steps.append((i, n, m)))
    assert r.pages_converted == 2 and not r.ocr_pages and not r.warnings
    assert steps[-1][0] == steps[-1][1]  # progress reaches the end
    d = docx.Document(out)
    text = "\n".join(p.text for p in d.paragraphs)
    assert "Quarterly report" in text and "new kettles" in text
    cells = [[c.text.strip() for c in row.cells] for t in d.tables for row in t.rows]
    assert TABLE[1] in cells and TABLE[2] in cells
    assert not [f for f in os.listdir(tmp_path) if f.startswith("tmp")]  # no temp files left


@needs_ocr
def test_word_reads_scans_as_text(tmp_path):
    doc = pymupdf.open()
    add_text_page(doc)
    add_scan_page(doc)
    src = save(doc, tmp_path / "Mixed.pdf")
    r = convert.pdf_to_word(src, str(tmp_path / "Mixed.docx"))
    assert r.ocr_pages == [2] and r.pages_converted == 2
    text = " ".join(p.text for p in docx.Document(r.output_path).paragraphs)
    assert "Quarterly report" in text
    assert "Delivery" in text and "receipt" in text  # editable text, not a picture


# ------------------------------------------------------------------ Excel


def test_excel_table_types(table_pdf, tmp_path):
    r = convert.pdf_to_excel(table_pdf, str(tmp_path / "Table.xlsx"))
    assert r.tables_found == 1 and r.pages_converted == 1
    wb = openpyxl.load_workbook(r.output_path)
    assert wb.sheetnames == ["Page 1"]
    ws = wb["Page 1"]
    assert [c.value for c in ws[1]] == TABLE[0] and all(c.font.bold for c in ws[1])
    code, item, price, qty, vat = (c.value for c in ws[2])
    assert code == "00123" and item == "Kettle"
    assert price == 1234.5 and ws["C2"].number_format == '"£"#,##0.00'
    assert qty == 2 and isinstance(qty, int)
    assert vat == pytest.approx(0.2) and ws["E2"].number_format == "0%"
    assert ws["A3"].value == "AMM11280899" and ws["C3"].value == 12 and ws["E3"].value == pytest.approx(0.055)
    assert not ws["A2"].font.bold
    assert 8 <= ws.column_dimensions["A"].width <= 60
    assert ws.column_dimensions["A"].width > ws.column_dimensions["D"].width  # sized to the content


def test_excel_two_tables_on_a_page(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page()
    draw_table(page, TABLE, top=80)
    draw_table(page, [["Name", "Total"], ["Jane", "£5.00"]], top=400)
    src = save(doc, tmp_path / "Two.pdf")
    r = convert.pdf_to_excel(src, str(tmp_path / "Two.xlsx"))
    assert r.tables_found == 2
    wb = openpyxl.load_workbook(r.output_path)
    assert wb.sheetnames == ["Page 1", "Page 1 (2)"]
    assert wb["Page 1 (2)"]["B2"].value == 5.0


def test_excel_falls_back_to_text_columns(tmp_path):
    doc = pymupdf.open()
    add_text_page(doc)
    draw_table(doc.new_page(), TABLE)
    src = save(doc, tmp_path / "Mixed.pdf")
    r = convert.pdf_to_excel(src, str(tmp_path / "Mixed.xlsx"))
    assert r.tables_found == 1 and r.pages_converted == 2
    wb = openpyxl.load_workbook(r.output_path)
    assert wb.sheetnames == ["Page 1", "Page 2"]
    values = [c.value for row in wb["Page 1"].iter_rows() for c in row if c.value]
    assert "Quarterly report" in values
    assert not wb["Page 1"]["A1"].font.bold  # plain text, not a table header


def test_excel_text_columns_split_by_position(tmp_path):
    doc = pymupdf.open()
    p = doc.new_page()
    for k, row in enumerate([("Name", "Phone", "Amount"), ("Jane", "01452 123456", "£5.00"), ("Bob", "07700 900123", "£12.50")]):
        for x, text in zip((72, 220, 400), row):
            p.insert_text((x, 100 + k * 18), text)
    rows = convert._text_rows(p)
    assert rows == [["Name", "Phone", "Amount"], ["Jane", "01452 123456", "£5.00"], ["Bob", "07700 900123", "£12.50"]]


@needs_ocr
def test_excel_reads_scans(tmp_path):
    doc = pymupdf.open()
    add_scan_page(doc)
    src = save(doc, tmp_path / "Scan.pdf")
    r = convert.pdf_to_excel(src, str(tmp_path / "Scan.xlsx"))
    assert r.ocr_pages == [1]
    text = " ".join(str(c.value) for ws in openpyxl.load_workbook(r.output_path) for row in ws.iter_rows() for c in row if c.value)
    assert "Delivery" in text


def test_excel_nothing_found(tmp_path):
    doc = pymupdf.open()
    doc.new_page()
    src = save(doc, tmp_path / "Blank.pdf")
    with pytest.raises(ValueError, match="nothing to put in a spreadsheet"):
        convert.pdf_to_excel(src, str(tmp_path / "Blank.xlsx"))
    assert not os.path.exists(tmp_path / "Blank.xlsx")


# ------------------------------------------------------------------ passwords


@pytest.mark.parametrize("kind", [convert.WORD, convert.EXCEL])
def test_password_protected(tmp_path, kind):
    doc = pymupdf.open()
    draw_table(doc.new_page(), TABLE)
    src = save(doc, tmp_path / "Locked.pdf", encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="secret")
    out = str(tmp_path / f"Locked{convert.EXTENSIONS[kind]}")
    with pytest.raises(convert.PasswordError, match="password protected"):
        convert.convert(kind, src, out)
    with pytest.raises(convert.PasswordError, match="isn't right"):
        convert.convert(kind, src, out, password="nope")
    r = convert.convert(kind, src, out, password="secret")
    assert os.path.exists(r.output_path)
    if kind == convert.EXCEL:
        assert openpyxl.load_workbook(out)["Page 1"]["B2"].value == "Kettle"
    else:
        assert any("Kettle" in c.text for t in docx.Document(out).tables for row in t.rows for c in row.cells)
