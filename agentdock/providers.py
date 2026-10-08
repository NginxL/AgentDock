"""Native execution entry point; protocol clients have separate modules."""
from __future__ import annotations
import json
import math
import os
import uuid
from .provider_common import ProviderError, ProviderCancelled, _identifier, _validate_mcp
from .provider_common import account_error as account_error
from .registry import PROVIDERS, ACP_PROVIDERS
from .turn import NativeTurn
from dataclasses import replace
from .native_io import _Pipe as _Pipe, _Callbacks as _Callbacks
from .codex_protocol import _Codex as _Codex
from .claude_protocol import _Claude as _Claude

def execute(*args, **kwargs):
    """Compatibility entry for callers; implementation accepts one typed turn."""
    return execute_turn(NativeTurn(*args, **kwargs))


def execute_turn(turn: NativeTurn):
    if turn.session_home is None:
        return _execute(turn)
    from .execution_lease import lease
    from .credential_lease import credentials
    try:
        with lease(turn.session_home) as descriptor:
            turn = replace(turn, execution_fd=descriptor)
            if turn.provider in ACP_PROVIDERS:
                environment = dict(os.environ if turn.base_environment is None else turn.base_environment)
                with credentials(turn.provider, os.path.join(turn.session_home, turn.provider), environment, turn.stop) as environment:
                    return _execute(replace(turn, base_environment=environment, acp_prepared=True))
            return _execute(turn)
    except BlockingIOError:
        raise ProviderError('A previous native process still owns this conversation; wait before resuming.') from None


