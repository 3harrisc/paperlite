import AppKit
import PDFKit
import SwiftUI

/// PDFView with PaperLite's tools: click to place, drag to select an area,
/// hover highlights and an in-page text editor.
final class PaperPDFView: PDFView, NSTextFieldDelegate {
    weak var model: DocumentModel?
    private let overlay = OverlayView()
    private var dragStart: NSPoint?
    private var editor: NSTextField?
    private var editorCommit: ((String) -> Void)?
    private var trackingArea: NSTrackingArea?

    override init(frame: NSRect) {
        super.init(frame: frame)
        overlay.frame = bounds
        overlay.autoresizingMask = [.width, .height]
        addSubview(overlay)
    }

    required init?(coder: NSCoder) { fatalError("not used") }

    override func updateTrackingAreas() {
        super.updateTrackingAreas()
        if let trackingArea { removeTrackingArea(trackingArea) }
        let t = NSTrackingArea(rect: bounds, options: [.mouseMoved, .activeInKeyWindow, .inVisibleRect, .mouseEnteredAndExited],
                               owner: self, userInfo: nil)
        addTrackingArea(t)
        trackingArea = t
    }

    private var tool: Tool { model?.tool ?? .select }
    private var isDragTool: Bool { tool == .area || tool == .erase }

    // MARK: coordinates

    private func pagePoint(_ event: NSEvent) -> (PDFPage, CGPoint)? {
        let p = convert(event.locationInWindow, from: nil)
        guard let page = page(for: p, nearest: false) else { return nil }
        return (page, convert(p, to: page))
    }

    func viewRect(_ r: CGRect, on page: PDFPage) -> NSRect { convert(r, from: page) }

    // MARK: mouse

    override func mouseMoved(with event: NSEvent) {
        super.mouseMoved(with: event)
        guard let model, let (page, pt) = pagePoint(event) else {
            overlay.hover = nil
            return
        }
        switch tool {
        case .editText:
            if let r = textRect(at: pt, on: page) ?? model.ocrWords(for: page)?.first(where: { $0.rect.insetBy(dx: -2, dy: -2).contains(pt) })?.rect {
                overlay.hover = viewRect(r, on: page).insetBy(dx: -2, dy: -2)
                NSCursor.pointingHand.set()
            } else {
                overlay.hover = nil
                NSCursor.iBeam.set()
            }
        case .place:
            if let clip = model.clip {
                let r = CGRect(origin: CGPoint(x: pt.x, y: pt.y - clip.size.height), size: clip.size)
                overlay.hover = viewRect(r, on: page)
            }
            NSCursor.crosshair.set()
        case .select:
            overlay.hover = nil
        default:
            overlay.hover = nil
            NSCursor.crosshair.set()
        }
    }

    override func mouseExited(with event: NSEvent) {
        super.mouseExited(with: event)
        overlay.hover = nil
    }

    override func mouseDown(with event: NSEvent) {
        commitEditor()
        guard let model, tool != .select, let (page, pt) = pagePoint(event) else {
            super.mouseDown(with: event)
            return
        }
        // form fields stay clickable in every Fill & Sign tool
        if [.text, .tick, .cross, .date, .sign, .initials].contains(tool),
           let a = page.annotation(at: pt), a.type == "Widget" {
            super.mouseDown(with: event)
            return
        }
        if isDragTool {
            dragStart = convert(event.locationInWindow, from: nil)
            return
        }
        handleClick(model: model, page: page, point: pt)
    }

    override func mouseDragged(with event: NSEvent) {
        guard let start = dragStart else { return super.mouseDragged(with: event) }
        let now = convert(event.locationInWindow, from: nil)
        overlay.selection = NSRect(x: min(start.x, now.x), y: min(start.y, now.y),
                                   width: abs(now.x - start.x), height: abs(now.y - start.y))
        overlay.selectionIsErase = tool == .erase
    }

    override func mouseUp(with event: NSEvent) {
        guard let start = dragStart else { return super.mouseUp(with: event) }
        dragStart = nil
        let sel = overlay.selection
        overlay.selection = nil
        guard let model, let sel, sel.width > 4, sel.height > 4,
              let page = page(for: NSPoint(x: sel.midX, y: sel.midY), nearest: true) else { return }
        _ = start
        let a = convert(sel.origin, to: page)
        let b = convert(NSPoint(x: sel.maxX, y: sel.maxY), to: page)
        let rect = CGRect(x: min(a.x, b.x), y: min(a.y, b.y), width: abs(b.x - a.x), height: abs(b.y - a.y))
        if tool == .erase {
            model.addAnnotations("Erase", page: page, ScanEditor.erase(page: page, rect: rect))
            model.forgetOCR(on: page, in: rect)
        } else {
            showAreaMenu(model: model, page: page, rect: rect, event: event)
        }
    }

