import PDFKit

/// Burns PaperLite's edits into the pages before saving.
///
/// * Normal pages: the page is redrawn into a new vector page with the edits on
///   top, so text stays sharp and selectable. (Covered text is hidden but still in
///   the file underneath, as with most Mac PDF editors.)
/// * Scanned pages: the page is re-rendered as a 300 DPI image with the edits
///   applied, so the original pixels under an edit are really gone.
///
/// Pages without PaperLite edits are left untouched, so their form fields and
/// links keep working.
enum Flattener {
    static func hasEdits(_ page: PDFPage) -> Bool {
        page.annotations.contains(where: Annotations.isOurs)
    }

    static func flattenedCopy(of doc: PDFDocument) -> PDFDocument? {
        guard let data = doc.dataRepresentation(), let copy = PDFDocument(data: data) else { return nil }
        // dataRepresentation() drops custom-drawn annotations, so rebuild those pages from the live document.
        for i in 0..<doc.pageCount {
            guard let page = doc.page(at: i), hasEdits(page), let flat = flatten(page) else { continue }
            copy.removePage(at: i)
            copy.insert(flat, at: i)
        }
        return copy
    }

    static func flatten(_ page: PDFPage) -> PDFPage? {
        let size = page.bounds(for: .mediaBox).size
        if PageInfo.isScanned(page) {
            guard let image = PageRenderer.render(page, dpi: 300), let jpeg = PageRenderer.jpegData(image, quality: 0.85)
            else { return nil }
            return PageRenderer.pdfPage(fromJPEG: jpeg, size: size, rotation: page.rotation)
        }
        return PageRenderer.pdfPage(size: size, rotation: page.rotation) { ctx in
            page.draw(with: .mediaBox, to: ctx)
        }
    }
}
