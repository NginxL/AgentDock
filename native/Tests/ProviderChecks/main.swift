import Foundation
import Darwin
import MeterCore
import MeterProviders

// The test binary doubles as a synthetic app-server. No installed CLI, login, or network is used.
func runFakeAppServer() throws {
    let environment = ProcessInfo.processInfo.environment
    guard let mode = environment["AGENTMETER_CHECK_MODE"],
          let pidPath = environment["AGENTMETER_CHECK_PID"],
          let requestsPath = environment["AGENTMETER_CHECK_REQUESTS"] else { exit(80) }
    try Data(String(getpid()).utf8).write(to: URL(fileURLWithPath: pidPath))
    if mode == "timeout" { Thread.sleep(forTimeInterval: 20); return }
    if mode == "early-exit" { return }
    var methods: [String] = []
    while let line = readLine() {
        guard let request = try JSONSerialization.jsonObject(with: Data(line.utf8)) as? [String: Any],
              let method = request["method"] as? String,
              ["initialize", "initialized", "account/read", "account/rateLimits/read"].contains(method) else { exit(81) }
        methods.append(method)
        try Data(methods.joined(separator: "\n").utf8).write(to: URL(fileURLWithPath: requestsPath))
        if method == "initialized" { continue }
        let result: [String: Any]
        if method == "initialize" {
            result = ["userAgent": "offline-test"]
        } else if method == "account/read" {
            guard let params = request["params"] as? [String: Any], params["refreshToken"] as? Bool == false else { exit(82) }
            if mode == "signed-out" { result = ["account": NSNull()] }
            else { result = ["account": ["type": "chatgpt", "planType": "plus"]] }
        } else if mode == "rpc-error" {
            try emit(["id": request["id"]!, "error": ["code": -32000, "message": "synthetic-secret-never-expose 401 expired"]])
            continue
        } else if mode == "malformed" {
            result = ["rateLimits": ["primary": NSNull()]]
        } else if mode == "huge" {
            // This tests size validation, independently of the timeout fixture's short deadline.
            // A delayed, unterminated frame must still hit the unchanged 1 MiB size guard.
            Thread.sleep(forTimeInterval: 1.2)
            try FileHandle.standardOutput.write(contentsOf: Data(repeating: 0x78, count: 1_100_000))
            Thread.sleep(forTimeInterval: 20)
            continue
        } else {
            result = ["rateLimits": ["primary": ["usedPercent": 88]],
                      "rateLimitsByLimitId": ["codex": ["primary": ["usedPercent": 17, "windowDurationMins": 300],
                                                               "secondary": ["usedPercent": 3, "windowDurationMins": 10080]]]]
        }
        try emit(["method": "test/notification", "params": [:]])
        try emit(["id": request["id"]!, "result": result])
    }
}

func emit(_ object: [String: Any]) throws {
    let data = try JSONSerialization.data(withJSONObject: object)
    print(String(decoding: data, as: UTF8.self))
    fflush(stdout)
}

struct CheckFailure: Error, CustomStringConvertible {
    let description: String
}

func require(_ condition: @autoclosure () -> Bool, _ message: String) throws {
    if !condition() { throw CheckFailure(description: message) }
}

func failureKind(_ error: Error) -> String {
    guard let failure = error as? MeterFailure else { return String(describing: type(of: error)) }
    switch failure {
    case .invalidResponse: return "invalidResponse"
    case .timedOut: return "timedOut"
    case .unavailable: return "unavailable"
    case .notSignedIn: return "notSignedIn"
    case .expired: return "expired"
    case .rateLimited: return "rateLimited"
    default: return "other MeterFailure"
    }
}

