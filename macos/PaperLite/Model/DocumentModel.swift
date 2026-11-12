import AppKit
import PDFKit
import SwiftUI
import UniformTypeIdentifiers

enum AppSection: String, CaseIterable, Identifiable {
    case home, view, fill, edit, organise
    var id: String { rawValue }

    var title: String {
        switch self {
        case .home: "Home"
        case .view: "View"
        case .fill: "Fill & Sign"
        case .edit: "Edit"
        case .organise: "Organise"
        }
    }

    var symbol: String {
        switch self {
        case .home: "house"
        case .view: "doc.text"
        case .fill: "signature"
        case .edit: "text.viewfinder"
        case .organise: "square.grid.2x2"
        }
    }
}

enum Tool: String {
    case select, text, tick, cross, date, sign, initials, editText, area, erase, place

    var hint: String {
        switch self {
        case .select: "Click a form field to type in it, or tick a box."
        case .text: "Click where the text should start, type, then press Return."
        case .tick: "Click to place a tick."
        case .cross: "Click to place a cross."
        case .date: "Click to place today's date."
        case .sign: "Click where your signature should go."
        case .initials: "Click where your initials should go."
        case .editText: "Hover over text and click to change it. Scanned pages are read automatically."
        case .area: "Drag a box around handwriting, a stamp or a number, then choose what to do with it."
        case .erase: "Drag over anything you want gone. It's filled with the paper colour."
        case .place: "Click where it should go. Press Esc to cancel."
        }
    }
}

enum EditFont: String, CaseIterable, Identifiable {
    case match, sans, serif, mono
    var id: String { rawValue }
    var title: String {
        switch self {
        case .match: "Match original"
        case .sans: "Sans serif (Helvetica)"
        case .serif: "Serif (Times)"
        case .mono: "Monospace (Courier)"
        }
    }
    var fontName: String {
        switch self {
        case .match, .sans: "Helvetica"
        case .serif: "Times-Roman"
        case .mono: "Courier"
        }
    }
}

/// An area picked up with Move / Copy, waiting to be placed.
struct AreaClip {
    let image: CGImage
    let size: CGSize
    let sourcePage: PDFPage
    let sourceRect: CGRect
    let isMove: Bool
}

/// One undoable change. Edits are kept as live objects (annotations, pages),
/// so undo/redo is instant and nothing is re-parsed.
struct Change {
    let label: String
    let undo: () -> Void
    let redo: () -> Void
}

@MainActor
final class DocumentModel: ObservableObject {
    @Published var document: PDFDocument?
    @Published var url: URL?
    @Published var isDirty = false
    @Published var section: AppSection = .home
    @Published var tool: Tool = .select
    @Published var pageIndex = 0
    @Published var revision = 0
    @Published var toast: Toast?
    @Published var editFont: EditFont = .match
    @Published var ocrStatus = ""
    @Published var clip: AreaClip?
    @Published var recent: [URL] = []

    // sheets
    @Published var showCompress = false
    @Published var compressFiles: [URL] = []
    @Published var showCombine = false
    @Published var signatureSheet: SignatureKind?
    @Published var pagesSheet: PagesAction?

    weak var pdfView: PaperPDFView?
    /// This document's window (tab), and the hook that asks before closing it with unsaved changes.
    weak var window: NSWindow?
    let closeGuard = CloseGuard()
    private var undoStack: [Change] = []
    private var redoStack: [Change] = []
    private var ocrCache: [ObjectIdentifier: [OCRWord]] = [:]
    private var accessedURL: URL?

    struct Toast: Identifiable, Equatable {
        let id = UUID()
        let text: String
        let success: Bool
    }

    init() {
        recent = RecentFiles.load()
    }

    var canUndo: Bool { !undoStack.isEmpty }
    var canRedo: Bool { !redoStack.isEmpty }
    var undoLabel: String { undoStack.last?.label ?? "" }
    var redoLabel: String { redoStack.last?.label ?? "" }
    var fileName: String { url?.lastPathComponent ?? "" }

    var fileSizeText: String {
        guard let url, let doc = document else { return "" }
        let size = ByteCountFormatter.string(fromByteCount: Int64(Compressor.fileSize(url)), countStyle: .file)
        return "\(size) · \(doc.pageCount) page\(doc.pageCount == 1 ? "" : "s")"
    }

    func notify(_ text: String, success: Bool = false) {
        toast = Toast(text: text, success: success)
        let id = toast?.id
        DispatchQueue.main.asyncAfter(deadline: .now() + 3) { [weak self] in
            if self?.toast?.id == id { self?.toast = nil }
        }
    }

    // MARK: sections & tools

    func show(_ s: AppSection) {
        if s != .home && document == nil {
            openPanel()
            guard document != nil else { return }
        }
        section = s
        switch s {
        case .fill: if ![.select, .text, .tick, .cross, .date, .sign, .initials].contains(tool) { tool = .select }
        case .edit: if ![.editText, .text, .area, .erase].contains(tool) { tool = .editText }
        default: tool = .select
        }
        if s == .edit { prepareOCRForCurrentPage() }
    }

