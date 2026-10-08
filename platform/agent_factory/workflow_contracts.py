"""Original external operation observations and adapter protocol.

Agno owns workflow topology, progress, human review and continuation. These
contracts carry only bounded original-effect identity and stop evidence.
"""
from copy import deepcopy
from dataclasses import dataclass
import json
import math
import re
from typing import Any, Literal, Protocol, TypedDict

ERROR = 'WORKFLOW_CONTRACT_INVALID'
State = Literal['RUNNING', 'WAITING', 'COMPLETED', 'FAILED', 'UNKNOWN', 'CANCELLED']
STATES = frozenset({'RUNNING', 'WAITING', 'COMPLETED', 'FAILED', 'UNKNOWN', 'CANCELLED'})
TERMINAL = frozenset({'COMPLETED', 'FAILED', 'CANCELLED'})


class WorkflowAcknowledgementUnknown(Exception):
    """Adapter explicitly cannot confirm its original start acknowledgement.

    The operation may exist. Keep its durable identity and capacity; never retry
    start. Reconciliation must look up that same identity. Ordinary adapter
    errors and cancellation retain their existing failure semantics.
    """


class FailureJSON(TypedDict):
    schema: int
    code: str
    messageCode: str
    retryable: bool


class AdapterHandle(TypedDict):
    adapterId: str
    revision: str
    id: str






class RuntimeObservation(TypedDict):
    schema: int
    operationId: str
    handle: AdapterHandle | None
    state: State
    allStopped: bool
    output: dict[str, Any] | None
    failure: FailureJSON | None


def _require(value):
    if not value:
        raise ValueError(ERROR)


def _keys(value, expected):
    _require(type(value) is dict and set(value) == set(expected.split()))


def _identifier(value):
    return type(value) is str and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}', value) is not None


def _code(value):
    return type(value) is str and re.fullmatch(r'[A-Z][A-Z0-9_]{0,63}', value) is not None


def _schema(value):
    _require(type(value) is int and value == 1)


def _encoded(value, maximum):
    raw = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()
    _require(len(raw) <= maximum)
    return raw


def _inert(value, depth=0):
    _require(depth <= 6)
    if type(value) is dict:
        _require(len(value) <= 64)
        for key, item in value.items():
            _require(_identifier(key))
            normalized = re.sub('[^a-z]', '', key.lower())
            _require(normalized not in {'url', 'endpoint', 'baseurl', 'host', 'port', 'headers',
                'authorization', 'credential', 'credentials', 'password', 'secret', 'token', 'apikey',
                'command', 'cmd', 'exec', 'executable', 'shell', 'python', 'module', 'callable', 'factory'})
            _inert(item, depth + 1)
    elif type(value) is list:
        _require(len(value) <= 64)
        for item in value:
            _inert(item, depth + 1)
    elif type(value) is str:
        _require(len(value) <= 4096 and all(char.isprintable() for char in value)
                 and re.search(r'(?i)(?:https?|wss?|file|ssh)://', value) is None)
    elif type(value) in {int, float}:
        _require(math.isfinite(value) and abs(value) <= 2**53 - 1)
    else:
        _require(value is None or type(value) is bool)


def validate_failure_json(value):
    """Bounded symbolic codes only, never exception messages or provider payloads."""
    try:
        _keys(value, 'schema code messageCode retryable'); _schema(value['schema'])
        _require(_code(value['code']) and _code(value['messageCode']) and value['retryable'] is False)
        return deepcopy(value)
    except (TypeError, KeyError, ValueError, RecursionError):
        raise ValueError(ERROR) from None






def validate_runtime_observation(value, operation_id, adapter_id, revision, previous_handle=None):
    """Structural result checks; service must supply the original persisted IDs."""
    try:
        _require(all(_identifier(item) for item in (operation_id, adapter_id, revision)))
        _keys(value, 'schema operationId handle state allStopped output failure'); _schema(value['schema'])
        _require(value['operationId'] == operation_id and value['state'] in STATES
                 and type(value['allStopped']) is bool)
        def handle(candidate):
            _keys(candidate, 'adapterId revision id')
            _require(candidate['adapterId'] == adapter_id and candidate['revision'] == revision
                     and _identifier(candidate['id']))
        current = value['handle']
        if current is not None:
            handle(current)
        if previous_handle is not None:
            handle(previous_handle)
            _require(current == previous_handle)
        state = value['state']
        _require(current is not None or state == 'UNKNOWN')
        _require(value['allStopped'] is (state in TERMINAL))
        if state == 'COMPLETED':
            _require(type(value['output']) is dict and value['failure'] is None)
            _inert(value['output']); _encoded(value['output'], 16384)
        else:
            _require(value['output'] is None)
            if state == 'FAILED':
                validate_failure_json(value['failure'])
            else:
                _require(value['failure'] is None)
        _encoded(value, 32768)
        return deepcopy(value)
    except (TypeError, KeyError, ValueError, RecursionError, OverflowError):
        raise ValueError(ERROR) from None




@dataclass(frozen=True)
class WorkflowContext:
    workflow_id: str
    run_id: str
    owner_id: str
    stage_id: str
    definition_sha256: str

    def __post_init__(self):
        _require(all(_identifier(value) for value in (self.workflow_id, self.run_id, self.stage_id))
                 and type(self.owner_id) is str and 1 <= len(self.owner_id) <= 200
                 and all(char.isprintable() for char in self.owner_id)
                 and type(self.definition_sha256) is str
                 and re.fullmatch('[a-f0-9]{64}', self.definition_sha256) is not None)


class WorkflowAdapter(Protocol):
    """Trusted adapter; start receives an already durable intent, never replayed.

    lookup is read-only recovery of the original operation after a lost start
    acknowledgement. A missing lookup implementation must leave UNKNOWN held.
    allStopped is an adapter assertion backed by original identity stop proof;
    CANCELLED before dispatch requires positive provider proof of no dispatch,
    never absence of a handle/process. Definitions cannot supply such proof.
    Domain file identifiers remain subject to adapter-side owner authorization.
    """
    async def start(self, context: WorkflowContext, operation_id: str, inputs: dict[str, Any]) -> RuntimeObservation: ...
    async def lookup(self, context: WorkflowContext, operation_id: str) -> RuntimeObservation: ...
    async def inspect(self, context: WorkflowContext, handle: AdapterHandle) -> RuntimeObservation: ...
    async def cancel(self, context: WorkflowContext, handle: AdapterHandle) -> RuntimeObservation: ...
