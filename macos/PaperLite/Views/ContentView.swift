import PDFKit
import SwiftUI
import UniformTypeIdentifiers

struct ContentView: View {
    @EnvironmentObject var model: DocumentModel

    var body: some View {
        HStack(spacing: 0) {
            ToolRail()
            Divider()
            if model.document != nil, [.view, .fill, .edit].contains(model.section) {
                SidePanel()
                    .frame(width: model.section == .view ? 190 : 260)
                Divider()
            }
            main
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .overlay(alignment: .bottom) { ToastView() }
        .toolbar { toolbar }
        .navigationTitle(model.fileName.isEmpty ? "PaperLite" : model.fileName)
        .navigationSubtitle(model.isDirty ? "Edited" : model.fileSizeText)
        .dropDestination(for: URL.self) { urls, _ in
            guard urls.contains(where: { $0.pathExtension.lowercased() == "pdf" }) else { return false }
            WindowRouter.shared.open(urls, from: model)
            return true
        }
        .sheet(isPresented: $model.showCompress) { CompressSheet(files: model.compressFiles) }
        .sheet(isPresented: $model.showCombine) { CombineSheet(files: model.compressFiles) }
        .sheet(item: $model.convertSheet) { kind in ConvertSheet(kind: kind) }
        .sheet(item: $model.signatureSheet) { kind in
            SignatureSheet(kind: kind) { model.revision += 1 }
        }
        .sheet(item: $model.pagesSheet) { action in PagesSheet(action: action) }
        .frame(minWidth: 960, minHeight: 620)
    }

    @ViewBuilder private var main: some View {
        switch model.section {
        case .home:
            WelcomeView()
        case .organise:
            OrganiseView()
        default:
            if model.document != nil { PDFKitView(model: model) } else { WelcomeView() }
        }
    }

    @ToolbarContentBuilder private var toolbar: some ToolbarContent {
        ToolbarItemGroup(placement: .primaryAction) {
            Button { model.openPanel() } label: { Label("Open", systemImage: "folder") }
                .help("Open (⌘O)")
            Button { model.save() } label: { Label("Save", systemImage: "square.and.arrow.down") }
                .disabled(model.document == nil).help("Save (⌘S)")
            Button { model.pdfView?.print(with: NSPrintInfo.shared, autoRotate: true) } label: { Label("Print", systemImage: "printer") }
                .disabled(model.document == nil).help("Print (⌘P)")
            Divider()
            Button { model.undo() } label: { Label("Undo", systemImage: "arrow.uturn.backward") }
                .disabled(!model.canUndo).help(model.canUndo ? "Undo \(model.undoLabel)" : "Undo")
            Button { model.redo() } label: { Label("Redo", systemImage: "arrow.uturn.forward") }
                .disabled(!model.canRedo).help(model.canRedo ? "Redo \(model.redoLabel)" : "Redo")
            Divider()
            Button { model.compressCurrent() } label: {
                Label("Compress", systemImage: "arrow.down.right.and.arrow.up.left")
                    .labelStyle(.titleAndIcon)
            }
            .buttonStyle(.borderedProminent)
            .tint(Theme.brand)
            .help("Make this PDF smaller (⇧⌘C)")
        }
    }
}

// MARK: - Tool rail

struct ToolRail: View {
    @EnvironmentObject var model: DocumentModel

    var body: some View {
        VStack(spacing: 4) {
            ForEach(AppSection.allCases) { s in
                RailButton(symbol: s.symbol, title: s.title, selected: model.section == s) { model.show(s) }
            }
            Divider().frame(width: 40).padding(.vertical, 6)
            RailButton(symbol: "arrow.down.right.and.arrow.up.left", title: "Compress", selected: false) { model.compressCurrent() }
            RailButton(symbol: "arrow.left.arrow.right", title: "Convert", selected: false) { model.convertCurrent() }
            RailButton(symbol: "rectangle.stack.badge.plus", title: "Combine", selected: false) {
                model.compressFiles = model.url.map { [$0] } ?? []
                model.showCombine = true
            }
            Spacer()
        }
        .padding(.vertical, 10)
        .padding(.horizontal, 6)
        .frame(width: 82)
        .background(Theme.panel)
    }
}

struct RailButton: View {
    let symbol: String
    let title: String
    let selected: Bool
    let action: () -> Void
    @State private var hover = false

    var body: some View {
        Button(action: action) {
            VStack(spacing: 4) {
                Image(systemName: symbol).font(.system(size: 18, weight: .regular)).frame(height: 22)
                Text(title).font(.system(size: 10, weight: selected ? .semibold : .regular)).lineLimit(1)
            }
            .frame(width: 70, height: 56)
            .foregroundStyle(selected ? Theme.accent : .secondary)
            .background(RoundedRectangle(cornerRadius: 9, style: .continuous)
                .fill(selected ? Theme.accent.opacity(0.12) : (hover ? Color.primary.opacity(0.06) : .clear)))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .onHover { hover = $0 }
    }
}

// MARK: - Side panels

struct SidePanel: View {
    @EnvironmentObject var model: DocumentModel

