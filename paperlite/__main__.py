"""PaperLite PDF.

    PaperLite.exe [file.pdf]                         open the app
    PaperLite.exe --compress [--preset standard] a.pdf b.pdf ...
                                                     compress from the command line, no window
    PaperLite.exe --compress-dialog a.pdf ...        show just the Compress window
                                                     (used by the Explorer right-click menu)
"""

from __future__ import annotations

import argparse
import os
import sys


def cli_compress(argv: list[str]) -> int:
    from paperlite.core import compress
    from paperlite.ui.dialogs import compressed_name

    ap = argparse.ArgumentParser(prog="PaperLite --compress")
    ap.add_argument("--compress", action="store_true")
    ap.add_argument("--preset", default=compress.DEFAULT_PRESET, choices=list(compress.PRESETS))
    ap.add_argument("--in-place", action="store_true", help="overwrite the originals")
    ap.add_argument("files", nargs="+")
    args = ap.parse_args(argv)
    failed = 0
    for f in args.files:
        out = f if args.in_place else compressed_name(f)
        try:
            r = compress.compress_pdf(f, out, args.preset)
            print(f"{f}: {compress.human_size(r.original_bytes)} -> {compress.human_size(r.compressed_bytes)} "
                  f"({r.saved_percent:.0f}% smaller) -> {out}")
        except Exception as e:
            failed += 1
            print(f"{f}: FAILED: {e}", file=sys.stderr)
    return 1 if failed else 0


def resource_path(rel: str) -> str:
    """Path to a bundled file, both from source and inside the PyInstaller .exe."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, rel)


def main() -> int:
    argv = sys.argv[1:]
    if "--compress" in argv:
        return cli_compress(argv)

    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from paperlite.ui.main_window import APP_NAME, MainWindow

    from paperlite.ui import theme

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("PaperLite")
    app.setStyle("Fusion")
    app.setFont(theme.app_font())
    app.setStyleSheet(theme.stylesheet())
    app.setWindowIcon(QIcon(resource_path("assets/icon.png")))
    files = [a for a in argv if a.lower().endswith(".pdf")]
    if "--compress-dialog" in argv:
        from paperlite.ui.dialogs import CompressDialog

        CompressDialog(None, files).exec()
        return 0
    win = MainWindow()
    win.show()
    if files:
        win.open_file(files[0])
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
