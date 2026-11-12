import AppKit
import SwiftUI

/// One window per PDF, shown by macOS as tabs of a single window.
///
/// Every way of opening a file (Open…, Finder, drag and drop, Recent) goes
/// through `open(_:from:)`. A file that is already open just brings its tab to
/// the front; otherwise it goes into the window it was opened from if that one
/// is empty, or a new tab. New tabs are asked for with SwiftUI's `openWindow`
/// and pick up their file from `pending` when they appear.
@MainActor
final class WindowRouter {
    static let shared = WindowRouter()

    private struct Entry { weak var model: DocumentModel? }
    private var entries: [Entry] = []
    private var pending: [URL] = []
    /// Tabs asked for that haven't appeared yet, so each pending file gets exactly one.
    private var requested = 0
    /// Files sent by the Finder "Compress with PaperLite" action before any window existed.
    private var pendingCompress: [URL] = []

    var openWindow: OpenWindowAction?

    var models: [DocumentModel] { entries.compactMap(\.model) }

    /// The tab the person is looking at.
    var frontModel: DocumentModel? {
        models.first { $0.window?.isKeyWindow == true } ?? models.first { $0.window?.isMainWindow == true } ?? models.first
    }

    /// Called by each window as it appears. Returns the file it should show, if any.
    func register(_ model: DocumentModel) -> URL? {
        entries.removeAll { $0.model == nil }
        entries.append(Entry(model: model))
        if requested > 0 { requested -= 1 }
        let url = pending.isEmpty ? nil : pending.removeFirst()
        if !pendingCompress.isEmpty {
            model.compressFiles = pendingCompress
            model.showCompress = true
            pendingCompress = []
        }
        requestTabs()
        return url
    }

    func open(_ urls: [URL], from source: DocumentModel?) {
        var empty = source?.document == nil ? source : nil
        for url in urls where url.pathExtension.lowercased() == "pdf" {
            if let existing = models.first(where: { $0.url?.standardizedFileURL == url.standardizedFileURL }) {
                existing.window?.makeKeyAndOrderFront(nil)
            } else if let target = empty {
                target.open(url)
                empty = nil
            } else {
                pending.append(url)
            }
        }
        requestTabs()
    }

    /// Show the Compress window for files picked in Finder.
    func compress(_ urls: [URL]) {
        let pdfs = urls.filter { $0.pathExtension.lowercased() == "pdf" }
        guard !pdfs.isEmpty else { return }
        NSApp.activate(ignoringOtherApps: true)
        if let model = frontModel {
            model.window?.makeKeyAndOrderFront(nil)
            model.compressFiles = pdfs
            model.showCompress = true
        } else {
            pendingCompress = pdfs
        }
    }

    /// After a compress has replaced files, reload any tab showing one of them.
    func reload(_ urls: [URL]) {
        let paths = Set(urls.map(\.standardizedFileURL))
        for model in models where !model.isDirty {
            if let url = model.url, paths.contains(url.standardizedFileURL) { model.open(url) }
        }
    }

    /// Ask every tab with unsaved changes. False if the person cancelled.
    func confirmDiscardAll() -> Bool {
        models.filter(\.isDirty).allSatisfy { model in
            model.window?.makeKeyAndOrderFront(nil)
            return model.confirmDiscardChanges()
        }
    }

    private func requestTabs() {
        guard let openWindow else { return }
        while requested < pending.count {
            requested += 1
            openWindow(id: "document")
        }
    }
}

/// Gives the model its NSWindow, makes new windows open as tabs, and asks
/// before a tab with unsaved changes is closed.
struct WindowAccessor: NSViewRepresentable {
    let model: DocumentModel

    func makeNSView(context: Context) -> NSView {
        let view = NSView()
        DispatchQueue.main.async { attach(view.window) }
        return view
    }

    func updateNSView(_ view: NSView, context: Context) {
        DispatchQueue.main.async { attach(view.window) }
    }

    private func attach(_ window: NSWindow?) {
        guard let window, model.window !== window else { return }
        model.window = window
        window.tabbingIdentifier = "PaperLiteDocument"
        window.tabbingMode = .preferred
        // Reopening yesterday's tabs empty is no help, and their files may need permission again.
        window.isRestorable = false
        model.closeGuard.install(on: window, model: model)
    }
}

/// SwiftUI owns the window's delegate, so this sits in front of it, answers
/// `windowShouldClose`, and passes every other message straight through.
final class CloseGuard: NSObject, NSWindowDelegate {
    private weak var original: NSWindowDelegate?
    private weak var model: DocumentModel?

    @MainActor func install(on window: NSWindow, model: DocumentModel) {
        guard window.delegate !== self else { return }
        original = window.delegate
        self.model = model
        window.delegate = self
    }

    func windowShouldClose(_ sender: NSWindow) -> Bool {
        let allowed = MainActor.assumeIsolated { () -> Bool in
            guard let model, model.confirmDiscardChanges() else { return model == nil }
            // Saved or discarded: don't ask again when the app quits.
            model.isDirty = false
            return true
        }
        guard allowed else { return false }
        return original?.windowShouldClose?(sender) ?? true
    }

    override func responds(to selector: Selector!) -> Bool {
        super.responds(to: selector) || (original?.responds(to: selector) ?? false)
    }

    override func forwardingTarget(for selector: Selector!) -> Any? {
        original?.responds(to: selector) == true ? original : super.forwardingTarget(for: selector)
    }
}