def _execute(turn: NativeTurn):
    """Run one turn and return final text, retaining native session identity.

    ``command`` is a trusted server-side argv prefix (``codex app-server`` or
    ``claude``), never user/model supplied. ``mcp_config`` is the sole AgentDock
    stdio server descriptor: ``{command, args, env}``. The caller owns session
    authorization and callbacks; ``approve`` returns an offered optionId.
    Cancellation and deadlines stop the whole child process group.
    """
    if turn.provider not in PROVIDERS:
        raise ProviderError("Unsupported native agent provider.")
    if turn.permission_mode not in ("ask", "full_access", "read_only"):
        raise ProviderError("Invalid agent permission mode")
    if (not isinstance(turn.command, list) or not turn.command or any(not isinstance(v, str) or not v
            or "\x00" in v for v in turn.command)):
        raise ProviderError("Configure a native CLI command for this provider.")
    if not isinstance(turn.prompt, str) or not turn.prompt.strip() or len(turn.prompt.encode()) > 400000:
        raise ProviderError("Agent prompt exceeds the supported size.")
    from .acp import ACP, identifier as acp_identifier
    valid_identifier = acp_identifier if turn.provider in ACP_PROVIDERS else _identifier
    if turn.native_session_id is not None and not valid_identifier(turn.native_session_id):
        raise ProviderError("The saved native session identifier is invalid.")
    if not isinstance(turn.timeout, (int, float)) or not math.isfinite(turn.timeout) or not 0 < turn.timeout <= 86400:
        raise ProviderError("The agent run timeout is invalid.")
    mcp, additions = _validate_mcp(turn.mcp_config)
    env = dict(os.environ if turn.base_environment is None else turn.base_environment)
    for key in ('CODEX_APP_TOOLS_PIPE_PATH', 'CODEX_THREAD_ID', 'CODEX_SESSION_ID', 'CODEX_INTERNAL_ORIGINATOR_OVERRIDE'):
        env.pop(key, None)
    env.update(additions)
    if turn.execution_fd is not None: env['AGENTDOCK_EXECUTION_LOCK_FD']=str(turn.execution_fd)
    argv = list(turn.command)
    native_id = turn.native_session_id
    session_ready = None
    if turn.provider == "codex":
        if turn.session_home is not None:
            from .codex_home import prepare
            original_env = dict(env)
            try:
                env, flags, legacy = prepare(os.path.join(turn.session_home, 'codex'), env, native_id, turn.cwd, managed=turn.managed_account)
            except (OSError, ValueError):
                raise ProviderError('Could not prepare isolated Codex session storage; no prompt was sent.') from None
            argv += flags
            if legacy:
                def session_ready():
                    # The private transcript has resumed successfully; remove the
                    # old duplicate without touching any other desktop conversation.
                    from .codex_home import retire_legacy
                    retire_legacy(turn.command, original_env, native_id)
        argv += ["--listen", "stdio://"]
    elif turn.provider == 'claude':
        original_env = dict(env)
        if turn.session_home is not None:
            from .session_storage import prepare_claude
            env = prepare_claude(os.path.join(turn.session_home, 'claude'), env, native_id)
        # Each worker owns one foreground turn; background work cannot outlive it.
        env["CLAUDE_CODE_DISABLE_BACKGROUND_TASKS"] = "1"
        if native_id:
            try:
                uuid.UUID(native_id)
            except ValueError:
                raise ProviderError("The saved Claude session identifier is invalid.") from None
        else:
            native_id = str(uuid.uuid4())
        argv += ["--print", "--output-format", "stream-json", "--verbose", "--input-format", "stream-json",
                 "--include-partial-messages", "--permission-prompt-tool", "stdio",
                 "--permission-mode", {'full_access':'bypassPermissions','read_only':'plan','ask':'manual'}[turn.permission_mode], "--strict-mcp-config",
                 "--mcp-config", json.dumps({"mcpServers": {"agentdock": {"type": "stdio", **mcp}}})]
        if turn.managed_account:
            # Keep project apiKeyHelper/env settings from silently replacing the
            # chosen subscription. Instructions and project files stay shared.
            argv += ['--setting-sources', 'user']
        if turn.model: argv += ["--model", turn.model]
        if turn.effort: argv += ["--effort", turn.effort]
        argv += ["--resume=" + native_id] if turn.native_session_id else ["--session-id", native_id]
    else:
        if turn.session_home is None:
            raise ProviderError('ACP agents require an isolated AgentDock session directory.')
        if turn.provider == 'pi' and turn.permission_mode != 'full_access':
            raise ProviderError('Pi does not gate its tools through ACP. Select full access explicitly to use Pi.')
        if not turn.acp_prepared: raise ProviderError('ACP credential lease is required.')
        from .registry import acp_command
        argv = acp_command(turn.provider, argv, turn.cwd, env, turn.stop)
        if turn.provider == 'opencode':
            env['OPENCODE_PERMISSION'] = '{"*":"ask"}'
    pipe = adapter = callbacks = None
    try:
        pipe = _Pipe(argv, turn.cwd, env, turn.stop, turn.timeout)
        callbacks = _Callbacks(pipe, turn.emit, turn.bind_session, turn.approve, additions)
        if turn.provider == "codex":
            adapter = _Codex(pipe, callbacks)
            return adapter.run(turn.cwd, turn.prompt, turn.native_session_id, mcp, additions, turn.model, turn.effort, turn.inherit_process_cwd, turn.permission_mode, session_ready, turn.control)
        if turn.provider in ACP_PROVIDERS:
            adapter = ACP(pipe, callbacks, turn.provider, turn.permission_mode)
            return adapter.run(os.path.realpath(turn.cwd), turn.prompt, turn.native_session_id, mcp, additions, turn.model, turn.effort)
        adapter = _Claude(pipe, callbacks, native_id)
        result = adapter.run(turn.prompt)
        if turn.session_home is not None and turn.native_session_id:
            from .session_storage import retire_legacy_claude
            retire_legacy_claude(original_env, turn.native_session_id)
        return result
    except (ProviderCancelled, ProviderError):
        if adapter:
            adapter.cancel()
        raise
    except Exception:
        raise ProviderError("Native agent run failed; private process details were omitted.") from None
    finally:
        if turn.control: turn.control.close()
        if pipe:
            pipe.close()
        if callbacks:
            callbacks.stream.close()
