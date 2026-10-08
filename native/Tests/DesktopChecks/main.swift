import Foundation
import DesktopCore

var checks = 0
var failures: [String] = []
func expect(_ value: @autoclosure () -> Bool, _ message: String) {
    checks += 1
    if !value() { failures.append(message); print("FAIL: \(message)") }
}
let now = ISO8601DateFormatter().date(from: "2026-09-28T04:00:00Z")!
let utc = TimeZone(secondsFromGMT: 0)!
func quota(_ values: [String: Any]) throws -> MenuQuota {
    var base: [String: Any] = ["provider": "codex", "status": "available", "fetched_at": "2026-09-28T04:00:00Z", "windows": []]
    base.merge(values) { _, new in new }
    return try JSONDecoder().decode(MenuQuota.self, from: JSONSerialization.data(withJSONObject: base))
}
func lines(_ values: [String: Any], _ language: DesktopLanguage = .zh) throws -> [String] {
    try quota(values).lines(language: language, now: now, timeZone: utc)
}

do {
    expect(ServiceLaunch.origin(in: "AgentDock: http://127.0.0.1:52345\n")?.port == 52345, "Readiness uses the actual bound loopback port")
    expect(ServiceLaunch.origin(in: "AgentDock: http://127.0.0.1:5234") == nil, "Partial readiness lines cannot authorize a different port")
    for address in ["http://localhost:52345", "https://127.0.0.1:52345", "http://127.0.0.1:80", "http://user@127.0.0.1:52345", "http://127.0.0.1:52345/path", "http://127.0.0.1:52345?token=x", "http://127.0.0.1:52345#x"] {
        expect(ServiceLaunch.origin(in: "AgentDock: " + address + "\n") == nil, "Unexpected origins never receive the desktop token")
    }
    let values: [String: Any] = ["windows": [["label": "5 小时", "remaining_percent": 25.5, "reset_at": "2026-09-28T05:30:00.000Z"]]]
    let zh = try lines(values), en = try lines(values, .en)
    expect(zh.contains("5 小时 · 剩余 25.5%"), "Remaining percentage is displayed without inverting it")
    expect(zh.contains("重置 9月28日 05:30"), "Reset time is shown in the selected time zone")
    expect(en.contains("5 hours · 25.5% left"), "Quota labels follow English language selection")
    expect(en.contains("Resets Sep 28, 05:30"), "English reset dates are localized")
    let zero = try lines(["windows": [["label": "Weekly", "remaining_percent": 0]]])
    expect(zero.contains("7 天 · 剩余 0%"), "Zero is a known exhausted quota, not unknown")
    let unknown = try lines(["windows": [["label": "Weekly", "remaining_percent": NSNull()]]])
    expect(unknown.contains("7 天 · 剩余未知"), "Missing allowance never becomes zero")
    for value in [-1, 101] {
        let invalid = try lines(["windows": [["label": "Quota", "remaining_percent": value]]])
        expect(invalid.contains("额度 · 剩余未知"), "Out-of-range quota is unknown")
    }
    let expired = try lines(["windows": [["label": "Quota", "remaining_percent": 70, "reset_at": "2026-09-28T03:00:00Z"]]])
    expect(expired.contains("额度 · 剩余未知"), "Passed reset time cannot keep an old remaining percentage")
    var old = values; old["fetched_at"] = "2026-09-28T03:00:00Z"
    let stale = try lines(old)
    expect(stale.contains("待自动更新 · 显示上次数据"), "Menu marks stale data without requesting a manual refresh")
    expect(stale.contains("5 小时 · 剩余 25.5%"), "Stale unexpired windows preserve last-known quota")
    let scoped = try lines(["windows": [["label": "Sonnet · 7 天", "remaining_percent": 100]]], .en)
    expect(scoped.contains("Sonnet · 7 days · 100% left"), "Scoped model windows translate duration labels")
    let failure = try lines(["status": "unavailable", "error_code": "authorization_required", "error": "private-token-fixture"])
    expect(failure.contains("等待 Claude 本地快照"), "Legacy authorization errors wait for a local snapshot without requesting Keychain access")
    expect(!failure.joined().contains("private-token"), "Raw provider errors are never rendered in the menu")
    let many = try lines(["windows": Array(repeating: ["label": "Quota", "remaining_percent": 80], count: 6)])
    expect(many.filter { $0.contains("80%") }.count == 4 && many.last == "更多额度请打开工作台", "Long provider lists are bounded with a workbench link hint")
    let empty = try JSONDecoder().decode(MenuQuotaResponse.self, from: Data(#"{"quotas":[]}"#.utf8))
    expect(empty.quotas.isEmpty, "A first launch with no quota cache decodes cleanly")
    let named = try quota(["agent_names": ["Helper", "Helper"], "environment_name": "Private devbox"])
    expect(named.displayName == "Helper · Helper", "Menu uses custom names, preserves equal names, and hides connection labels")
    let renamed = try quota(["agent_names": ["My assistant"]])
    expect(renamed.displayName == "My assistant", "A renamed agent is displayed without provider or device suffixes")
    let oldServer = try quota([:])
    expect(oldServer.displayName == "Codex", "Older server responses remain readable")
    let gemini = try quota(["provider":"gemini", "status":"unknown", "error_code":"unavailable", "fetched_at":NSNull()])
    expect(gemini.displayName == "Gemini CLI", "Other providers do not fall back to Claude")
    expect(gemini.lines(language:.en, now:now, timeZone:utc).contains("Quota unknown"), "Unsupported quota readers remain unknown")
    let longName = try quota(["agent_names": [String(repeating: "a", count: 120)]])
    expect(longName.displayName.count == 80, "Menu names are bounded")
} catch { failures.append("Unexpected error: \(error)") }
print("\(checks) checks, \(failures.count) failures")
if !failures.isEmpty { failures.forEach { print($0) }; exit(1) }
