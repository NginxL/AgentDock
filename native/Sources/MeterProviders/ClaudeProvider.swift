import Foundation
import CoreFoundation
import MeterCore

/// Reads a quota-only snapshot written by Claude Desktop. Never reads credentials.
public struct ClaudeProvider: UsageProvider {
    public let kind: ProviderKind = .claude
    let snapshotURL: URL

    public init(snapshotURL: URL? = nil) {
        self.snapshotURL = snapshotURL ?? FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/Claude/plan-usage-history.json")
    }

    public func fetch() async throws -> UsageSnapshot {
        try Task.checkCancellation()
        guard FileManager.default.fileExists(atPath: snapshotURL.path) else {
            throw MeterFailure.unavailable("Claude Desktop 尚未保存额度数据，请在客户端登录并打开用量页面。")
        }
        let handle = try FileHandle(forReadingFrom: snapshotURL)
        defer { try? handle.close() }
        let data = try handle.read(upToCount: 4_194_305) ?? Data()
        guard data.count <= 4_194_304 else { throw MeterFailure.invalidResponse("Claude 额度快照过大。") }
        return try Self.parse(data)
    }

    public static func parse(_ data: Data, now: Date = Date()) throws -> UsageSnapshot {
        guard let root = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              let version = number(root["version"]), version == 2,
              let samples = root["samples"] as? [[String: Any]], !samples.isEmpty,
              samples.count <= 50_000 else { throw MeterFailure.invalidResponse("Claude 额度快照格式暂不支持。") }
        // The file does not identify the selected organization. Never mix accounts.
        let organizations = Set(samples.compactMap { $0["org"] as? String })
        guard organizations.count == 1, samples.allSatisfy({ ($0["org"] as? String)?.isEmpty == false }) else {
            throw MeterFailure.unavailable("额度快照包含多个账户，无法确认当前账户。")
        }
        let valid = samples.compactMap { sample -> (Double, [String: Any])? in
            guard let t = number(sample["t"]), t > 0, t / 1000 <= now.timeIntervalSince1970 + 60,
                  let usage = sample["u"] as? [String: Any] else { return nil }
            return (t, usage)
        }
        guard let latest = valid.max(by: { $0.0 < $1.0 }) else {
            throw MeterFailure.invalidResponse("Claude 额度快照没有有效时间。")
        }
        let windows = [("fh", "5 小时"), ("sd", "7 天")].map { key, title in
            let value = number(latest.1[key]).flatMap { (0...100).contains($0) ? $0 : nil }
            return QuotaWindow(id: key, title: title, usedPercent: value)
        }
        guard windows.contains(where: { $0.usedPercent != nil }) else {
            throw MeterFailure.invalidResponse("Claude 额度快照没有有效用量。")
        }
        return UsageSnapshot(provider: .claude, windows: windows,
                             fetchedAt: Date(timeIntervalSince1970: latest.0 / 1000), source: "claude-desktop-snapshot")
    }

    private static func number(_ value: Any?) -> Double? {
        guard let n = value as? NSNumber, CFGetTypeID(n) != CFBooleanGetTypeID(), n.doubleValue.isFinite else { return nil }
        return n.doubleValue
    }
}
