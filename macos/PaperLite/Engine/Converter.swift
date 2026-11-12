import AppKit
import PDFKit

/// PDF → Word (.docx) and PDF → Excel (.xlsx).
///
/// The rules match `paperlite/core/convert.py` in the Windows app (sheet names,
/// number detection, column layout, wording) so both versions give the same
/// results. One difference: Windows finds ruled tables with PyMuPDF, which has no
/// PDFKit equivalent, so here every page becomes a sheet of its text laid out in
/// columns, the same way Windows treats a page without a ruled table.
enum ConvertKind: String, CaseIterable, Identifiable {
    case word, excel
    var id: String { rawValue }
    var title: String { self == .word ? "Word (.docx)" : "Excel (.xlsx)" }
    var detail: String {
        self == .word ? "Editable text, keeps the layout as closely as possible."
                      : "Text and tables in columns, one sheet per page."
    }
    var fileExtension: String { self == .word ? "docx" : "xlsx" }
}

struct ConvertResult {
    let output: URL
    let pages: Int
    let ocrPages: [Int]
    let warnings: [String]

    func summary(kind: ConvertKind) -> String {
        var line = "Saved \(output.lastPathComponent) — \(pages) page\(pages == 1 ? "" : "s")"
        if kind == .excel { line += ", laid out in columns" }
        if !ocrPages.isEmpty {
            line += ", \(ocrPages.count) scanned page\(ocrPages.count == 1 ? "" : "s") read with OCR"
        }
        return line
    }
}

enum ConvertError: LocalizedError {
    case nothingForWord, nothingForExcel, cannotSave(String)
    var errorDescription: String? {
        switch self {
        case .nothingForWord: return "Nothing in this PDF could be converted to Word."
        case .nothingForExcel: return "No tables or text were found in this PDF, so there's nothing to put in a spreadsheet."
        case .cannotSave(let name): return "Couldn't save \(name). If it's open in Word or Excel, close it and try again."
        }
    }
}

enum Converter {
    typealias Progress = @Sendable (Int, Int, String) -> Void

    static func convert(_ kind: ConvertKind, document: PDFDocument, to output: URL,
                        progress: Progress) throws -> ConvertResult {
        let data: Data
        let pages: Int
        var ocr: [Int] = []
        var warnings: [String] = []
        let n = document.pageCount

        switch kind {
        case .word:
            let text = NSMutableAttributedString()
            var made = 0
            for i in 0..<n {
                guard let page = document.page(at: i) else { continue }
                progress(i, n, "Reading page \(i + 1) of \(n)…")
                let lines: [Line]
                if PageInfo.isScanned(page) {
                    progress(i, n, "Reading scanned page \(i + 1) with OCR…")
                    lines = ocrLines(page)
                    if lines.isEmpty { warnings.append("Page \(i + 1) is a scan with no readable text."); continue }
                    ocr.append(i + 1)
                } else {
                    lines = textLines(page)
                }
                if lines.isEmpty { continue }
                // A form feed becomes a page break in the .docx.
                if made > 0 { text.append(NSAttributedString(string: "\u{0C}")) }
                text.append(paragraphs(from: lines))
                made += 1
            }
            guard made > 0 else { throw ConvertError.nothingForWord }
            progress(n, n, "Saving…")
            data = try text.data(from: NSRange(location: 0, length: text.length),
                                 documentAttributes: [.documentType: NSAttributedString.DocumentType.officeOpenXML])
            pages = made

        case .excel:
            var sheets: [XLSXWriter.Sheet] = []
            var used = Set<String>()
            for i in 0..<n {
                guard let page = document.page(at: i) else { continue }
                progress(i, n, "Reading page \(i + 1) of \(n)…")
                let words: [Item]
                if PageInfo.isScanned(page) {
                    progress(i, n, "Reading scanned page \(i + 1) with OCR…")
                    words = ((try? ScanEditor.recognizeWords(on: page)) ?? []).map {
                        Item(rect: $0.rect, text: $0.text)
                    }
                    if words.isEmpty { warnings.append("Page \(i + 1) is a scan with no readable text."); continue }
                    ocr.append(i + 1)
                } else {
                    words = textWords(page)
                }
                let rows = columnRows(words)
                if !rows.isEmpty { sheets.append(.init(name: sheetName("Page \(i + 1)", used: &used), rows: rows)) }
            }
            guard !sheets.isEmpty else { throw ConvertError.nothingForExcel }
            progress(n, n, "Saving…")
            data = XLSXWriter.workbook(sheets)
            pages = sheets.count
        }

        do {
            try data.write(to: output)
        } catch {
            throw ConvertError.cannotSave(output.lastPathComponent)
        }
        return ConvertResult(output: output, pages: pages, ocrPages: ocr, warnings: warnings)
    }

    // MARK: Word

    struct Line {
        let text: NSAttributedString
        let rect: CGRect
        var size: CGFloat {
            text.length == 0 ? 0 : ((text.attribute(.font, at: 0, effectiveRange: nil) as? NSFont)?.pointSize ?? 0)
        }
    }

