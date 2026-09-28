import Foundation

public enum MeterPolicy {
    public static let refreshInterval: TimeInterval = 15 * 60
    public static let staleInterval: TimeInterval = 30 * 60

    public static func isStale(_ snapshot: UsageSnapshot, now: Date = Date()) -> Bool {
        now.timeIntervalSince(snapshot.fetchedAt) > staleInterval || snapshot.fetchedAt > now.addingTimeInterval(60)
    }

    public static func currencyTotals(_ subscriptions: [Subscription]) -> [String: Double] {
        subscriptions.filter(\.enabled).reduce(into: [:]) { result, item in
            guard let amount = item.monthlyCost, amount.isFinite, amount >= 0 else { return }
            result[item.currency, default: 0] += amount
        }
    }

    public static func isNewerVersion(_ candidate: String, than current: String) -> Bool {
        func components(_ text: String) -> [Int]? {
            let value = text.hasPrefix("v") ? String(text.dropFirst()) : text
            let parts = value.split(separator: ".", omittingEmptySubsequences: false)
            guard parts.count == 3 else { return nil }
            let values = parts.compactMap { Int($0) }
            return values.count == 3 && values.allSatisfy { $0 >= 0 } ? values : nil
        }
        guard let lhs = components(candidate), let rhs = components(current) else { return false }
        return lhs.lexicographicallyPrecedes(rhs) == false && lhs != rhs
    }
}
