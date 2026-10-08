"""Operator-authored tool policy identity; never factories or user extensions."""
from dataclasses import asdict, dataclass
import re
from typing import Any

from fastapi import HTTPException

_IDENTIFIER = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}')


@dataclass(frozen=True)
class ToolPolicyRegistration:
    name: str
    capability: str
    revision: str
    read_only: bool
    adapter_id: str
    adapter_revision: str

    def __post_init__(self):
        if type(self.read_only) is not bool or any(type(value) is not str or not _IDENTIFIER.fullmatch(value)
            for value in (self.name, self.capability, self.revision, self.adapter_id, self.adapter_revision)):
            raise ValueError('Invalid operator tool policy registration')


def normalize_tool_policies(values) -> tuple[ToolPolicyRegistration, ...]:
    if type(values) not in (tuple, list) or len(values) > 128:
        raise ValueError('Tool policies require a bounded sequence')
    entries = tuple(item if type(item) is ToolPolicyRegistration else ToolPolicyRegistration(**item)
                    if type(item) is dict else None for item in values)
    if any(item is None for item in entries):
        raise ValueError('Tool policy descriptors must be exact registrations')
    checked: tuple[ToolPolicyRegistration, ...] = tuple(item for item in entries if item is not None)
    if len({item.name for item in checked}) != len(checked):
        raise ValueError('Tool policy names must be unique')
    return tuple(sorted(checked, key=lambda item: item.name))


def validate_tool_policies(values, runtime_adapters) -> tuple[ToolPolicyRegistration, ...]:
    entries = normalize_tool_policies(values)
    for policy in entries:
        matches = [adapter for adapter in runtime_adapters if
            getattr(adapter, 'kind', None) == 'tool' and getattr(adapter, 'adapter_id', None) == policy.adapter_id
            and getattr(adapter, 'revision', None) == policy.adapter_revision]
        if (len(matches) != 1 or matches[0].tool_name != policy.name
                or tuple(matches[0].permissions) != (policy.capability,)):
            raise ValueError('Tool policy must match one exact trusted adapter and capability')
    return entries


def merged_tools(base, values, *, reserved):
    entries = normalize_tool_policies(values)
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
    entries = normalize_tool_policies(policies)
    settings = getattr(store, 'settings', None)
    configured = normalize_tool_policies(getattr(settings, 'tool_policies', ()))
    if entries != configured:
        raise HTTPException(409, 'TOOL_POLICY_CHANGED: operator policy differs from current approval configuration')
    if not entries:
        return
    try:
        bindings = getattr(store, 'execution_bindings', None)
        if bindings is None:
            validate_tool_policies(entries, getattr(settings, 'runtime_adapters', ()))
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
    policy = next((item for item in normalize_tool_policies(policies) if item.name == material.get('content')), None)
    if policy is None:
        return
    binding = material.get('runtimeBinding') or {}
    if (binding.get('adapterId') != policy.adapter_id or binding.get('revision') != policy.adapter_revision
            or material.get('permissions') != [policy.capability]):
        raise HTTPException(409, 'TOOL_POLICY_BINDING_CHANGED: material must pin its registered adapter')


def require_plan_policies(plan, policies):
    selected = [item for item in normalize_tool_policies(policies) if item.name in plan.get('tools', [])]
    specs = (plan.get('executionBindings') or {}).get('tools', [])
    for item in selected:
        found = [spec for spec in specs if spec.get('toolName') == item.name]
        if (len(found) != 1 or found[0].get('adapterId') != item.adapter_id
                or found[0].get('revision') != item.adapter_revision):
            raise HTTPException(409, 'TOOL_POLICY_BINDING_CHANGED: plan must pin its registered adapter')
