import AppKit
import CoreGraphics
import ImageIO
import PDFKit
import UniformTypeIdentifiers

/// Compression presets. These numbers match `paperlite/core/compress.py` in the
/// Windows app so both versions give the same results.
struct CompressionPreset: Identifiable, Hashable {
    let id: String
    let title: String
    let detail: String
    let dpiThreshold: CGFloat
    let dpiTarget: CGFloat
    let jpegQuality: CGFloat // 0...1
    let grayscale: Bool

    static let all: [CompressionPreset] = [
        .init(id: "high", title: "High quality", detail: "Print-ready. Smaller file, hard to tell apart from the original.",
              dpiThreshold: 225, dpiTarget: 200, jpegQuality: 0.85, grayscale: false),
        .init(id: "standard", title: "Standard (recommended)", detail: "Good for email and archiving. Text stays sharp.",
              dpiThreshold: 165, dpiTarget: 150, jpegQuality: 0.70, grayscale: false),
        .init(id: "small", title: "Smallest file", detail: "Good for on-screen reading. Photos lose some detail.",
              dpiThreshold: 110, dpiTarget: 96, jpegQuality: 0.55, grayscale: false),
        .init(id: "small_gray", title: "Smallest, black & white", detail: "Converts pages to greyscale. Best for text-only scans.",
              dpiThreshold: 110, dpiTarget: 96, jpegQuality: 0.55, grayscale: true),
    ]
    static let standard = all[1]
}

struct CompressionResult {
    let input: URL
    let output: URL
    let originalBytes: Int
    let compressedBytes: Int
    let keptOriginal: Bool

    var savedPercent: Double {
        originalBytes == 0 ? 0 : 100 * Double(originalBytes - compressedBytes) / Double(originalBytes)
    }
}

enum CompressionError: LocalizedError {
    case cannotOpen, locked, writeFailed
    var errorDescription: String? {
        switch self {
        case .cannotOpen: return "This file couldn't be opened as a PDF."
        case .locked: return "This PDF is password protected."
        case .writeFailed: return "The compressed file couldn't be written."
        }
    }
}

/// How compression works on the Mac:
///
/// * **Scanned pages** (pages that are a picture with little or no text) are
///   re-rendered at the preset DPI and stored as JPEG at the preset quality. This
///   is where nearly all of the saving on scans comes from.
/// * **Normal pages** are left exactly as they are, so text, links and form
///   fields keep working.
/// * PDFKit's own image optimisation is also tried, and the smallest result wins.
///   If nothing beats the original, the original is kept.
enum Compressor {
    /// Read from disk every time. `URL.resourceValues` caches per URL, so when
    /// compressing over the original it reported the old size as the new one.
    static func fileSize(_ url: URL) -> Int {
        let attrs = try? FileManager.default.attributesOfItem(atPath: url.path)
        return (attrs?[.size] as? NSNumber)?.intValue ?? 0
    }

    static func compress(input: URL, output: URL, preset: CompressionPreset) throws -> CompressionResult {
        let original = fileSize(input)
        guard let doc = PDFDocument(url: input) else { throw CompressionError.cannotOpen }
        if doc.isLocked { throw CompressionError.locked }

        let tmpDir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: tmpDir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: tmpDir) }

        var candidates: [URL] = []

        // Candidate A: re-render scanned pages, keep normal pages.
        for i in 0..<doc.pageCount {
            guard let page = doc.page(at: i), PageInfo.isScanned(page) else { continue }
            if let replacement = rasterizedPage(page, preset: preset) {
                doc.removePage(at: i)
                doc.insert(replacement, at: i)
            }
        }
        let a = tmpDir.appendingPathComponent("a.pdf")
        if doc.write(to: a) { candidates.append(a) }

        // Candidate B: PDFKit's built-in image optimisation (macOS 13+).
        if let fresh = PDFDocument(url: input) {
            let b = tmpDir.appendingPathComponent("b.pdf")
            var opts: [PDFDocumentWriteOption: Any] = [.saveImagesAsJPEGOption: true]
            if preset.id != "high" { opts[.optimizeImagesForScreenOption] = true }
            if fresh.write(to: b, withOptions: opts) { candidates.append(b) }
        }

        let best = candidates.min { fileSize($0) < fileSize($1) }
        if let best, fileSize(best) < original {
            try place(best, at: output)
            return CompressionResult(input: input, output: output, originalBytes: original,
                                     compressedBytes: fileSize(output), keptOriginal: false)
        }
        if input.standardizedFileURL != output.standardizedFileURL {
            try place(input, at: output)
        }
        return CompressionResult(input: input, output: output, originalBytes: original,
                                 compressedBytes: original, keptOriginal: true)
    }

    /// Overwrite in place rather than delete-and-copy: the sandbox lets us write
    /// to a picked file, but deleting it and creating a new one is refused.
    private static func place(_ source: URL, at output: URL) throws {
        try Data(contentsOf: source).write(to: output)
    }

    /// Render a page to a JPEG at the preset DPI and wrap it in a new single-page PDF page.
    static func rasterizedPage(_ page: PDFPage, preset: CompressionPreset) -> PDFPage? {
        guard let image = PageRenderer.render(page, dpi: preset.dpiTarget, grayscale: preset.grayscale),
              let jpeg = PageRenderer.jpegData(image, quality: preset.jpegQuality)
        else { return nil }
        return PageRenderer.pdfPage(fromJPEG: jpeg, size: page.bounds(for: .mediaBox).size, rotation: page.rotation)
    }
}

