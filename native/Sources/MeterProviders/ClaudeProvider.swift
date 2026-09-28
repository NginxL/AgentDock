import Foundation
import Security
import LocalAuthentication
import CoreFoundation
import MeterCore

public struct ClaudeProvider: UsageProvider {
    public let kind: ProviderKind = .claude
    let allowKeychainPrompt: Bool
    let environment: [String: String]

    public init(allowKeychainPrompt: Bool = false, environment: [String: String] = ProcessInfo.processInfo.environment) {
        self.allowKeychainPrompt = allowKeychainPrompt
        self.environment = environment
    }

    public func fetch() async throws -> UsageSnapshot {
        try Task.checkCancellation()
        let credentials = try await Task.detached(priority: .utility) {
            try ClaudeCredentialReader.read(environment: environment, allowKeychainPrompt: allowKeychainPrompt)
        }.value
        try Task.checkCancellation()
        if let expiration = credentials.expiresAt, expiration <= Date() { throw MeterFailure.expired("Claude Code") }
        if let scopes = credentials.scopes, !scopes.contains("user:profile") {
            throw MeterFailure.unavailable("Claude 登录凭据缺少 user:profile 权限，请在 Claude Code 重新登录。")
        }

        var request = URLRequest(url: URL(string: "https://api.anthropic.com/api/oauth/usage")!)
        request.httpMethod = "GET"
        request.timeoutInterval = 25
        request.setValue("Bearer \(credentials.accessToken)", forHTTPHeaderField: "Authorization")
        request.setValue("oauth-2025-04-20", forHTTPHeaderField: "anthropic-beta")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("AgentDock/0.2.3", forHTTPHeaderField: "User-Agent")
        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = 25
        configuration.timeoutIntervalForResource = 30
        configuration.waitsForConnectivity = false
        configuration.urlCache = nil
        configuration.httpCookieStorage = nil
        configuration.httpShouldSetCookies = false
        configuration.urlCredentialStorage = nil
        let session = URLSession(configuration: configuration, delegate: NoUsageRedirects(), delegateQueue: nil)
        defer { session.invalidateAndCancel() }
        do {
            let (data, response) = try await session.data(for: request)
            try Task.checkCancellation()
            guard let response = response as? HTTPURLResponse else { throw MeterFailure.invalidResponse("Claude 返回了无效响应。") }
            switch response.statusCode {
            case 200:
                guard data.count <= 1_048_576 else { throw MeterFailure.invalidResponse("Claude 返回数据超出预期大小。") }
                return try QuotaParsers.claude(data: data, plan: credentials.plan)
            case 401: throw MeterFailure.expired("Claude Code")
            case 403: throw MeterFailure.unavailable("Claude 拒绝读取额度，请检查订阅和 Claude Code 登录权限。")
            case 429: throw MeterFailure.rateLimited
            default: throw MeterFailure.unavailable("Claude 额度接口暂不可用（HTTP \(response.statusCode)）。")
            }
        } catch is CancellationError { throw CancellationError() }
        catch let error as MeterFailure { throw error }
        catch let error as URLError where error.code == .cancelled { throw CancellationError() }
        catch let error as URLError where error.code == .timedOut { throw MeterFailure.timedOut }
        catch { throw MeterFailure.unavailable("无法连接 Claude 额度接口，请检查网络后重试。") }
    }
}

/// Do not forward a bearer credential to a redirected endpoint.
private final class NoUsageRedirects: NSObject, URLSessionTaskDelegate, @unchecked Sendable {
    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) {
        completionHandler(nil)
    }
}

private struct ClaudeReadCredential: Sendable {
    let accessToken: String
    let expiresAt: Date?
    let scopes: [String]?
    let plan: String?
}

private enum ClaudeCredentialReader {
    static func read(environment: [String: String], allowKeychainPrompt: Bool) throws -> ClaudeReadCredential {
        let customDirectory = environment["CLAUDE_CONFIG_DIR"]?.trimmingCharacters(in: .whitespacesAndNewlines)
        let usesCustomDirectory = customDirectory?.isEmpty == false
        let directory: URL
        if let customDirectory, usesCustomDirectory {
            directory = URL(fileURLWithPath: (customDirectory as NSString).expandingTildeInPath, isDirectory: true)
        } else {
            directory = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".claude", isDirectory: true)
        }
        let file = directory.appendingPathComponent(".credentials.json")
        var fileFailure: MeterFailure?
        if FileManager.default.fileExists(atPath: file.path) {
            do {
                let size = try file.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0
                guard size <= 1_048_576 else { throw MeterFailure.invalidResponse("Claude 登录凭据格式异常，请在官方客户端重新登录。") }
                let credential = try parse(Data(contentsOf: file))
                if credential.expiresAt.map({ $0 <= Date() }) != true { return credential }
                fileFailure = .expired("Claude Code")
            } catch let error as MeterFailure { fileFailure = error }
            catch { fileFailure = .unavailable("无法读取 Claude Code 登录凭据。") }
        }
        // A different CLAUDE_CONFIG_DIR denotes another profile. Never borrow the default profile's login.
        if usesCustomDirectory { throw fileFailure ?? MeterFailure.notSignedIn("Claude Code") }
        do {
            return try parse(readKeychain(allowPrompt: allowKeychainPrompt))
        } catch let error as MeterFailure {
            if case .notSignedIn = error, let fileFailure { throw fileFailure }
            throw error
        }
    }

    private static func readKeychain(allowPrompt: Bool) throws -> Data {
        var query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: "Claude Code-credentials",
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        if !allowPrompt {
            let context = LAContext()
            context.interactionNotAllowed = true
            query[kSecUseAuthenticationContext as String] = context
        }
        var result: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        switch status {
        case errSecSuccess:
            guard let data = result as? Data, data.count <= 1_048_576 else {
                throw MeterFailure.invalidResponse("Claude 钥匙串凭据格式异常。")
            }
            return data
        case errSecItemNotFound: throw MeterFailure.notSignedIn("Claude Code")
        case errSecInteractionNotAllowed, errSecAuthFailed, errSecUserCanceled:
            throw MeterFailure.authorizationRequired
        default: throw MeterFailure.unavailable("无法读取 Claude Code 钥匙串凭据，请检查系统钥匙串权限。")
        }
    }

    private static func parse(_ data: Data) throws -> ClaudeReadCredential {
        guard let root = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
              let oauth = root["claudeAiOauth"] as? [String: Any],
              let rawToken = oauth["accessToken"] as? String else { throw MeterFailure.notSignedIn("Claude Code") }
        let token = rawToken.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !token.isEmpty, !token.contains("\r"), !token.contains("\n") else { throw MeterFailure.notSignedIn("Claude Code") }
        var expiresAt: Date?
        if let raw = oauth["expiresAt"] as? NSNumber, CFGetTypeID(raw) != CFBooleanGetTypeID(),
           raw.doubleValue.isFinite, raw.doubleValue > 0, raw.doubleValue < 253_402_300_800_000 {
            expiresAt = Date(timeIntervalSince1970: raw.doubleValue / 1000)
        }
        let plan = (oauth["subscriptionType"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines)
        return ClaudeReadCredential(accessToken: token, expiresAt: expiresAt, scopes: oauth["scopes"] as? [String],
                                    plan: plan?.isEmpty == false ? plan : nil)
    }
}
