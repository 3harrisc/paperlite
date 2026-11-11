import AppKit
import PDFKit

/// Annotations PaperLite adds while you edit. All are tagged so `Flattener` can
/// burn them into the page on save.
enum Annotations {
    static let tag = "PaperLite"

    static func isOurs(_ a: PDFAnnotation) -> Bool { a.userName == tag }

    private static func tagged(_ a: PDFAnnotation) -> PDFAnnotation {
        a.userName = tag
        return a
    }

    /// Typed text with its top-left corner at `topLeft`... PDF y grows upwards, so
    /// pass the *baseline-ish* bottom-left point here.
    static func text(_ s: String, at bottomLeft: CGPoint, size: CGFloat, fontName: String = "Helvetica",
                     color: NSColor = .black) -> PDFAnnotation {
        let font = NSFont(name: fontName, size: size) ?? .systemFont(ofSize: size)
        let width = (s as NSString).size(withAttributes: [.font: font]).width + size * 0.6
        let height = size * 1.3
        let a = PDFAnnotation(bounds: CGRect(x: bottomLeft.x - 2, y: bottomLeft.y, width: width, height: height),
                              forType: .freeText, withProperties: nil)
        a.contents = s
        a.font = font
        a.fontColor = color
        a.color = .clear
        a.alignment = .left
        let border = PDFBorder()
        border.lineWidth = 0
        a.border = border
        return tagged(a)
    }

    static func tick(at p: CGPoint, size: CGFloat = 12) -> PDFAnnotation {
        let s = size / 2
        let bounds = CGRect(x: p.x - s - 2, y: p.y - s - 2, width: size + 4, height: size + 4)
        let path = NSBezierPath()
        // paths are relative to the annotation's origin
        path.move(to: CGPoint(x: 2, y: s + 2))
        path.line(to: CGPoint(x: 2 + s * 0.66, y: 2 + s * 0.3))
        path.line(to: CGPoint(x: 2 + size, y: 2 + size * 0.9))
        return ink(bounds: bounds, paths: [path], width: max(1.2, size / 8))
    }

    static func cross(at p: CGPoint, size: CGFloat = 11) -> PDFAnnotation {
        let bounds = CGRect(x: p.x - size / 2 - 2, y: p.y - size / 2 - 2, width: size + 4, height: size + 4)
        let a = NSBezierPath(), b = NSBezierPath()
        a.move(to: CGPoint(x: 2, y: 2)); a.line(to: CGPoint(x: 2 + size, y: 2 + size))
        b.move(to: CGPoint(x: 2, y: 2 + size)); b.line(to: CGPoint(x: 2 + size, y: 2))
        return ink(bounds: bounds, paths: [a, b], width: max(1.2, size / 8))
    }

    private static func ink(bounds: CGRect, paths: [NSBezierPath], width: CGFloat) -> PDFAnnotation {
        let a = PDFAnnotation(bounds: bounds, forType: .ink, withProperties: nil)
        for p in paths {
            p.lineCapStyle = .round
            p.lineJoinStyle = .round
            a.add(p)
        }
        a.color = .black
        let border = PDFBorder()
        border.lineWidth = width
        a.border = border
        return tagged(a)
    }

    /// A filled box in the paper colour: hides what's underneath (removed for real on save).
    static func whiteout(rect: CGRect, color: NSColor) -> PDFAnnotation {
        tagged(FillAnnotation(rect: rect, color: color))
    }

    /// An image (signature, initials, moved/copied area).
    static func image(_ image: CGImage, in rect: CGRect) -> PDFAnnotation {
        tagged(ImageAnnotation(image: image, rect: rect))
    }
}

/// Draws a solid rectangle. Custom drawing so it renders identically on screen and on save.
final class FillAnnotation: PDFAnnotation {
    let fill: NSColor

    init(rect: CGRect, color: NSColor) {
        fill = color
        super.init(bounds: rect, forType: .square, withProperties: nil)
    }

    required init?(coder: NSCoder) { fatalError("not used") }

    override func draw(with box: PDFDisplayBox, in context: CGContext) {
        context.saveGState()
        context.setFillColor(fill.cgColor)
        context.fill(bounds)
        context.restoreGState()
    }
}

/// Draws a bitmap (signature, initials, copied area) inside its bounds.
final class ImageAnnotation: PDFAnnotation {
    let image: CGImage

    init(image: CGImage, rect: CGRect) {
        self.image = image
        super.init(bounds: rect, forType: .stamp, withProperties: nil)
    }

    required init?(coder: NSCoder) { fatalError("not used") }

    override func draw(with box: PDFDisplayBox, in context: CGContext) {
        context.saveGState()
        context.interpolationQuality = .high
        context.draw(image, in: bounds)
        context.restoreGState()
    }
}
