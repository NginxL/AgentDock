import Foundation
import Darwin
import MeterCore

public struct CodexProvider: UsageProvider {
    public let kind: ProviderKind = .codex
    let timeout: TimeInterval
    let executableURL: URL?
    let environment: [String: String]

    public init(timeout: TimeInterval = 25, executableURL: URL? = nil,
         environment: [String: String] = ProcessInfo.processInfo.environment) {
        self.timeout = max(1, min(timeout, 120))
        self.executableURL = executableURL
        self.environment = environment
    }

    public func fetch() async throws -> UsageSnapshot {
        guard let executable = executableURL ?? CodexExecutable.find(environment: environment) else {
            throw MeterFailure.notInstalled("Codex")
        }
        let reader = CodexRPCReader(executable: executable, environment: environment, timeout: timeout)
        return try await withTaskCancellationHandler {
            try Task.checkCancellation()
            return try await withCheckedThrowingContinuation { continuation in
                DispatchQueue.global(qos: .utility).async {
                    do { continuation.resume(returning: try reader.read()) }
                    catch { continuation.resume(throwing: error) }
                }
            }
        } onCancel: { reader.cancel() }
    }
}

private enum CodexExecutable {
    static func find(environment: [String: String]) -> URL? {
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        var directories = (environment["PATH"] ?? "").split(separator: ":").map(String.init).filter { $0.hasPrefix("/") }
        directories += ["\(home)/.local/bin", "\(home)/.npm-global/bin", "\(home)/.volta/bin", "\(home)/.asdf/shims",
                        "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin"]
        let nvm = environment["NVM_DIR"] ?? "\(home)/.nvm"
        let versions = "\(nvm)/versions/node"
        if let entries = try? FileManager.default.contentsOfDirectory(atPath: versions) {
            directories += entries.sorted { $0.compare($1, options: .numeric) == .orderedDescending }.map { "\(versions)/\($0)/bin" }
        }
        var candidates = directories.map { "\($0)/codex" }
        candidates += ["/Applications/Codex.app/Contents/Resources/codex", "/Applications/ChatGPT.app/Contents/Resources/codex",
                       "\(home)/Applications/Codex.app/Contents/Resources/codex", "\(home)/Applications/ChatGPT.app/Contents/Resources/codex"]
        return candidates.first(where: { FileManager.default.isExecutableFile(atPath: $0) }).map(URL.init(fileURLWithPath:))
    }
}

/// Each refresh owns one short-lived, stdio-only app-server. It never starts a conversation.
private final class CodexRPCReader: @unchecked Sendable {
    private let executable: URL
    private let environment: [String: String]
    private let timeout: TimeInterval
    private let lock = NSLock()
    private var cancelled = false
    private var buffer = Data()
    private var bytesRead = 0

    init(executable: URL, environment: [String: String], timeout: TimeInterval) {
        self.executable = executable; self.environment = environment; self.timeout = timeout
    }

    func cancel() {
        lock.lock(); cancelled = true; lock.unlock()
        // The polling reader checks every 100 ms and owns process cleanup.
    }

    private func checkCancellation() throws {
        lock.lock(); let value = cancelled; lock.unlock()
        if value { throw CancellationError() }
    }

