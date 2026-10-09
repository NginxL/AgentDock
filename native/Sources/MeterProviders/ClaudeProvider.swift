import Foundation
import MeterCore

/// Claude quota arrives through running Claude Code sessions in the workbench.
/// Keep the helper protocol compatible without reading a desktop snapshot.
public struct ClaudeProvider: UsageProvider {
    public let kind: ProviderKind = .claude

    public init() {}

    public func fetch() async throws -> UsageSnapshot {
        try Task.checkCancellation()
        throw MeterFailure.unavailable("Claude 额度由运行中的 CLI 返回，尚无数据时显示未知。")
    }
}
