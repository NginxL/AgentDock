import Foundation

public enum ServiceLaunch {
    public static func origin(in output: String) -> URL? {
        for line in output.split(separator: "\n", omittingEmptySubsequences: false).dropLast() {
            let prefix = "AgentDock: "
            guard line.hasPrefix(prefix),
                  let value = URLComponents(string: String(line.dropFirst(prefix.count))),
                  value.scheme == "http", value.host == "127.0.0.1",
                  let port = value.port, (1024...65535).contains(port),
                  value.user == nil, value.password == nil,
                  value.path.isEmpty, value.query == nil, value.fragment == nil else { continue }
            return value.url
        }
        return nil
    }

    public static func python(resources: URL, settings: [String: String], environment: [String: String]) -> URL? {
        let bundled = resources.appendingPathComponent("Python/bin/python3").path
        var candidates = [bundled]
        if let configured = settings["python"] { candidates.append(configured) }
        for directory in ["/opt/homebrew/bin", "/usr/local/bin"] {
            for version in ["3.13", "3.12", "3.11"] { candidates.append(directory + "/python" + version) }
        }
        for directory in (environment["PATH"] ?? settings["path"] ?? "").split(separator: ":") {
            if directory.hasPrefix("/") { candidates.append(String(directory) + "/python3") }
        }
        var seen = Set<String>()
        for candidate in candidates where seen.insert(candidate).inserted && FileManager.default.isExecutableFile(atPath: candidate) {
            let process = Process()
            process.executableURL = URL(fileURLWithPath: candidate)
            process.arguments = ["-I", "-B", "-c", "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"]
            process.standardOutput = FileHandle.nullDevice
            process.standardError = FileHandle.nullDevice
            do {
                try process.run()
                let deadline = Date().addingTimeInterval(2)
                while process.isRunning && Date() < deadline { Thread.sleep(forTimeInterval: 0.02) }
                if process.isRunning { process.terminate(); continue }
                if process.terminationStatus == 0 { return process.executableURL }
            } catch { continue }
        }
        return nil
    }
}
