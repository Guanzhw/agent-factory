"""Versioned, inert SSH process requests and exact native tool bindings."""
from dataclasses import asdict, fields
import json
from pathlib import PurePosixPath
import re

from .process_enforcement import ProcessLimits, ProcessSpec, ResearchProcessLimits, ResearchProcessSpec
from .store import digest

PROTOCOL = 'factory-ssh-process-v1'
REVISION = '1'
OPERATION_PIN = {'adapterId': 'ssh-process-operation-v1', 'revision': REVISION,
                 'configFingerprint': digest({})}
LAUNCH_ADAPTER_ID = 'ssh-process-launch-v1'
WAIT_ADAPTER_ID = 'ssh-process-wait-v1'
LAUNCH_TOOL = 'ssh_process_launch'
WAIT_TOOL = 'factory_wait_ssh_process'
RUNTIME_OWNER = 'core-ssh-process'
BINDINGS = (('tool', LAUNCH_ADAPTER_ID, REVISION), ('tool', WAIT_ADAPTER_ID, REVISION))
MAX_REQUEST_BYTES = 32768
MAX_RESPONSE_BYTES = 1024 * 1024
OUTPUT_BYTES = 256 * 1024
ACTIONS = frozenset({'capabilities', 'submit', 'inspect', 'cancel', 'reclaim', 'output'})
BINDING_FIELDS = frozenset({'leaseId', 'operationId', 'ownerId', 'taskId', 'runId',
                            'planId', 'planHash', 'requestId', 'targetFingerprint'})


def require(value):
    if not value:
        raise ValueError('SSH_PROCESS_PROTOCOL_INVALID')


def encoded(value, maximum):
    raw = json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(',', ':')).encode()
    require(len(raw) <= maximum)
    return raw


def binding(value):
    require(type(value) is dict and set(value) == BINDING_FIELDS)
    for key, item in value.items():
        if key == 'ownerId':
            require(type(item) is str and 1 <= len(item) <= 200 and all(c.isprintable() for c in item))
        elif key in {'planHash', 'targetFingerprint'}:
            require(type(item) is str and re.fullmatch('[a-f0-9]{64}', item))
        else:
            require(type(item) is str and re.fullmatch('[A-Za-z0-9_.-]{1,128}', item)
                    and item not in {'.', '..'})
    return dict(value)


def specification(spec, limits):
    require(type(spec) is dict and type(limits) is dict)
    cls = ResearchProcessSpec if 'working_directory' in spec else ProcessSpec
    limit_cls = ResearchProcessLimits if cls is ResearchProcessSpec else ProcessLimits
    require(set(spec) == {f.name for f in fields(cls)} and set(limits) == {f.name for f in fields(limit_cls)})
    values = dict(spec)
    require(type(values['argv']) in {tuple, list})
    values['argv'] = tuple(values['argv'])
    if cls is ResearchProcessSpec:
        require(type(values['environment']) in {tuple, list}
                and type(values['working_directory_identity']) in {tuple, list})
        values['environment'] = tuple(tuple(pair) for pair in values['environment'])
        values['working_directory_identity'] = tuple(values['working_directory_identity'])
    return cls(**values), limit_cls(**limits)


def request(value):
    encoded(value, MAX_REQUEST_BYTES)
    require(type(value) is dict and value.get('protocol') == PROTOCOL and value.get('action') in ACTIONS)
    if value['action'] == 'capabilities':
        require(set(value) == {'protocol', 'action'})
        return dict(value)
    require(set(value) == {'protocol', 'action', 'binding', 'root', 'spec', 'limits'})
    root = value['root']
    require(type(root) is str and 1 < len(root) <= 4096 and root.startswith('/')
            and all(c.isprintable() for c in root) and '..' not in PurePosixPath(root).parts
            and str(PurePosixPath(root)) == root)
    spec, limits = specification(value['spec'], value['limits'])
    return {**value, 'binding': binding(value['binding']), 'spec': asdict(spec), 'limits': asdict(limits)}