    func choose(_ t: Tool) {
        tool = t
        if t == .editText { prepareOCRForCurrentPage() }
    }

    // MARK: open / save

    /// Pick one or more PDFs. They open here if this tab is empty, otherwise in new tabs.
    func openPanel() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.pdf]
        panel.allowsMultipleSelection = true
        if panel.runModal() == .OK { WindowRouter.shared.open(panel.urls, from: self) }
    }

    func open(_ url: URL) {
        stopAccessing()
        let scoped = url.startAccessingSecurityScopedResource()
        guard let doc = PDFDocument(url: url) else {
            if scoped { url.stopAccessingSecurityScopedResource() }
            alert("Couldn't open this file", "\(url.lastPathComponent) isn't a PDF PaperLite can read.")
            return
        }
        if doc.isLocked {
            guard let pw = askPassword(), doc.unlock(withPassword: pw) else {
                if scoped { url.stopAccessingSecurityScopedResource() }
                return
            }
        }
        if scoped { accessedURL = url }
        document = doc
        self.url = url
        isDirty = false
        undoStack.removeAll()
        redoStack.removeAll()
        ocrCache.removeAll()
        pageIndex = 0
        revision += 1
        RecentFiles.add(url)
        recent = RecentFiles.load()
        if section == .home { section = .view }
    }

    private func stopAccessing() {
        accessedURL?.stopAccessingSecurityScopedResource()
        accessedURL = nil
    }

    @discardableResult
    func save() -> Bool {
        guard let url else { return false }
        return write(to: url)
    }

    @discardableResult
    func saveAs() -> Bool {
        guard document != nil else { return false }
        let panel = NSSavePanel()
        panel.allowedContentTypes = [.pdf]
        panel.nameFieldStringValue = fileName.isEmpty ? "Document.pdf" : fileName
        guard panel.runModal() == .OK, let dest = panel.url else { return false }
        guard write(to: dest) else { return false }
        open(dest)
        return true
    }

    private func write(to dest: URL) -> Bool {
        guard let doc = document, let flat = Flattener.flattenedCopy(of: doc) else { return false }
        // Render to the app's own temp folder, then write over `dest` in place.
        // The sandbox only grants the picked file, not its folder, so a temp file
        // beside it (or replaceItemAt, which makes one) is refused.
        let tmp = FileManager.default.temporaryDirectory.appendingPathComponent("\(UUID().uuidString).pdf")
        defer { try? FileManager.default.removeItem(at: tmp) }
        guard flat.write(to: tmp) else {
            alert("Couldn't save", "Try Save As… to a different folder.")
            return false
        }
        do {
            try Data(contentsOf: tmp).write(to: dest)
        } catch {
            alert("Couldn't save", error.localizedDescription)
            return false
        }
        // Reload so edits are now part of the page, not annotations.
        let page = pageIndex
        if dest == url, let reloaded = PDFDocument(url: dest) {
            document = reloaded
            undoStack.removeAll()
            redoStack.removeAll()
            ocrCache.removeAll()
            revision += 1
            pageIndex = min(page, reloaded.pageCount - 1)
        }
        isDirty = false
        notify("Saved", success: true)
        return true
    }

    /// Returns false if the user cancelled.
    func confirmDiscardChanges() -> Bool {
        guard isDirty else { return true }
        let a = NSAlert()
        a.messageText = "Save changes to \(fileName)?"
        a.informativeText = "Your changes will be lost if you don't save them."
        a.addButton(withTitle: "Save")
        a.addButton(withTitle: "Cancel")
        a.addButton(withTitle: "Don't Save")
        switch a.runModal() {
        case .alertFirstButtonReturn: return save()
        case .alertThirdButtonReturn: return true
        default: return false
        }
    }

    // MARK: changes & undo

    func record(_ change: Change) {
        undoStack.append(change)
        redoStack.removeAll()
        if undoStack.count > 100 { undoStack.removeFirst() }
        isDirty = true
        revision += 1
    }

    func undo() {
        guard let c = undoStack.popLast() else { return }
        c.undo()
        redoStack.append(c)
        isDirty = true
        revision += 1
        ocrCache.removeAll()
        notify("Undid \(c.label.lowercased())")
    }

    func redo() {
        guard let c = redoStack.popLast() else { return }
        c.redo()
        undoStack.append(c)
        isDirty = true
        revision += 1
        notify("Redid \(c.label.lowercased())")
    }

    /// Add annotations to a page as one undoable step.
    func addAnnotations(_ label: String, page: PDFPage, _ annots: [PDFAnnotation]) {
        guard !annots.isEmpty else { return }
        for a in annots where a.page == nil { page.addAnnotation(a) }
        record(Change(label: label,
                      undo: { annots.forEach { page.removeAnnotation($0) } },
                      redo: { annots.forEach { page.addAnnotation($0) } }))
    }

    /// Run a page-structure change (reorder, rotate, insert, delete) as one undoable step.
    func changePages(_ label: String, _ body: (PDFDocument) throws -> Void) {
        guard let doc = document else { return }
        let before = (0..<doc.pageCount).compactMap { doc.page(at: $0) }
        let beforeRotation = before.map(\.rotation)
        do {
            try body(doc)
        } catch {
            alert("That didn't work", error.localizedDescription)
            return
        }
        let after = (0..<doc.pageCount).compactMap { doc.page(at: $0) }
        let afterRotation = after.map(\.rotation)
        record(Change(label: label,
                      undo: { Self.restore(doc, pages: before, rotations: beforeRotation) },
                      redo: { Self.restore(doc, pages: after, rotations: afterRotation) }))
    }

    private static func restore(_ doc: PDFDocument, pages: [PDFPage], rotations: [Int]) {
        while doc.pageCount > 0 { doc.removePage(at: doc.pageCount - 1) }
        for (i, p) in pages.enumerated() {
            doc.insert(p, at: i)
            p.rotation = rotations[i]
        }
    }

    // MARK: OCR

    func ocrWords(for page: PDFPage) -> [OCRWord]? { ocrCache[ObjectIdentifier(page)] }

    func ensureOCR(_ page: PDFPage) -> [OCRWord] {
        let key = ObjectIdentifier(page)
        if let cached = ocrCache[key] { return cached }
        let number = (document?.index(for: page) ?? 0) + 1
        ocrStatus = "Reading the text on page \(number)…"
        NSCursor.operationNotAllowed.push()
        defer { NSCursor.pop() }
        let words = (try? ScanEditor.recognizeWords(on: page)) ?? []
        ocrCache[key] = words
        ocrStatus = "Page \(number) is a scan — \(words.count) words recognised. Click one to change it."
        return words
    }

    func forgetOCR(on page: PDFPage, in rect: CGRect) {
        let key = ObjectIdentifier(page)
        ocrCache[key] = ocrCache[key]?.filter { !$0.rect.intersects(rect) }
    }

    func prepareOCRForCurrentPage() {
        guard tool == .editText, let page = document?.page(at: pageIndex) else { return }
        if PageInfo.isScanned(page) {
            DispatchQueue.main.async { _ = self.ensureOCR(page) }
        } else {
            ocrStatus = ""
        }
    }

    // MARK: compress / combine

    func compressCurrent() {
        if let url {
            if isDirty {
                let a = NSAlert()
                a.messageText = "Save your changes before compressing?"
                a.addButton(withTitle: "Save")
                a.addButton(withTitle: "Cancel")
                guard a.runModal() == .alertFirstButtonReturn, save() else { return }
            }
            compressFiles = [url]
        } else {
            compressFiles = []
        }
        showCompress = true
    }

    // MARK: helpers

    func alert(_ title: String, _ text: String) {
        let a = NSAlert()
        a.messageText = title
        a.informativeText = text
        a.runModal()
    }

    private func askPassword() -> String? {
        let a = NSAlert()
        a.messageText = "This PDF is password protected"
        a.informativeText = "Enter the password to open it."
        let field = NSSecureTextField(frame: NSRect(x: 0, y: 0, width: 240, height: 24))
        a.accessoryView = field
        a.addButton(withTitle: "Open")
        a.addButton(withTitle: "Cancel")
        a.window.initialFirstResponder = field
        return a.runModal() == .alertFirstButtonReturn ? field.stringValue : nil
    }
}

