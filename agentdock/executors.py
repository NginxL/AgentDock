"""Local credential ownership and SSH transport share one execution request."""
from contextlib import nullcontext
from dataclasses import dataclass
from typing import Callable, Optional
import time

from .turn import NativeTurn


@dataclass(frozen=True)
class ExecutionRequest:
    turn: NativeTurn
    environment_id: str
    run_id: str
    session_id: str
    legacy_workspace: Optional[str]
    account: Optional[dict]
    account_branch: Optional[str]
    tool: Callable


class LocalExecutor:
    def __init__(self, accounts, execute):
        self.accounts, self.execute = accounts, execute

    def run(self, request: ExecutionRequest):
        turn = request.turn
        deadline = time.monotonic() + turn.timeout
        lease = self.accounts.credentials(request.account, turn.session_home, turn.stop) if request.account else nullcontext(None)
        with lease as environment:
            # Preserve the injected executor contract used by embedders/tests.
            options = dict(timeout=max(.1, deadline-time.monotonic()), permission_mode=turn.permission_mode, session_home=turn.session_home)
            if turn.control: options['control'] = turn.control
            if turn.model or turn.effort: options.update(model=turn.model, effort=turn.effort)
            if request.account: options.update(base_environment=environment, managed_account=True)
            return self.execute(turn.provider, turn.command, turn.cwd, turn.prompt, turn.native_session_id,
                                turn.mcp_config, turn.stop, turn.emit, turn.bind_session, turn.approve, **options)


class SSHExecutor:
    def __init__(self, remote):
        self.remote = remote

    def run(self, request: ExecutionRequest):
        turn = request.turn
        spec = {'provider': turn.provider, 'cwd': turn.cwd, 'prompt': turn.prompt,
                'session_id': request.session_id, 'legacy_workspace': request.legacy_workspace,
                'native_session_id': turn.native_session_id, 'model': turn.model, 'effort': turn.effort,
                'permission_mode': turn.permission_mode, 'timeout': turn.timeout}
        if request.account_branch: spec['account_branch'] = request.account_branch
        if request.account: spec['account'] = {key: request.account[key] for key in ('id', 'provider', 'generation')}
        return self.remote.run(request.environment_id, request.run_id, spec, turn.stop, turn.emit,
                               turn.bind_session, turn.approve, request.tool,
                               **({'control': turn.control} if turn.control else {}))
