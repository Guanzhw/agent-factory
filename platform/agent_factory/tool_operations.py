"""Public fixed-destination tool recipes, independent of account credentials.

Creation is explicit: arbitrary argument/environment strings are public data,
not automatically discovered or certified free of secrets. No adapter is invoked
here. Persistence and process-local adapter reuse belong to the caller.
"""
from copy import deepcopy
import json

from .personal_tool_contract import ToolDescriptor
from .store import digest

_ERROR = 'TOOL_OPERATION_CONFIGURATION_INVALID'
_DERIVED = {'credentialProviderId', 'credentialDestination'}
_EXTRA = _DERIVED | {'permission', 'capabilities'}
_PRIVATE = {'requestId', 'credentialRef', 'credentialRevision'}


def _descriptor(configuration, adapter_id, revision):
    return ToolDescriptor(
        adapter_id=adapter_id, revision=revision,
        tool_name=configuration['toolName'], description=configuration['description'],
        input_schema=configuration['inputSchema'], transport=configuration['transport'],
        credential_provider_id=configuration['credentialProviderId'],
        credential_destination=configuration['credentialDestination'],
        capabilities=tuple(configuration['capabilities']), permission=configuration['permission'],
        timeout_seconds=configuration['timeoutSeconds'], max_output_bytes=configuration['maxOutputBytes'],
        read_only=configuration['readOnly'])


def normalize_operation(configuration: dict) -> dict:
    """Validate and copy a complete public recipe; errors never include input."""
    try:
        # Lazy import avoids a cycle when PersonalTools integrates this helper.
        from .personal_tools import ConfigureResourceRequest
        if type(configuration) is not dict or _PRIVATE.intersection(configuration):
            raise ValueError()
        allowed = set(ConfigureResourceRequest.model_fields) - _PRIVATE | _EXTRA
        if set(configuration) - allowed:
            raise ValueError()
        public = deepcopy(configuration)
        request = ConfigureResourceRequest.model_validate(
            {key: value for key, value in public.items() if key not in _EXTRA}
            | {'requestId': 'public-operation-validation'})
        result = request.model_dump(exclude=_PRIVATE)
        if result['transport'] == 'mcp':
            from .personal_mcp import mcp_url
            result['url'] = mcp_url(result['url'])
            destination = result['url']
        else:
            from .personal_cli import cli_destination
            result['executable'] = cli_destination(result['executable'])
            if result['workingDirectory'] is not None:
                result['workingDirectory'] = cli_destination(result['workingDirectory'])
            destination = result['executable']
        result['credentialProviderId'] = 'member-' + result['transport']
        result['credentialDestination'] = destination
        if any(key in public and public[key] != result[key] for key in _DERIVED):
            raise ValueError()
        result['permission'] = public.get('permission', 'tool:invoke')
        capabilities = public.get('capabilities', ['tool:invoke'])
        if result['permission'] != 'tool:invoke' or capabilities != ['tool:invoke'] or type(capabilities) is not list:
            raise ValueError()
        result['capabilities'] = capabilities
        descriptor = _descriptor(result, 'operation-validation', '1')
        result['inputSchema'] = dict(descriptor.input_schema)
        # Canonical mapping iteration also fixes CLI argumentOptions dispatch
        # order; its adapter must execute exactly the recipe that was hashed.
        return json.loads(json.dumps(result, sort_keys=True, allow_nan=False))
    except Exception:
        raise ValueError(_ERROR) from None


def operation_hash(normalized: dict) -> str:
    """Hash the complete normalized recipe, with no generated identity fields."""
    return digest(normalize_operation(normalized))


def instantiate_operation_adapter(normalized: dict, adapter_id: str, revision: str):
    """Restore an adapter without dispatch; caller owns singleton registration."""
    configuration = normalize_operation(normalized)
    try:
        descriptor = _descriptor(configuration, adapter_id, revision)
        if configuration['transport'] == 'cli':
            from .personal_cli import MemberCliAdapter
            return MemberCliAdapter(descriptor, configuration)
        from .personal_mcp import MCPToolAdapter
        return MCPToolAdapter(descriptor, url=configuration['url'],
                              remote_tool_name=configuration['remoteToolName'])
    except Exception:
        raise ValueError('TOOL_OPERATION_ADAPTER_UNAVAILABLE') from None