enum SignatureKind: String, Identifiable {
    case signature, initials
    var id: String { rawValue }
}

enum PagesAction: String, Identifiable {
    case extract, exportImages, split
    var id: String { rawValue }
}

/// Recent files, stored as security-scoped bookmarks so the sandboxed app can reopen them.
enum RecentFiles {
    private static let key = "recentBookmarks"

    static func load() -> [URL] {
        let datas = UserDefaults.standard.array(forKey: key) as? [Data] ?? []
        return datas.compactMap { data in
            var stale = false
            return try? URL(resolvingBookmarkData: data, options: .withSecurityScope, relativeTo: nil,
                            bookmarkDataIsStale: &stale)
        }
    }

    static func add(_ url: URL) {
        guard let data = try? url.bookmarkData(options: .withSecurityScope, includingResourceValuesForKeys: nil,
                                               relativeTo: nil) else { return }
        var datas = UserDefaults.standard.array(forKey: key) as? [Data] ?? []
        let existing = load()
        if let i = existing.firstIndex(where: { $0.standardizedFileURL == url.standardizedFileURL }), i < datas.count {
            datas.remove(at: i)
        }
        datas.insert(data, at: 0)
        UserDefaults.standard.set(Array(datas.prefix(8)), forKey: key)
    }
}
