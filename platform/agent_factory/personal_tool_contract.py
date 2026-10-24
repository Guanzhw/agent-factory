"""CLI/MCP adapter contract; descriptors never contain owner credentials.

Core owns connection resolution, native Function wrapping and effect receipts.
Adapters own their process/protocol lifecycle, including positive stop evidence.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
import re
from typing import Any, Callable, Literal, Mapping, Protocol

from .personal_remote_provider import SecretLease


def validate_tool_schema(schema: Mapping[str, Any]) -> dict[str, Any]:
    """Preserve standard tool JSON Schema while bounding the declaration itself.

    Application form schemas intentionally use a smaller vocabulary. MCP tool
    schemas may contain annotations, const values and optional length limits.
    Neither declarations nor validation may retrieve an external schema.
    """
    from jsonschema import Draft202012Validator
    from .input_schema import bounded_json
    try:
        value = bounded_json(dict(schema), maximum=32768)
        if value.get('type') != 'object' or {'fc', 'run_context', '_agno_run_context'} & set(value.get('properties', {})):
            raise ValueError()
        Draft202012Validator.check_schema(value)
        return value
    except Exception:
        raise ValueError('PERSONAL_TOOL_DESCRIPTOR_INVALID') from None


def validate_tool_arguments(schema: Mapping[str, Any], arguments: Mapping[str, Any]) -> dict[str, Any]:
    from jsonschema import Draft202012Validator
    from referencing import Registry
    from .input_schema import bounded_json
    try:
        value = bounded_json(dict(arguments))
        if {'fc', 'run_context', '_agno_run_context'} & set(value):
            raise ValueError()
        Draft202012Validator(dict(schema), registry=Registry()).validate(value)
        return value
    except Exception:
        raise ValueError('PERSONAL_TOOL_INPUT_INVALID') from None


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
        from .connections import _capabilities, _identifier
        identifier = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}')
        if (any(type(value) is not str or not identifier.fullmatch(value) for value in
                (self.adapter_id, self.revision, self.credential_provider_id, self.permission))
                or type(self.tool_name) is not str or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_-]{0,63}', self.tool_name)
                or self.transport not in {'cli', 'mcp'}
                or type(self.description) is not str or not 1 <= len(self.description) <= 2000
                or type(self.credential_destination) is not str or not 1 <= len(self.credential_destination) <= 512
                or any(ord(char) < 32 for char in self.credential_destination)
                or type(self.capabilities) is not tuple or not 1 <= len(self.capabilities) <= 30
                or any(type(value) is not str or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,99}', value)
                    for value in self.capabilities)
                or len(set(self.capabilities)) != len(self.capabilities)
                or type(self.timeout_seconds) not in (int, float) or not math.isfinite(self.timeout_seconds)
                or not 0.1 <= self.timeout_seconds <= 300
                or type(self.max_output_bytes) is not int or not 1 <= self.max_output_bytes <= 1048576
                or type(self.read_only) is not bool):
            raise ValueError('PERSONAL_TOOL_DESCRIPTOR_INVALID')
        _capabilities(self.capabilities)
        _identifier(self.adapter_id)
        _identifier(self.credential_provider_id)
        schema = validate_tool_schema(self.input_schema)
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
    resolve_credential: Callable[[], SecretLease | None] = field(repr=False)


class ToolInvocationError(RuntimeError):
    """Fixed code only; process output, URLs and secrets are never diagnostics.

    UNKNOWN is required after ambiguous dispatch. A cancelled result requires
    positive stop evidence; closing an MCP client alone does not prove stop.
    ``failed`` describes a known business failure independently of cleanup.
    Set ``stopped=True`` only with positive evidence that invocation-owned work
    is settled; failed/unstopped receipts retain custody and stop the native run.
    """
    def __init__(self, code: str, *, outcome: Literal["failed", "cancelled", "unknown"] = "unknown",
                 stopped: bool = False):
        super().__init__(code)
        self.code, self.outcome, self.stopped = code, outcome, stopped


class PersonalToolAdapter(Protocol):
    descriptor: ToolDescriptor

    async def invoke(self, invocation: ToolInvocation) -> Any:
        """Return bounded JSON and attempt owned-resource cleanup in finally.

        No ambient credential fallback, owner-global mutable auth, automatic
        redispatch or cross-owner session reuse. Verify known credential echoes
        before returning output. Initial implementation uses one call/session.
        Stop and cleanup evidence remain separate from the business outcome;
        retain private CLI state whenever process stop cannot be confirmed.
        """
        ...