    override func keyDown(with event: NSEvent) {
        if event.keyCode == 53, let model { // Esc
            if model.tool == .place { model.clip = nil; model.tool = .area; overlay.hover = nil; return }
        }
        super.keyDown(with: event)
    }

    // MARK: tools

    private func textRect(at pt: CGPoint, on page: PDFPage) -> CGRect? {
        guard !PageInfo.isScanned(page), let sel = page.selectionForLine(at: pt), !(sel.string ?? "").trimmingCharacters(in: .whitespaces).isEmpty
        else { return nil }
        let r = sel.bounds(for: page)
        return r.insetBy(dx: -1, dy: -1).contains(pt) ? r : nil
    }

    private func handleClick(model: DocumentModel, page: PDFPage, point pt: CGPoint) {
        let fontSize = CGFloat(UserDefaults.standard.double(forKey: "fillFontSize").nonZero ?? 11)
        switch tool {
        case .text:
            openEditor(on: page, rect: CGRect(x: pt.x, y: pt.y - fontSize * 1.3, width: 180, height: fontSize * 1.3),
                       text: "", size: fontSize, color: .black) { text in
                guard !text.trimmingCharacters(in: .whitespaces).isEmpty else { return }
                model.addAnnotations("Add text", page: page,
                                     [Annotations.text(text, at: CGPoint(x: pt.x, y: pt.y - fontSize * 1.3), size: fontSize)])
            }
        case .tick:
            model.addAnnotations("Tick", page: page, [Annotations.tick(at: pt)])
        case .cross:
            model.addAnnotations("Cross", page: page, [Annotations.cross(at: pt)])
        case .date:
            let today = DateFormatter.localizedString(from: Date(), dateStyle: .short, timeStyle: .none)
            model.addAnnotations("Add date", page: page,
                                 [Annotations.text(today, at: CGPoint(x: pt.x, y: pt.y - fontSize * 0.65), size: fontSize)])
        case .sign, .initials:
            let kind: SignatureKind = tool == .sign ? .signature : .initials
            guard let image = SignatureStore.image(kind) else {
                model.signatureSheet = kind
                return
            }
            let maxW: CGFloat = kind == .signature ? 150 : 60, maxH: CGFloat = kind == .signature ? 55 : 32
            let aspect = CGFloat(image.width) / CGFloat(max(1, image.height))
            var w = maxW, h = maxW / aspect
            if h > maxH { h = maxH; w = h * aspect }
            let rect = CGRect(x: pt.x - w / 2, y: pt.y - h / 2, width: w, height: h)
            model.addAnnotations(kind == .signature ? "Sign" : "Initial", page: page, [Annotations.image(image, in: rect)])
        case .editText:
            editText(model: model, page: page, point: pt)
        case .place:
            guard let clip = model.clip else { return }
            let dest = CGRect(origin: CGPoint(x: pt.x, y: pt.y - clip.size.height), size: clip.size)
            var src: [PDFAnnotation] = []
            if clip.isMove {
                src = ScanEditor.erase(page: clip.sourcePage, rect: clip.sourceRect)
                model.forgetOCR(on: clip.sourcePage, in: clip.sourceRect)
            }
            let placed = Annotations.image(clip.image, in: dest)
            page.addAnnotation(placed)
            let srcPage = clip.sourcePage
            model.record(Change(label: clip.isMove ? "Move" : "Copy",
                                undo: { page.removeAnnotation(placed); src.forEach { srcPage.removeAnnotation($0) } },
                                redo: { src.forEach { srcPage.addAnnotation($0) }; page.addAnnotation(placed) }))
            model.clip = nil
            model.tool = .area
            overlay.hover = nil
        default:
            break
        }
    }

