"""Pure, path-free aggregate process evidence contracts (standard library only).

Static scope declarations do not prove kernel effects. Dynamic evidence is
accepted only with the exact immutable process binding and configuration.
"""
from copy import deepcopy
import hashlib
import json
import re

_BACKEND = "delegated-cgroup-v2"
_STATES = frozenset({"NEW", "CREATE_INTENT", "CONFIGURE_INTENT", "READY", "ATTACH_INTENT", "ATTACHED",
                     "KILL_INTENT", "EMPTY", "REMOVE_INTENT", "RELEASED", "UNKNOWN"})
_FIELDS = frozenset({"schema", "backend", "ticketId", "bindingSha256", "configSha256", "rootPinSha256",
                     "groupPinSha256", "state", "populated", "limitsReadbackVerified", "releasedProof", "attached"})
_ERROR = "AGGREGATE_EVIDENCE_INVALID"


def _require(condition):
    if not condition:
        raise ValueError(_ERROR)


def _hex(value, length):
    return type(value) is str and re.fullmatch(r"[a-f0-9]{" + str(length) + r"}", value) is not None


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _enforcement(fingerprint):
    _require(_hex(fingerprint, 64))
    return {"schema": 2, "backend": _BACKEND, "cpu": "cgroup-v2-cpu.max",
            "memory": "cgroup-v2-memory.max+memory.swap.max", "pids": "cgroup-v2-pids.max",
            "fileSize": "per-file-RLIMIT_FSIZE", "wall": "original-delegated-cgroup-guardian",
            "aggregateScopes": ["aggregate-cpu", "aggregate-memory", "aggregate-pids"],
            "hostileCodeSandbox": False, "networkIsolation": False, "configurationSha256": fingerprint}


def aggregate_enforcement(config):
    """Return static declarations for an explicitly selected configuration."""
    return _enforcement(config.fingerprint)


def _validate(value, binding_hash, enforcement):
    _require(type(enforcement) is dict and type(enforcement.get("schema")) is int)
    _require(enforcement.get("hostileCodeSandbox") is False and enforcement.get("networkIsolation") is False)
    _require(enforcement == _enforcement(enforcement.get("configurationSha256")))
    _require(type(value) is dict and set(value) == _FIELDS)
    _require(type(value["schema"]) is int and value["schema"] == 1 and value["backend"] == _BACKEND)
    _require(_hex(value["ticketId"], 32))
    for key in ("bindingSha256", "configSha256", "rootPinSha256"):
        _require(_hex(value[key], 64))
    _require(_hex(binding_hash, 64) and value["bindingSha256"] == binding_hash)
    _require(value["configSha256"] == enforcement["configurationSha256"])
    _require(value["groupPinSha256"] is None or _hex(value["groupPinSha256"], 64))
    _require(type(value["state"]) is str and value["state"] in _STATES)
    _require(value["populated"] is None or type(value["populated"]) is bool)
    for key in ("limitsReadbackVerified", "releasedProof", "attached"):
        _require(type(value[key]) is bool)
    _require((value["state"] == "RELEASED") == value["releasedProof"])
    if value["groupPinSha256"] is None:
        _require(value["state"] in {"NEW", "CREATE_INTENT", "UNKNOWN"})
        _require(value["populated"] is None and not value["attached"] and not value["limitsReadbackVerified"])
    if value["state"] == "NEW":
        _require(value["groupPinSha256"] is None)
    if value["releasedProof"]:
        _require(value["groupPinSha256"] is not None and value["populated"] is False)
    if value["state"] in {"EMPTY", "REMOVE_INTENT"}:
        _require(value["populated"] is False)
    return value


def validate_aggregate_evidence(value, binding_hash, enforcement, previous=None):
    """Validate strict safe schema and immutable custody; never retain aliases."""
    try:
        _validate(value, binding_hash, enforcement)
        if previous is not None:
            _validate(previous, binding_hash, enforcement)
            for key in ("ticketId", "bindingSha256", "configSha256", "rootPinSha256"):
                _require(value[key] == previous[key])
            if previous["groupPinSha256"] is not None:
                _require(value["groupPinSha256"] == previous["groupPinSha256"])
            if previous["attached"]:
                _require(value["attached"])
            if previous["releasedProof"]:
                _require(value == previous)
            if previous["state"] != "NEW":
                _require(value["state"] != "NEW")
        return deepcopy(value)
    except (KeyError, TypeError, ValueError, AttributeError):
        raise ValueError(_ERROR) from None


def project_aggregate_evidence(ticket, proof):
    """Expose hashes and finite observations, never OS paths, PIDs or limits."""
    try:
        _require(type(ticket) is dict and type(proof) is dict)
        _require(ticket.get("backend") == _BACKEND and type(ticket.get("schema")) is int and ticket["schema"] == 1)
        _require(type(ticket.get("rootPin")) is dict)
        _require(ticket.get("pin") is None or type(ticket["pin"]) is dict)
        _require(type(ticket.get("attached")) is bool)
        fresh = ticket.get("state") == "NEW"
        if fresh:
            _require(ticket.get("pin") is None and ticket.get("attachIdentity") is None)
            for field in ("createAttempted", "attachAttempted", "killAttempted", "releaseAttempted", "attached", "limitsVerified"):
                _require(ticket.get(field) is False)
        value = {"schema": 1, "backend": _BACKEND, "ticketId": ticket["id"],
                 "bindingSha256": ticket["bindingSha256"], "configSha256": ticket["configSha256"],
                 "rootPinSha256": _hash(ticket["rootPin"]),
                 "groupPinSha256": None if ticket["pin"] is None else _hash(ticket["pin"]),
                 "state": "NEW" if fresh else proof["state"],
                 "populated": None if fresh else proof["populated"],
                 "limitsReadbackVerified": False if fresh else proof["limitsReadbackVerified"],
                 "releasedProof": False if fresh else proof["releasedProof"],
                 "attached": False if fresh else ticket["attached"]}
        return validate_aggregate_evidence(value, ticket["bindingSha256"], _enforcement(ticket["configSha256"]))
    except (KeyError, TypeError, ValueError, AttributeError):
        raise ValueError(_ERROR) from None


def aggregate_stopped(evidence):
    """Only original removed-group positive proof permits capacity release."""
    try:
        _validate(evidence, evidence["bindingSha256"], _enforcement(evidence["configSha256"]))
        return (evidence["state"] == "RELEASED" and evidence["releasedProof"] is True
                and evidence["populated"] is False and evidence["groupPinSha256"] is not None)
    except (KeyError, TypeError, ValueError, AttributeError):
        return False
