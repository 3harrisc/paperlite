import AppKit
import SwiftUI

/// One window per PDF, shown by macOS as tabs of a single window.
///
/// Every way of opening a file (Open…, Finder, drag and drop, Recent) goes
/// through `open(_:from:)`. A file that is already open just brings its tab to
/// the front; otherwise it goes into the window it was opened from if that one
/// is empty, or a new tab. New tabs are asked for with SwiftUI's `openWindow`
/// and pick up their file from `pending` when they appear.
///
/// SwiftUI also opens a window of its own for every file that arrives from
/// Finder, before AppDelegate hears about it. Those are used like any other empty
/// tab, and `tidy()` closes whatever is left empty afterwards.
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
        // onAppear runs again when a window is moved into a tab group; only count it once.
        guard !models.contains(where: { $0 === model }) else { return nil }
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
        scheduleTidy()
        return url
    }

    func open(_ urls: [URL], from source: DocumentModel?) {
        // Empty tabs first (the one it came from, then any other), then new tabs.
        var empty = models.filter { $0.document == nil && !$0.hasSheet }
        if let source, let i = empty.firstIndex(where: { $0 === source }) { empty.insert(empty.remove(at: i), at: 0) }
        for url in urls where url.pathExtension.lowercased() == "pdf" {
            if let existing = models.first(where: { $0.url?.standardizedFileURL == url.standardizedFileURL }) {
                existing.window?.makeKeyAndOrderFront(nil)
            } else if !empty.isEmpty {
                let target = empty.removeFirst()
                target.open(url)
                target.window?.makeKeyAndOrderFront(nil)
            } else {
                pending.append(url)
            }
        }
        requestTabs()
        scheduleTidy()
    }

    /// Show the Compress window for files picked in Finder.
    func compress(_ urls: [URL]) {
        let pdfs = urls.filter { $0.pathExtension.lowercased() == "pdf" }
        guard !pdfs.isEmpty else { return }
        NSApp.activate(ignoringOtherApps: true)
        // Over a tab that has a document, so an empty one SwiftUI just made can be tidied away.
        if let model = models.first(where: { $0.document != nil && $0.window?.isKeyWindow == true })
            ?? models.first(where: { $0.document != nil }) ?? frontModel {
            model.window?.makeKeyAndOrderFront(nil)
            model.compressFiles = pdfs
            model.showCompress = true
        } else {
            pendingCompress = pdfs
        }
        scheduleTidy()
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

    /// Close tabs left empty by routing. Keeps one window, and never closes one
    /// showing a sheet. Waits while tabs are still on their way.
    private func scheduleTidy(attempt: Int = 0) {
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.8) { [self] in
            guard pending.isEmpty || attempt >= 5 else { return scheduleTidy(attempt: attempt + 1) }
            let empty = models.filter { $0.document == nil && !$0.hasSheet }
            let anyInUse = models.contains { $0.document != nil || $0.hasSheet }
            for model in anyInUse ? empty : Array(empty.dropFirst()) { model.window?.close() }
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
    private static let tabbingID = "PaperLiteDocument"

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
        window.tabbingIdentifier = Self.tabbingID
        window.tabbingMode = .preferred
        // Reopening yesterday's tabs empty is no help, and their files may need permission again.
        window.isRestorable = false
        model.closeGuard.install(on: window, model: model)

        // By the time SwiftUI hands us the window it is already on screen, so
        // tabbingMode alone is too late. Move it into an existing window's tabs.
        let host = NSApp.windows.first {
            $0 !== window && $0.tabbingIdentifier == Self.tabbingID && $0.isVisible
        }
        if let host, !(host.tabbedWindows?.contains(window) ?? false) {
            host.addTabbedWindow(window, ordered: .above)
            window.makeKeyAndOrderFront(nil)
        }
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

