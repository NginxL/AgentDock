"""macOS generic passwords. Secrets never enter process arguments or logs."""
import base64
from . import credential_broker
import getpass
import hashlib
import json
from pathlib import Path
import sys
import unicodedata


class KeychainError(ValueError):
    def __init__(self): super().__init__('Cannot access the macOS login Keychain.')


class Keychain:
    """All macOS authorization belongs to the signed Swift desktop process."""
    def __init__(self):
        if sys.platform != 'darwin':
            raise KeychainError()

    def read(self, service, account):
        try:
            value = credential_broker.request('read', service=service, account=account)
            return base64.b64decode(value, validate=True) if value is not None else None
        except (ValueError, credential_broker.BrokerUnavailable):
            raise KeychainError() from None

    def write(self, service, account, data):
        try:
            credential_broker.request('write', service=service, account=account,
                                      data=base64.b64encode(data).decode() if data is not None else None)
        except credential_broker.BrokerUnavailable:
            raise KeychainError() from None


def claude_service(environment):
    source = environment.get('CLAUDE_SECURESTORAGE_CONFIG_DIR', environment.get('CLAUDE_CONFIG_DIR', ''))
    suffix = '-' + hashlib.sha256(unicodedata.normalize('NFC', source).encode()).hexdigest()[:8] if source else ''
    return 'Claude Code-credentials' + suffix, environment.get('USER') or getpass.getuser()


def claude_credentials(environment):
    """Keychain is authoritative on macOS; errors are never treated as a miss."""
    if sys.platform == 'darwin':
        data = Keychain().read(*claude_service(environment))
        if data is not None:
            try:
                value = json.loads(data)
                if not isinstance(value, dict): raise ValueError()
                return value
            except ValueError: raise KeychainError() from None
    from .accounts import _read
    return _read(Path(environment.get('CLAUDE_CONFIG_DIR') or Path.home() / '.claude') / '.credentials.json', {})