    private func editText(model: DocumentModel, page: PDFPage, point pt: CGPoint) {
        let fontName = model.editFont.fontName
        if let rect = textRect(at: pt, on: page), let sel = page.selectionForLine(at: pt), let old = sel.string {
            let size = max(6, rect.height * 0.82)
            openEditor(on: page, rect: rect, text: old, size: size, color: .black) { text in
                guard text != old else { return }
                let added = ScanEditor.replace(page: page, rect: rect, text: text, fontSize: size, fontName: fontName)
                model.addAnnotations("Edit text", page: page, added)
            }
            return
        }
        guard PageInfo.isScanned(page) else {
            model.notify("No text there. Use Add text to write something new.")
            return
        }
        let words = model.ensureOCR(page)
        guard let word = words.first(where: { $0.rect.insetBy(dx: -2, dy: -2).contains(pt) }) else {
            model.notify("No text found there. For handwriting, use Select area.")
            return
        }
        let size = ScanEditor.fontSize(for: word)
        let ink = ScanEditor.sampleColors(page: page, rect: word.rect).ink
        openEditor(on: page, rect: word.rect, text: word.text, size: size, color: ink) { text in
            guard text != word.text else { return }
            let added = ScanEditor.replace(page: page, rect: word.rect, text: text, fontSize: size, fontName: fontName)
            model.addAnnotations("Edit text", page: page, added)
            model.forgetOCR(on: page, in: word.rect)
        }
    }

    private func showAreaMenu(model: DocumentModel, page: PDFPage, rect: CGRect, event: NSEvent) {
        let menu = NSMenu()
        let handler = AreaMenuHandler { [weak self, weak model] action in
            guard let self, let model else { return }
            switch action {
            case "replace":
                let words = model.ocrWords(for: page)?.filter { $0.rect.intersects(rect) } ?? []
                let size = words.first.map(ScanEditor.fontSize) ?? rect.height * 0.72
                let ink = ScanEditor.sampleColors(page: page, rect: rect).ink
                self.openEditor(on: page, rect: rect, text: words.map(\.text).joined(separator: " "), size: size, color: ink) { text in
                    guard !text.isEmpty else { return }
                    let added = ScanEditor.replace(page: page, rect: rect, text: text, fontSize: size, fontName: model.editFont.fontName)
                    model.addAnnotations("Replace", page: page, added)
                    model.forgetOCR(on: page, in: rect)
                }
            case "erase":
                model.addAnnotations("Erase", page: page, ScanEditor.erase(page: page, rect: rect))
                model.forgetOCR(on: page, in: rect)
            case "move", "copy":
                guard let image = ScanEditor.grab(page: page, rect: rect) else { return }
                model.clip = AreaClip(image: image, size: rect.size, sourcePage: page, sourceRect: rect, isMove: action == "move")
                model.tool = .place
                model.notify("Now click where it should go (Esc to cancel)")
            default: break
            }
        }
        for (title, symbol, key) in [("Replace with text…", "character.cursor.ibeam", "replace"), ("Erase", "eraser", "erase"),
                                     ("-", "", ""), ("Move", "arrow.up.and.down.and.arrow.left.and.right", "move"),
                                     ("Copy", "doc.on.doc", "copy")] {
            if title == "-" { menu.addItem(.separator()); continue }
            let item = NSMenuItem(title: title, action: #selector(AreaMenuHandler.pick(_:)), keyEquivalent: "")
            item.representedObject = key
            item.target = handler
            item.image = NSImage(systemSymbolName: symbol, accessibilityDescription: nil)
            menu.addItem(item)
        }
        objc_setAssociatedObject(menu, &AreaMenuHandler.key, handler, .OBJC_ASSOCIATION_RETAIN)
        NSMenu.popUpContextMenu(menu, with: event, for: self)
    }

    // MARK: in-page editor

    func openEditor(on page: PDFPage, rect: CGRect, text: String, size: CGFloat, color: NSColor,
                    commit: @escaping (String) -> Void) {
        commitEditor()
        let r = viewRect(rect, on: page)
        let fontPx = size * scaleFactor
        let height = max(r.height, fontPx * 1.45) + 4
        let field = NSTextField(frame: NSRect(x: r.minX - 4, y: r.midY - height / 2, width: max(r.width + 40, 160), height: height))
        field.stringValue = text
        field.font = NSFont(name: "Helvetica", size: fontPx) ?? .systemFont(ofSize: fontPx)
        field.textColor = color
        field.isBordered = false
        field.drawsBackground = true
        field.backgroundColor = NSColor.white.withAlphaComponent(0.96)
        field.focusRingType = .none
        field.wantsLayer = true
        field.layer?.borderColor = NSColor.controlAccentColor.cgColor
        field.layer?.borderWidth = 1.5
        field.layer?.cornerRadius = 3
        field.delegate = self
        addSubview(field)
        window?.makeFirstResponder(field)
        field.currentEditor()?.selectAll(nil)
        editor = field
        editorCommit = commit
    }

    func commitEditor() {
        guard let field = editor else { return }
        let text = field.stringValue
        let commit = editorCommit
        editor = nil
        editorCommit = nil
        field.removeFromSuperview()
        commit?(text)
    }

    private func cancelEditor() {
        editor?.removeFromSuperview()
        editor = nil
        editorCommit = nil
    }

    func control(_ control: NSControl, textView: NSTextView, doCommandBy selector: Selector) -> Bool {
        if selector == #selector(NSResponder.insertNewline(_:)) { commitEditor(); return true }
        if selector == #selector(NSResponder.cancelOperation(_:)) { cancelEditor(); return true }
        return false
    }

    func controlTextDidChange(_ obj: Notification) {
        guard let field = editor else { return }
        let needed = (field.stringValue as NSString).size(withAttributes: [.font: field.font as Any]).width + 30
        if needed > field.frame.width { field.frame.size.width = needed }
    }

    override func scrollWheel(with event: NSEvent) {
        commitEditor()
        super.scrollWheel(with: event)
    }
}

/// Draws hover and selection rectangles above the pages.
final class OverlayView: NSView {
    var hover: NSRect? { didSet { needsDisplay = true } }
    var selection: NSRect? { didSet { needsDisplay = true } }
    var selectionIsErase = false

