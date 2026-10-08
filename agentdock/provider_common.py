"""Shared protocol errors and validation, independent of execution/storage."""
from __future__ import annotations
import math
import re

_MAX_LINE = 524288
_MAX_OUTPUT = 8388608
_MAX_EVENTS = 10000
_MAX_RESULT = 262144
_MAX_APPROVALS = 64

class ProviderError(Exception):
    """A safe, stable diagnostic; never contains raw provider stderr or errors."""

    def __init__(self, message, *, code=None, retry_after=None, rejected=False):
        super().__init__(message)
        self.code = code
        self.retry_after = retry_after
        self.rejected = bool(rejected)

def account_error(value, fallback):
    """Classify structured CLI rejection codes, never model text or raw stderr.

    A rejection is only a candidate for retry. The dispatcher independently
    proves that no output, tool, approval or collaboration activity occurred.
    """
    code, retry_after = None, None
    pending = [(value, 0)]
    while pending:
        item, depth = pending.pop()
        if depth > 4 or not isinstance(item, dict):
            continue
        marker = item.get('codexErrorInfo', item.get('error_code', item.get('code', item.get('type'))))
        if isinstance(marker, dict):
            pending.append((marker, depth + 1))
            marker = next(iter(marker), '')
        if isinstance(marker, str):
            normalized = re.sub(r'[_-]', '', marker).lower()
            if normalized in ('unauthorized', 'authenticationfailed', 'authenticationerror', 'autherror', 'invalidapikey'):
                code = 'auth_expired'
            elif normalized in ('usagelimitexceeded', 'quotaexceeded', 'insufficientquota'):
                code = 'quota_exhausted'
            elif normalized in ('ratelimit', 'ratelimited', 'ratelimiterror', 'ratelimitexceeded'):
                code = 'rate_limited'
        status = item.get('httpStatusCode', item.get('status_code'))
        if status == 401: code = 'auth_expired'
        elif status == 429: code = code or 'rate_limited'
        delay = item.get('retryAfterSeconds', item.get('retry_after'))
        if isinstance(delay, (int, float)) and not isinstance(delay, bool) and math.isfinite(delay) and delay >= 0:
            retry_after = min(86400 * 7, max(1, delay))
        for key in ('error', 'data', 'details', 'httpConnectionFailed', 'responseStreamConnectionFailed'):
            child = item.get(key)
            if isinstance(child, dict): pending.append((child, depth + 1))
            elif key == 'error' and isinstance(child, str): pending.append(({'code': child}, depth + 1))
    messages = {'auth_expired': 'This account needs to sign in again.',
                'quota_exhausted': 'This account has reached its usage limit.',
                'rate_limited': 'This account is temporarily rate limited.'}
    return ProviderError(messages.get(code, fallback), code=code, retry_after=retry_after, rejected=bool(code))

class ProviderCancelled(Exception):
    pass

def _identifier(value):
    return isinstance(value, str) and bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}", value))

def _validate_mcp(config):
    if (not isinstance(config, dict) or not isinstance(config.get("command"), str)
            or not config["command"] or "\x00" in config["command"]):
        raise ProviderError("The configured AgentDock MCP command is invalid.")
    args, env = config.get("args", []), config.get("env", {})
    if (not isinstance(args, list) or any(not isinstance(v, str) or "\x00" in v for v in args)
            or not isinstance(env, dict) or any(not isinstance(k, str) or not k
                or "=" in k or "\x00" in k or not isinstance(v, str) or "\x00" in v
                for k, v in env.items())):
        raise ProviderError("The configured AgentDock MCP arguments are invalid.")
    return {"command": config["command"], "args": list(args)}, dict(env)
