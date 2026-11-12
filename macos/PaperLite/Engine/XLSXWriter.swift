import Foundation

/// Writes a minimal .xlsx: a zip of the few XML parts Excel needs, one
/// worksheet per sheet, inline strings, and a style per number format.
/// Cell rules match `_write_sheet` in the Windows app's convert.py.
enum XLSXWriter {
    struct Sheet {
        let name: String
        let rows: [[String]]
    }

    static func workbook(_ sheets: [Sheet]) -> Data {
        var styles = Styles()
        var files: [(String, Data)] = []
        for (i, sheet) in sheets.enumerated() {
            files.append(("xl/worksheets/sheet\(i + 1).xml", Data(worksheet(sheet, styles: &styles).utf8)))
        }
        let ids = sheets.indices
        files += [
            ("[Content_Types].xml", Data(("""
            <?xml version="1.0" encoding="UTF-8" standalone="yes"?>
            <Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\
            <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>\
            <Default Extension="xml" ContentType="application/xml"/>\
            <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>\
            <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
            """ + ids.map { "<Override PartName=\"/xl/worksheets/sheet\($0 + 1).xml\" ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml\"/>" }.joined()
              + "</Types>").utf8)),
            ("_rels/.rels", Data("""
            <?xml version="1.0" encoding="UTF-8" standalone="yes"?>
            <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\
            <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>\
            </Relationships>
            """.utf8)),
            ("xl/workbook.xml", Data(("""
            <?xml version="1.0" encoding="UTF-8" standalone="yes"?>
            <workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>
            """ + sheets.enumerated().map { "<sheet name=\"\(escape($1.name))\" sheetId=\"\($0 + 1)\" r:id=\"rId\($0 + 1)\"/>" }.joined()
              + "</sheets></workbook>").utf8)),
            ("xl/_rels/workbook.xml.rels", Data(("""
            <?xml version="1.0" encoding="UTF-8" standalone="yes"?>
            <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
            """ + ids.map { "<Relationship Id=\"rId\($0 + 1)\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet\" Target=\"worksheets/sheet\($0 + 1).xml\"/>" }.joined()
              + "<Relationship Id=\"rId\(sheets.count + 1)\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles\" Target=\"styles.xml\"/></Relationships>").utf8)),
            ("xl/styles.xml", Data(styles.xml.utf8)),
        ]
        return Zip.stored(files)
    }

    private static func worksheet(_ sheet: Sheet, styles: inout Styles) -> String {
        var widths: [Int: Int] = [:]
        var body = ""
        for (r, row) in sheet.rows.enumerated() {
            var cells = ""
            for (c, text) in row.enumerated() where !text.isEmpty {
                let ref = column(c) + String(r + 1)
                if let n = Converter.parseNumber(text) {
                    let value = n.isInteger ? String(Int64(n.value)) : String(n.value)
                    cells += "<c r=\"\(ref)\" s=\"\(styles.index(format: n.format, wrap: false))\"><v>\(value)</v></c>"
                } else {
                    let wrap = text.contains("\n")
                    let s = wrap ? " s=\"\(styles.index(format: "General", wrap: true))\"" : ""
                    cells += "<c r=\"\(ref)\" t=\"inlineStr\"\(s)><is><t xml:space=\"preserve\">\(escape(text))</t></is></c>"
                }
                widths[c] = max(widths[c] ?? 0, text.split(separator: "\n").map(\.count).max() ?? 0)
            }
            body += "<row r=\"\(r + 1)\">\(cells)</row>"
        }
        let cols = widths.keys.sorted().map {
            "<col min=\"\($0 + 1)\" max=\"\($0 + 1)\" width=\"\(min(60, max(8, widths[$0]! + 2)))\" customWidth=\"1\"/>"
        }.joined()
        return """
        <?xml version="1.0" encoding="UTF-8" standalone="yes"?>
        <worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">\
        \(cols.isEmpty ? "" : "<cols>\(cols)</cols>")<sheetData>\(body)</sheetData></worksheet>
        """
    }

    /// 0 → A, 25 → Z, 26 → AA.
    static func column(_ index: Int) -> String {
        var n = index + 1
        var name = ""
        while n > 0 {
            let r = (n - 1) % 26
            name = String(UnicodeScalar(65 + r)!) + name
            n = (n - 1) / 26
        }
        return name
    }

    static func escape(_ s: String) -> String {
        // XML 1.0 can't hold most control characters at all, even escaped.
        let allowed = s.unicodeScalars.filter { $0.value >= 0x20 || $0 == "\t" || $0 == "\n" || $0 == "\r" }
        return String(String.UnicodeScalarView(allowed))
            .replacingOccurrences(of: "&", with: "&amp;")
            .replacingOccurrences(of: "<", with: "&lt;")
            .replacingOccurrences(of: ">", with: "&gt;")
            .replacingOccurrences(of: "\"", with: "&quot;")
    }

