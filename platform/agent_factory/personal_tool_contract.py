"""Static CLI/MCP adapter contract; descriptors never contain owner credentials.

Core owns connection resolution, native Function wrapping and effect receipts.
Adapters own their process/protocol lifecycle, including positive stop evidence.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Mapping, Protocol

from .personal_remote_provider import SecretLease


@dataclass(frozen=True)
class ToolDescriptor:
    adapter_id: str
    revision: str
    tool_name: str
    description: str
    input_schema: Mapping[str, Any]
    transport: Literal["cli", "mcp"]
    credential_provider_id: str
    credential_destination: str
    capabilities: tuple[str, ...]
    timeout_seconds: float = 30.0
    max_output_bytes: int = 65536


@dataclass(frozen=True)
class ToolInvocation:
    """One owner-scoped call. Never cache this object or its credential lease.

    Call check_authorized before dispatch and while observing cancellation.
    resolve_credential repeats exact owner/ref/revision/provider/target checks.
    call_id identifies the original durable effect; retry must not redispatch it.
    """
    owner_id: str
    connection_ref: str
    connection_revision: str
    call_id: str
    arguments: Mapping[str, Any]
    run_context: Any = field(repr=False)
    check_authorized: Callable[[], None] = field(repr=False)
    resolve_credential: Callable[[], SecretLease] = field(repr=False)


class ToolInvocationError(RuntimeError):
    """Fixed code only; process output, URLs and secrets are never diagnostics.

    UNKNOWN is required after ambiguous dispatch. A cancelled result requires
    positive stop evidence; closing an MCP client alone does not prove stop.
    """
    def __init__(self, code: str, *, outcome: Literal["failed", "cancelled", "unknown"] = "unknown",
                 stopped: bool = False):
        super().__init__(code)
        self.code, self.outcome, self.stopped = code, outcome, stopped


class PersonalToolAdapter(Protocol):
    descriptor: ToolDescriptor

    async def invoke(self, invocation: ToolInvocation) -> Any:
        """Return bounded JSON; close all invocation-owned resources in finally.

        No ambient credential fallback, owner-global mutable auth, automatic
        redispatch or cross-owner session reuse. Verify known credential echoes
        before returning output. Initial implementation uses one call/session.
        """
        ...
