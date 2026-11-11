import AppKit
import PDFKit
import Vision

/// A word found by OCR, in PDF page coordinates (origin bottom-left).
struct OCRWord: Identifiable {
    let id = UUID()
    let text: String
    let rect: CGRect
    let lineRect: CGRect
}

/// Reads scanned pages with Apple's Vision framework and edits them.
///
/// Edits are added as annotations while you work (so undo is instant), tagged
/// with `Annotations.tag`. When the file is saved, `Flattener` burns them into the
/// page; on scanned pages the page is re-rendered so the old pixels are really gone.
enum ScanEditor {
    static func recognizeWords(on page: PDFPage) throws -> [OCRWord] {
        let box = page.bounds(for: .mediaBox)
        guard let image = PageRenderer.render(page, dpi: 300) else { return [] }
        let request = VNRecognizeTextRequest()
        request.recognitionLevel = .accurate
        request.usesLanguageCorrection = true
        try VNImageRequestHandler(cgImage: image, options: [:]).perform([request])

        var words: [OCRWord] = []
        for observation in request.results ?? [] {
            guard let candidate = observation.topCandidates(1).first else { continue }
            let line = toPage(observation.boundingBox, box: box)
            let string = candidate.string
            var searchStart = string.startIndex
            for token in string.split(separator: " ", omittingEmptySubsequences: true) {
                guard let range = string.range(of: token, range: searchStart..<string.endIndex) else { continue }
                searchStart = range.upperBound
                if let wordBox = try? candidate.boundingBox(for: range)?.boundingBox {
                    words.append(OCRWord(text: String(token), rect: toPage(wordBox, box: box), lineRect: line))
                }
            }
        }
        return words
    }

    /// Vision's normalised (0-1, bottom-left) rect to page coordinates.
    private static func toPage(_ r: CGRect, box: CGRect) -> CGRect {
        CGRect(x: box.minX + r.minX * box.width, y: box.minY + r.minY * box.height,
               width: r.width * box.width, height: r.height * box.height)
    }

    /// Font size that matches the scanned line. Vision's line box runs from the
    /// top of capitals to the bottom of descenders, about 1.0 em in common fonts.
    static func fontSize(for word: OCRWord) -> CGFloat {
        max(5, word.lineRect.height * 0.98)
    }

    // MARK: colours

    struct Colors {
        let paper: NSColor
        let ink: NSColor
    }

    /// Sample the paper colour (around the rect) and the ink colour (darkest pixels inside).
    static func sampleColors(page: PDFPage, rect: CGRect) -> Colors {
        let pad = max(3, rect.height * 0.35)
        let ring = rect.insetBy(dx: -pad, dy: -pad).intersection(page.bounds(for: .mediaBox))
        guard let image = PageRenderer.render(page, dpi: 100, clip: ring),
              let pixels = RGBPixels(image) else {
            return Colors(paper: .white, ink: .black)
        }
        let sx = CGFloat(pixels.width) / ring.width, sy = CGFloat(pixels.height) / ring.height
        // inner rect in bitmap coordinates (bitmap rows start at the top)
        let ix0 = (rect.minX - ring.minX) * sx, ix1 = (rect.maxX - ring.minX) * sx
        let iy0 = (ring.maxY - rect.maxY) * sy, iy1 = (ring.maxY - rect.minY) * sy

        var outside: [(Int, Int, Int)] = [], inside: [(Int, Int, Int)] = []
        for y in 0..<pixels.height {
            for x in 0..<pixels.width {
                let c = pixels.at(x, y)
                let isInside = CGFloat(x) >= ix0 && CGFloat(x) <= ix1 && CGFloat(y) >= iy0 && CGFloat(y) <= iy1
                if isInside { inside.append(c) } else { outside.append(c) }
            }
        }
        outside.sort { $0.0 + $0.1 + $0.2 < $1.0 + $1.1 + $1.2 }
        let bright = Array(outside.dropFirst(outside.count / 3))
        let paper = median(bright.isEmpty ? outside : bright)
        inside.sort { $0.0 + $0.1 + $0.2 < $1.0 + $1.1 + $1.2 }
        let dark = Array(inside.prefix(max(1, inside.count / 12)))
        var ink = average(dark)
        let contrast = (paper.redComponent + paper.greenComponent + paper.blueComponent)
            - (ink.redComponent + ink.greenComponent + ink.blueComponent)
        if contrast < 0.6 { ink = NSColor(srgbRed: 0.1, green: 0.1, blue: 0.12, alpha: 1) }
        return Colors(paper: paper, ink: ink)
    }

    private static func median(_ c: [(Int, Int, Int)]) -> NSColor {
        guard !c.isEmpty else { return .white }
        let r = c.map(\.0).sorted()[c.count / 2], g = c.map(\.1).sorted()[c.count / 2], b = c.map(\.2).sorted()[c.count / 2]
        return NSColor(srgbRed: CGFloat(r) / 255, green: CGFloat(g) / 255, blue: CGFloat(b) / 255, alpha: 1)
    }

    private static func average(_ c: [(Int, Int, Int)]) -> NSColor {
        guard !c.isEmpty else { return .black }
        let n = CGFloat(c.count)
        return NSColor(srgbRed: CGFloat(c.reduce(0) { $0 + $1.0 }) / n / 255,
                       green: CGFloat(c.reduce(0) { $0 + $1.1 }) / n / 255,
                       blue: CGFloat(c.reduce(0) { $0 + $1.2 }) / n / 255, alpha: 1)
    }

    // MARK: edits (return the annotations added, for undo)

    static func erase(page: PDFPage, rect: CGRect, paper: NSColor? = nil) -> [PDFAnnotation] {
        let color = paper ?? sampleColors(page: page, rect: rect).paper
        let a = Annotations.whiteout(rect: rect, color: color)
        page.addAnnotation(a)
        return [a]
    }

    static func replace(page: PDFPage, rect: CGRect, text: String, fontSize: CGFloat, fontName: String) -> [PDFAnnotation] {
        let colors = sampleColors(page: page, rect: rect)
        let pad = rect.height * 0.12
        var added = erase(page: page, rect: rect.insetBy(dx: -pad, dy: -pad), paper: colors.paper)
        if !text.isEmpty {
            let t = Annotations.text(text, at: CGPoint(x: rect.minX, y: rect.minY - fontSize * 0.22),
                                     size: fontSize, fontName: fontName, color: colors.ink)
            page.addAnnotation(t)
            added.append(t)
        }
        return added
    }

    /// Picture of an area of the page, for Move / Copy.
    static func grab(page: PDFPage, rect: CGRect) -> CGImage? {
        PageRenderer.render(page, dpi: 300, clip: rect)
    }
}

/// Simple RGBA pixel access for a CGImage.
struct RGBPixels {
    let width: Int, height: Int
    private let data: [UInt8]

    init?(_ image: CGImage) {
        width = image.width
        height = image.height
        var buf = [UInt8](repeating: 0, count: width * height * 4)
        guard let ctx = CGContext(data: &buf, width: width, height: height, bitsPerComponent: 8, bytesPerRow: width * 4,
                                  space: CGColorSpace(name: CGColorSpace.sRGB)!,
                                  bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue) else { return nil }
        ctx.draw(image, in: CGRect(x: 0, y: 0, width: width, height: height))
        data = buf
    }

    /// Pixel at (x, y) with y measured from the top row.
    func at(_ x: Int, _ y: Int) -> (Int, Int, Int) {
        let i = (y * width + x) * 4
        return (Int(data[i]), Int(data[i + 1]), Int(data[i + 2]))
    }
}
