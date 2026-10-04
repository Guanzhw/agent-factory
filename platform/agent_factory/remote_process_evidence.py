"""Safe receiver process evidence carried by the existing handoff receipt.

No transport, execution authority, local identity rewriting or release effects.
Only one root process lease is supported; descendant custody is not implied.
"""
from __future__ import annotations

from copy import deepcopy
import re
from typing import cast

from .resources import PersistentResourceService, TERMINAL

_FIELDS = frozenset({"id", "ownerId", "localTaskId", "planId", "nativeRunId", "fingerprint",
    "providerJobId", "processBinding", "enforcement", "aggregateEvidence", "stopEvidence", "state", "capacityHeld",
    "executionStatus", "exitCode", "poolId", "poolFingerprint", "limits"})
_IMMUTABLE = ("id", "ownerId", "localTaskId", "planId", "nativeRunId", "fingerprint",
              "poolId", "poolFingerprint", "limits")
_STATES = TERMINAL | {"RESERVED", "ACCEPTED", "RUNNING", "UNKNOWN", "CANCEL_REQUESTED", "RECLAIMING", "RECLAIMED"}
_OUTCOMES = {"PREPARED", "DISPATCHING", "RUNNING", "UNKNOWN", "COMPLETED", "CANCELLED", "LIMIT_STOPPED", "FAILED"}


def _require(value):
    if not value:
        raise ValueError("REMOTE_PROCESS_EVIDENCE_INVALID")


def _id(value):
    return type(value) is str and re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", value) is not None


def _hash(value):
    return type(value) is str and re.fullmatch(r"[a-f0-9]{64}", value) is not None


def project_process_evidence(leases: list[dict]) -> dict:
    """Discard operator-only fields from trusted rows, then validate with receipt.

The caller must supply only the receipt's exact root task rows. This projection
is deliberately not a query or an authorization decision.
"""
    _require(type(leases) is list and len(leases) <= 1)
    result = []
    for lease in leases:
        _require(type(lease) is dict)
        value = {key: deepcopy(lease.get(key)) for key in _FIELDS}
        if value["aggregateEvidence"] is None:
            value.pop("aggregateEvidence")
        if value["executionStatus"] is None:
            value["executionStatus"] = "UNKNOWN"
        validate_process_evidence({"processLeases": {"schema": 1, "complete": True, "leases": [value]},
            "remoteOwnerId": value["ownerId"], "remoteTaskId": value["localTaskId"],
            "remotePlanId": value["planId"], "remoteRunId": value["nativeRunId"]})
        result.append(value)
    return {"schema": 1, "complete": True, "leases": result}


def _validated(receipt: dict) -> dict:
    _require(type(receipt) is dict)
    evidence = receipt.get("processLeases")
    _require(type(evidence) is dict and set(evidence) == {"schema", "complete", "leases"}
             and type(evidence["schema"]) is int and evidence["schema"] == 1 and evidence["complete"] is True
             and type(evidence["leases"]) is list and len(evidence["leases"]) <= 1)
    evidence = deepcopy(cast(dict, evidence))
    for lease in evidence["leases"]:
        _require(type(lease) is dict and set(lease) in (_FIELDS, _FIELDS - {"aggregateEvidence"}))
        lease = cast(dict, lease)
        _require(all(_id(lease[key]) for key in ("id", "localTaskId", "planId", "nativeRunId", "poolId")))
        _require(type(lease["ownerId"]) is str and 1 <= len(lease["ownerId"]) <= 200
                 and all(ord(char) >= 32 and ord(char) != 127 for char in lease["ownerId"]))
        _require(all(_hash(lease[key]) for key in ("fingerprint", "poolFingerprint")))
        for local, remote in (("ownerId", "remoteOwnerId"), ("localTaskId", "remoteTaskId"),
                              ("planId", "remotePlanId"), ("nativeRunId", "remoteRunId")):
            _require(lease[local] == receipt.get(remote))
        limits = lease["limits"]
        _require(type(limits) is dict and set(limits) == {"cpu", "memoryMb", "diskMb", "seconds"}
                 and all(type(value) is int and 0 < value <= 2147483647 for value in limits.values()))
        state, outcome, code = lease["state"], lease["executionStatus"], lease["exitCode"]
        _require(type(state) is str and state in _STATES and type(outcome) is str and outcome in _OUTCOMES)
        _require(type(lease["capacityHeld"]) is bool and lease["capacityHeld"] is (state != "RECLAIMED"))
        _require(code is None or type(code) is int and -255 <= code <= 255)
        if state in TERMINAL:
            _require(outcome in {"COMPLETED": {"COMPLETED"}, "FAILED": {"FAILED", "LIMIT_STOPPED"},
                                 "CANCEL_CONFIRMED": {"CANCELLED"}}[state])
        stop = lease["stopEvidence"]
        _require(stop is None or type(stop) is dict and set(stop) == {"allStopped", "kind"}
                 and stop["allStopped"] is True and type(stop["kind"]) is str
                 and stop["kind"] in {"never-dispatched", "original-root-reaped-and-no-live-process-group-members", "original-delegated-cgroup-empty-and-removed"})
        if lease["providerJobId"] is None and lease["processBinding"] is None:
            _require(state in {"RESERVED", "UNKNOWN", "CANCEL_REQUESTED"} and lease["capacityHeld"] is True
                     and outcome == "UNKNOWN" and code is None and stop is None and lease["enforcement"] is None
                     and lease.get("aggregateEvidence") is None)
        else:
            snapshot = {**lease, "leaseId": lease["id"], "released": state == "RECLAIMED"}
            PersistentResourceService.process_snapshot(lease, snapshot)
            if stop is not None:
                _require(stop["kind"] != "never-dispatched" or outcome == "CANCELLED")
                _require(outcome in {"COMPLETED", "CANCELLED", "LIMIT_STOPPED", "FAILED"}
                         and state in TERMINAL | {"RECLAIMING", "RECLAIMED"})
    return deepcopy(evidence)


def validate_process_evidence(receipt: dict, previous: dict | None = None) -> dict:
    """Validate exact receiver custody and monotonic identity against prior receipt."""
    try:
        evidence = _validated(receipt)
        if previous is not None:
            old = _validated(previous)
            for key in ("id", "remoteOwnerId", "remoteTaskId", "remotePlanId", "remoteRunId"):
                if previous.get(key) is not None:
                    _require(receipt.get(key) == previous[key])
            if old["leases"]:
                _require(len(evidence["leases"]) == 1)
                prior, current = old["leases"][0], evidence["leases"][0]
                _require(all(prior[key] == current[key] for key in _IMMUTABLE))
                for key in ("providerJobId", "processBinding", "enforcement"):
                    if prior[key] is not None:
                        _require(current[key] == prior[key])
                if prior.get("aggregateEvidence") is not None:
                    from .aggregate_process import validate_aggregate_evidence
                    validate_aggregate_evidence(current.get("aggregateEvidence"), current["processBinding"]["bindingFingerprint"],
                        current["enforcement"], prior["aggregateEvidence"])
                if prior["state"] == "RECLAIMED":
                    _require(current == prior)
                elif prior["stopEvidence"] is not None:
                    _require(all(current[key] == prior[key] for key in ("stopEvidence", "executionStatus", "exitCode")))
        return evidence
    except (KeyError, TypeError, ValueError, AttributeError):
        raise ValueError("REMOTE_PROCESS_EVIDENCE_INVALID") from None
