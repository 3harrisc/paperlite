# PyInstaller build: pyinstaller paperlite.spec  ->  dist/PaperLite/PaperLite.exe
import sys

block_cipher = None
excluded_qt = [
    "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtSql",
    "PySide6.QtTest", "PySide6.QtOpenGL", "PySide6.QtDBus", "PySide6.QtConcurrent",
    "PySide6.QtXml", "PySide6.QtSvg",
]

a = Analysis(
    ["run.py"],
    pathex=["."],
    datas=[("assets/icon.png", "assets"), ("assets/icon.ico", "assets")],
    hiddenimports=["PySide6.QtPrintSupport"],
    excludes=["tkinter", "unittest", "pydoc", "pymupdf4llm", "pymupdf_layout", *excluded_qt],
    noarchive=False,
)

# Drop parts of the libraries this app never uses, to keep the installer small.
def _keep(entry):
    dest = entry[0].replace("\\", "/")
    return not (
        dest.startswith(("pymupdf/layout", "pymupdf/mupdf-devel", "PySide6/Qt/translations", "PySide6/translations"))
        or "/qml/" in dest
    )


a.datas = [d for d in a.datas if _keep(d)]
a.binaries = [b for b in a.binaries if _keep(b)]

pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PaperLite",
    icon="assets/icon.ico",
    console=False,
    version="installer/version_info.txt" if sys.platform == "win32" else None,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="PaperLite", upx=False)
