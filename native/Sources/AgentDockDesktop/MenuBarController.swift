import AppKit
import DesktopCore

private final class LocalRedirectPolicy: NSObject, URLSessionTaskDelegate {
    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) {
        completionHandler(nil) // Never forward the local bearer token to a redirect destination.
    }
}

@MainActor
final class MenuBarController: NSObject, NSMenuDelegate {
    private let statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
    private let menu = NSMenu()
    private let openItem = NSMenuItem()
    private let quitItem = NSMenuItem()
    private let stateItem = NSMenuItem()
    private var quotaItems: [NSMenuItem] = []
    private let openWorkbench: () -> Void
    private let origin: URL
    private var token: String?
    private var task: Task<Void, Never>?
    private var generation = 0
    private var connectionFailed = false
    private var snapshots: [MenuQuota] = []
    private let session: URLSession
    var language: DesktopLanguage { didSet { render() } }

    init(origin: URL, language: DesktopLanguage, openWorkbench: @escaping () -> Void) {
        self.origin = origin
        self.language = language
        self.openWorkbench = openWorkbench
        let configuration = URLSessionConfiguration.ephemeral
        configuration.httpShouldSetCookies = false
        configuration.urlCache = nil
        configuration.requestCachePolicy = .reloadIgnoringLocalCacheData
        session = URLSession(configuration: configuration, delegate: LocalRedirectPolicy(), delegateQueue: nil)
        super.init()
        menu.delegate = self
        menu.autoenablesItems = false
        statusItem.autosaveName = "AgentDock.menu"
        if let button = statusItem.button {
            let image = NSImage(systemSymbolName: "square.stack.3d.up", accessibilityDescription: "AgentDock")
            image?.isTemplate = true
            button.image = image
            if image == nil { button.title = "AD" }
            button.toolTip = "AgentDock"
            button.setAccessibilityLabel("AgentDock")
        }
        statusItem.menu = menu
        menu.addItem(withTitle: "AgentDock", action: nil, keyEquivalent: "").isEnabled = false
        configure(openItem, action: #selector(openWindow)); menu.addItem(openItem)
        menu.addItem(.separator())
        stateItem.isEnabled = false; menu.addItem(stateItem)
        menu.addItem(.separator())
        configure(quitItem, action: #selector(quit)); menu.addItem(quitItem)
        render()
    }

    private func configure(_ item: NSMenuItem, action: Selector) {
        item.target = self; item.action = action; item.isEnabled = true
    }

    func connect(token: String) {
        generation += 1; task?.cancel(); task = nil
        self.token = token; connectionFailed = false
        render(); fetch()
    }

    func disconnect() {
        generation += 1; task?.cancel(); task = nil
        token = nil; connectionFailed = true
        render()
    }

    func menuWillOpen(_ menu: NSMenu) { render(); fetch() }

    func showMenu() { statusItem.button?.performClick(nil) }

    private func render() {
        let t = language.text
        openItem.title = t("打开工作台", "Open workbench")
        quitItem.title = t("退出 AgentDock", "Quit AgentDock")
        stateItem.title = connectionFailed ? t("本地服务不可用 · 请重新打开应用", "Local service unavailable · reopen the app") : token == nil ? t("正在启动本地服务…", "Starting local service…") : t("添加 Agent 以查看额度", "Add an agent to view usage")
        stateItem.isHidden = !connectionFailed && token != nil && !snapshots.isEmpty
        for item in quotaItems { menu.removeItem(item) }
        quotaItems.removeAll()
        var index = 3
        for snapshot in snapshots {
            let name = snapshot.provider == "codex" ? "Codex" : "Claude"
            let environment = snapshot.environment_id == nil || snapshot.environment_id == "local" ? t("本机", "This Mac") : snapshot.environment_name ?? t("远端", "Remote")
            let header = NSMenuItem(title: name + " · " + environment + (snapshot.plan.map { " · " + $0 } ?? ""), action: nil, keyEquivalent: "")
            header.isEnabled = false
            var group = [header]
            for text in snapshot.lines(language: language).prefix(12) {
                let item = NSMenuItem(title: text, action: nil, keyEquivalent: "")
                item.isEnabled = false; item.indentationLevel = 1; group.append(item)
            }
            group.append(.separator())
            for item in group { menu.insertItem(item, at: index); index += 1; quotaItems.append(item) }
        }
    }

    private func fetch() {
        guard let token, task == nil else { return }
        let started = generation
        task = Task { [weak self] in
            guard let self else { return }
            defer {
                if generation == started { task = nil; render() }
            }
            do {
                let data = try await request("api/quotas", token: token)
                let response = try JSONDecoder().decode(MenuQuotaResponse.self, from: data)
                guard generation == started, !Task.isCancelled else { return }
                snapshots = response.quotas
                connectionFailed = false
            } catch {
                guard generation == started, !Task.isCancelled else { return }
                connectionFailed = true
            }
        }
    }

    private func request(_ path: String, token: String) async throws -> Data {
        var request = URLRequest(url: origin.appendingPathComponent(path), timeoutInterval: 5)
        request.setValue("Bearer " + token, forHTTPHeaderField: "Authorization")
        let (data, response) = try await session.data(for: request)
        guard (response as? HTTPURLResponse)?.statusCode == 200, data.count <= 1_048_576 else { throw URLError(.badServerResponse) }
        return data
    }

    @objc private func openWindow() { openWorkbench() }
    @objc private func quit() { NSApp.terminate(nil) }
}
