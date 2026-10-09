"""Private inherited-pipe client for the signed macOS host.

No socket, file token, command argument, environment secret or callable credential
helper is exposed. Native subprocesses receive neither the bootstrap secret nor
the broker's response pipe. The desktop host owns all Keychain/CryptoKit calls.
"""

import base64
import json
import os
import sys
import threading

from .errors import Forbidden

_channel = None
_lock = threading.Lock()


class BrokerUnavailable(Forbidden):
    code = "native_credentials_desktop_required"

    def __init__(self):
        super().__init__("Open AgentDock desktop to use protected native credentials.")


def initialize():
    global _channel
    if os.environ.pop("AGENTDOCK_CREDENTIAL_PIPE", "") != "1":
        return
    # Only the signed launcher sends this once, before readiness. Keep the pipe
    # private and replace stdin/stderr so subsequently launched children cannot
    # inherit either broker endpoint.
    incoming = os.fdopen(os.dup(0), "rb")
    outgoing = os.fdopen(os.dup(2), "wb")
    null = os.open(os.devnull, os.O_RDWR)
    os.dup2(null, 0)
    os.dup2(null, 2)
    os.close(null)
    try:
        bootstrap = json.loads(incoming.readline(1024))
        secret = bootstrap["credential_bootstrap"]
        if not isinstance(secret, str) or len(secret) != 64:
            raise ValueError()
    except (KeyError, ValueError, OSError):
        incoming.close()
        outgoing.close()
        raise BrokerUnavailable() from None
    _channel = (incoming, outgoing, secret)


def available():
    return _channel is not None and sys.platform == "darwin"


def request(operation, **values):
    if not available():
        raise BrokerUnavailable()
    with _lock:
        incoming, outgoing, secret = _channel
        try:
            outgoing.write(
                json.dumps(
                    {"secret": secret, "operation": operation, **values}
                ).encode()
                + b"\n"
            )
            outgoing.flush()
            data = incoming.readline(96 * 1024 * 1024)
            response = json.loads(data)
            if response.get("error") or "data" not in response:
                raise ValueError()
            return response["data"]
        except (OSError, ValueError):
            raise BrokerUnavailable() from None


def seal(data, context):
    return request("seal", data=base64.b64encode(data).decode(), context=context)


def unseal(data, context):
    try:
        return base64.b64decode(
            request("unseal", data=data, context=context), validate=True
        )
    except (ValueError, TypeError):
        raise BrokerUnavailable() from None