    var body: some View {
        Group {
            switch model.section {
            case .view:
                VStack(alignment: .leading, spacing: 8) {
                    Text("Pages").font(.headline).padding(.horizontal, 14).padding(.top, 14)
                    ThumbnailsView(model: model)
                }
            case .fill:
                ToolPanel(title: "Fill & Sign", hint: "Pick a tool, then click on the page. Form fields can be clicked in any tool.") {
                    ToolRow(.select, "cursorarrow", "Fill form fields")
                    ToolRow(.text, "textformat", "Add text")
                    ToolRow(.tick, "checkmark", "Tick")
                    ToolRow(.cross, "xmark", "Cross")
                    ToolRow(.date, "calendar", "Today's date")
                    SectionLabel("Signature").padding(.top, 12)
                    ToolRow(.sign, "signature", "Sign")
                    SignatureCard(kind: .signature)
                    ToolRow(.initials, "pencil.line", "Initials")
                    SignatureCard(kind: .initials)
                }
            case .edit:
                ToolPanel(title: "Edit PDF", hint: "Works on normal PDFs and on scans — including handwriting.") {
                    ToolRow(.editText, "character.cursor.ibeam", "Edit text")
                    ToolRow(.text, "textformat", "Add text")
                    ToolRow(.area, "rectangle.dashed", "Select area")
                    ToolRow(.erase, "eraser", "Erase")
                    SectionLabel("Text style").padding(.top, 12)
                    Picker("", selection: $model.editFont) {
                        ForEach(EditFont.allCases) { Text($0.title).tag($0) }
                    }
                    .labelsHidden()
                    if !model.ocrStatus.isEmpty {
                        Text(model.ocrStatus).font(.callout).foregroundStyle(.secondary).padding(.top, 8)
                    }
                }
            default:
                EmptyView()
            }
        }
        .frame(maxHeight: .infinity, alignment: .top)
        .background(Theme.panel)
    }
}

struct ToolPanel<Content: View>: View {
    @EnvironmentObject var model: DocumentModel
    let title: String
    let hint: String
    @ViewBuilder let content: Content

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 4) {
                Text(title).font(.title3.weight(.semibold))
                Text(hint).font(.callout).foregroundStyle(.secondary).padding(.bottom, 10)
                content
                Text(model.tool.hint).font(.callout).foregroundStyle(.secondary).padding(.top, 14)
            }
            .padding(16)
        }
    }
}

struct ToolRow: View {
    @EnvironmentObject var model: DocumentModel
    let tool: Tool
    let symbol: String
    let title: String
    @State private var hover = false

    init(_ tool: Tool, _ symbol: String, _ title: String) {
        self.tool = tool
        self.symbol = symbol
        self.title = title
    }

    var body: some View {
        let selected = model.tool == tool
        Button { model.choose(tool) } label: {
            HStack(spacing: 10) {
                Image(systemName: symbol).frame(width: 20)
                Text(title).fontWeight(.medium)
                Spacer()
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 8)
            .foregroundStyle(selected ? Theme.accent : .primary)
            .background(RoundedRectangle(cornerRadius: 8, style: .continuous)
                .fill(selected ? Theme.accent.opacity(0.12) : (hover ? Color.primary.opacity(0.05) : .clear)))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .onHover { hover = $0 }
    }
}

struct SignatureCard: View {
    @EnvironmentObject var model: DocumentModel
    let kind: SignatureKind

    var body: some View {
        let _ = model.revision
        let image = SignatureStore.image(kind)
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(kind == .signature ? "Your signature" : "Your initials").font(.caption).foregroundStyle(.secondary)
                Spacer()
                Button(image == nil ? "Create" : "Change") { model.signatureSheet = kind }
                    .buttonStyle(.link).font(.caption)
            }
            Group {
                if let image {
                    Image(decorative: image, scale: 3).resizable().scaledToFit()
                } else {
                    Text("Not created yet").font(.caption).foregroundStyle(.tertiary)
                }
            }
            .frame(maxWidth: .infinity, minHeight: 40, maxHeight: 44)
        }
        .padding(10)
        .background(RoundedRectangle(cornerRadius: 8).fill(Color.primary.opacity(0.03)))
        .overlay(RoundedRectangle(cornerRadius: 8).strokeBorder(style: StrokeStyle(lineWidth: 1, dash: [4, 3])).foregroundStyle(Theme.border))
        .padding(.bottom, 6)
    }
}

// MARK: - Toast

struct ToastView: View {
    @EnvironmentObject var model: DocumentModel

    var body: some View {
        if let t = model.toast {
            HStack(spacing: 8) {
                Image(systemName: t.success ? "checkmark.circle.fill" : "info.circle")
                    .foregroundStyle(t.success ? .green : .secondary)
                Text(t.text)
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 10)
            .background(.regularMaterial, in: Capsule())
            .shadow(color: .black.opacity(0.15), radius: 12, y: 4)
            .padding(.bottom, 28)
            .transition(.move(edge: .bottom).combined(with: .opacity))
            .id(t.id)
        }
    }
}