    static func textLines(_ page: PDFPage) -> [Line] {
        let lines = page.selection(for: page.bounds(for: .cropBox))?.selectionsByLine() ?? []
        return lines.compactMap { sel in
            guard let attr = sel.attributedString else { return nil }
            let trimmed = NSMutableAttributedString(attributedString: attr)
            while trimmed.length > 0, let last = trimmed.string.last, last.isNewline || last == " " {
                trimmed.deleteCharacters(in: NSRange(location: trimmed.length - 1, length: 1))
            }
            return trimmed.length == 0 ? nil : Line(text: trimmed, rect: sel.bounds(for: page))
        }
    }

    /// OCR words rewritten as lines of Helvetica, sized like the scan.
    static func ocrLines(_ page: PDFPage) -> [Line] {
        let words = (try? ScanEditor.recognizeWords(on: page)) ?? []
        var groups: [(rect: CGRect, words: [OCRWord])] = []
        for word in words {
            if let i = groups.firstIndex(where: { $0.rect == word.lineRect }) {
                groups[i].words.append(word)
            } else {
                groups.append((word.lineRect, [word]))
            }
        }
        return groups
            .sorted { $0.rect.midY > $1.rect.midY }
            .map { group in
                let sizes = group.words.map(ScanEditor.fontSize(for:)).sorted()
                let size = (sizes[sizes.count / 2] * 2).rounded() / 2
                let text = group.words.sorted { $0.rect.minX < $1.rect.minX }.map(\.text).joined(separator: " ")
                let font = NSFont(name: "Helvetica", size: size) ?? .systemFont(ofSize: size)
                return Line(text: NSAttributedString(string: text, attributes: [.font: font]), rect: group.rect)
            }
    }

    /// Lines joined into paragraphs: a new one starts at a bigger gap or a change of size.
    static func paragraphs(from lines: [Line]) -> NSAttributedString {
        let out = NSMutableAttributedString()
        for (k, line) in lines.enumerated() {
            if k > 0 {
                let prev = lines[k - 1]
                let gap = prev.rect.minY - line.rect.maxY
                let height = max(prev.rect.height, 1)
                let newParagraph = gap > 0.6 * height || gap < -height || abs(prev.size - line.size) > 1
                    || prev.text.string.hasSuffix(":")
                out.append(NSAttributedString(string: newParagraph ? "\n" : " ",
                                              attributes: prev.text.attributes(at: max(0, prev.text.length - 1), effectiveRange: nil)))
            }
            out.append(line.text)
        }
        out.append(NSAttributedString(string: "\n"))
        return out
    }

    // MARK: Excel

    struct Item {
        var rect: CGRect
        var text: String
    }

    /// The page's words with their boxes (PDF coordinates, origin bottom-left).
    /// Read line by line: `page.string` and `characterBounds(at:)` count line breaks
    /// differently, but a line's selection range and its own string line up.
    static func textWords(_ page: PDFPage) -> [Item] {
        let lines = page.selection(for: page.bounds(for: .cropBox))?.selectionsByLine() ?? []
        var words: [Item] = []
        for line in lines {
            guard let text = line.string, line.numberOfTextRanges(on: page) == 1 else { continue }
            let range = line.range(at: 0, on: page)
            let units = Array(text.utf16)
            guard units.count == range.length else {
                // can't map characters to boxes; keep the line as one cell
                let t = text.trimmingCharacters(in: .whitespacesAndNewlines)
                if !t.isEmpty { words.append(Item(rect: line.bounds(for: page), text: t)) }
                continue
            }
            var start: Int?
            for k in 0...units.count {
                let isSpace = k == units.count || (Character(UnicodeScalar(units[k]) ?? " ").isWhitespace)
                if !isSpace, start == nil { start = k }
                if isSpace, let s0 = start {
                    let word = String(utf16CodeUnits: Array(units[s0..<k]), count: k - s0)
                    let rect = page.selection(for: NSRange(location: range.location + s0, length: k - s0))?.bounds(for: page) ?? .zero
                    if !rect.isEmpty { words.append(Item(rect: rect, text: word)) }
                    start = nil
                }
            }
        }
        return words
    }

