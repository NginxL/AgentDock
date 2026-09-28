import AppKit

let destination = URL(fileURLWithPath: CommandLine.arguments[1])
let folder = destination.deletingPathExtension().appendingPathExtension("iconset")
try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
for size in [16, 32, 128, 256, 512] {
    for scale in [1, 2] {
        let pixels = size * scale
        let image = NSImage(size: NSSize(width: pixels, height: pixels))
        image.lockFocus()
        let side = CGFloat(pixels)
        NSColor(srgbRed: 0.36, green: 0.32, blue: 0.72, alpha: 1).setFill()
        NSBezierPath(roundedRect: NSRect(x: side * 0.06, y: side * 0.06, width: side * 0.88, height: side * 0.88), xRadius: side * 0.20, yRadius: side * 0.20).fill()
        let text = NSAttributedString(string: "AD", attributes: [.font: NSFont.systemFont(ofSize: side * 0.40, weight: .bold), .foregroundColor: NSColor.white])
        let measured = text.size()
        text.draw(at: NSPoint(x: (side - measured.width) / 2, y: (side - measured.height) / 2))
        image.unlockFocus()
        let bitmap = NSBitmapImageRep(data: image.tiffRepresentation!)!
        let suffix = scale == 1 ? "" : "@2x"
        try bitmap.representation(using: .png, properties: [:])!.write(to: folder.appendingPathComponent("icon_\(size)x\(size)\(suffix).png"))
    }
}
let process = Process()
process.executableURL = URL(fileURLWithPath: "/usr/bin/iconutil")
process.arguments = ["-c", "icns", folder.path, "-o", destination.path]
try process.run(); process.waitUntilExit()
guard process.terminationStatus == 0 else { exit(1) }
try FileManager.default.removeItem(at: folder)
