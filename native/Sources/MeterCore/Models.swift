import Foundation

public enum ProviderKind: String, Codable, Sendable {
    case codex, claude, manual
    // Decode-only compatibility for persisted entries removed by AppModel's migration.
    case trae, doubao
    public static let selectableCases: [ProviderKind] = [.codex, .claude, .manual]
    public var isRetired: Bool { self == .trae || self == .doubao }
    public var supportsAutomaticUsage: Bool { self == .codex || self == .claude }
    public var name: String {
        switch self { case .codex: return "Codex"; case .claude: return "Claude"; case .manual, .trae, .doubao: return "Custom" }
    }
}

public struct QuotaWindow: Codable, Identifiable, Equatable, Sendable {
    public var id: String
    public var title: String
    public var usedPercent: Double?
    public var resetsAt: Date?
    public var remainingPercent: Double? { usedPercent.map { max(0, min(100, 100 - $0)) } }
    public init(id: String, title: String, usedPercent: Double?, resetsAt: Date? = nil) {
        self.id = id; self.title = title
        self.usedPercent = usedPercent.flatMap { $0.isFinite ? max(0, min(100, $0)) : nil }
        self.resetsAt = resetsAt
    }
}

public struct UsageSnapshot: Codable, Equatable, Sendable {
    public var provider: ProviderKind
    public var plan: String?
    public var windows: [QuotaWindow]
    public var fetchedAt: Date
    public var source: String
    public var accountID: String?
    public init(provider: ProviderKind, plan: String? = nil, windows: [QuotaWindow], fetchedAt: Date = Date(), source: String, accountID: String? = nil) {
        self.provider = provider; self.plan = plan; self.windows = windows
        self.fetchedAt = fetchedAt; self.source = source; self.accountID = accountID
    }
}

public enum RenewalKind: String, Codable, CaseIterable, Sendable { case renews, expires }

public struct ManualUsage: Codable, Equatable, Sendable {
    public var windows: [QuotaWindow]
    public var recordedAt: Date
    public init(windows: [QuotaWindow], recordedAt: Date = Date()) {
        self.windows = windows; self.recordedAt = recordedAt
    }
}

public struct Subscription: Codable, Identifiable, Equatable, Sendable {
    public var id: UUID
    public var provider: ProviderKind
    public var name: String
    public var plan: String
    public var renewalDate: Date?
    public var renewalKind: RenewalKind
    public var monthlyCost: Double?
    public var currency: String
    public var notes: String
    public var enabled: Bool
    public var manualTracking: Bool?
    public var manualUsage: ManualUsage?
    public var usesManualUsage: Bool { !provider.supportsAutomaticUsage || manualTracking == true }
    public init(id: UUID = UUID(), provider: ProviderKind, name: String, plan: String = "", renewalDate: Date? = nil, renewalKind: RenewalKind = .renews, monthlyCost: Double? = nil, currency: String = "USD", notes: String = "", enabled: Bool = true, manualTracking: Bool? = nil, manualUsage: ManualUsage? = nil) {
        self.id = id; self.provider = provider; self.name = name; self.plan = plan
        self.renewalDate = renewalDate; self.renewalKind = renewalKind; self.monthlyCost = monthlyCost
        self.currency = currency; self.notes = notes; self.enabled = enabled
        self.manualTracking = manualTracking; self.manualUsage = manualUsage
    }
    public static var defaults: [Subscription] {
        [Subscription(provider: .codex, name: "Codex"), Subscription(provider: .claude, name: "Claude")]
    }
}

public enum MeterFailure: Error, LocalizedError, Sendable {
    case authorizationRequired
    case notInstalled(String), notSignedIn(String), expired(String), unavailable(String), invalidResponse(String), timedOut, rateLimited
    public var errorDescription: String? {
        switch self {
        case .authorizationRequired: return "Claude 凭据需要钥匙串授权，请点击“连接 Claude”。"
        case .notInstalled(let name): return "\(name) CLI 未安装，或未找到可执行文件。"
        case .notSignedIn(let name): return "请先在 \(name) 官方客户端登录订阅账号。"
        case .expired(let name): return "\(name) 登录已过期，请在官方客户端重新登录。"
        case .unavailable(let message), .invalidResponse(let message): return message
        case .timedOut: return "读取超时，稍后可重试。"
        case .rateLimited: return "服务商暂时限流，请稍后重试。"
        }
    }
}

public protocol UsageProvider: Sendable {
    var kind: ProviderKind { get }
    func fetch() async throws -> UsageSnapshot
}
