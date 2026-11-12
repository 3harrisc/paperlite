import AppKit
import SwiftUI

/// Saved signature and initials, stored as PNGs in the app's Application Support folder.
enum SignatureStore {
    static func url(_ kind: SignatureKind) -> URL {
        let dir = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("PaperLite", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir.appendingPathComponent("\(kind.rawValue).png")
    }

    static func image(_ kind: SignatureKind) -> CGImage? {
        guard let src = CGImageSourceCreateWithURL(url(kind) as CFURL, nil) else { return nil }
        return CGImageSourceCreateImageAtIndex(src, 0, nil)
    }

    static func save(_ image: CGImage, kind: SignatureKind) {
        if let data = PageRenderer.pngData(image) { try? data.write(to: url(kind)) }
    }
}

struct SignatureSheet: View {
    let kind: SignatureKind
    var onDone: () -> Void
    @State private var mode = 0
    @State private var typed = ""
    @State private var strokes: [[CGPoint]] = []
    @Environment(\.dismiss) private var dismiss

    private static let ink = NSColor(srgbRed: 0.04, green: 0.08, blue: 0.31, alpha: 1)
    private static let scriptFonts = ["Snell Roundhand", "Apple Chancery", "Bradley Hand", "Noteworthy"]

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack(spacing: 12) {
                IconBadge(symbol: "signature", tint: Theme.tints["fill"]!, size: 40)
                VStack(alignment: .leading, spacing: 2) {
                    Text(kind == .signature ? "Create signature" : "Create initials").font(.headline)
                    Text("Type it or draw it with your trackpad or mouse. It's saved on this Mac for next time.")
                        .font(.callout).foregroundStyle(.secondary)
                }
            }
            Picker("", selection: $mode) {
                Text("Type").tag(0)
                Text("Draw").tag(1)
            }
            .pickerStyle(.segmented)
            .labelsHidden()

            Group {
                if mode == 0 {
                    VStack(spacing: 10) {
                        TextField(kind == .signature ? "Your name" : "Your initials", text: $typed)
                            .textFieldStyle(.roundedBorder)
                            .controlSize(.large)
                        Text(typed.isEmpty ? " " : typed)
                            .font(.custom(Self.scriptFont, size: 44))
                            .foregroundStyle(Color(nsColor: Self.ink))
                            .frame(maxWidth: .infinity, minHeight: 90)
                    }
                } else {
                    drawPad
                }
            }
            .frame(height: 160)
            .padding(12)
            .background(RoundedRectangle(cornerRadius: 10).fill(.white))
            .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(Theme.border))

            HStack {
                if mode == 1 { Button("Clear") { strokes = [] } }
                Spacer()
                Button("Cancel") { dismiss() }.keyboardShortcut(.cancelAction)
                Button("Use this") { save() }
                    .keyboardShortcut(.defaultAction)
                    .buttonStyle(.borderedProminent)
                    .tint(Theme.brand)
                    .disabled(mode == 0 ? typed.trimmingCharacters(in: .whitespaces).isEmpty : strokes.isEmpty)
            }
        }
        .padding(22)
        .frame(width: 520)
    }

    private var drawPad: some View {
        Canvas { ctx, size in
            var guide = Path()
            guide.move(to: CGPoint(x: 16, y: size.height * 0.75))
            guide.addLine(to: CGPoint(x: size.width - 16, y: size.height * 0.75))
            ctx.stroke(guide, with: .color(.gray.opacity(0.3)), style: StrokeStyle(lineWidth: 1, dash: [4, 4]))
            for s in strokes {
                var p = Path()
                p.addLines(s.count == 1 ? [s[0], s[0].applying(.init(translationX: 0.1, y: 0.1))] : s)
                ctx.stroke(p, with: .color(Color(nsColor: Self.ink)), style: StrokeStyle(lineWidth: 2.6, lineCap: .round, lineJoin: .round))
            }
        }
        .contentShape(Rectangle())
        .gesture(DragGesture(minimumDistance: 0)
            .onChanged { v in
                if isDrawing {
                    strokes[strokes.count - 1].append(v.location)
                } else {
                    strokes.append([v.location])
                    isDrawing = true
                }
            }
            .onEnded { _ in isDrawing = false })
    }

    @State private var isDrawing = false

    private static var scriptFont: String {
        scriptFonts.first { NSFont(name: $0, size: 12) != nil } ?? "Helvetica"
    }

    private func save() {
        let image: CGImage?
        if mode == 0 {
            image = Self.renderTyped(typed.trimmingCharacters(in: .whitespaces))
        } else {
            image = Self.renderStrokes(strokes)
        }
        guard let image else { return }
        SignatureStore.save(image, kind: kind)
        onDone()
        dismiss()
    }

    private static func renderTyped(_ text: String) -> CGImage? {
        let font = NSFont(name: scriptFont, size: 120) ?? .systemFont(ofSize: 120)
        let attrs: [NSAttributedString.Key: Any] = [.font: font, .foregroundColor: ink]
        let size = (text as NSString).size(withAttributes: attrs)
        let w = Int(size.width + 40), h = Int(size.height + 20)
        guard let ctx = CGContext(data: nil, width: w, height: h, bitsPerComponent: 8, bytesPerRow: 0,
                                  space: CGColorSpace(name: CGColorSpace.sRGB)!,
                                  bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { return nil }
        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.current = NSGraphicsContext(cgContext: ctx, flipped: false)
        (text as NSString).draw(at: NSPoint(x: 20, y: 10), withAttributes: attrs)
        NSGraphicsContext.restoreGraphicsState()
        return ctx.makeImage()
    }

    private static func renderStrokes(_ strokes: [[CGPoint]]) -> CGImage? {
        let pts = strokes.flatMap { $0 }
        guard let minX = pts.map(\.x).min(), let maxX = pts.map(\.x).max(),
              let minY = pts.map(\.y).min(), let maxY = pts.map(\.y).max() else { return nil }
        let pad: CGFloat = 8, scale: CGFloat = 3
        let w = Int((maxX - minX + pad * 2) * scale), h = Int((maxY - minY + pad * 2) * scale)
        guard let ctx = CGContext(data: nil, width: max(w, 1), height: max(h, 1), bitsPerComponent: 8, bytesPerRow: 0,
                                  space: CGColorSpace(name: CGColorSpace.sRGB)!,
                                  bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { return nil }
        ctx.scaleBy(x: scale, y: scale)
        ctx.setStrokeColor(ink.cgColor)
        ctx.setLineWidth(2.6)
        ctx.setLineCap(.round)
        ctx.setLineJoin(.round)
        let height = maxY - minY + pad * 2
        for s in strokes {
            // SwiftUI y grows downwards; bitmap y grows upwards
            let mapped = s.map { CGPoint(x: $0.x - minX + pad, y: height - ($0.y - minY + pad)) }
            if mapped.count == 1 {
                ctx.move(to: mapped[0]); ctx.addLine(to: mapped[0].applying(.init(translationX: 0.1, y: 0.1)))
            } else {
                ctx.addLines(between: mapped)
            }
            ctx.strokePath()
        }
        return ctx.makeImage()
    }
}