    /// Cell styles, one per (number format, wrap) pair, in the order first used.
    private struct Styles {
        private static let builtIn: [String: Int] = ["General": 0, "0": 1, "0.00": 2, "#,##0": 3, "#,##0.00": 4, "0%": 9, "0.00%": 10]
        private var custom: [String] = []
        private var xfs: [(format: Int, wrap: Bool)] = [(0, false)]

        mutating func index(format: String, wrap: Bool) -> Int {
            let id: Int
            if let b = Self.builtIn[format] {
                id = b
            } else if let k = custom.firstIndex(of: format) {
                id = 164 + k
            } else {
                custom.append(format)
                id = 164 + custom.count - 1
            }
            if let k = xfs.firstIndex(where: { $0.format == id && $0.wrap == wrap }) { return k }
            xfs.append((id, wrap))
            return xfs.count - 1
        }

        var xml: String {
            let formats = custom.enumerated().map { "<numFmt numFmtId=\"\(164 + $0)\" formatCode=\"\(XLSXWriter.escape($1))\"/>" }.joined()
            let cellXfs = xfs.map { xf in
                let apply = xf.format == 0 ? "" : " applyNumberFormat=\"1\""
                return xf.wrap
                    ? "<xf numFmtId=\"\(xf.format)\" fontId=\"0\" fillId=\"0\" borderId=\"0\" xfId=\"0\"\(apply) applyAlignment=\"1\"><alignment wrapText=\"1\" vertical=\"top\"/></xf>"
                    : "<xf numFmtId=\"\(xf.format)\" fontId=\"0\" fillId=\"0\" borderId=\"0\" xfId=\"0\"\(apply)/>"
            }.joined()
            return """
            <?xml version="1.0" encoding="UTF-8" standalone="yes"?>
            <styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">\
            \(custom.isEmpty ? "" : "<numFmts count=\"\(custom.count)\">\(formats)</numFmts>")\
            <fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>\
            <fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>\
            <borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>\
            <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>\
            <cellXfs count="\(xfs.count)">\(cellXfs)</cellXfs>\
            <cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>\
            </styleSheet>
            """
        }
    }
}

/// An uncompressed ("stored") zip archive. Excel and Numbers read these fine,
/// and it needs nothing beyond Foundation.
enum Zip {
    static func stored(_ files: [(String, Data)]) -> Data {
        var out = Data()
        var central = Data()
        for (name, data) in files {
            let nameData = Data(name.utf8)
            let crc = crc32(data)
            let offset = UInt32(out.count)
            // local file header
            out.append(le32(0x04034b50)); out.append(le16(20)); out.append(le16(0x0800)); out.append(le16(0))
            out.append(le16(0)); out.append(le16(0x21))  // time, date: 1980-01-01
            out.append(le32(crc)); out.append(le32(UInt32(data.count))); out.append(le32(UInt32(data.count)))
            out.append(le16(UInt16(nameData.count))); out.append(le16(0))
            out.append(nameData); out.append(data)
            // central directory entry
            central.append(le32(0x02014b50)); central.append(le16(20)); central.append(le16(20)); central.append(le16(0x0800))
            central.append(le16(0)); central.append(le16(0)); central.append(le16(0x21))
            central.append(le32(crc)); central.append(le32(UInt32(data.count))); central.append(le32(UInt32(data.count)))
            central.append(le16(UInt16(nameData.count))); central.append(le16(0)); central.append(le16(0))
            central.append(le16(0)); central.append(le16(0)); central.append(le32(0)); central.append(le32(offset))
            central.append(nameData)
        }
        let centralOffset = UInt32(out.count)
        out.append(central)
        out.append(le32(0x06054b50)); out.append(le16(0)); out.append(le16(0))
        out.append(le16(UInt16(files.count))); out.append(le16(UInt16(files.count)))
        out.append(le32(UInt32(central.count))); out.append(le32(centralOffset)); out.append(le16(0))
        return out
    }

    private static let table: [UInt32] = (0..<256).map { n -> UInt32 in
        var c = UInt32(n)
        for _ in 0..<8 { c = c & 1 != 0 ? 0xEDB88320 ^ (c >> 1) : c >> 1 }
        return c
    }

    static func crc32(_ data: Data) -> UInt32 {
        var c: UInt32 = 0xFFFFFFFF
        for byte in data { c = table[Int((c ^ UInt32(byte)) & 0xFF)] ^ (c >> 8) }
        return c ^ 0xFFFFFFFF
    }

    private static func le16(_ v: UInt16) -> Data { withUnsafeBytes(of: v.littleEndian) { Data($0) } }
    private static func le32(_ v: UInt32) -> Data { withUnsafeBytes(of: v.littleEndian) { Data($0) } }
}
