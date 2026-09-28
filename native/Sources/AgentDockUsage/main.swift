import Foundation
import MeterCore
import MeterProviders

// This helper has no windows, menu item, timers, subscription store or login flow.
// Credentials remain in the provider's existing local store and are never emitted.
let arguments = Array(CommandLine.arguments.dropFirst())
guard arguments.count == 2, ["--probe", "--authorize"].contains(arguments[0]),
      ["codex", "claude"].contains(arguments[1]),
      arguments[0] != "--authorize" || arguments[1] == "claude" else {
    fputs("Usage: AgentDockUsage --probe codex|claude, or --authorize claude\n", stderr)
    exit(2)
}
let kind = arguments[1]
Task {
    do {
        let provider: any UsageProvider = kind == "codex"
            ? CodexProvider() : ClaudeProvider(allowKeychainPrompt: arguments[0] == "--authorize")
        var snapshot = try await provider.fetch()
        snapshot.accountID = nil
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        print(String(decoding: try encoder.encode(snapshot), as: UTF8.self))
    } catch {
        let code: String
        switch error as? MeterFailure {
        case .authorizationRequired: code = "authorization_required"
        case .notInstalled: code = "not_installed"
        case .notSignedIn: code = "not_signed_in"
        case .expired: code = "expired"
        case .rateLimited: code = "rate_limited"
        case .timedOut: code = "timeout"
        default: code = "unavailable"
        }
        // Whitelisted error codes only; no provider body, token or account identifier.
        let data = try! JSONSerialization.data(withJSONObject: ["provider": kind, "error_code": code])
        print(String(decoding: data, as: UTF8.self))
    }
    exit(0)
}
RunLoop.main.run()
