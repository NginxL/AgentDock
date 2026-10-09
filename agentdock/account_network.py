"""Read the CLI's network settings without changing them or executing shell code."""

import json
import re
import shlex
import ssl
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import (
    HTTPRedirectHandler,
    HTTPSHandler,
    ProxyHandler,
    Request,
    build_opener,
    proxy_bypass_environment,
)

from . import __version__
from .errors import Invalid

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


class NetworkError(Invalid):
    def __init__(self, code, retry_after=0):
        self.code, self.retry_after = code, retry_after
        super().__init__(code)


def claude_network(environment, command=(), *, strict=False):
    """Wrapper exports win over the parent environment, as at CLI startup.

    Only literal network assignments in a simple shell launcher are accepted.
    Dynamic launchers continue to work for the native CLI; independent HTTP
    reads refuse to guess their network policy. No proxy data is stored per user.
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
        except FileNotFoundError:
            pass
        except (OSError, ValueError, AttributeError):
            if strict:
                raise NetworkError("network_configuration_unavailable") from None
    if command:
        if strict and Path(command[0]).name in (
            "env",
            "sh",
            "bash",
            "zsh",
            "python",
            "python3",
            "node",
        ):
            raise NetworkError("network_configuration_unavailable")
        try:
            with Path(command[0]).open("rb") as handle:
                raw = handle.read(65537)
        except OSError:
            if strict:
                raise NetworkError("network_configuration_unavailable") from None
            raw = b""
        if raw.startswith(b"#!") and re.search(
            rb"\b(?:ba|z|da)?sh\b", raw.split(b"\n", 1)[0]
        ):
            if strict and len(raw) > 65536:
                raise NetworkError("network_configuration_unavailable")
            text = raw.decode("utf-8", errors="replace")
            for line in text.splitlines()[1:]:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                match = re.fullmatch(r"export\s+([A-Za-z_][A-Za-z_0-9]*)=(.*)", line)
                if match and match[1] in NETWORK_ENV:
                    value = match[2]
                    # Do not evaluate variables, substitutions, or conditionals.
                    if re.search(r"[$`;\n]", value):
                        if strict:
                            raise NetworkError("network_configuration_unavailable")
                        continue
                    try:
                        parts = shlex.split(value)
                    except ValueError:
                        parts = []
                    if len(parts) != 1:
                        if strict:
                            raise NetworkError("network_configuration_unavailable")
                        continue
                    result[match[1]] = parts[0]
                elif line.startswith("exec ") and line.endswith('"$@"'):
                    # A native executable may be delegated to, never another
                    # script whose additional networking we cannot establish.
                    try:
                        target = (
                            shlex.split(line)[1]
                            .replace("${HOME}", str(Path.home()))
                            .replace("$HOME", str(Path.home()))
                        )
                        with Path(target).open("rb") as handle:
                            nested = handle.read(128)
                        if nested.startswith(b"#!") and re.search(
                            rb"\b(?:ba|z|da)?sh\b", nested.split(b"\n", 1)[0]
                        ):
                            if strict:
                                raise NetworkError("network_configuration_unavailable")
                    except (OSError, ValueError):
                        if strict:
                            raise NetworkError(
                                "network_configuration_unavailable"
                            ) from None
                elif strict:
                    raise NetworkError("network_configuration_unavailable")
    return result


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # An OAuth credential must never follow a response to another origin.
        raise NetworkError("quota_unavailable")


def claude_get(path, token, network):
    """Read-only OAuth endpoints, with explicit proxy selection and no retry route."""
    if path not in ("usage", "profile"):
        raise ValueError("Invalid account endpoint")
    proxy = network.get(
        "https_proxy",
        network.get("HTTPS_PROXY", network.get("all_proxy", network.get("ALL_PROXY"))),
    )
    if proxy:
        try:
            parsed = urlsplit(proxy)
            if parsed.scheme not in ("http", "https") or not parsed.hostname:
                raise ValueError()
        except ValueError:
            raise NetworkError("network_configuration_unavailable") from None
    if proxy_bypass_environment(
        "api.anthropic.com",
        {"no": network.get("no_proxy", network.get("NO_PROXY", ""))},
    ):
        proxy = None

    # The stdlib reads NO_PROXY from the process environment. For credential
    # requests use an explicit handler so unrelated service environment cannot
    # silently bypass the inherited proxy.
    class FixedProxy(ProxyHandler):
        def proxy_open(self, req, proxy_url, type_):
            req.set_proxy(urlsplit(proxy_url).netloc, urlsplit(proxy_url).scheme)
            return None

    if proxy and (urlsplit(proxy).username or urlsplit(proxy).password):
        raise NetworkError("network_configuration_unavailable")
    try:
        if network.get("CLAUDE_CODE_CERT_STORE") not in (None, "", "bundled"):
            raise NetworkError("network_configuration_unavailable")
        context = ssl.create_default_context(
            cafile=network.get("SSL_CERT_FILE"), capath=network.get("SSL_CERT_DIR")
        )
        if network.get("NODE_EXTRA_CA_CERTS"):
            context.load_verify_locations(network["NODE_EXTRA_CA_CERTS"])
        if network.get("CLAUDE_CODE_CLIENT_CERT"):
            context.load_cert_chain(
                network["CLAUDE_CODE_CLIENT_CERT"],
                network.get("CLAUDE_CODE_CLIENT_KEY"),
                network.get("CLAUDE_CODE_CLIENT_KEY_PASSPHRASE"),
            )
        opener = build_opener(
            FixedProxy({"https": proxy} if proxy else {}),
            HTTPSHandler(context=context),
            _NoRedirect(),
        )
        request = Request(
            "https://api.anthropic.com/api/oauth/" + path,
            headers={
                "Authorization": "Bearer " + token,
                "anthropic-beta": "oauth-2025-04-20",
                "User-Agent": "AgentDock/" + __version__,
                "Accept": "application/json",
            },
        )
        with opener.open(request, timeout=15) as response:
            data = response.read(1024 * 1024 + 1)
        if len(data) > 1024 * 1024:
            raise ValueError()
        value = json.loads(data)
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except HTTPError as error:
        retry = error.headers.get("Retry-After", "")
        try:
            retry = (
                int(retry)
                if retry.isdigit()
                else (
                    parsedate_to_datetime(retry) - datetime.now(timezone.utc)
                ).total_seconds()
            )
            retry = min(86400, max(60, retry))
        except (ValueError, TypeError, OverflowError):
            retry = 60
        raise NetworkError(
            "auth_expired"
            if error.code == 401
            else "rate_limited"
            if error.code == 429
            else "quota_unavailable",
            retry,
        ) from None
    except (OSError, URLError, ValueError) as error:
        if isinstance(error, NetworkError):
            raise
        raise NetworkError("network_unavailable") from None