func runProviderChecks() async throws {
    let directory = FileManager.default.temporaryDirectory.appendingPathComponent("AgentMeter-ProviderChecks-\(UUID().uuidString)", isDirectory: true)
    try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
    defer { try? FileManager.default.removeItem(at: directory) }
    let executable = URL(fileURLWithPath: CommandLine.arguments[0]).standardizedFileURL
    let pidFile = directory.appendingPathComponent("pid")
    let requestsFile = directory.appendingPathComponent("requests")
    var checks = 0

    for mode in ["valid", "signed-out", "malformed", "rpc-error", "timeout", "early-exit", "huge", "cancel"] {
        let environment = ["AGENTMETER_CHECK_MODE": mode == "cancel" ? "timeout" : mode,
                           "AGENTMETER_CHECK_PID": pidFile.path,
                           "AGENTMETER_CHECK_REQUESTS": requestsFile.path,
                           "PATH": "/usr/bin:/bin"]
        // Slow CI runners must reach the parser/size guard before its result is classified.
        // Keep the dedicated deadline and cancellation checks strict and independent.
        let timeout: TimeInterval = mode == "timeout" ? 1 : mode == "cancel" ? 20 : 10
        let provider = CodexProvider(timeout: timeout, executableURL: executable, environment: environment)
        let started = Date()
        let task = Task { try await provider.fetch() }
        if mode == "cancel" { try await Task.sleep(nanoseconds: 150_000_000); task.cancel() }
        let outcome: Result<UsageSnapshot, Error>
        do { outcome = .success(try await task.value) }
        catch { outcome = .failure(error) }

        let duration = Date().timeIntervalSince(started)
        let maximumDuration: TimeInterval = mode == "timeout" || mode == "cancel" ? 4 : 12
        try require(duration < maximumDuration, "\(mode): provider did not return promptly")
        let pidText = try String(contentsOf: pidFile, encoding: .utf8)
        guard let pid = Int32(pidText) else { throw CheckFailure(description: "\(mode): fake CLI never started") }
        try await Task.sleep(nanoseconds: 150_000_000)
        try require(kill(pid, 0) != 0, "\(mode): fake CLI still alive after fetch")
        switch outcome {
        case .success(let snapshot):
            try require(mode == "valid", "\(mode): unexpected successful quota")
            try require(snapshot.windows.map(\.usedPercent) == [17, 3], "Must prefer general Codex bucket")
            try require(snapshot.windows.map(\.title) == ["5 小时", "7 天"], "Window titles must reflect actual duration")
            let transcript = try String(contentsOf: requestsFile, encoding: .utf8)
            try require(transcript == "initialize\ninitialized\naccount/read\naccount/rateLimits/read", "Unexpected RPC method or ordering")
        case .failure(let error):
            try require(mode != "valid", "Valid fake CLI failed: \(error.localizedDescription)")
            try require(!error.localizedDescription.contains("synthetic-secret"), "Provider exposed a secret from RPC error")
            switch mode {
            case "signed-out": guard case MeterFailure.notSignedIn = error else { throw CheckFailure(description: "Wrong signed-out classification") }
            case "rpc-error": guard case MeterFailure.expired = error else { throw CheckFailure(description: "Wrong expired classification") }
            case "timeout": guard case MeterFailure.timedOut = error else { throw CheckFailure(description: "Wrong timeout classification") }
            case "cancel": try require(error is CancellationError, "Cancellation must remain cancellation")
            case "malformed", "huge":
                guard case MeterFailure.invalidResponse = error else {
                    throw CheckFailure(description: "\(mode): expected invalidResponse, received \(failureKind(error))")
                }
            default: break
            }
        }
        checks += 1
        print("PASS Codex \(mode), child cleaned up (\(String(format: "%.2f", duration))s)")
    }

    let snapshotFile = directory.appendingPathComponent("quota.json")
    let claude = ClaudeProvider(snapshotURL: snapshotFile)
    let stamp = Date().timeIntervalSince1970 * 1000 - 3_600_000
    let valid: [String: Any] = ["version": 2, "samples": [["t": stamp, "org": "fixture-org", "u": ["fh": 25, "sd": 70]]]]
    try JSONSerialization.data(withJSONObject: valid).write(to: snapshotFile)
    let result = try await claude.fetch()
    try require(result.windows.map(\.usedPercent) == [25, 70], "Wrong local usage")
    try require(result.windows.allSatisfy { $0.resetsAt == nil }, "Do not invent reset times")
    try require(abs(result.fetchedAt.timeIntervalSince1970 - stamp / 1000) < 0.001, "Do not replace the source timestamp")
    try require(result.accountID == nil, "Do not expose org identity")
    checks += 1
    for invalid: [String: Any] in [
        ["version": 3, "samples": []],
        ["version": 2, "samples": [["t": stamp, "org": "a", "u": ["fh": true]]]],
        ["version": 2, "samples": [["t": stamp, "org": "a", "u": ["fh": 101]]]],
        ["version": 2, "samples": [["t": stamp, "org": "a", "u": ["fh": 10]], ["t": stamp, "org": "b", "u": ["fh": 30]]]]
    ] {
        let data = try JSONSerialization.data(withJSONObject: invalid)
        var rejected = false
        do { _ = try ClaudeProvider.parse(data) } catch { rejected = true }
        try require(rejected, "Invalid or ambiguous quota must be rejected")
        checks += 1
    }
    print("\(checks) provider checks, 0 failures; no real credentials or account requests")
}

if CommandLine.arguments.dropFirst().first == "app-server" {
    do { try runFakeAppServer(); exit(0) }
    catch { exit(83) }
}

Task {
    do { try await runProviderChecks(); exit(0) }
    catch { print("FAIL: \(error)"); exit(1) }
}
dispatchMain()
