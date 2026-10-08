# Native credential boundary

| Evidence | Verified behavior | Boundary |
| --- | --- | --- |
| `CredentialCore/CredentialVault.swift` | Keychain reads and writes run inside the signed AgentDock desktop process. Snapshot AES-256-GCM keys stay in that process and its own Keychain entry. | Python never loads Security.framework. Previously granted Python Keychain permissions remain macOS settings; this upgrade cannot safely revoke another client's permissions. |
| `credential_broker.py`, desktop launcher | A private inherited pipe authenticates requests using a random bootstrap capability; it is absent from files, arguments, environment and HTTP. Python closes the original standard handles and makes duplicates non-inheritable before starting CLIs. | No public socket or standalone executable returns credentials to arbitrary callers. Processes that already control AgentDock's own memory remain outside this boundary. |
| `NativeAccounts._save/_load` | Account snapshots and rollback journals contain authenticated ciphertext. Paths are bound as additional authenticated data; the key is never saved beside the ciphertext. | Public labels and saved timestamps remain readable. Encryption does not hide them. |
| `protect_legacy` | Desktop startup atomically encrypts older base64-only files, including pending and previous snapshots, before native account actions. Authorization failure leaves native logins untouched. | Removed plaintext may remain in filesystem snapshots or backups. Migration does not claim secure erasure on APFS/SSD. |
| `CredentialChecks` | Real CryptoKit encrypt/decrypt, key persistence with an in-memory Keychain fixture, tamper/path rejection, and Swift↔Python pipe transport pass. | No actual native login was switched and no real Keychain item was read during verification. |

Native switching requires the desktop credential broker. Launching the Python server alone does not grant it Keychain access. Existing CLI execution keeps its original authentication and proxy configuration. First use after an app update may require macOS Keychain authorization for the signed AgentDock application.

The snapshot key belongs to this Mac's login Keychain. Copying encrypted files to another machine without that key does not restore a login. Loss or refusal of the key fails closed; there is no plaintext fallback.