    func read() throws -> UsageSnapshot {
        try checkCancellation()
        let child = Process()
        let input = Pipe(), output = Pipe()
        child.executableURL = executable
        child.arguments = ["app-server"]
        var env = environment
        // npm's codex launcher uses /usr/bin/env node; GUI launches often lack its directory.
        env["PATH"] = executable.deletingLastPathComponent().path + ":" + (environment["PATH"] ?? "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin")
        child.environment = env
        child.currentDirectoryURL = FileManager.default.homeDirectoryForCurrentUser
        child.standardInput = input
        child.standardOutput = output
        child.standardError = FileHandle.nullDevice // Do not persist CLI diagnostics or account data.
        defer {
            try? input.fileHandleForWriting.close()
            try? output.fileHandleForReading.close()
            if child.isRunning {
                child.terminate()
                for _ in 0..<10 where child.isRunning { usleep(10_000) }
                if child.isRunning { kill(child.processIdentifier, SIGKILL) }
            }
        }
        do { try child.run() }
        catch { throw MeterFailure.unavailable("无法启动 Codex CLI，请检查安装。") }
        try? input.fileHandleForReading.close()
        try? output.fileHandleForWriting.close()
        let fd = output.fileHandleForReading.fileDescriptor
        _ = fcntl(fd, F_SETFL, fcntl(fd, F_GETFL) | O_NONBLOCK)
        // A CLI crash between two requests must produce an error, not terminate the dashboard.
        _ = fcntl(input.fileHandleForWriting.fileDescriptor, F_SETNOSIGPIPE, 1)
        let deadline = Date().addingTimeInterval(timeout)
        try send(["id": 1, "method": "initialize", "params": ["clientInfo": ["name": "agentdock-usage", "title": "AgentDock", "version": Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "development"]]], to: input)
        _ = try response(id: 1, fd: fd, deadline: deadline)
        try send(["method": "initialized", "params": [:]], to: input)
        try send(["id": 2, "method": "account/read", "params": ["refreshToken": false]], to: input)
        let accountData = try response(id: 2, fd: fd, deadline: deadline)
        let accountPayload = (try? JSONSerialization.jsonObject(with: accountData)) as? [String: Any]
        guard let account = accountPayload?["account"] as? [String: Any] else { throw MeterFailure.notSignedIn("Codex") }
        guard account["type"] as? String == "chatgpt" else {
            throw MeterFailure.unavailable("Codex 当前使用 API 凭据；请在官方客户端登录 ChatGPT 订阅账号。")
        }
        try send(["id": 3, "method": "account/rateLimits/read", "params": [:]], to: input)
        let usage = try response(id: 3, fd: fd, deadline: deadline)
        try checkCancellation()
        return try QuotaParsers.codex(data: usage, accountData: accountData)
    }

    private func send(_ object: [String: Any], to pipe: Pipe) throws {
        try checkCancellation()
        var data = try JSONSerialization.data(withJSONObject: object)
        data.append(0x0a)
        do { try pipe.fileHandleForWriting.write(contentsOf: data) }
        catch { throw MeterFailure.unavailable("Codex CLI 连接已关闭。") }
    }

    private func response(id: Int, fd: Int32, deadline: Date) throws -> Data {
        while true {
            try checkCancellation()
            guard Date() < deadline else { throw MeterFailure.timedOut }
            while let newline = buffer.firstIndex(of: 0x0a) {
                let line = buffer.subdata(in: buffer.startIndex..<newline)
                buffer.removeSubrange(buffer.startIndex...newline)
                guard let object = (try? JSONSerialization.jsonObject(with: line)) as? [String: Any],
                      (object["id"] as? NSNumber)?.intValue == id else { continue }
                if let error = object["error"] as? [String: Any] { throw sanitizedRPCError(error) }
                guard let result = object["result"] as? [String: Any] else {
                    throw MeterFailure.invalidResponse("Codex CLI 返回了无效结果。")
                }
                return try JSONSerialization.data(withJSONObject: result)
            }
            var descriptor = pollfd(fd: fd, events: Int16(POLLIN), revents: 0)
            let ready = poll(&descriptor, 1, 100)
            if ready < 0 {
                if errno == EINTR { continue }
                throw MeterFailure.unavailable("读取 Codex CLI 失败。")
            }
            if ready == 0 { continue }
            var bytes = [UInt8](repeating: 0, count: 16_384)
            let count = Darwin.read(fd, &bytes, bytes.count)
            if count > 0 {
                bytesRead += count
                guard bytesRead <= 4_194_304, buffer.count + count <= 1_048_576 else {
                    throw MeterFailure.invalidResponse("Codex CLI 返回数据超出预期大小。")
                }
                buffer.append(contentsOf: bytes.prefix(count))
            } else if count == 0 { throw MeterFailure.unavailable("Codex CLI 提前退出，请检查 CLI 版本和登录状态。") }
            else if errno != EAGAIN && errno != EINTR { throw MeterFailure.unavailable("读取 Codex CLI 失败。") }
        }
    }

    private func sanitizedRPCError(_ error: [String: Any]) -> MeterFailure {
        // Inspect only to classify; never surface provider bodies which may contain account details.
        let message = (error["message"] as? String ?? "").lowercased()
        if message.contains("429") || message.contains("rate limit") { return .rateLimited }
        if message.contains("401") || message.contains("expired") { return .expired("Codex") }
        if message.contains("not logged") || message.contains("not authenticated") || message.contains("unauthorized") { return .notSignedIn("Codex") }
        if (error["code"] as? Int) == -32601 { return .unavailable("Codex CLI 不支持额度接口，请升级官方 CLI。") }
        return .unavailable("Codex 额度读取失败，请检查网络与官方客户端登录状态。")
    }
}
