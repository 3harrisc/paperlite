import AppKit
import SwiftUI

@main
struct PaperLiteApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @StateObject private var model = DocumentModel()

    var body: some Scene {
        Window("PaperLite", id: "main") {
            ContentView()
                .environmentObject(model)
                .onAppear { appDelegate.model = model; appDelegate.openPending() }
        }
        .defaultSize(width: 1280, height: 860)
        .commands {
            CommandGroup(replacing: .newItem) {
                Button("Open…") { model.openPanel() }.keyboardShortcut("o")
                Menu("Open Recent") {
                    ForEach(model.recent, id: \.self) { url in
                        Button(url.lastPathComponent) { if model.confirmDiscardChanges() { model.open(url) } }
                    }
                }
            }
            CommandGroup(replacing: .saveItem) {
                Button("Save") { model.save() }.keyboardShortcut("s").disabled(model.document == nil)
                Button("Save As…") { model.saveAs() }.keyboardShortcut("s", modifiers: [.command, .shift]).disabled(model.document == nil)
                Divider()
                Button("Compress…") { model.compressCurrent() }.keyboardShortcut("c", modifiers: [.command, .shift])
                Button("Combine Files…") { model.compressFiles = model.url.map { [$0] } ?? []; model.showCombine = true }
            }
            CommandGroup(replacing: .printItem) {
                Button("Print…") { model.pdfView?.print(with: NSPrintInfo.shared, autoRotate: true) }.keyboardShortcut("p").disabled(model.document == nil)
            }
            CommandGroup(replacing: .undoRedo) {
                Button(model.canUndo ? "Undo \(model.undoLabel)" : "Undo") { model.undo() }
                    .keyboardShortcut("z").disabled(!model.canUndo)
                Button(model.canRedo ? "Redo \(model.redoLabel)" : "Redo") { model.redo() }
                    .keyboardShortcut("z", modifiers: [.command, .shift]).disabled(!model.canRedo)
            }
            CommandMenu("Tools") {
                ForEach(AppSection.allCases) { s in
                    Button(s.title) { model.show(s) }
                }
            }
            CommandGroup(after: .toolbar) {
                Button("Zoom In") { model.pdfView?.zoomIn(nil) }.keyboardShortcut("+")
                Button("Zoom Out") { model.pdfView?.zoomOut(nil) }.keyboardShortcut("-")
                Button("Fit Width") { model.pdfView?.autoScales = true }.keyboardShortcut("0")
            }
        }
    }
}

/// Handles files opened from Finder ("Open With", double-click) and quitting with unsaved changes.
@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    weak var model: DocumentModel?
    private var pending: [URL] = []

    func application(_ application: NSApplication, open urls: [URL]) {
        pending = urls
        openPending()
    }

    func openPending() {
        guard let model, let url = pending.first(where: { $0.pathExtension.lowercased() == "pdf" }) else { return }
        pending = []
        if model.confirmDiscardChanges() { model.open(url) }
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        (model?.confirmDiscardChanges() ?? true) ? .terminateNow : .terminateCancel
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
}
