import Foundation
import MeterCore

var checks = 0
var failures: [String] = []
func expect(_ value: @autoclosure () -> Bool, _ message: String) {
    checks += 1
    if !value() { failures.append(message); print("FAIL: \(message)") }
}
func payload(_ text: String) -> Data { Data(text.utf8) }
func rejects(_ text: String, parser: (Data) throws -> UsageSnapshot, _ message: String) {
    do { _ = try parser(payload(text)); expect(false, message) }
    catch { expect(true, message) }
}

do {
    expect(ProviderKind.selectableCases == [.codex, .claude, .manual], "Only supported providers can be selected")
    expect(Subscription.defaults.map(\.provider) == [.codex, .claude], "Default subscriptions contain only Codex and Claude")
    let legacyKinds = try JSONDecoder().decode([ProviderKind].self, from: payload(#"["trae","doubao"]"#))
    expect(legacyKinds.allSatisfy { $0.isRetired && !$0.supportsAutomaticUsage }, "Legacy provider values decode for migration and cannot make automatic requests")
    let codex = try QuotaParsers.codex(data: payload(#"{"rateLimits":{"primary":{"usedPercent":21,"windowDurationMins":300,"resetsAt":1800000000},"secondary":{"usedPercent":43,"windowDurationMins":10080,"resetsAt":1800500000},"planType":"plus"}}"#))
    expect(codex.windows.count == 2, "Codex parses both quota windows")
    expect(codex.windows.first?.remainingPercent == 79, "Used and remaining percentages are not confused")
    expect(codex.windows.first?.resetsAt == Date(timeIntervalSince1970: 1800000000), "Reset timestamps use seconds")
    let weekly = try QuotaParsers.codex(data: payload(#"{"result":{"rateLimits":{"primary":{"usedPercent":9,"windowDurationMins":10080,"resetsAt":1800000000},"secondary":null}}}"#))
    expect(weekly.windows.count == 1, "Weekly-only plans do not invent a 5-hour allowance")
    expect(!weekly.windows[0].title.contains("5"), "Weekly-only plan has a duration-appropriate label")
    let mapped = try QuotaParsers.codex(data: payload(#"{"rateLimitsByLimitId":{"codex":{"primary":{"usedPercent":72,"windowDurationMins":300}},"code-review":{"primary":{"usedPercent":1,"windowDurationMins":10080}}},"rateLimits":{"primary":{"usedPercent":3,"windowDurationMins":300}}}"#))
    expect(mapped.windows.first?.usedPercent == 72, "Codex-specific map beats legacy and unrelated code-review data")
    let unknown = try QuotaParsers.codex(data: payload(#"{"rateLimits":{"primary":{"windowDurationMins":300,"resetsAt":1800000000}}}"#))
    expect(unknown.windows.first?.usedPercent == nil, "Missing percentage stays unknown, never zero")
    let claude = try QuotaParsers.claude(data: payload(#"{"five_hour":{"utilization":36.5,"resets_at":"2026-09-26T10:00:00Z"},"seven_day":{"utilization":61,"resets_at":"2026-10-01T10:00:00.000Z"},"seven_day_sonnet":null}"#))
    expect(claude.windows.count == 2, "Null Claude model windows are omitted")
    expect(claude.windows.first?.remainingPercent == 63.5, "Claude fractional quota remains precise")
    expect(claude.windows.allSatisfy { $0.resetsAt != nil }, "ISO8601 timestamps parse with and without fractional seconds")
    rejects("<html>Sign in</html>", parser: { try QuotaParsers.claude(data: $0) }, "HTML/login response cannot become a successful zero quota")
    rejects(#"{"error":{"message":"no access"}}"#, parser: { try QuotaParsers.codex(data: $0) }, "Error payload cannot become a successful zero quota")
    let now = Date(timeIntervalSince1970: 1800000000)
    let fresh = UsageSnapshot(provider: .codex, windows: [], fetchedAt: now, source: "Test")
    expect(!MeterPolicy.isStale(fresh, now: now.addingTimeInterval(60)), "Recent data stays fresh")
    expect(MeterPolicy.isStale(fresh, now: now.addingTimeInterval(1801)), "Old data is explicitly stale")
    expect(MeterPolicy.isStale(fresh, now: now.addingTimeInterval(-120)), "Future timestamps from clock changes are not considered fresh")
    let items = [Subscription(provider: .codex, name: "Codex", monthlyCost: 20, currency: "USD"), Subscription(provider: .manual, name: "Other", monthlyCost: 100, currency: "CNY"), Subscription(provider: .manual, name: "Paused", monthlyCost: 10, enabled: false)]
    expect(MeterPolicy.currencyTotals(items) == ["USD": 20, "CNY": 100], "Budgets are kept per currency and exclude disabled subscriptions")
    let encoded = try JSONEncoder().encode(items)
    let decoded = try JSONDecoder().decode([Subscription].self, from: encoded)
    expect(decoded == items, "Manual subscription values persist without changing dates or currency")
    expect(MeterPolicy.isNewerVersion("v1.1.0", than: "1.0.9"), "Semantic update comparison handles version segments")
    expect(!MeterPolicy.isNewerVersion("1.0.0-beta", than: "0.9.0"), "Stable updater ignores malformed/prerelease tags")
    expect(!MeterPolicy.isNewerVersion("1.0.0", than: "1.0.0"), "Current release does not trigger an update")
} catch { failures.append("Unexpected test error: \(error)"); print(failures.last!) }
print("\(checks) checks, \(failures.count) failures")
if !failures.isEmpty { exit(1) }
