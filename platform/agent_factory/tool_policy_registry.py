"""Operator-authored tool policy identity; never factories or user extensions."""
from dataclasses import asdict, dataclass
import re
from typing import Any

from fastapi import HTTPException

_IDENTIFIER = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}')


@dataclass(frozen=True)
class ToolPolicyRegistration:
    adapter_id: str
    adapter_revision: str
    revision: str
    read_only: bool

    def __post_init__(self):
        if type(self.read_only) is not bool or any(type(value) is not str or not _IDENTIFIER.fullmatch(value)
            for value in (self.revision, self.adapter_id, self.adapter_revision)):
            raise ValueError('Invalid operator tool policy registration')


@dataclass(frozen=True)
class ResolvedToolPolicy(ToolPolicyRegistration):
    """Internal immutable approval projection, derived from a trusted adapter."""
    name: str
    capability: str

    def __post_init__(self):
        super().__post_init__()
        if any(type(value) is not str or not _IDENTIFIER.fullmatch(value)
               for value in (self.name, self.capability)):
            raise ValueError('Invalid resolved tool policy')


def _normalize(values, cls):
    if type(values) not in (tuple, list) or len(values) > 128:
        raise ValueError('Tool policies require a bounded sequence')
    try:
        entries = tuple(item if type(item) is cls else cls(**item)
                        if type(item) is dict else None for item in values)
    except TypeError as error:
        raise ValueError('Tool policy fields must be exact') from error
    if any(item is None for item in entries):
        raise ValueError('Tool policies must use the correct declaration or projection')
    entries = tuple(item for item in entries if item is not None)
    if len({(item.adapter_id, item.adapter_revision) for item in entries}) != len(entries):
        raise ValueError('Tool policy adapter references must be unique')
    return tuple(sorted(entries, key=lambda item: (item.adapter_id, item.adapter_revision)))


def normalize_tool_policies(values) -> tuple[ToolPolicyRegistration, ...]:
    return _normalize(values, ToolPolicyRegistration)


def normalize_resolved_tool_policies(values) -> tuple[ResolvedToolPolicy, ...]:
    entries = _normalize(values, ResolvedToolPolicy)
    if len({item.name for item in entries}) != len(entries):
        raise ValueError('Resolved tool names must be unique')
    return entries


def resolve_tool_policies(values, runtime_adapters) -> tuple[ResolvedToolPolicy, ...]:
    entries = normalize_tool_policies(values)
    resolved = []
    for policy in entries:
        matches = [adapter for adapter in runtime_adapters if
            getattr(adapter, 'kind', None) == 'tool' and getattr(adapter, 'adapter_id', None) == policy.adapter_id
            and getattr(adapter, 'revision', None) == policy.adapter_revision]
        if len(matches) != 1 or len(matches[0].permissions) != 1:
            raise ValueError('Tool policy requires one exact trusted adapter and one capability')
        resolved.append(ResolvedToolPolicy(**asdict(policy), name=matches[0].tool_name,
                                          capability=matches[0].permissions[0]))
    return normalize_resolved_tool_policies(resolved)


def validate_tool_policies(values, runtime_adapters) -> tuple[ToolPolicyRegistration, ...]:
    resolve_tool_policies(values, runtime_adapters)
    return normalize_tool_policies(values)


def merged_tools(base, values, *, reserved):
    entries = normalize_resolved_tool_policies(values)
    if any(item.name in reserved for item in entries):
        raise ValueError('Operator tool policies cannot replace built-in tool identities')
    return {**base, **{item.name: item.capability for item in entries}}


def policy_body(config):
    """Preserve historical serialized configuration when registration is empty."""
    body = asdict(config)
    if not config.tool_policies:
        body.pop('tool_policies', None)
    return body


def require_installed_policies(store, policies):
    entries = normalize_resolved_tool_policies(policies)
    settings = getattr(store, 'settings', None)
    try:
        configured = resolve_tool_policies(getattr(settings, 'tool_policies', ()), getattr(settings, 'runtime_adapters', ()))
    except ValueError as error:
        raise HTTPException(409, 'TOOL_POLICY_ADAPTER_UNAVAILABLE: current trusted adapter differs') from error
    if entries != configured:
        raise HTTPException(409, 'TOOL_POLICY_CHANGED: operator policy differs from current approval configuration')
    if not entries:
        return
    try:
        bindings = getattr(store, 'execution_bindings', None)
        if bindings is None:
            resolve_tool_policies(getattr(settings, 'tool_policies', ()), getattr(settings, 'runtime_adapters', ()))
            return
        descriptors = bindings.describe()
        for item in entries:
            found = [entry for entry in descriptors if entry['kind'] == 'tool'
                and entry['adapterId'] == item.adapter_id and entry['revision'] == item.adapter_revision]
            if (len(found) != 1 or found[0]['toolName'] != item.name
                    or found[0]['permissions'] != [item.capability] or not found[0]['availableForMode']):
                raise ValueError()
    except (ValueError, KeyError, TypeError) as error:
        raise HTTPException(409, 'TOOL_POLICY_ADAPTER_UNAVAILABLE: current trusted adapter differs') from error


def require_material_policy(material: dict[str, Any], policies):
    if material.get('kind') != 'tool':
        return
    policy = next((item for item in normalize_resolved_tool_policies(policies) if item.name == material.get('content')), None)
    if policy is None:
        return
    binding = material.get('runtimeBinding') or {}
    if (binding.get('adapterId') != policy.adapter_id or binding.get('revision') != policy.adapter_revision
            or material.get('permissions') != [policy.capability]):
        raise HTTPException(409, 'TOOL_POLICY_BINDING_CHANGED: material must pin its registered adapter')


def require_plan_policies(plan, policies):
    selected = [item for item in normalize_resolved_tool_policies(policies) if item.name in plan.get('tools', [])]
    specs = (plan.get('executionBindings') or {}).get('tools', [])
    for item in selected:
        found = [spec for spec in specs if spec.get('toolName') == item.name]
        if (len(found) != 1 or found[0].get('adapterId') != item.adapter_id
                or found[0].get('revision') != item.adapter_revision):
            raise HTTPException(409, 'TOOL_POLICY_BINDING_CHANGED: plan must pin its registered adapter')
