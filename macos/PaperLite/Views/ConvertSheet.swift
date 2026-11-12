import AppKit
import PDFKit
import SwiftUI

/// Convert the open PDF to Word or Excel. Wording matches the Windows app's
/// convert_dialog.py.
struct ConvertSheet: View {
    @EnvironmentObject var model: DocumentModel
    @Environment(\.dismiss) private var dismiss
    @AppStorage("convertKind") private var savedKind = ConvertKind.word.rawValue
    @State var kind: ConvertKind
    @State private var running = false
    @State private var progress = 0.0
    @State private var status = ""
    @State private var result: String?
    @State private var warnings: [String] = []
    @State private var error: String?
    @State private var output: URL?

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .top, spacing: 12) {
                IconBadge(symbol: "arrow.left.arrow.right", tint: Theme.accent, size: 40)
                VStack(alignment: .leading, spacing: 2) {
                    Text("Convert PDF").font(.headline)
                    Text("Turn a PDF into a file you can edit in Word or Excel.").font(.callout).foregroundStyle(.secondary)
                }
            }
            SectionLabel("File")
            HStack {
                Image(systemName: "doc.text").foregroundStyle(.secondary)
                Text(model.fileName).lineLimit(1).truncationMode(.middle)
            }
            SectionLabel("Convert to")
            Picker("", selection: $kind) {
                ForEach(ConvertKind.allCases) { k in
                    VStack(alignment: .leading, spacing: 1) {
                        Text(k.title).fontWeight(.semibold)
                        Text(k.detail).font(.callout).foregroundStyle(.secondary)
                    }
                    .padding(.vertical, 3)
                    .tag(k)
                }
            }
            .pickerStyle(.radioGroup)
            .labelsHidden()
            .disabled(running)

            if running {
                ProgressView(value: progress)
                Text(status).font(.callout).foregroundStyle(.secondary)
            }
            if let result {
                VStack(alignment: .leading, spacing: 4) {
                    Text("✓ " + result).font(.callout)
                    ForEach(warnings, id: \.self) { Text("• " + $0).font(.callout).foregroundStyle(.secondary) }
                }
                .textSelection(.enabled)
            }
            if let error {
                Text(error).font(.callout).foregroundStyle(.red).textSelection(.enabled)
            }

            HStack {
                Spacer()
                Button("Close") { dismiss() }.keyboardShortcut(.cancelAction).disabled(running)
                if let output {
                    Button(result == nil ? "Convert" : "Convert again") { start() }.disabled(running)
                    Button("Open") { NSWorkspace.shared.open(output) }
                        .keyboardShortcut(.defaultAction)
                        .buttonStyle(.borderedProminent)
                        .tint(Theme.brand)
                } else {
                    Button("Convert") { start() }
                        .keyboardShortcut(.defaultAction)
                        .buttonStyle(.borderedProminent)
                        .tint(Theme.brand)
                        .disabled(running || model.url == nil)
                }
            }
        }
        .padding(22)
        .frame(width: 540)
    }

    private func start() {
        savedKind = kind.rawValue
        guard let source = model.url else { return }
        let panel = NSSavePanel()
        panel.allowedContentTypes = [kind == .word ? .init(filenameExtension: "docx")! : .init(filenameExtension: "xlsx")!]
        panel.directoryURL = source.deletingLastPathComponent()
        panel.nameFieldStringValue = source.deletingPathExtension().lastPathComponent + "." + kind.fileExtension
        guard panel.runModal() == .OK, let dest = panel.url else { return }

        // Converted from the file as saved (convertCurrent saves edits first), on its own
        // copy so the view's document is never touched off the main thread.
        guard let doc = PDFDocument(url: source) else {
            error = "This file couldn't be opened as a PDF."
            return
        }
        if doc.isLocked {
            guard let pw = model.askPassword(reason: "Enter the password to convert it.") else { return }
            guard doc.unlock(withPassword: pw) else {
                error = "That password isn't right."
                return
            }
        }

        running = true
        progress = 0
        result = nil
        warnings = []
        error = nil
        let kind = kind
        Task.detached(priority: .userInitiated) {
            do {
                let r = try Converter.convert(kind, document: doc, to: dest) { done, total, text in
                    Task { @MainActor in
                        progress = total == 0 ? 1 : Double(done) / Double(total)
                        status = text
                    }
                }
                await MainActor.run {
                    result = r.summary(kind: kind)
                    warnings = r.warnings
                    output = r.output
                    running = false
                }
            } catch let e {
                await MainActor.run {
                    error = e.localizedDescription
                    running = false
                }
            }
        }
    }
}
