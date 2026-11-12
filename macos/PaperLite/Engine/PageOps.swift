import AppKit
import PDFKit
import UniformTypeIdentifiers

/// Organise pages: reorder, rotate, insert, combine, extract, split, export images.
enum PageOps {
    /// Put pages in a new order (`order` lists current page indexes).
    static func reorder(_ doc: PDFDocument, to order: [Int]) {
        let pages = (0..<doc.pageCount).compactMap { doc.page(at: $0) }
        for (target, source) in order.enumerated() {
            let page = pages[source]
            let current = doc.index(for: page)
            if current != target { doc.exchangePage(at: current, withPageAt: target) }
        }
    }

    static func blankPage(like ref: PDFPage?) -> PDFPage {
        let page = PDFPage()
        page.setBounds(ref?.bounds(for: .mediaBox) ?? CGRect(x: 0, y: 0, width: 595, height: 842), for: .mediaBox)
        return page
    }

    /// Pages of a PDF or image file, ready to insert into another document.
    static func pages(from url: URL) throws -> [PDFPage] {
        if let type = UTType(filenameExtension: url.pathExtension), type.conforms(to: .image) {
            guard let image = NSImage(contentsOf: url), let page = PDFPage(image: image) else {
                throw PageOpsError.unreadable(url.lastPathComponent)
            }
            return [page]
        }
        guard let doc = PDFDocument(url: url) else { throw PageOpsError.unreadable(url.lastPathComponent) }
        if doc.isLocked { throw PageOpsError.locked(url.lastPathComponent) }
        return (0..<doc.pageCount).compactMap { doc.page(at: $0)?.copy() as? PDFPage }
    }

    static func combine(_ urls: [URL], into output: URL) throws -> Int {
        let out = PDFDocument()
        for url in urls {
            for page in try pages(from: url) { out.insert(page, at: out.pageCount) }
        }
        guard out.write(to: output) else { throw PageOpsError.writeFailed }
        return out.pageCount
    }

    static func extract(_ doc: PDFDocument, pages indexes: [Int], to output: URL) throws {
        let out = PDFDocument()
        for i in indexes {
            if let p = doc.page(at: i)?.copy() as? PDFPage { out.insert(p, at: out.pageCount) }
        }
        guard out.write(to: output) else { throw PageOpsError.writeFailed }
    }

    static func split(_ doc: PDFDocument, every: Int, folder: URL, baseName: String) throws -> [URL] {
        var files: [URL] = []
        var start = 0
        while start < doc.pageCount {
            let end = min(start + every, doc.pageCount) - 1
            let name = end > start ? "\(baseName) - pages \(start + 1)-\(end + 1).pdf" : "\(baseName) - page \(start + 1).pdf"
            let url = folder.appendingPathComponent(name)
            try extract(doc, pages: Array(start...end), to: url)
            files.append(url)
            start = end + 1
        }
        return files
    }

    static func exportImages(_ doc: PDFDocument, pages indexes: [Int], folder: URL, baseName: String,
                             jpeg: Bool, dpi: CGFloat) throws -> [URL] {
        var files: [URL] = []
        for i in indexes {
            guard let page = doc.page(at: i), let image = PageRenderer.render(page, dpi: dpi),
                  let data = jpeg ? PageRenderer.jpegData(image, quality: 0.9) : PageRenderer.pngData(image)
            else { continue }
            let url = folder.appendingPathComponent("\(baseName) - page \(i + 1).\(jpeg ? "jpg" : "png")")
            try data.write(to: url)
            files.append(url)
        }
        return files
    }

    /// "1-3, 5, 8-" → zero-based indexes.
    static func parseRanges(_ text: String, pageCount: Int) throws -> [Int] {
        var result: [Int] = []
        for part in text.replacingOccurrences(of: " ", with: "").split(separator: ",") {
            let bits = part.split(separator: "-", omittingEmptySubsequences: false).map(String.init)
            let start: Int?, end: Int?
            if bits.count == 2 {
                start = bits[0].isEmpty ? 1 : Int(bits[0])
                end = bits[1].isEmpty ? pageCount : Int(bits[1])
            } else {
                start = Int(bits[0]); end = start
            }
            guard let s = start, let e = end, (1...pageCount).contains(s), (1...pageCount).contains(e) else {
                throw PageOpsError.badRange(pageCount)
            }
            result += s <= e ? Array(s...e).map { $0 - 1 } : Array((e...s).reversed()).map { $0 - 1 }
        }
        if result.isEmpty { throw PageOpsError.badRange(pageCount) }
        return result
    }
}

enum PageOpsError: LocalizedError {
    case unreadable(String), locked(String), writeFailed, badRange(Int)
    var errorDescription: String? {
        switch self {
        case .unreadable(let n): return "\(n) couldn't be opened."
        case .locked(let n): return "\(n) is password protected."
        case .writeFailed: return "The file couldn't be saved."
        case .badRange(let n): return "Enter page numbers between 1 and \(n), like 1-3, 5."
        }
    }
}