enum PageInfo {
    /// True when the page is basically a picture: little or no real text.
    static func isScanned(_ page: PDFPage) -> Bool {
        let text = (page.string ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        return text.count < 20
    }
}

enum PageRenderer {
    /// Render the page (unrotated, with annotations) into a bitmap.
    static func render(_ page: PDFPage, dpi: CGFloat, grayscale: Bool = false, clip: CGRect? = nil) -> CGImage? {
        let box = page.bounds(for: .mediaBox)
        let area = clip ?? box
        let scale = dpi / 72
        let width = max(1, Int((area.width * scale).rounded()))
        let height = max(1, Int((area.height * scale).rounded()))
        let space = grayscale ? CGColorSpaceCreateDeviceGray() : CGColorSpace(name: CGColorSpace.sRGB)!
        let info = grayscale ? CGImageAlphaInfo.none.rawValue : CGImageAlphaInfo.noneSkipLast.rawValue
        guard let ctx = CGContext(data: nil, width: width, height: height, bitsPerComponent: 8,
                                  bytesPerRow: 0, space: space, bitmapInfo: info) else { return nil }
        ctx.setFillColor(grayscale ? CGColor(gray: 1, alpha: 1) : CGColor(red: 1, green: 1, blue: 1, alpha: 1))
        ctx.fill(CGRect(x: 0, y: 0, width: width, height: height))
        ctx.interpolationQuality = .high
        ctx.scaleBy(x: scale, y: scale)
        // PDFPage.draw puts the box's origin at the context origin; shift so `area` lands at (0, 0).
        ctx.translateBy(x: box.minX - area.minX, y: box.minY - area.minY)
        page.draw(with: .mediaBox, to: ctx)
        return ctx.makeImage()
    }

    static func jpegData(_ image: CGImage, quality: CGFloat) -> Data? {
        let data = NSMutableData()
        guard let dest = CGImageDestinationCreateWithData(data, UTType.jpeg.identifier as CFString, 1, nil) else { return nil }
        CGImageDestinationAddImage(dest, image, [kCGImageDestinationLossyCompressionQuality: quality] as CFDictionary)
        return CGImageDestinationFinalize(dest) ? data as Data : nil
    }

    static func pngData(_ image: CGImage) -> Data? {
        let data = NSMutableData()
        guard let dest = CGImageDestinationCreateWithData(data, UTType.png.identifier as CFString, 1, nil) else { return nil }
        CGImageDestinationAddImage(dest, image, nil)
        return CGImageDestinationFinalize(dest) ? data as Data : nil
    }

    /// A one-page PDF page showing a JPEG full-size. Quartz keeps JPEG data as-is
    /// (DCT) when the image comes from a JPEG source, so the size stays small.
    static func pdfPage(fromJPEG jpeg: Data, size: CGSize, rotation: Int) -> PDFPage? {
        guard let provider = CGDataProvider(data: jpeg as CFData),
              let image = CGImage(jpegDataProviderSource: provider, decode: nil, shouldInterpolate: true, intent: .defaultIntent)
        else { return nil }
        return pdfPage(size: size, rotation: rotation) { ctx in
            ctx.draw(image, in: CGRect(origin: .zero, size: size))
        }
    }

    /// Build a single PDF page by drawing into a PDF context.
    static func pdfPage(size: CGSize, rotation: Int, draw: (CGContext) -> Void) -> PDFPage? {
        let data = NSMutableData()
        var box = CGRect(origin: .zero, size: size)
        guard let consumer = CGDataConsumer(data: data as CFMutableData),
              let ctx = CGContext(consumer: consumer, mediaBox: &box, nil) else { return nil }
        ctx.beginPDFPage(nil)
        draw(ctx)
        ctx.endPDFPage()
        ctx.closePDF()
        guard let doc = PDFDocument(data: data as Data), let page = doc.page(at: 0) else { return nil }
        page.rotation = rotation
        return page
    }
}
