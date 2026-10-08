"""macOS generic passwords. Secrets never enter process arguments or logs."""
import ctypes
import getpass
import hashlib
import json
import os
from pathlib import Path
import sys
import unicodedata


class KeychainError(ValueError):
    def __init__(self): super().__init__('Cannot access the macOS login Keychain.')


class Keychain:
    def __init__(self):
        if sys.platform != 'darwin': raise KeychainError()
        self.lib = ctypes.CDLL('/System/Library/Frameworks/Security.framework/Security')
        self.cf = ctypes.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
        pointer, length = ctypes.c_void_p, ctypes.c_uint32
        self.lib.SecKeychainFindGenericPassword.argtypes = [pointer, length, pointer, length, pointer,
                                                          ctypes.POINTER(length), ctypes.POINTER(pointer), ctypes.POINTER(pointer)]
        self.lib.SecKeychainItemModifyAttributesAndData.argtypes = [pointer, pointer, length, pointer]
        self.lib.SecKeychainAddGenericPassword.argtypes = [pointer, length, pointer, length, pointer, length, pointer, pointer]
        self.lib.SecKeychainItemFreeContent.argtypes = [pointer, pointer]
        self.lib.SecKeychainItemDelete.argtypes = [pointer]
        self.cf.CFRelease.argtypes = [pointer]

    def _find(self, service, account):
        service, account = service.encode(), account.encode()
        size, data, item = ctypes.c_uint32(), ctypes.c_void_p(), ctypes.c_void_p()
        status = self.lib.SecKeychainFindGenericPassword(None, len(service), service, len(account), account,
                                                       ctypes.byref(size), ctypes.byref(data), ctypes.byref(item))
        if status == -25300: return None, None
        if status: raise KeychainError()
        try:
            if size.value > 1024 * 1024: raise KeychainError()
            return ctypes.string_at(data, size.value), item
        finally: self.lib.SecKeychainItemFreeContent(None, data)

    def read(self, service, account):
        data, item = self._find(service, account)
        if item: self.cf.CFRelease(item)
        return data

    def write(self, service, account, data):
        _, item = self._find(service, account)
        try:
            if data is None:
                status = self.lib.SecKeychainItemDelete(item) if item else 0
            elif item:
                status = self.lib.SecKeychainItemModifyAttributesAndData(item, None, len(data), data)
            else:
                service, account = service.encode(), account.encode()
                status = self.lib.SecKeychainAddGenericPassword(None, len(service), service, len(account), account,
                                                               len(data), data, None)
            if status: raise KeychainError()
        finally:
            if item: self.cf.CFRelease(item)


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
