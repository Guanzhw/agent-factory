"""CLI/MCP adapter contract; descriptors never contain owner credentials.

Core owns connection resolution, native Function wrapping and effect receipts.
Adapters own their process/protocol lifecycle, including positive stop evidence.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
import json
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
    try:
        value = bounded_tool_json(dict(schema), maximum=None)
        if value.get('type') != 'object':
            raise ValueError()
        Draft202012Validator.check_schema(value)
        return value
    except Exception:
        raise ValueError('PERSONAL_TOOL_DESCRIPTOR_INVALID') from None


def bounded_tool_json(value: Any, *, maximum: int | None) -> Any:
    """Use the tool's byte budget, not application-form shape limits."""
    def check(item):
        if type(item) is dict:
            if any(type(key) is not str for key in item):
                raise ValueError()
            for child in item.values():
                check(child)
        elif type(item) is list:
            for child in item:
                check(child)
        elif item is not None and type(item) not in (str, bool, int, float):
            raise ValueError()

    try:
        check(value)
        encoded = json.dumps(value, allow_nan=False)
        if maximum is not None and len(encoded.encode()) > maximum:
            raise ValueError()
        return json.loads(encoded)
    except (TypeError, ValueError, OverflowError, RecursionError):
        raise ValueError('PERSONAL_TOOL_JSON_INVALID') from None


def validate_tool_arguments(schema: Mapping[str, Any], arguments: Mapping[str, Any]) -> dict[str, Any]:
    from jsonschema import Draft202012Validator
    from referencing import Registry
    try:
        value = bounded_tool_json(dict(arguments), maximum=None)
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
    timeout_seconds: float | None = None
    max_output_bytes: int | None = None
    permission: str = "tool:invoke"
    read_only: bool = False

    def __post_init__(self):
        from .connections import _capabilities, _identifier
        identifier = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]*')
        if (any(type(value) is not str or not identifier.fullmatch(value) for value in
                (self.adapter_id, self.revision, self.credential_provider_id, self.permission))
                or type(self.tool_name) is not str or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_-]*', self.tool_name)
                or self.transport not in {'cli', 'mcp'}
                or type(self.description) is not str or not self.description
                or type(self.credential_destination) is not str or not self.credential_destination
                or any(ord(char) < 32 for char in self.credential_destination)
                or type(self.capabilities) is not tuple or not self.capabilities
                or any(type(value) is not str or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]*', value)
                    for value in self.capabilities)
                or len(set(self.capabilities)) != len(self.capabilities)
                or self.timeout_seconds is not None and (type(self.timeout_seconds) not in (int, float)
                    or not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0)
                or self.max_output_bytes is not None and (type(self.max_output_bytes) is not int or self.max_output_bytes <= 0)
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

    Call check_authorized before dispatch.
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
                 stopped: bool = False, output: Any = None):
        super().__init__(code)
        self.code, self.outcome, self.stopped = code, outcome, stopped
        self.output = output


class PersonalToolAdapter(Protocol):
    descriptor: ToolDescriptor

    async def invoke(self, invocation: ToolInvocation) -> Any:
        """Return JSON and clean up invocation-owned resources in finally.

        No ambient credential fallback, owner-global mutable auth, automatic
        redispatch or cross-owner session reuse. MCP uses one call/session.
        Stop and cleanup evidence remain separate from the business outcome;
        retain private CLI state whenever process stop cannot be confirmed.
        """
        ...
