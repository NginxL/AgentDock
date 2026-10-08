"""Read local CLI model capabilities without submitting a prompt."""

import os
import tempfile
import threading
import time
from pathlib import Path

from .errors import Forbidden
from .providers import ProviderError, _Callbacks, _Codex, _Pipe
from .registry import ACP_PROVIDERS, PROVIDERS, commands


class Catalog:
    def __init__(self, config, *, stop=None):
        self.config, self.cache = config, {}
        self.locks = {provider: threading.Lock() for provider in PROVIDERS}
        self.stop = stop if stop is not None else threading.Event()

    def close(self):
        self.stop.set()
        for lock in self.locks.values():
            with lock:
                pass

    def invalidate(self):
        for provider, lock in self.locks.items():
            with lock:
                for key in list(self.cache):
                    if key == provider or isinstance(key, tuple) and key[0] == provider:
                        self.cache.pop(key, None)

    def read(self, provider, account_id=None, generation=0, environment=None):
        if not self.config.get("execution_enabled"):
            raise Forbidden("Execution is disabled for review")
        if provider not in PROVIDERS:
            raise ValueError("Unsupported provider")
        key = (provider, account_id, generation) if account_id else provider
        with self.locks[provider]:
            if self.stop.is_set():
                raise Forbidden("Model discovery is closed")
            stamp, value = self.cache.get(key, (0, None))
            if value and time.monotonic() - stamp < 300:
                return value
            command = commands(self.config.get("commands", {})).get(provider)
            if not isinstance(command, list) or not command:
                raise ValueError("Native CLI is not configured")
            if provider in ACP_PROVIDERS:
                value = self._acp(provider, command, environment)
                self.cache[key] = (time.monotonic(), value)
                return value
            argv = command + (
                ["--listen", "stdio://"]
                if provider == "codex"
                else [
                    "--print",
                    "--input-format",
                    "stream-json",
                    "--output-format",
                    "stream-json",
                    "--verbose",
                ]
            )
            env = dict(os.environ if environment is None else environment)
            cwd = str(Path.home())
            if account_id:
                cwd = env["AGENTDOCK_ACCOUNT_HOME"]
                if provider == "codex":
                    argv += [
                        "-c",
                        'cli_auth_credentials_store="file"',
                        "-c",
                        'model_provider="openai"',
                        "-c",
                        'forced_login_method="chatgpt"',
                    ]
                else:
                    argv += ["--setting-sources", "user"]
            pipe = _Pipe(argv, cwd, env, self.stop, 25)
            try:
                if provider == "codex":
                    adapter = _Codex(
                        pipe,
                        _Callbacks(
                            pipe, lambda *a: None, lambda *a: None, lambda *a: None, {}
                        ),
                    )
                    adapter.initialize()
                    raw, cursor = [], None
                    for _ in range(5):
                        result = adapter.request(
                            "model/list",
                            {
                                "limit": 100,
                                "includeHidden": False,
                                **({"cursor": cursor} if cursor else {}),
                            },
                        )
                        raw.extend(result.get("data", []))
                        cursor = result.get("nextCursor")
                        if not cursor:
                            break
                    models = [
                        {
                            "id": m.get("model"),
                            "name": m.get("displayName", m.get("model")),
                            "efforts": [
                                v.get("reasoningEffort")
                                for v in m.get("supportedReasoningEfforts", [])
                            ],
                        }
                        for m in raw
                        if isinstance(m, dict)
                    ]
                else:
                    pipe.send(
                        {
                            "type": "control_request",
                            "request_id": "catalog",
                            "request": {"subtype": "initialize", "hooks": None},
                        }
                    )
                    while True:
                        message = pipe.next()
                        if message.get("type") == "control_response":
                            response = message.get("response", {})
                            if (
                                response.get("request_id") != "catalog"
                                or response.get("subtype") != "success"
                            ):
                                raise ProviderError("Model discovery failed")
                            raw = response.get("response", {}).get("models", [])
                            break
                    models = [
                        {
                            "id": m.get("value"),
                            "name": m.get("displayName", m.get("value")),
                            "efforts": m.get("supportedEffortLevels", []),
                        }
                        for m in raw
                        if isinstance(m, dict)
                    ]
                # Whitelist metadata: initialize may also return private account information.
                models = [
                    m
                    for m in models
                    if isinstance(m["id"], str)
                    and len(m["id"]) <= 160
                    and isinstance(m["name"], str)
                    and isinstance(m["efforts"], list)
                    and all(isinstance(e, str) and len(e) <= 32 for e in m["efforts"])
                ][:100]
                value = {"provider": provider, "models": models}
                if account_id:
                    value["account_id"] = account_id
                self.cache[key] = (time.monotonic(), value)
                return value
            finally:
                pipe.close()

    def _acp(self, provider, command, environment=None):
        from contextlib import ExitStack

        from .acp import ACP
        from .credential_lease import catalog_home, credentials
        from .registry import acp_command

        with ExitStack() as stack:
            directory = stack.enter_context(
                tempfile.TemporaryDirectory(prefix="agentdock-catalog-")
            )
            source = os.environ if environment is None else environment
            env = stack.enter_context(
                credentials(provider, catalog_home(provider, source), source, self.stop)
            )
            cwd = Path(directory) / "workspace"
            cwd.mkdir()
            pipe = _Pipe(
                acp_command(provider, command, str(cwd), env, self.stop),
                str(cwd),
                env,
                self.stop,
                25,
            )
            try:
                adapter = ACP(
                    pipe,
                    _Callbacks(
                        pipe, lambda *a: None, lambda *a: None, lambda *a: None, {}
                    ),
                    provider,
                )
                adapter.setup(str(cwd), None, [])
                return {"provider": provider, "models": adapter.models()}
            finally:
                pipe.close()
