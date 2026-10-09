"""Inherit the CLI's network settings without changing them or running a shell."""

import json
import re
import shlex
from pathlib import Path

NETWORK_ENV = frozenset(
    {
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "no_proxy",
        "NODE_EXTRA_CA_CERTS",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "CODEX_CA_CERTIFICATE",
        "CLAUDE_CODE_CLIENT_CERT",
        "CLAUDE_CODE_CLIENT_KEY",
        "CLAUDE_CODE_CLIENT_KEY_PASSPHRASE",
        "CLAUDE_CODE_PROXY_RESOLVES_HOSTS",
        "CLAUDE_CODE_CERT_STORE",
    }
)


def claude_network(environment, command=()):
    """Keep network-only values; the native CLI still executes its own launcher.

    Literal wrapper exports override inherited values. Dynamic shell expressions
    are left to the CLI launcher and are never evaluated by AgentDock.
    """
    result = {k: v for k, v in environment.items() if k in NETWORK_ENV}
    source = Path(environment.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    for name in ("settings.json", "settings.local.json"):
        try:
            data = (source / name).read_bytes()
            if len(data) > 1024 * 1024:
                raise ValueError()
            values = json.loads(data).get("env", {})
            if isinstance(values, dict):
                for key, value in values.items():
                    if (
                        key in NETWORK_ENV
                        and isinstance(value, str)
                        and "\x00" not in value
                    ):
                        result.setdefault(key, value)
        except (OSError, ValueError, AttributeError):
            pass
    if command:
        try:
            with Path(command[0]).open("rb") as handle:
                raw = handle.read(65537)
        except OSError:
            raw = b""
        if raw.startswith(b"#!") and re.search(
            rb"\b(?:ba|z|da)?sh\b", raw.split(b"\n", 1)[0]
        ):
            for line in raw.decode("utf-8", errors="replace").splitlines()[1:]:
                match = re.fullmatch(
                    r"export\s+([A-Za-z_][A-Za-z_0-9]*)=(.*)", line.strip()
                )
                if (
                    not match
                    or match[1] not in NETWORK_ENV
                    or re.search(r"[$`;\n]", match[2])
                ):
                    continue
                try:
                    parts = shlex.split(match[2])
                except ValueError:
                    continue
                if len(parts) == 1:
                    result[match[1]] = parts[0]
    return result
