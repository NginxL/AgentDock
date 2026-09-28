import Foundation
import CoreFoundation

/// Parsing is deliberately independent of credentials and transport, so fixtures can verify it offline.
public enum QuotaParsers {
    public static func codex(data: Data, accountData: Data? = nil, fetchedAt: Date = Date()) throws -> UsageSnapshot {
        let payload = try object(data, provider: "Codex")
        let accountPayload = try accountData.map { try object($0, provider: "Codex") }
        let account = accountPayload?["account"] as? [String: Any]
        let buckets = payload["rateLimitsByLimitId"] as? [String: Any]
        var selected: [String: Any]?
        for key in ["codex", "general", "default"] {
            if let bucket = buckets?[key] as? [String: Any], isGeneralCodexBucket(bucket) {
                selected = bucket
                break
            }
        }
        if selected == nil, let legacy = payload["rateLimits"] as? [String: Any], isGeneralCodexBucket(legacy) {
            // An unlabelled legacy snapshot is ambiguous when only specialized buckets are supplied.
            if buckets == nil || buckets?.isEmpty == true || cleanString(legacy["limitId"]) != nil {
                selected = legacy
            }
        }
        guard let selected else {
            throw MeterFailure.invalidResponse("Codex 未返回通用订阅额度。")
        }
        var windows: [QuotaWindow] = []
        for key in ["primary", "secondary"] {
            guard let window = selected[key] as? [String: Any] else { continue }
            windows.append(QuotaWindow(
                id: "codex.\(key)",
                title: durationTitle(number(window["windowDurationMins"]), fallback: key == "primary" ? "主要窗口" : "次要窗口"),
                usedPercent: number(window["usedPercent"]),
                resetsAt: epochDate(window["resetsAt"])))
        }
        guard !windows.isEmpty else { throw MeterFailure.invalidResponse("Codex 未返回可用的额度窗口。") }
        return UsageSnapshot(provider: .codex,
                             plan: cleanString(selected["planType"]) ?? cleanString(account?["planType"]),
                             windows: windows, fetchedAt: fetchedAt, source: "Codex CLI",
                             accountID: cleanString(payload["accountId"]) ?? cleanString(account?["email"]))
    }

    public static func claude(data: Data, plan: String? = nil, fetchedAt: Date = Date()) throws -> UsageSnapshot {
        let payload = try object(data, provider: "Claude")
        var windows: [QuotaWindow] = []
        let definitions = [("five_hour", "5 小时"), ("seven_day", "7 天"),
                           ("seven_day_sonnet", "Sonnet · 7 天"), ("seven_day_opus", "Opus · 7 天")]
        for (key, title) in definitions {
            guard let window = payload[key] as? [String: Any] else { continue }
            windows.append(QuotaWindow(id: key, title: title, usedPercent: number(window["utilization"]),
                                       resetsAt: isoDate(window["resets_at"])))
        }
        // Newer Claude responses expose model-specific limits separately from the legacy windows.
        // is_active is not a validity flag: real scoped quotas may report false.
        if let limits = payload["limits"] as? [[String: Any]] {
            var seen = Set<String>()
            for entry in limits where cleanString(entry["kind"]) == "weekly_scoped" {
                guard cleanString(entry["group"]) == "weekly",
                      let scope = entry["scope"] as? [String: Any],
                      let model = scope["model"] as? [String: Any],
                      let name = cleanString(model["display_name"]) else { continue }
                let identity = cleanString(model["id"]) ?? name.lowercased()
                guard seen.insert(identity).inserted else { continue }
                let replacementKey = "seven_day_\(name.lowercased())"
                if number(entry["percent"]) == nil, windows.contains(where: { $0.id == replacementKey && $0.usedPercent != nil }) { continue }
                // An explicit scoped row supersedes the matching legacy model row.
                windows.removeAll { $0.id == replacementKey }
                windows.append(QuotaWindow(id: "claude.scoped.\(identity)", title: "\(name) · 7 天",
                                           usedPercent: number(entry["percent"]), resetsAt: isoDate(entry["resets_at"])))
            }
        }
        guard !windows.isEmpty else { throw MeterFailure.invalidResponse("Claude 未返回可用的额度窗口。") }
        return UsageSnapshot(provider: .claude, plan: plan, windows: windows, fetchedAt: fetchedAt, source: "Claude OAuth")
    }

    private static func object(_ data: Data, provider: String) throws -> [String: Any] {
        guard let root = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw MeterFailure.invalidResponse("\(provider) 返回了无法解析的数据。")
        }
        if root["error"] != nil { throw MeterFailure.invalidResponse("\(provider) 读取额度失败。") }
        if root.keys.contains("result") {
            guard let result = root["result"] as? [String: Any] else {
                throw MeterFailure.invalidResponse("\(provider) 返回了空的读取结果。")
            }
            return result
        }
        return root
    }

    private static func isGeneralCodexBucket(_ bucket: [String: Any]) -> Bool {
        guard let id = cleanString(bucket["limitId"])?.lowercased() else { return true }
        return ["codex", "general", "default"].contains(id)
    }

    private static func cleanString(_ value: Any?) -> String? {
        guard let value = value as? String else { return nil }
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed
    }

    private static func number(_ value: Any?) -> Double? {
        guard let value = value as? NSNumber, CFGetTypeID(value) != CFBooleanGetTypeID(), value.doubleValue.isFinite else { return nil }
        return value.doubleValue
    }

    private static func epochDate(_ value: Any?) -> Date? {
        guard let seconds = number(value), seconds > 0, seconds < 253_402_300_800 else { return nil }
        return Date(timeIntervalSince1970: seconds)
    }

    private static func isoDate(_ value: Any?) -> Date? {
        guard let string = cleanString(value) else { return nil }
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = formatter.date(from: string) { return date }
        formatter.formatOptions = [.withInternetDateTime]
        return formatter.date(from: string)
    }

    private static func durationTitle(_ minutes: Double?, fallback: String) -> String {
        guard let minutes, minutes > 0, minutes < 10_000_000 else { return fallback }
        let value: Double
        let unit: String
        if minutes.truncatingRemainder(dividingBy: 1440) == 0 { value = minutes / 1440; unit = "天" }
        else if minutes.truncatingRemainder(dividingBy: 60) == 0 { value = minutes / 60; unit = "小时" }
        else { value = minutes; unit = "分钟" }
        return "\(value == value.rounded() ? String(Int(value)) : String(format: "%.1f", value)) \(unit)"
    }
}
