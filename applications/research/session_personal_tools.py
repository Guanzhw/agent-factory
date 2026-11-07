"""Compose configured member tools into the existing research application."""
from copy import deepcopy


def personal_tool_materials(store, owner, reserved_names=()):
    service = getattr(store, 'personal_tools', None)
    if service is None:
        return {'materials': [], 'requirements': [], 'connections': {}, 'names': []}
    result = {'materials': [], 'requirements': [], 'connections': {}, 'names': []}
    names = set(reserved_names)
    # Prefer the member's own configured account when the same named tool is
    # also shared by someone else. One native function name selects one account.
    resources = sorted(service.list(owner), key=lambda item: (item.get('ownerId') != owner, item['registrationRef']))
    for item in resources:
        if not item.get('available') or item['toolName'] in names:
            continue
        service.ensure_registered(item['adapterId'])
        adapter = service.adapters[item['adapterId']]
        descriptor = adapter.descriptor
        slot = 'personal_tool_' + str(len(result['names']))
        binding = deepcopy(item['runtimeBinding'])
        binding['config']['connectionName'] = slot
        result['materials'].append({'kind': 'tool', 'name': descriptor.tool_name,
            'content': descriptor.tool_name, 'permissions': [descriptor.permission], 'runtimeBinding': binding})
        result['requirements'].append({'name': slot, 'kind': 'tool',
            'requiredCapabilities': list(descriptor.capabilities), 'required': True})
        result['connections'][slot] = item['registrationRef']
        result['names'].append(descriptor.tool_name)
        names.add(descriptor.tool_name)
    return result
