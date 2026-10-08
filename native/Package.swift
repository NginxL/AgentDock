// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "AgentDockDesktop",
    platforms: [.macOS(.v14)],
    products: [
        .executable(name: "AgentDock", targets: ["AgentDockDesktop"]),
        .executable(name: "AgentDockUsage", targets: ["AgentDockUsage"]),
    ],
    targets: [
        .target(name: "MeterCore"),
        .target(name: "DesktopCore"),
        .target(name: "CredentialCore"),
        .target(name: "MeterProviders", dependencies: ["MeterCore"]),
        .executableTarget(name: "AgentDockUsage", dependencies: ["MeterCore", "MeterProviders"]),
        .executableTarget(name: "AgentDockDesktop", dependencies: ["DesktopCore", "CredentialCore"]),
        .executableTarget(name: "CredentialChecks", dependencies: ["CredentialCore"], path: "Tests/CredentialChecks"),
        .executableTarget(name: "MeterChecks", dependencies: ["MeterCore"], path: "Tests/MeterChecks"),
        .executableTarget(name: "DesktopChecks", dependencies: ["DesktopCore"], path: "Tests/DesktopChecks"),
        .executableTarget(name: "MeterProviderChecks", dependencies: ["MeterCore", "MeterProviders"], path: "Tests/ProviderChecks"),
    ]
)
