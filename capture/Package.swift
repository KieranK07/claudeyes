// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "claudeyes-capture",
    platforms: [.macOS(.v13)],
    targets: [
        .executableTarget(name: "claudeyes-capture", path: "Sources/claudeyes-capture")
    ]
)
