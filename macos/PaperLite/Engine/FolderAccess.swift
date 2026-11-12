import AppKit

/// The sandbox only lets PaperLite touch the files the person picked, not the
/// folders they sit in, so writing "name_compressed.pdf" next to a picked file
/// is refused. This asks for a folder once and remembers the answer as a
/// security-scoped bookmark, so the same folder is never asked about again.
@MainActor
enum FolderAccess {
    private static let defaultsKey = "folderBookmarks"

    /// A folder the app may create files in: `folder` itself, or another one the
    /// person chose instead. Nil if they cancelled. Call
    /// `stopAccessingSecurityScopedResource()` on the result when finished.
    static func writableFolder(for folder: URL) -> URL? {
        if let stored = storedFolder(for: folder) {
            if stored.startAccessingSecurityScopedResource(), canWrite(in: stored) { return stored }
            stored.stopAccessingSecurityScopedResource()
        }
        if canWrite(in: folder) { return folder }

        let panel = NSOpenPanel()
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.canCreateDirectories = true
        panel.directoryURL = folder
        panel.prompt = "Allow"
        panel.message = "PaperLite needs your permission to save into “\(folder.lastPathComponent)”. Click Allow, or choose another folder."
        guard panel.runModal() == .OK, let chosen = panel.url else { return nil }
        remember(chosen, for: folder)
        _ = chosen.startAccessingSecurityScopedResource()
        return chosen
    }

    /// The sandbox gives no way to ask "may I write here?", so try it.
    private static func canWrite(in folder: URL) -> Bool {
        let probe = folder.appendingPathComponent(".paperlite-\(UUID().uuidString)")
        guard FileManager.default.createFile(atPath: probe.path, contents: nil) else { return false }
        try? FileManager.default.removeItem(at: probe)
        return true
    }

    private static func storedFolder(for folder: URL) -> URL? {
        let all = UserDefaults.standard.dictionary(forKey: defaultsKey) as? [String: Data] ?? [:]
        guard let data = all[folder.standardizedFileURL.path] else { return nil }
        var stale = false
        guard let url = try? URL(resolvingBookmarkData: data, options: .withSecurityScope,
                                 bookmarkDataIsStale: &stale) else { return nil }
        if stale { remember(url, for: folder) }
        return url
    }

    private static func remember(_ granted: URL, for folder: URL) {
        guard let data = try? granted.bookmarkData(options: .withSecurityScope,
                                                   includingResourceValuesForKeys: nil,
                                                   relativeTo: nil) else { return }
        var all = UserDefaults.standard.dictionary(forKey: defaultsKey) as? [String: Data] ?? [:]
        all[folder.standardizedFileURL.path] = data
        UserDefaults.standard.set(all, forKey: defaultsKey)
    }
}
