"""Internal wiring for the public application context; no new authority."""
from copy import deepcopy
import re
from typing import Any

from .application_interface import ApplicationIdentity
from .input_schema import bounded_json


class FactoryApplicationContext:
    def __init__(self, store, root, tool_name):
        self._store, self._root, self._tool_name = store, root, tool_name
        plan = store.resolve_run(root)
        ref = plan.get('applicationRef') or {'id': plan['application'], 'version': 1}
        self._identity = ApplicationIdentity(root.user_id, root.session_id, root.run_id, ref['id'], ref['version'])
        self._inputs = deepcopy(plan.get('inputValues', {}))
        self._resources = {
            'materials': [{key: item[key] for key in ('id', 'version', 'sha256') if key in item}
                          for item in plan.get('materialRefs', [])],
            'connections': {name: {key: pin[key] for key in ('ref', 'version', 'kind', 'fingerprint') if key in pin}
                            for name, pin in plan.get('bindingManifest', {}).get('connections', {}).items()},
        }

    @property
    def identity(self): return self._identity

    @property
    def inputs(self): return deepcopy(self._inputs)

    @property
    def resources(self): return deepcopy(self._resources)

    def _authorize(self):
        if (self._root.user_id, self._root.session_id, self._root.run_id) != (
                self._identity.owner_id, self._identity.task_id, self._identity.run_id):
            raise PermissionError('APPLICATION_ORIGINAL_RUN_REQUIRED')
        # One existing authority boundary owns current policy, native workflow
        # pin, original run mapping, owner/tool scope and cancellation checks.
        self._store.authorize_tool(self._root, self._tool_name)

    def emit_event(self, name, message, data=None):
        if (type(name) is not str or re.fullmatch(r'[a-z][a-z0-9_]{0,47}', name) is None
                or type(message) is not str or not 1 <= len(message) <= 1000):
            raise ValueError('APPLICATION_EVENT_INVALID')
        payload: Any = bounded_json(dict(data or {}), maximum=16384)
        self._authorize()
        self._store.event(self._identity.task_id, 'application_' + name, message, payload)

    def write_artifact(self, name, content, media_type='application/json'):
        self._authorize()
        return deepcopy(self._store.artifact_write(self._identity.run_id, name, content, media_type,
            metadata={'evidenceKind': 'application_output', 'verificationStatus': 'unverified',
                'applicationInterfaceVersion': 1,
                'applicationRef': {'id': self._identity.application_id, 'version': self._identity.application_version}}))
