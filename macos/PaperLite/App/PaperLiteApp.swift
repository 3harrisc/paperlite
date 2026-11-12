import AppKit
import SwiftUI

@main
struct PaperLiteApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate

    var body: some Scene {
        // One window per PDF; WindowAccessor makes macOS show them as tabs.
        WindowGroup("PaperLite", id: "document") {
            DocumentWindow()
        }
        .defaultSize(width: 1280, height: 860)
        .commands { AppCommands() }
    }
}

/// A window (tab) with its own document.
private struct DocumentWindow: View {
    @StateObject private var model = DocumentModel()
    @Environment(\.openWindow) private var openWindow

    var body: some View {
        ContentView()
            .environmentObject(model)
            .focusedSceneObject(model)
            .background(WindowAccessor(model: model))
            .onAppear {
                let router = WindowRouter.shared
                router.openWindow = openWindow
                if let url = router.register(model) { model.open(url) }
            }
    }
}

/// Menu commands act on the tab in front.
private struct AppCommands: Commands {
    @FocusedObject private var focused: DocumentModel?

    var body: some Commands {
        CommandGroup(replacing: .newItem) {
            Button("Open…") { focused?.openPanel() }.keyboardShortcut("o")
            Menu("Open Recent") {
                ForEach(RecentFiles.load(), id: \.self) { url in
                    Button(url.lastPathComponent) { WindowRouter.shared.open([url], from: focused) }
                }
            }
        }
        CommandGroup(replacing: .saveItem) {
            Button("Save") { focused?.save() }.keyboardShortcut("s").disabled(focused?.document == nil)
            Button("Save As…") { focused?.saveAs() }.keyboardShortcut("s", modifiers: [.command, .shift]).disabled(focused?.document == nil)
            Divider()
            Button("Compress…") { focused?.compressCurrent() }.keyboardShortcut("c", modifiers: [.command, .shift])
            Button("Combine Files…") { focused?.compressFiles = focused?.url.map { [$0] } ?? []; focused?.showCombine = true }
        }
        CommandGroup(replacing: .printItem) {
            Button("Print…") { focused?.pdfView?.print(with: NSPrintInfo.shared, autoRotate: true) }.keyboardShortcut("p").disabled(focused?.document == nil)
        }
        CommandGroup(replacing: .undoRedo) {
            Button(focused?.canUndo == true ? "Undo \(focused?.undoLabel ?? "")" : "Undo") { focused?.undo() }
                .keyboardShortcut("z").disabled(focused?.canUndo != true)
            Button(focused?.canRedo == true ? "Redo \(focused?.redoLabel ?? "")" : "Redo") { focused?.redo() }
                .keyboardShortcut("z", modifiers: [.command, .shift]).disabled(focused?.canRedo != true)
        }
        CommandMenu("Tools") {
            ForEach(AppSection.allCases) { s in
                Button(s.title) { focused?.show(s) }.disabled(focused == nil)
            }
        }
        CommandGroup(after: .toolbar) {
            Button("Zoom In") { focused?.pdfView?.zoomIn(nil) }.keyboardShortcut("+")
            Button("Zoom Out") { focused?.pdfView?.zoomOut(nil) }.keyboardShortcut("-")
            Button("Fit Width") { focused?.pdfView?.autoScales = true }.keyboardShortcut("0")
        }
    }
}

/// Handles files opened from Finder ("Open With", double-click, several at once),
/// the Finder "Compress with PaperLite" action, and quitting with unsaved changes.
@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.servicesProvider = FinderService()
        NSUpdateDynamicServices()
    }

    func application(_ application: NSApplication, open urls: [URL]) {
        let router = WindowRouter.shared
        router.open(urls, from: router.frontModel)
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        WindowRouter.shared.confirmDiscardAll() ? .terminateNow : .terminateCancel
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
}

/// Finder → right-click → Quick Actions → "Compress with PaperLite" (NSServices in Info.plist).
final class FinderService: NSObject {
    @objc func compressFiles(_ pasteboard: NSPasteboard, userData: String?,
                             error: AutoreleasingUnsafeMutablePointer<NSString?>) {
        let urls = pasteboard.readObjects(forClasses: [NSURL.self],
                                          options: [.urlReadingFileURLsOnly: true]) as? [URL] ?? []
        MainActor.assumeIsolated { WindowRouter.shared.compress(urls) }
    }
}
