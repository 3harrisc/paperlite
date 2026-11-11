import SwiftUI

/// Colour tokens shared with the Windows app (`paperlite/ui/theme.py`).
enum Theme {
    static let brand = Color(red: 0.851, green: 0.227, blue: 0.169)      // #D93A2B
    static let accent = Color(red: 0.145, green: 0.388, blue: 0.922)     // #2563EB
    static let canvas = Color(nsColor: NSColor(name: nil) { app in
        app.bestMatch(from: [.darkAqua]) == .darkAqua
            ? NSColor(white: 0.13, alpha: 1)
            : NSColor(srgbRed: 0.91, green: 0.914, blue: 0.929, alpha: 1)   // #E8E9ED
    })
    static let panel = Color(nsColor: .windowBackgroundColor)
    static let card = Color(nsColor: .controlBackgroundColor)
    static let border = Color(nsColor: .separatorColor)
    static let muted = Color.secondary

    static let tints: [String: Color] = [
        "compress": brand,
        "fill": Color(red: 0.486, green: 0.227, blue: 0.929),
        "edit": accent,
        "organise": Color(red: 0.055, green: 0.624, blue: 0.431),
        "combine": Color(red: 0.851, green: 0.467, blue: 0.024),
    ]
}

struct SectionLabel: View {
    let text: String
    init(_ text: String) { self.text = text }
    var body: some View {
        Text(text.uppercased())
            .font(.system(size: 10.5, weight: .semibold))
            .tracking(0.6)
            .foregroundStyle(.tertiary)
    }
}

struct IconBadge: View {
    let symbol: String
    let tint: Color
    var size: CGFloat = 36
    var body: some View {
        RoundedRectangle(cornerRadius: size * 0.26, style: .continuous)
            .fill(tint.gradient)
            .frame(width: size, height: size)
            .overlay(Image(systemName: symbol).font(.system(size: size * 0.48, weight: .medium)).foregroundStyle(.white))
    }
}
