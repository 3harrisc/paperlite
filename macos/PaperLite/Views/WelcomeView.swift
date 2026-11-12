import SwiftUI

struct WelcomeView: View {
    @EnvironmentObject var model: DocumentModel
    @State private var dropHover = false

    private let cards: [(key: String, symbol: String, title: String, text: String)] = [
        ("compress", "arrow.down.right.and.arrow.up.left", "Compress PDF", "Make big scans small enough to email."),
        ("fill", "signature", "Fill & Sign", "Fill in forms, add text, sign and initial."),
        ("edit", "text.viewfinder", "Edit PDF", "Change text, even on scanned and handwritten pages."),
        ("organise", "square.grid.2x2", "Organise Pages", "Reorder, rotate, delete, extract or split pages."),
        ("combine", "rectangle.stack.badge.plus", "Combine Files", "Join several PDFs or images into one PDF."),
    ]

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                Text("Welcome to PaperLite").font(.system(size: 28, weight: .bold))
                Text("Open, shrink, sign and tidy up your PDFs.").font(.title3).foregroundStyle(.secondary).padding(.top, 4)

                VStack(spacing: 12) {
                    Image(systemName: "doc.text").font(.system(size: 34, weight: .light)).foregroundStyle(.tertiary)
                    Text("Drop a PDF here to open it").font(.headline)
                    Button { model.openPanel() } label: {
                        Label("Choose a file", systemImage: "folder").padding(.horizontal, 8)
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(Theme.brand)
                    .controlSize(.large)
                }
                .frame(maxWidth: .infinity, minHeight: 180)
                .background(RoundedRectangle(cornerRadius: 14).fill(dropHover ? Theme.accent.opacity(0.08) : Theme.card))
                .overlay(RoundedRectangle(cornerRadius: 14)
                    .strokeBorder(style: StrokeStyle(lineWidth: 1.5, dash: [6, 4]))
                    .foregroundStyle(dropHover ? Theme.accent : Theme.border))
                .dropDestination(for: URL.self) { urls, _ in
                    guard urls.contains(where: { $0.pathExtension.lowercased() == "pdf" }) else { return false }
                    WindowRouter.shared.open(urls, from: model)
                    return true
                } isTargeted: { dropHover = $0 }
                .padding(.top, 26)

                SectionLabel("Tools").padding(.top, 28).padding(.bottom, 10)
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 220), spacing: 12)], spacing: 12) {
                    ForEach(cards, id: \.key) { c in
                        ToolCard(symbol: c.symbol, title: c.title, text: c.text, tint: Theme.tints[c.key] ?? Theme.accent) {
                            open(c.key)
                        }
                    }
                }

                if !model.recent.isEmpty {
                    SectionLabel("Recent").padding(.top, 28).padding(.bottom, 6)
                    VStack(spacing: 0) {
                        ForEach(model.recent, id: \.self) { url in
                            RecentRow(url: url) {
                                WindowRouter.shared.open([url], from: model)
                            }
                        }
                    }
                }
            }
            .padding(.horizontal, 32)
            .padding(.vertical, 44)
            .frame(maxWidth: 860)
            .frame(maxWidth: .infinity)
        }
        .background(Color(nsColor: .underPageBackgroundColor).opacity(0.35))
    }

    private func open(_ key: String) {
        switch key {
        case "compress": model.compressCurrent()
        case "combine": model.compressFiles = model.url.map { [$0] } ?? []; model.showCombine = true
        case "fill": model.show(.fill)
        case "edit": model.show(.edit)
        case "organise": model.show(.organise)
        default: break
        }
    }
}

struct ToolCard: View {
    let symbol: String
    let title: String
    let text: String
    let tint: Color
    let action: () -> Void
    @State private var hover = false

    var body: some View {
        Button(action: action) {
            VStack(alignment: .leading, spacing: 6) {
                IconBadge(symbol: symbol, tint: tint).padding(.bottom, 6)
                Text(title).font(.headline)
                Text(text).font(.callout).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                Spacer(minLength: 0)
            }
            .padding(16)
            .frame(maxWidth: .infinity, minHeight: 132, alignment: .topLeading)
            .background(RoundedRectangle(cornerRadius: 12, style: .continuous).fill(Theme.card))
            .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).strokeBorder(hover ? Color.secondary.opacity(0.5) : Theme.border))
            .shadow(color: .black.opacity(hover ? 0.08 : 0), radius: 8, y: 3)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .onHover { hover = $0 }
        .animation(.easeOut(duration: 0.12), value: hover)
    }
}

struct RecentRow: View {
    let url: URL
    let action: () -> Void
    @State private var hover = false

    var body: some View {
        Button(action: action) {
            HStack(spacing: 10) {
                Image(systemName: "doc.text").foregroundStyle(.secondary)
                Text(url.lastPathComponent)
                Text("·  \(url.deletingLastPathComponent().lastPathComponent)").foregroundStyle(.secondary)
                Spacer()
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 8)
            .background(RoundedRectangle(cornerRadius: 8).fill(hover ? Theme.card : .clear))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .onHover { hover = $0 }
        .help(url.path)
    }
}
