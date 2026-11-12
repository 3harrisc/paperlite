import AppKit
import PDFKit
import SwiftUI
import UniformTypeIdentifiers

private struct SheetHeader: View {
    let symbol: String
    let title: String
    let text: String
    let tint: Color
    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            IconBadge(symbol: symbol, tint: tint, size: 40)
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(.headline)
                Text(text).font(.callout).foregroundStyle(.secondary)
            }
        }
    }
}

private func fileRow(_ url: URL) -> some View {
    HStack {
        Image(systemName: "doc.text").foregroundStyle(.secondary)
        Text(url.lastPathComponent).lineLimit(1).truncationMode(.middle)
    }
    .help(url.path)
}

private func pickFiles(_ types: [UTType]) -> [URL] {
    let panel = NSOpenPanel()
    panel.allowedContentTypes = types
    panel.allowsMultipleSelection = true
    return panel.runModal() == .OK ? panel.urls : []
}

// MARK: - Compress

struct CompressSheet: View {
    @EnvironmentObject var model: DocumentModel
    @Environment(\.dismiss) private var dismiss
    @State var files: [URL]
    @AppStorage("compressPreset") private var presetID = CompressionPreset.standard.id
    @AppStorage("compressReplace") private var replace = false
    @State private var running = false
    @State private var progress = 0
    @State private var lines: [String] = []
    @State private var results: [CompressionResult] = []

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            SheetHeader(symbol: "arrow.down.right.and.arrow.up.left", title: "Compress PDF",
                        text: "Make files smaller. Scanned documents usually shrink the most.", tint: Theme.brand)
            SectionLabel("Files")
            List { ForEach(files, id: \.self) { fileRow($0) } }
                .frame(height: 90)
                .clipShape(RoundedRectangle(cornerRadius: 8))
            HStack {
                Button("Add Files…") { files += pickFiles([.pdf]) }
                Button("Clear") { files = [] }
            }
            SectionLabel("Compression level")
            Picker("", selection: $presetID) {
                ForEach(CompressionPreset.all) { p in
                    VStack(alignment: .leading, spacing: 1) {
                        Text(p.title).fontWeight(.semibold)
                        Text(p.detail).font(.callout).foregroundStyle(.secondary)
                    }
                    .padding(.vertical, 3)
                    .tag(p.id)
                }
            }
            .pickerStyle(.radioGroup)
            .labelsHidden()
            Toggle("Replace the original files (otherwise saves as “name_compressed.pdf”)", isOn: $replace)
            if running || !lines.isEmpty {
                if running { ProgressView(value: Double(progress), total: Double(max(files.count, 1))) }
                VStack(alignment: .leading, spacing: 4) {
                    ForEach(lines, id: \.self) { Text($0).font(.callout).textSelection(.enabled) }
                }
            }
            HStack {
                Spacer()
                Button("Close") { dismiss() }.keyboardShortcut(.cancelAction).disabled(running)
                Button(lines.isEmpty ? "Compress" : "Compress Again") { start() }
                    .keyboardShortcut(.defaultAction)
                    .buttonStyle(.borderedProminent)
                    .tint(Theme.brand)
                    .disabled(files.isEmpty || running)
            }
        }
        .padding(22)
        .frame(width: 540)
        .onDisappear(perform: offerOpen)
    }

    private func start() {
        let preset = CompressionPreset.all.first { $0.id == presetID } ?? .standard
        let jobs = files.map { url -> (URL, URL) in
            if replace { return (url, url) }
            let name = url.deletingPathExtension().lastPathComponent + "_compressed.pdf"
            return (url, url.deletingLastPathComponent().appendingPathComponent(name))
        }
        running = true
        progress = 0
        lines = []
        results = []
        Task.detached(priority: .userInitiated) {
            for (input, output) in jobs {
                let line: String
                let result: CompressionResult?
                let scoped = input.startAccessingSecurityScopedResource()
                do {
                    let r = try Compressor.compress(input: input, output: output, preset: preset)
                    result = r
                    let f = ByteCountFormatter()
                    line = r.keptOriginal
                        ? "• \(output.lastPathComponent): already small, left unchanged"
                        : "✓ \(output.lastPathComponent): \(f.string(fromByteCount: Int64(r.originalBytes))) → \(f.string(fromByteCount: Int64(r.compressedBytes))) (\(Int(r.savedPercent.rounded()))% smaller)"
                } catch {
                    result = nil
                    line = "✗ \(input.lastPathComponent): \(error.localizedDescription)"
                }
                if scoped { input.stopAccessingSecurityScopedResource() }
                await MainActor.run {
                    lines.append(line)
                    if let result { results.append(result) }
                    progress += 1
                }
            }
            await MainActor.run { running = false }
        }
    }

    private func offerOpen() {
        guard let r = results.last(where: { !$0.keptOriginal }), let current = model.url else { return }
        if r.output == current {
            model.open(current)
        } else if r.input == current {
            model.notify("Saved as \(r.output.lastPathComponent)", success: true)
        }
    }
}

// MARK: - Combine

