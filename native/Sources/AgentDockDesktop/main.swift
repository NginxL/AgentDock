import AppKit
import WebKit

final class DesktopDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate {
    private var window: NSWindow!
    private var web: WKWebView!
    private var child: Process?
    private var startupOutput = ""
    private var ready = false
    private var quitting = false
    private let origin = "http://127.0.0.1:47831"
    private let dataDirectory = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".local/share/agentdock")

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        makeMenu()
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1220, height: 840),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "AgentDock"
        window.minSize = NSSize(width: 780, height: 600)
        window.isReleasedWhenClosed = false
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .nonPersistent()
        web = WKWebView(frame: .zero, configuration: configuration)
        web.navigationDelegate = self
        window.contentView = web
        window.center()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        startService()
    }

    private func makeMenu() {
        let menu = NSMenu()
        let app = NSMenuItem(); menu.addItem(app)
        let applicationMenu = NSMenu(); app.submenu = applicationMenu
        applicationMenu.addItem(withTitle: "关于 AgentDock", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        applicationMenu.addItem(.separator())
        applicationMenu.addItem(withTitle: "退出 AgentDock", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        let edit = NSMenuItem(); menu.addItem(edit)
        let editMenu = NSMenu(title: "编辑"); edit.submenu = editMenu
        for (title, selector, key) in [("撤销", "undo:", "z"), ("剪切", "cut:", "x"), ("复制", "copy:", "c"), ("粘贴", "paste:", "v"), ("全选", "selectAll:", "a")] {
            editMenu.addItem(withTitle: title, action: Selector(selector), keyEquivalent: key)
        }
        let view = NSMenuItem(); menu.addItem(view)
        let viewMenu = NSMenu(title: "显示"); view.submenu = viewMenu
        let reload = viewMenu.addItem(withTitle: "重新载入", action: #selector(reloadPage), keyEquivalent: "r")
        reload.target = self
        NSApp.mainMenu = menu
    }

    private func startService() {
        do {
            guard let resources = Bundle.main.resourceURL,
                  let settings = try JSONSerialization.jsonObject(with: Data(contentsOf: resources.appendingPathComponent("runtime.json"))) as? [String: String],
                  let python = settings["python"], FileManager.default.isExecutableFile(atPath: python) else {
                throw NSError(domain: "AgentDock", code: 1)
            }
            let process = Process(), output = Pipe()
            process.executableURL = URL(fileURLWithPath: python)
            process.currentDirectoryURL = resources.appendingPathComponent("workbench")
            process.arguments = ["-u", "-m", "agentdock", "--config", dataDirectory.appendingPathComponent("config.json").path, "--enable-execution"]
            var env = ProcessInfo.processInfo.environment
            env["PATH"] = settings["path"] ?? "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"
            process.environment = env
            process.standardOutput = output
            process.standardError = FileHandle.nullDevice
            // Readiness is emitted only after this process owns the database, port and token.
            output.fileHandleForReading.readabilityHandler = { [weak self] handle in
                let data = handle.availableData
                guard !data.isEmpty else { handle.readabilityHandler = nil; return }
                let line = String(decoding: data, as: UTF8.self)
                DispatchQueue.main.async {
                    guard let self, !self.ready else { return }
                    self.startupOutput = String((self.startupOutput + line).suffix(4096))
                    if self.startupOutput.contains("AgentDock: " + self.origin) { self.connectOwnedService() }
                }
            }
            process.terminationHandler = { [weak self] _ in
                DispatchQueue.main.async {
                    guard let self else { return }
                    if self.quitting { NSApp.reply(toApplicationShouldTerminate: true) }
                    else { self.showFailure() }
                }
            }
            child = process
            try process.run()
        } catch { showFailure() }
    }

    private func connectOwnedService() {
        guard !ready, child?.isRunning == true else { return }
        do {
            let token = try String(contentsOf: dataDirectory.appendingPathComponent("admin.token"), encoding: .utf8).trimmingCharacters(in: .whitespacesAndNewlines)
            guard !token.isEmpty else { throw NSError(domain: "AgentDock", code: 2) }
            let values = try JSONSerialization.data(withJSONObject: ["token": token, "origin": origin])
            let literal = String(decoding: values, as: UTF8.self)
            let script = "(() => { const v = \(literal); if (location.origin === v.origin) { Object.defineProperty(window, '__AGENTDOCK_DESKTOP_TOKEN__', {value:v.token,configurable:true}); } })();"
            web.configuration.userContentController.addUserScript(WKUserScript(source: script, injectionTime: .atDocumentStart, forMainFrameOnly: true))
            ready = true
            web.load(URLRequest(url: URL(string: origin)!))
        } catch { showFailure() }
    }

    private func showFailure() {
        guard !quitting else { return }
        ready = false
        web.configuration.userContentController.removeAllUserScripts()
        web.loadHTMLString("<meta charset='utf-8'><body style='font:16px -apple-system;padding:60px'><h1>AgentDock 无法启动</h1><p>请确认 Python 可用，且没有其他 AgentDock 实例占用 47831 端口。退出后重新打开应用。</p><p>Unable to start. Check Python and port 47831, then reopen AgentDock.</p></body>", baseURL: nil)
    }

    @objc private func reloadPage() { if ready { web.reload() } }

    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = action.request.url else { decisionHandler(.cancel); return }
        if url.scheme == "about" || (url.scheme == "http" && url.host == "127.0.0.1" && url.port == 47831) {
            decisionHandler(.allow)
        } else {
            if action.navigationType == .linkActivated && ["http", "https"].contains(url.scheme ?? "") { NSWorkspace.shared.open(url) }
            decisionHandler(.cancel)
        }
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        window.makeKeyAndOrderFront(nil); return true
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard let child, child.isRunning else { return .terminateNow }
        if !quitting {
            quitting = true
            child.terminate() // Backend drains native children and quota probes before exiting.
        }
        return .terminateLater
    }
}

let application = NSApplication.shared
let delegate = DesktopDelegate()
application.delegate = delegate
application.run()
