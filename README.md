# PaperLite PDF

A lightweight PDF reader for Windows, similar to Acrobat Reader, focused on the features people use most:

- **Compress PDF** – shrinks large scanned PDFs, often by 80–99%. Compress one file or a whole batch, or right-click a PDF in File Explorer and choose **Compress with PaperLite**.
- **Fill & Sign** – fill in form fields, type text anywhere, add ticks, and place a signature or initials (typed or hand-drawn, saved for next time).
- **Edit text** – click a line of text and change it. The size, colour and position stay the same.
- Viewer: page thumbnails, zoom (Ctrl + mouse wheel), rotate pages, delete pages, print, undo/redo, drag-and-drop, password-protected PDFs.

## Getting the installer

The Windows installer (`PaperLite-PDF-Setup-x.y.z.exe`) is built automatically by GitHub Actions on a Windows machine:

1. Push this repo to GitHub.
2. Open the **Actions** tab, pick **Build Windows installer**, and click **Run workflow** (it also runs on every push to `main`).
3. When it finishes, download the **PaperLite-PDF-Setup** artifact from the run page.

To publish a release, push a tag such as `v0.1.0`. The installer is then attached to a GitHub Release.

The installer doesn't need admin rights. It adds Start-menu and desktop shortcuts, the right-click **Compress with PaperLite** entry, and an **Open with** option for PDFs. It does not take over the default PDF app; you can make PaperLite your default in Windows Settings.

> Windows SmartScreen will warn about an unsigned installer ("Windows protected your PC" → *More info* → *Run anyway*). Signing the installer with a code-signing certificate removes this warning.

## Building on a Windows PC by hand

```bat
py -3.13 -m venv .venv
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\python run.py
```

```bat
.venv\Scripts\pyinstaller --noconfirm paperlite.spec
```

```bat
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\paperlite.iss
```

The installer ends up in `installer\Output\`.

## Command-line compression

```bat
PaperLite.exe --compress --preset standard scan1.pdf scan2.pdf
```

The presets are `high`, `standard`, `small` and `small_gray`. Add `--in-place` to overwrite the originals; otherwise output is saved as `name_compressed.pdf`.

## How compression works

Scans are big because each page is a high-resolution picture. Compression does three things:

1. **Downsamples** images that are above the threshold DPI to the target DPI.
2. **Re-encodes** colour and greyscale images as JPEG at the preset quality. Black-and-white (1-bit) scans are kept lossless.
3. **Cleans up** the file: removes unused objects, compresses streams, subsets fonts and packs objects.

If the result would be *larger* than the original, the original is kept. Originals are only overwritten if you tick "Replace the original files".

| Preset        | Downsample above | to      | JPEG quality | Greyscale |
|---------------|------------------|---------|--------------|-----------|
| High quality  | 225 DPI          | 200 DPI | 85           | no        |
| Standard      | 165 DPI          | 150 DPI | 70           | no        |
| Smallest      | 110 DPI          | 96 DPI  | 55           | no        |
| Smallest B&W  | 110 DPI          | 96 DPI  | 55           | yes       |

These numbers are defined in `paperlite/core/compress.py`, which is the source of truth. Use the same values in the Mac app so both versions give the same results.

## Project layout

```
paperlite/core/     PDF logic, no UI (compress, forms/sign, text edit)
paperlite/ui/       Qt desktop interface
tests/              pytest tests (core + headless GUI)
paperlite.spec      PyInstaller build
installer/          Inno Setup installer script
.github/workflows/  Windows build pipeline
```

Run the tests with `python -m pytest`. On Linux CI, set `QT_QPA_PLATFORM=offscreen`.

## Notes for the Mac (Xcode) version

The `core/` modules are small and map directly onto Apple frameworks:

| Feature | Here (PyMuPDF) | macOS (Swift) |
|---|---|---|
| Viewing, thumbnails | `page.get_pixmap` | `PDFView`, `PDFThumbnailView` (PDFKit) |
| Compress | `Document.rewrite_images` + `save(garbage=4, deflate=True)` | Render each image with Core Graphics / `CGImageDestination` at the preset DPI and JPEG quality, then write a new PDF with `CGContext(consumer:mediaBox:)`. PDFKit's own `saveImagesAsJPEGOption` and `optimizeImagesForScreenOption` options are simpler but give you less control. |
| Form fields | `page.widgets()` | `PDFAnnotation` with `widgetFieldType` |
| Add text / tick | `insert_text`, line drawing | `PDFAnnotation` `.freeText` / `.ink`, or draw into the page |
| Signature | PNG stamped with `insert_image` | Custom `PDFAnnotation` subclass that draws the signature image (`draw(with:in:)`) |
| Edit text | redact the span, then `insert_text` | PDFKit has no built-in text editing. Cover the old text with a white box and draw new text, or use a library such as PSPDFKit/Nutrient. |

## Licensing

PyMuPDF (the PDF engine) is **AGPL-3.0**. That's fine for personal or internal use. If you distribute PaperLite to other people, you must either publish the source under the AGPL or buy a commercial licence from Artifex. Qt for Python (PySide6) is LGPL.
