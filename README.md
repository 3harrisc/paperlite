<p align="center"><img src="assets/logo.png" width="128" alt="PaperLite logo"></p>

# PaperLite PDF

A clean, fast PDF app for Windows, similar to Acrobat, focused on the features people use most:

- **Compress PDF**: shrinks large scanned PDFs, often by 80–99%. Compress one file or a batch, or right-click a PDF in File Explorer and choose **Compress with PaperLite**.
- **Convert to Word or Excel**: turn a PDF into an editable Word document that keeps the layout as closely as possible, or pull its tables into Excel, one sheet per table, with numbers, prices and percentages stored as real numbers. Scanned pages are read with the built-in OCR first, so they come out as text too.
- **Fill & Sign**: fill in form fields right on the page, type text anywhere, and add ticks, crosses and today's date. Place a signature or initials, typed or hand-drawn and remembered for next time.
- **Edit PDF**, including scans and handwriting:
  - **Edit text**: hover over a word and click to change it. On scanned pages the text is read first with built-in OCR, and the new text matches the original's size, position and ink colour on the scan's paper colour. The old pixels are really removed, not just covered.
  - **Select area**: drag a box around anything (handwriting, stamps, numbers), then **Replace with text**, **Erase**, **Move** or **Copy** it.
  - **Erase**: drag over anything to remove it.
- **Organise pages**: drag to reorder, rotate, delete, insert pages from another file or a blank page, extract pages to a new PDF, export pages as PNG/JPG, and split into several files.
- **Combine files**: join PDFs and images into one PDF.
- Undo/redo for everything, page thumbnails, zoom, print, drag-and-drop, recent files and password-protected PDFs.
- **Automatic updates**: the app tells you when a new version is out and installs it in one click.

## Making the .exe installer

### Option A: on your Windows PC (simplest)

1. Install **Python 3.13** from <https://www.python.org/downloads/>. Tick "Add python.exe to PATH" during setup.
2. Install **Inno Setup 6** from <https://jrsoftware.org/isdl.php>.
3. Double-click **`build.bat`** in this folder.

It takes a few minutes the first time. When it's done, a window opens at `installer\Output\PaperLite-PDF-Setup-<version>.exe`. That file is the installer you double-click or send to people.

### Option B: automatically on GitHub

Push this repo to GitHub. Every push to `main` runs the tests and builds the installer on a Windows machine; download it from the run's **Artifacts** section in the **Actions** tab. You can also start a build by hand with **Run workflow**.

The installer doesn't need admin rights. It adds Start-menu and desktop shortcuts, the right-click **Compress with PaperLite** entry, and **Open with** for PDFs.

> Windows SmartScreen warns about unsigned installers ("Windows protected your PC" → *More info* → *Run anyway*). A code-signing certificate removes this warning; see "Code signing" below.

## Releasing an update

Installed copies check GitHub once a day. When a newer release exists, a blue bar appears: **"PaperLite 0.3.0 is available → Install update"**. One click downloads the new installer, closes the app, upgrades it in place (settings, signatures and recent files are kept) and reopens it.

One-time setup:

1. Put the repo on GitHub. It must be **public** for the update check to work without a login. With a private repo you can publish releases to a separate public repo.
2. In `paperlite/__init__.py`, set `UPDATE_REPO = "your-github-name/paperlite"`.

To ship a new version:

1. Change `__version__` in `paperlite/__init__.py`, e.g. `"0.3.0"`.
2. Commit and push.
3. Tag it and push the tag (run this in Git Bash or a terminal):

   ```bash
   git tag v0.3.0
   ```

   ```bash
   git push origin v0.3.0
   ```

GitHub Actions builds the installer and publishes a **Release** with it attached. Within a day, every installed copy offers the update. People can also use **Menu → Check for updates…** at any time. The build fails if the tag and `__version__` don't match, so you can't publish a mislabelled version.

## Code signing (optional, recommended before sharing widely)

Buy a code-signing certificate (for example from Certum, Sectigo or SSL.com, or use Azure Trusted Signing), then add a signing step after the Inno Setup step in `.github/workflows/build-windows.yml`. This removes the SmartScreen warning and builds trust with people who download it.

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
paperlite/core/       PDF logic, no UI (easy to port)
  compress.py         compression presets and engine
  forms.py            form filling, text, ticks, signatures
  textedit.py         editing real text
  scanedit.py         OCR, editing scans and handwriting, erase/move/copy
  pages.py            reorder, rotate, insert, combine, extract, split, export images
  history.py          undo/redo
  updater.py          update checks via GitHub Releases
paperlite/ui/         Qt desktop interface (theme.py holds every colour and style)
assets/               app icon, Lucide icons (ISC), Tesseract English OCR model (Apache-2.0)
tests/                pytest tests (core + headless GUI)
build.bat             one-click Windows build
paperlite.spec        PyInstaller build
installer/            Inno Setup installer script
.github/workflows/    Windows build + release pipeline
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
| OCR on scans | Tesseract inside PyMuPDF | **Vision** framework (`VNRecognizeTextRequest`). It's built into macOS, and its `.accurate` level also reads a lot of handwriting. |
| Erase/replace on scans | redaction with image pixels removed, then the sampled paper colour | Draw into the page image with Core Graphics, or add a filled annotation and flatten it |
| Page organising | `pages.py` | `PDFDocument` `exchangePage`, `removePage`, `insert(_:at:)` |
| Updates | GitHub Releases + Inno Setup | **Sparkle** framework (the standard auto-updater for Mac apps) |

## Licensing

PyMuPDF (the PDF engine) is **AGPL-3.0**. That's fine for personal or internal use. If you distribute PaperLite to other people, you must either publish the source under the AGPL or buy a commercial licence from Artifex. Qt for Python (PySide6) is LGPL.
