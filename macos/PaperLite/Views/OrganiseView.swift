import PDFKit
import SwiftUI
import UniformTypeIdentifiers

struct OrganiseView: View {
    @EnvironmentObject var model: DocumentModel
    @State private var selection = Set<Int>()
    @State private var dragging: Int?

    var body: some View {
        VStack(spacing: 0) {
            bar
            Divider()
            ScrollView {
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 170), spacing: 18)], spacing: 22) {
                    let _ = model.revision
                    ForEach(0..<(model.document?.pageCount ?? 0), id: \.self) { i in
                        PageThumb(index: i, selected: selection.contains(i))
                            .onTapGesture { tap(i) }
                            .onTapGesture(count: 2) { model.pageIndex = i; model.show(.view) }
                            .draggable(String(i)) { PageThumb(index: i, selected: true).frame(width: 120) }
                            .dropDestination(for: String.self) { items, _ in
                                guard let s = items.first, let from = Int(s) else { return false }
                                move(from: from, to: i)
                                return true
                            }
                    }
                }
                .padding(24)
            }
            .background(Theme.canvas)
            .onDeleteCommand { act("delete") }
        }
    }

    private var bar: some View {
        HStack(spacing: 6) {
            Text("Organise pages").font(.headline)
            Text(selection.isEmpty ? "\(model.document?.pageCount ?? 0) pages · drag to reorder, ⌘-click to select several"
                                   : "\(selection.count) of \(model.document?.pageCount ?? 0) pages selected")
                .font(.callout).foregroundStyle(.secondary).padding(.leading, 10)
            Spacer()
            barButton("rotate.left", help: "Rotate left") { act("rotateLeft") }
            barButton("rotate.right", help: "Rotate right") { act("rotateRight") }
            barButton("trash", help: "Delete selected pages") { act("delete") }
            Menu {
                Button("Pages from a file…") { act("insertFile") }
                Button("Blank page") { act("insertBlank") }
            } label: { Label("Insert", systemImage: "doc.badge.plus") }
                .menuStyle(.borderlessButton).fixedSize()
            Button { model.pagesSheet = .extract } label: { Label("Extract", systemImage: "doc.on.doc") }
            Button { model.pagesSheet = .exportImages } label: { Label("Export images", systemImage: "photo") }
            Button { model.pagesSheet = .split } label: { Label("Split", systemImage: "scissors") }
            Button("Done") { model.show(.view) }
                .buttonStyle(.borderedProminent).tint(Theme.accent).padding(.leading, 8)
        }
        .buttonStyle(.borderless)
        .padding(.horizontal, 16)
        .padding(.vertical, 10)
        .background(Theme.panel)
        .onChange(of: selection) { _, new in OrganiseSelection.current = Array(new).sorted() }
    }

    private func barButton(_ symbol: String, help: String, action: @escaping () -> Void) -> some View {
        Button(action: action) { Image(systemName: symbol).frame(width: 26, height: 22) }.help(help)
    }

    private func tap(_ i: Int) {
        if NSEvent.modifierFlags.contains(.command) {
            if selection.contains(i) { selection.remove(i) } else { selection.insert(i) }
        } else if NSEvent.modifierFlags.contains(.shift), let last = selection.max() {
            selection.formUnion(min(last, i)...max(last, i))
        } else {
            selection = [i]
        }
    }

    private func targets() -> [Int] { selection.isEmpty ? [model.pageIndex] : selection.sorted() }

    private func move(from: Int, to: Int) {
        guard let doc = model.document, from != to else { return }
        var order = Array(0..<doc.pageCount)
        let item = order.remove(at: from)
        order.insert(item, at: to)
        model.changePages("Reorder pages") { PageOps.reorder($0, to: order) }
        selection = [to]
    }

    private func act(_ action: String) {
        guard let doc = model.document else { return }
        let sel = targets()
        switch action {
        case "rotateLeft", "rotateRight":
            let delta = action == "rotateLeft" ? -90 : 90
            model.changePages("Rotate") { d in sel.forEach { d.page(at: $0)?.rotation += delta } }
        case "delete":
            guard sel.count < doc.pageCount else { model.notify("A PDF needs at least one page."); return }
            model.changePages("Delete pages") { d in sel.reversed().forEach { d.removePage(at: $0) } }
            selection = []
            model.notify("Deleted \(sel.count) page\(sel.count == 1 ? "" : "s")", success: true)
        case "insertBlank":
            let at = (sel.max() ?? doc.pageCount - 1) + 1
            model.changePages("Insert blank page") { d in d.insert(PageOps.blankPage(like: d.page(at: at - 1)), at: at) }
        case "insertFile":
            let panel = NSOpenPanel()
            panel.allowedContentTypes = [.pdf, .image]
            guard panel.runModal() == .OK, let url = panel.url else { return }
            let at = (sel.max() ?? doc.pageCount - 1) + 1
            model.changePages("Insert pages") { d in
                for (n, p) in try PageOps.pages(from: url).enumerated() { d.insert(p, at: at + n) }
            }
        default: break
        }
    }
}

/// Selection shared with the Extract / Export / Split sheet.
enum OrganiseSelection {
    static var current: [Int] = []
}

struct PageThumb: View {
    @EnvironmentObject var model: DocumentModel
    let index: Int
    let selected: Bool

    var body: some View {
        VStack(spacing: 8) {
            if let page = model.document?.page(at: index) {
                let _ = model.revision
                Image(nsImage: page.thumbnail(of: CGSize(width: 340, height: 440), for: .mediaBox))
                    .resizable()
                    .scaledToFit()
                    .frame(height: 210)
                    .background(.white)
                    .shadow(color: .black.opacity(0.18), radius: 4, y: 2)
            }
            Text("\(index + 1)").font(.callout).foregroundStyle(selected ? Theme.accent : .secondary)
        }
        .padding(10)
        .background(RoundedRectangle(cornerRadius: 10).fill(selected ? Theme.accent.opacity(0.12) : .clear))
        .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(selected ? Theme.accent : .clear, lineWidth: 2))
        .contentShape(Rectangle())
    }
}