struct CombineSheet: View {
    @EnvironmentObject var model: DocumentModel
    @Environment(\.dismiss) private var dismiss
    @State var files: [URL]

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            SheetHeader(symbol: "rectangle.stack.badge.plus", title: "Combine files",
                        text: "Join PDFs and images into one PDF. Drag to change the order.", tint: Theme.tints["combine"]!)
            List {
                ForEach(files, id: \.self) { fileRow($0) }
                    .onMove { files.move(fromOffsets: $0, toOffset: $1) }
                    .onDelete { files.remove(atOffsets: $0) }
            }
            .frame(minHeight: 220)
            .clipShape(RoundedRectangle(cornerRadius: 8))
            HStack {
                Button("Add Files…") { files += pickFiles([.pdf, .image]) }
                Text("\(files.count) file\(files.count == 1 ? "" : "s")").foregroundStyle(.secondary)
                Spacer()
                Button("Cancel") { dismiss() }.keyboardShortcut(.cancelAction)
                Button("Combine") { combine() }
                    .keyboardShortcut(.defaultAction)
                    .buttonStyle(.borderedProminent)
                    .tint(Theme.brand)
                    .disabled(files.count < 2)
            }
        }
        .padding(22)
        .frame(width: 540)
    }

    private func combine() {
        let panel = NSSavePanel()
        panel.allowedContentTypes = [.pdf]
        panel.nameFieldStringValue = "Combined.pdf"
        guard panel.runModal() == .OK, let out = panel.url else { return }
        do {
            _ = try PageOps.combine(files, into: out)
            dismiss()
            if model.confirmDiscardChanges() { model.open(out) }
            model.notify("Combined into \(out.lastPathComponent)", success: true)
        } catch {
            model.alert("Couldn't combine the files", error.localizedDescription)
        }
    }
}

// MARK: - Extract / Export images / Split

struct PagesSheet: View {
    @EnvironmentObject var model: DocumentModel
    @Environment(\.dismiss) private var dismiss
    let action: PagesAction
    @State private var range = ""
    @State private var every = 1
    @State private var jpeg = false
    @State private var dpi: CGFloat = 150
    @State private var error = ""

    private var count: Int { model.document?.pageCount ?? 0 }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            SheetHeader(symbol: symbol, title: title, text: subtitle, tint: Theme.tints["organise"]!)
            if action == .split {
                SectionLabel("Pages per file")
                Stepper(value: $every, in: 1...max(1, count)) { Text("\(every) page\(every == 1 ? "" : "s") per file") }
            } else {
                SectionLabel("Pages")
                TextField("e.g. 1-3, 5, 8-", text: $range).textFieldStyle(.roundedBorder)
                Text("This PDF has \(count) pages. Use commas and dashes, e.g. 1-3, 5.").font(.callout).foregroundStyle(.secondary)
            }
            if action == .exportImages {
                SectionLabel("Format")
                HStack {
                    Picker("", selection: $jpeg) {
                        Text("PNG (sharp, larger)").tag(false)
                        Text("JPG (photos, smaller)").tag(true)
                    }.labelsHidden()
                    Picker("", selection: $dpi) {
                        Text("Screen – 96 DPI").tag(CGFloat(96))
                        Text("Standard – 150 DPI").tag(CGFloat(150))
                        Text("Print – 300 DPI").tag(CGFloat(300))
                    }.labelsHidden()
                }
            }
            if !error.isEmpty { Text(error).foregroundStyle(Theme.brand) }
            HStack {
                Spacer()
                Button("Cancel") { dismiss() }.keyboardShortcut(.cancelAction)
                Button(buttonTitle) { run() }
                    .keyboardShortcut(.defaultAction)
                    .buttonStyle(.borderedProminent)
                    .tint(Theme.brand)
            }
        }
        .padding(22)
        .frame(width: 460)
        .onAppear {
            let sel = OrganiseSelection.current
            range = sel.isEmpty ? "1-\(count)" : sel.map { String($0 + 1) }.joined(separator: ", ")
        }
    }

    private var symbol: String { action == .extract ? "doc.on.doc" : action == .split ? "scissors" : "photo" }
    private var title: String { action == .extract ? "Extract pages" : action == .split ? "Split PDF" : "Export as images" }
    private var buttonTitle: String { action == .extract ? "Extract" : action == .split ? "Split" : "Export" }
    private var subtitle: String {
        switch action {
        case .extract: "Save the chosen pages as a new PDF. The original isn't changed."
        case .split: "Break this PDF into several smaller files."
        case .exportImages: "Save pages as picture files."
        }
    }

    private func run() {
        guard let doc = model.document else { return }
        let base = model.url?.deletingPathExtension().lastPathComponent ?? "Document"
        do {
            let pages = action == .split ? [] : try PageOps.parseRanges(range, pageCount: count)
            var files: [URL] = []
            if action == .extract {
                let panel = NSSavePanel()
                panel.allowedContentTypes = [.pdf]
                panel.nameFieldStringValue = "\(base) (extract).pdf"
                guard panel.runModal() == .OK, let out = panel.url else { return }
                try PageOps.extract(doc, pages: pages, to: out)
                files = [out]
            } else {
                let panel = NSOpenPanel()
                panel.canChooseDirectories = true
                panel.canChooseFiles = false
                panel.canCreateDirectories = true
                panel.prompt = "Choose Folder"
                guard panel.runModal() == .OK, let folder = panel.url else { return }
                files = action == .split
                    ? try PageOps.split(doc, every: every, folder: folder, baseName: base)
                    : try PageOps.exportImages(doc, pages: pages, folder: folder, baseName: base, jpeg: jpeg, dpi: dpi)
            }
            dismiss()
            model.notify("Saved \(files.count) file\(files.count == 1 ? "" : "s")", success: true)
            if let first = files.first { NSWorkspace.shared.activateFileViewerSelecting([first]) }
        } catch {
            self.error = error.localizedDescription
        }
    }
}
