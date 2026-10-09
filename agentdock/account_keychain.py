"""macOS generic passwords. Secrets never enter process arguments or logs."""

import base64
import getpass
import hashlib
import sys
import unicodedata

from . import credential_broker
from .errors import Invalid


class KeychainError(Invalid):
    code = "keychain_unavailable"

    def __init__(self):
        super().__init__("Cannot access the macOS login Keychain.")


class Keychain:
    """All macOS authorization belongs to the signed Swift desktop process."""

    def __init__(self):
        if sys.platform != "darwin":
            raise KeychainError()

    def read(self, service, account):
        try:
            value = credential_broker.request("read", service=service, account=account)
            return base64.b64decode(value, validate=True) if value is not None else None
        except (ValueError, credential_broker.BrokerUnavailable):
            raise KeychainError() from None

    def write(self, service, account, data):
        try:
            credential_broker.request(
                "write",
                service=service,
                account=account,
                data=base64.b64encode(data).decode() if data is not None else None,
            )
        except credential_broker.BrokerUnavailable:
            raise KeychainError() from None


def claude_service(environment):
    source = environment.get(
        "CLAUDE_SECURESTORAGE_CONFIG_DIR", environment.get("CLAUDE_CONFIG_DIR", "")
    )
    suffix = (
        "-"
        + hashlib.sha256(unicodedata.normalize("NFC", source).encode()).hexdigest()[:8]
        if source
        else ""
    )
    return "Claude Code-credentials" + suffix, environment.get(
        "USER"
    ) or getpass.getuser()
