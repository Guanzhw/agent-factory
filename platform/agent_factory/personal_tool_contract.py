"""Static CLI/MCP adapter contract; descriptors never contain owner credentials.

Core owns connection resolution, native Function wrapping and effect receipts.
Adapters own their process/protocol lifecycle, including positive stop evidence.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
import re
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
    permission: str = "tool:invoke"
    read_only: bool = False

    def __post_init__(self):
        from .input_schema import validate_input_schema
        identifier = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}')
        if (any(type(value) is not str or not identifier.fullmatch(value) for value in
                (self.adapter_id, self.revision, self.credential_provider_id, self.permission))
                or type(self.tool_name) is not str or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}', self.tool_name)
                or self.transport not in {'cli', 'mcp'}
                or type(self.description) is not str or not 1 <= len(self.description) <= 2000
                or type(self.credential_destination) is not str or not 1 <= len(self.credential_destination) <= 512
                or any(ord(char) < 32 for char in self.credential_destination)
                or type(self.capabilities) is not tuple or not 1 <= len(self.capabilities) <= 32
                or any(type(value) is not str or not identifier.fullmatch(value) for value in self.capabilities)
                or len(set(self.capabilities)) != len(self.capabilities)
                or type(self.timeout_seconds) not in (int, float) or not math.isfinite(self.timeout_seconds)
                or not 0.1 <= self.timeout_seconds <= 300
                or type(self.max_output_bytes) is not int or not 1024 <= self.max_output_bytes <= 1048576
                or type(self.read_only) is not bool):
            raise ValueError('PERSONAL_TOOL_DESCRIPTOR_INVALID')
        schema = validate_input_schema(self.input_schema)
        if {'fc', 'run_context', '_agno_run_context'} & set(schema['properties']):
            raise ValueError('PERSONAL_TOOL_DESCRIPTOR_INVALID')
        object.__setattr__(self, 'input_schema', schema)


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
