import Foundation
import Security
import CryptoKit

public enum CredentialFailure: Error { case denied, malformed }

public protocol CredentialStorage {
    func read(service: String, account: String) throws -> Data?
    func write(service: String, account: String, data: Data?) throws
}

public struct LoginKeychain: CredentialStorage {
    public init() {}

    private func query(_ service: String, _ account: String) -> [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: service, kSecAttrAccount as String: account]
    }

    public func read(service: String, account: String) throws -> Data? {
        var query = query(service, account)
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        if status == errSecItemNotFound { return nil }
        guard status == errSecSuccess, let data = result as? Data, data.count <= 1_048_576 else {
            throw CredentialFailure.denied
        }
        return data
    }

    public func write(service: String, account: String, data: Data?) throws {
        let query = query(service, account)
        if let data {
            let status = SecItemUpdate(query as CFDictionary, [kSecValueData as String: data] as CFDictionary)
            if status == errSecItemNotFound {
                var insert = query
                insert[kSecValueData as String] = data
                guard SecItemAdd(insert as CFDictionary, nil) == errSecSuccess else { throw CredentialFailure.denied }
            } else if status != errSecSuccess { throw CredentialFailure.denied }
        } else {
            let status = SecItemDelete(query as CFDictionary)
            guard status == errSecSuccess || status == errSecItemNotFound else { throw CredentialFailure.denied }
        }
    }
}

/// Runs inside the signed desktop host, never a generic interpreter or a public
/// command-line credential oracle. The wrapping key never leaves this process.
public final class CredentialVault {
    private let storage: CredentialStorage
    private let keyService = "io.github.nginxl.AgentDock.snapshots"
    private var wrappingKey: SymmetricKey?
    public init(storage: CredentialStorage = LoginKeychain()) { self.storage = storage }

    private func key(create: Bool) throws -> SymmetricKey {
        if let wrappingKey { return wrappingKey }
        let key: SymmetricKey
        if let data = try storage.read(service: keyService, account: "aes-gcm-v1") {
            guard data.count == 32 else { throw CredentialFailure.malformed }
            key = SymmetricKey(data: data)
        } else {
            guard create else { throw CredentialFailure.denied }
            key = SymmetricKey(size: .bits256)
            try key.withUnsafeBytes { try storage.write(service: keyService, account: "aes-gcm-v1", data: Data($0)) }
        }
        wrappingKey = key
        return key
    }

    public func handle(_ request: [String: Any]) throws -> Any {
        guard let operation = request["operation"] as? String else { throw CredentialFailure.malformed }
        if operation == "seal" || operation == "unseal" {
            guard let encoded = request["data"] as? String, let data = Data(base64Encoded: encoded),
                  data.count <= 67_108_896, let context = request["context"] as? String,
                  !context.isEmpty, context.utf8.count <= 8192 else { throw CredentialFailure.malformed }
            let aad = Data(context.utf8)
            if operation == "seal" {
                let box = try AES.GCM.seal(data, using: key(create: true), authenticating: aad)
                guard let combined = box.combined else { throw CredentialFailure.malformed }
                return combined.base64EncodedString()
            }
            let box = try AES.GCM.SealedBox(combined: data)
            return try AES.GCM.open(box, using: key(create: false), authenticating: aad).base64EncodedString()
        }
        guard let service = request["service"] as? String, let account = request["account"] as? String,
              account.utf8.count <= 512,
              service == "Codex Auth" || service == "Claude Safe Storage" ||
              service == "Claude Code-credentials" || service.range(of: "^Claude Code-credentials-[a-f0-9]{8}$", options: .regularExpression) != nil else {
            throw CredentialFailure.denied
        }
        if operation == "read" {
            return try storage.read(service: service, account: account)?.base64EncodedString() as Any? ?? NSNull()
        }
        guard operation == "write", service != "Claude Safe Storage" else { throw CredentialFailure.denied }
        let data: Data?
        if request["data"] is NSNull { data = nil }
        else {
            guard let encoded = request["data"] as? String, let decoded = Data(base64Encoded: encoded), decoded.count <= 1_048_576 else {
                throw CredentialFailure.malformed
            }
            data = decoded
        }
        try storage.write(service: service, account: account, data: data)
        return NSNull()
    }
}

/// An unguessable capability is bootstrapped over the child's stdin. The Python
/// host duplicates then closes standard handles before spawning any CLI, and
/// never exports this capability via its environment, HTTP, files, or logs.
public final class CredentialChannel {
    public let requests = Pipe()
    public let responses = Pipe()
    private let secret: String
    private let vault: CredentialVault

    public init(vault: CredentialVault = CredentialVault()) {
        self.vault = vault
        let key = SymmetricKey(size: .bits256)
        secret = key.withUnsafeBytes { $0.map { String(format: "%02x", $0) }.joined() }
    }

    public func start() {
        try? requests.fileHandleForWriting.close()
        try? responses.fileHandleForReading.close()
        send(["credential_bootstrap": secret])
        DispatchQueue.global(qos: .userInitiated).async { [self] in
            var buffer = Data()
            while true {
                let chunk = requests.fileHandleForReading.availableData
                if chunk.isEmpty { break }
                buffer.append(chunk)
                if buffer.count > 96 * 1024 * 1024 { break }
                while let end = buffer.firstIndex(of: 10) {
                    let line = buffer.prefix(upTo: end)
                    buffer.removeSubrange(...end)
                    guard let request = (try? JSONSerialization.jsonObject(with: line)) as? [String: Any],
                          request["secret"] as? String == secret else { continue }
                    do { send(["data": try vault.handle(request)]) }
                    catch { send(["error": "credential_access_failed"]) }
                }
            }
            try? responses.fileHandleForWriting.close()
        }
    }

    private func send(_ value: [String: Any]) {
        guard var data = try? JSONSerialization.data(withJSONObject: value) else { return }
        data.append(10)
        try? responses.fileHandleForWriting.write(contentsOf: data)
    }
}
