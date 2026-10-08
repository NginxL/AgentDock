import Foundation
import CredentialCore

final class MemoryStorage: CredentialStorage {
    var values: [String: Data] = [:]
    func read(service: String, account: String) throws -> Data? { values[service + account] }
    func write(service: String, account: String, data: Data?) throws { values[service + account] = data }
}

let storage = MemoryStorage()
let vault = CredentialVault(storage: storage)
let plaintext = Data("fixture-refresh-token".utf8).base64EncodedString()
let encrypted = try vault.handle(["operation": "seal", "data": plaintext, "context": "/fixture/account-one"]) as! String
assert(encrypted != plaintext)
let reopened = CredentialVault(storage: storage)
let restored = try reopened.handle(["operation": "unseal", "data": encrypted, "context": "/fixture/account-one"]) as! String
assert(restored == plaintext)
for request: [String: Any] in [
    ["operation": "unseal", "data": encrypted, "context": "/fixture/account-two"],
    ["operation": "unseal", "data": Data(repeating: 0, count: 64).base64EncodedString(), "context": "/fixture/account-one"],
    ["operation": "read", "service": "io.github.nginxl.AgentDock.snapshots", "account": "aes-gcm-v1"],
    ["operation": "write", "service": "Claude Safe Storage", "account": "Claude", "data": plaintext],
] {
    var rejected = false
    do { _ = try vault.handle(request) } catch { rejected = true }
    assert(rejected)
}
print("Credential checks passed: AES-GCM roundtrip, persistence, tamper/context rejection, restricted Keychain operations. No real Keychain accessed.")

// Exercise the actual inherited-pipe transport with Python, without launching
// the desktop or opening a real credential store.
let process = Process(), output = Pipe()
let channel = CredentialChannel(vault: vault)
process.executableURL = URL(fileURLWithPath: "/usr/bin/env")
process.arguments = ["python3", "-c", """
from agentdock import credential_broker as broker
import os, subprocess, sys
broker.initialize()
assert 'AGENTDOCK_CREDENTIAL_PIPE' not in os.environ
assert all(not os.get_inheritable(f.fileno()) for f in broker._channel[:2])
encrypted = broker.seal(b'fixture-ipc', '/fixture/ipc')
assert broker.unseal(encrypted, '/fixture/ipc') == b'fixture-ipc'
try:
    broker.request('read', service='unrelated-service', account='unrelated-account')
    raise AssertionError('Unrelated Keychain item was accessible')
except broker.BrokerUnavailable:
    pass
child = subprocess.run([sys.executable, '-c', 'import sys; assert not sys.stdin.read(); print("isolated")'], capture_output=True)
assert child.returncode == 0 and child.stdout.strip() == b'isolated'
print('Credential IPC checks passed')
"""]
process.environment = ProcessInfo.processInfo.environment.merging(["AGENTDOCK_CREDENTIAL_PIPE": "1"]) { _, new in new }
process.standardInput = channel.responses
process.standardError = channel.requests
process.standardOutput = output
try process.run()
channel.start()
process.waitUntilExit()
assert(process.terminationStatus == 0)
let result = String(decoding: output.fileHandleForReading.readDataToEndOfFile(), as: UTF8.self)
assert(result.contains("Credential IPC checks passed"))
print(result.trimmingCharacters(in: .whitespacesAndNewlines))