    /// Rows of cells: words on the same line (centres within half a line height),
    /// split into cells at gaps wider than 0.8 × the line height, and lined up with
    /// the column bands of lines that have more than one cell.
    static func columnRows(_ words: [Item]) -> [[String]] {
        // rows, top of the page first
        var rows: [[Item]] = []
        for word in words.sorted(by: { $0.rect.midY > $1.rect.midY }) {
            if let last = rows.last?.last, abs(last.rect.midY - word.rect.midY) <= max(last.rect.height, word.rect.height) / 2 {
                rows[rows.count - 1].append(word)
            } else {
                rows.append([word])
            }
        }
        let lines: [[Item]] = rows.map { row in
            let sorted = row.sorted { $0.rect.minX < $1.rect.minX }
            let height = sorted.map(\.rect.height).max() ?? 1
            var runs: [Item] = []
            for word in sorted {
                if var last = runs.last, word.rect.minX - last.rect.maxX <= 0.8 * height {
                    last.text += " " + word.text
                    last.rect = last.rect.union(word.rect)
                    runs[runs.count - 1] = last
                } else {
                    runs.append(word)
                }
            }
            return runs
        }

        var bands: [(CGFloat, CGFloat)] = []
        for (x0, x1) in lines.filter({ $0.count > 1 }).flatMap({ $0 }).map({ ($0.rect.minX, $0.rect.maxX) }).sorted(by: { $0.0 < $1.0 }) {
            if let last = bands.last, x0 <= last.1 {
                bands[bands.count - 1].1 = max(last.1, x1)
            } else {
                bands.append((x0, x1))
            }
        }
        func column(_ run: Item) -> Int {
            if let k = bands.firstIndex(where: { run.rect.minX <= $0.1 && run.rect.maxX >= $0.0 }) { return k }
            return bands.indices.last(where: { bands[$0].0 <= run.rect.minX }) ?? 0
        }

        return lines.map { line in
            var cells = Array(repeating: "", count: max(1, bands.count))
            for run in line {
                let k = line.count > 1 ? column(run) : 0
                cells[k] = (cells[k] + " " + run.text).trimmingCharacters(in: .whitespaces)
            }
            while cells.count > 1, cells.last?.isEmpty == true { cells.removeLast() }
            return cells
        }
    }

    /// A valid, unique sheet name: at most 31 characters, none of []:*?/\,
    /// and "Page 3", "Page 3 (2)"… if a name repeats (compared ignoring case).
    static func sheetName(_ base: String, used: inout Set<String>) -> String {
        var clean = String(base.map { "[]:*?/\\".contains($0) ? " " : $0 })
            .trimmingCharacters(in: .whitespaces)
            .trimmingCharacters(in: CharacterSet(charactersIn: "'"))
        clean = String(clean.prefix(31)).trimmingCharacters(in: .whitespaces)
        if clean.isEmpty { clean = "Sheet" }
        var name = clean
        var k = 2
        while used.contains(name.lowercased()) {
            let suffix = " (\(k))"
            name = String(clean.prefix(31 - suffix.count)).trimmingCharacters(in: .whitespaces) + suffix
            k += 1
        }
        used.insert(name.lowercased())
        return name
    }

    /// The number in a cell and its Excel number format, or nil to keep it as text.
    ///
    /// Numbers: 1234, 1,234.50, -12.5, (45.00), £1,234.50, $12, 12 €, 20% (0.2).
    /// Text: leading-zero codes (00123, 07700 900123), refs with letters
    /// (AMM11280899), dates, anything over 15 digits.
    static func parseNumber(_ text: String) -> (value: Double, isInteger: Bool, format: String)? {
        var s = text.trimmingCharacters(in: .whitespaces)
            .replacingOccurrences(of: "\u{2212}", with: "-")
            .replacingOccurrences(of: "\u{00A0}", with: " ")
        guard !s.isEmpty, s.count <= 30, !s.contains("\n") else { return nil }
        var negative = false
        if s.hasPrefix("("), s.hasSuffix(")") { negative = true; s = String(s.dropFirst().dropLast()).trimmingCharacters(in: .whitespaces) }
        if s.hasPrefix("-") { negative = true; s = String(s.dropFirst()).trimmingCharacters(in: .whitespaces) }
        var currency = ""
        if let first = s.first, "£$€".contains(first) {
            currency = String(first); s = String(s.dropFirst()).trimmingCharacters(in: .whitespaces)
        } else if let last = s.last, "£$€".contains(last) {
            currency = String(last); s = String(s.dropLast()).trimmingCharacters(in: .whitespaces)
        }
        if !currency.isEmpty, s.hasPrefix("-"), !negative { negative = true; s = String(s.dropFirst()).trimmingCharacters(in: .whitespaces) }
        let percent = s.hasSuffix("%")
        if percent {
            if !currency.isEmpty { return nil }
            s = String(s.dropLast()).trimmingCharacters(in: .whitespaces)
        }
        guard s.range(of: #"^(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?$|^\.\d+$"#, options: .regularExpression) != nil else { return nil }
        let parts = s.split(separator: ".", omittingEmptySubsequences: false)
        let whole = parts[0].replacingOccurrences(of: ",", with: "")
        if whole.count > 1, whole.hasPrefix("0") { return nil }  // a code, not a number
        let digits = s.replacingOccurrences(of: ",", with: "").replacingOccurrences(of: ".", with: "")
        if digits.drop(while: { $0 == "0" }).count > 15 { return nil }  // beyond Excel's precision
        let decimals = parts.count > 1 ? parts[1].count : 0
        guard var value = Double(s.replacingOccurrences(of: ",", with: "")) else { return nil }
        if negative { value = -value }
        let places = decimals > 0 ? "." + String(repeating: "0", count: decimals) : ""
        if percent { return (value / 100, false, "0\(places)%") }
        if !currency.isEmpty { return (value, decimals == 0, "\"\(currency)\"#,##0\(places)") }
        if s.contains(",") { return (value, decimals == 0, "#,##0\(places)") }
        return (value, decimals == 0, decimals > 0 ? "0\(places)" : "General")
    }
}
