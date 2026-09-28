import Foundation

public enum DesktopLanguage: String {
    case zh, en
    public func text(_ chinese: String, _ english: String) -> String { self == .zh ? chinese : english }
}

public struct MenuQuotaResponse: Decodable {
    public let quotas: [MenuQuota]
}

public struct MenuQuota: Decodable {
    public let agent_names: [String]?
    public let environment_id: String?
    public let environment_name: String?
    public let provider: String
    public let plan: String?
    public let status: String
    public let windows: [Window]
    public let fetched_at: String?
    public let error_code: String?

    public struct Window: Decodable {
        public let label: String
        public let remaining_percent: Double?
        public let reset_at: String?
    }

    public var displayName: String {
        let names = (agent_names ?? []).map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }.filter { !$0.isEmpty }
        let name = names.isEmpty ? (provider == "codex" ? "Codex" : "Claude") : names.joined(separator: " · ")
        let singleLine = name.components(separatedBy: .newlines).joined(separator: " ")
        return singleLine.count > 80 ? String(singleLine.prefix(79)) + "…" : singleLine
    }

    public func lines(language: DesktopLanguage, now: Date = Date(), timeZone: TimeZone = .current) -> [String] {
        let t = language.text
        let fetched = Self.date(fetched_at)
        let stale = status == "stale" || fetched.map { now.timeIntervalSince($0) > 900 || $0.timeIntervalSince(now) > 60 } == true
        var result: [String] = []
        if stale { result.append(t("待自动更新 · 显示上次数据", "Update pending · showing previous data")) }
        if error_code == "authorization_required" {
            result.append(t("等待 Claude 本地快照", "Waiting for the Claude local snapshot"))
        } else if let error_code, error_code != "outdated_cache" {
            result.append(t("读取失败 · 请在工作台查看详情", "Read failed · see workbench for details"))
        } else if status == "unavailable" || status == "disabled" {
            result.append(t("额度暂不可用", "Usage unavailable"))
        }
        for window in windows.prefix(4) {
            let reset = Self.date(window.reset_at)
            let value = window.remaining_percent
            let valid = value.map { $0.isFinite && (0...100).contains($0) } == true && (reset == nil || reset! > now)
            let remaining = valid ? t("剩余 ", "") + Self.percent(value!) + t("", " left") : t("剩余未知", "Remaining unknown")
            result.append("\(Self.label(window.label, language: language)) · \(remaining)")
            if let reset {
                let formatter = DateFormatter()
                formatter.locale = Locale(identifier: language == .zh ? "zh_CN" : "en_US")
                formatter.timeZone = timeZone
                formatter.dateFormat = language == .zh ? "M月d日 HH:mm" : "MMM d, HH:mm"
                result.append(t("重置 ", "Resets ") + formatter.string(from: reset))
            }
        }
        if windows.isEmpty { result.append(t("尚无可用额度数据", "No available usage data")) }
        if windows.count > 4 { result.append(t("更多额度请打开工作台", "Open the workbench for more limits")) }
        return result
    }

    private static func percent(_ number: Double) -> String {
        let rounded = (number * 10).rounded() / 10
        return (rounded.rounded() == rounded ? String(Int(rounded)) : String(rounded)) + "%"
    }

    private static func date(_ text: String?) -> Date? {
        guard let text else { return nil }
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let value = formatter.date(from: text) { return value }
        formatter.formatOptions = [.withInternetDateTime]
        return formatter.date(from: text)
    }

    private static func label(_ value: String, language: DesktopLanguage) -> String {
        let t = language.text
        switch value {
        case "5 hours", "5-hour", "5-hour window", "5 小时", "5 小时额度": return t("5 小时", "5 hours")
        case "7 days", "Weekly", "Weekly window", "7 天", "每周额度": return t("7 天", "7 days")
        case "主要窗口", "Primary window": return t("主要窗口", "Primary window")
        case "次要窗口", "Secondary window": return t("次要窗口", "Secondary window")
        case "Quota", "额度": return t("额度", "Quota")
        default:
            return language == .en ? value.replacingOccurrences(of: " 小时", with: " hours").replacingOccurrences(of: " 天", with: " days").replacingOccurrences(of: " 分钟", with: " minutes") : value
        }
    }
}