    override func hitTest(_ point: NSPoint) -> NSView? { nil }
    // use the same coordinate orientation as the PDFView we sit in
    override var isFlipped: Bool { superview?.isFlipped ?? false }

    override func draw(_ dirtyRect: NSRect) {
        let accent = NSColor.controlAccentColor
        if let hover {
            let p = NSBezierPath(roundedRect: hover, xRadius: 3, yRadius: 3)
            accent.withAlphaComponent(0.1).setFill()
            p.fill()
            accent.setStroke()
            p.lineWidth = 1.5
            p.stroke()
        }
        if let selection {
            let color = selectionIsErase ? NSColor.systemRed : accent
            let p = NSBezierPath(rect: selection)
            color.withAlphaComponent(0.12).setFill()
            p.fill()
            color.setStroke()
            p.lineWidth = 1.5
            p.setLineDash([5, 3], count: 2, phase: 0)
            p.stroke()
        }
    }
}

final class AreaMenuHandler: NSObject {
    static var key: UInt8 = 0
    let action: (String) -> Void
    init(_ action: @escaping (String) -> Void) { self.action = action }
    @objc func pick(_ sender: NSMenuItem) { action(sender.representedObject as? String ?? "") }
}

private extension Double {
    var nonZero: Double? { self == 0 ? nil : self }
}

// MARK: - SwiftUI wrappers

struct PDFKitView: NSViewRepresentable {
    @ObservedObject var model: DocumentModel

    func makeNSView(context: Context) -> PaperPDFView {
        let v = PaperPDFView(frame: .zero)
        v.model = model
        v.autoScales = true
        v.displayMode = .singlePageContinuous
        v.displaysPageBreaks = true
        v.pageShadowsEnabled = true
        v.backgroundColor = NSColor(Theme.canvas)
        v.document = model.document
        model.pdfView = v
        NotificationCenter.default.addObserver(forName: .PDFViewPageChanged, object: v, queue: .main) { [weak v] _ in
            guard let v, let page = v.currentPage, let doc = v.document else { return }
            MainActor.assumeIsolated {
                let i = doc.index(for: page)
                if model.pageIndex != i {
                    model.pageIndex = i
                    if model.tool == .editText { model.prepareOCRForCurrentPage() }
                }
            }
        }
        return v
    }

    func updateNSView(_ v: PaperPDFView, context: Context) {
        if v.document !== model.document {
            v.document = model.document
            v.autoScales = true
        } else {
            v.layoutDocumentView()
            v.needsDisplay = true
        }
        if let doc = model.document, let page = doc.page(at: model.pageIndex), v.currentPage != page,
           context.coordinator.lastRequested != model.pageIndex {
            v.go(to: page)
        }
        context.coordinator.lastRequested = model.pageIndex
    }

    func makeCoordinator() -> Coordinator { Coordinator() }
    final class Coordinator { var lastRequested = -1 }
}

struct ThumbnailsView: NSViewRepresentable {
    @ObservedObject var model: DocumentModel

    func makeNSView(context: Context) -> PDFThumbnailView {
        let t = PDFThumbnailView()
        t.thumbnailSize = CGSize(width: 120, height: 150)
        t.backgroundColor = .clear
        t.pdfView = model.pdfView
        return t
    }

    func updateNSView(_ t: PDFThumbnailView, context: Context) {
        if t.pdfView !== model.pdfView { t.pdfView = model.pdfView }
    }
}
