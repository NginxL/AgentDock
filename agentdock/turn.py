"""Explicit immutable inputs to one native turn."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Event
from typing import Any, Callable, Optional


@dataclass(frozen=True)
class NativeTurn:
    provider: str
    command: list[str]
    cwd: str
    prompt: str
    native_session_id: Optional[str]
    mcp_config: dict
    stop: Event
    emit: Callable[[str, dict], None]
    bind_session: Callable[[str], Any]
    approve: Callable[[dict, list], Any]
    timeout: float = 900
    model: Optional[str] = None
    effort: Optional[str] = None
    inherit_process_cwd: bool = False
    permission_mode: str = "ask"
    session_home: Optional[str] = None
    base_environment: Optional[dict] = None
    managed_account: bool = False
    control: Any = None
    execution_fd: Optional[int] = None
    acp_prepared: bool = False
