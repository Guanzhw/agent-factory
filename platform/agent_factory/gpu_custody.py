"""GPU admission custody validation, without hardware or driver operations.

Evidence is a trusted operator provider assertion, not cryptographic authentication
or proof of GPU quotas, physical isolation, or exclusion of external processes.
The caller separately validates the complete native process stop contract.
"""
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import re
from typing import cast


def _require(value):
    if not value:
        raise ValueError("GPU_CUSTODY_INVALID")


def _hash(value):
    return type(value) is str and re.fullmatch(r"[a-f0-9]{64}", value) is not None


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


@dataclass(frozen=True)
class GpuBinding:
    receiver_namespace: str
    device_id: str

    def __post_init__(self):
        _require(_hash(self.receiver_namespace) and _hash(self.device_id))

    def to_dict(self):
        return {"schema": 1, "receiverNamespace": self.receiver_namespace, "deviceId": self.device_id,
                "policy": "exclusive-factory-lease", "quotaEnforced": False, "deviceIsolationEnforced": False}

    @property
    def identity_key(self):
        return _digest({"receiverNamespace": self.receiver_namespace, "deviceId": self.device_id})


def validate_binding(value):
    """Return a fresh canonical binding; reject extra fields and truthy booleans."""
    _require(type(value) is dict and set(value) == {"schema", "receiverNamespace", "deviceId", "policy",
                                                 "quotaEnforced", "deviceIsolationEnforced"})
    _require(type(value["schema"]) is int and value["schema"] == 1
             and value["policy"] == "exclusive-factory-lease"
             and value["quotaEnforced"] is False and value["deviceIsolationEnforced"] is False)
    return GpuBinding(cast(str, value["receiverNamespace"]), cast(str, value["deviceId"])).to_dict()


def evidence_fingerprint(lease):
    _require(type(lease) is dict)
    keys = ("id", "ownerId", "localTaskId", "nativeRunId", "planId", "fingerprint")
    for key in keys:
        value = lease.get(key)
        if key == "ownerId":
            _require(type(value) is str and 1 <= len(value) <= 200
                     and all(ord(char) >= 32 and ord(char) != 127 for char in value))
        else:
            _require(type(value) is str and re.fullmatch(r"[A-Za-z0-9_.:-]{1,200}", value) is not None)
    _require(_hash(lease["fingerprint"]))
    return _digest({**{key: lease[key] for key in keys}, "gpuBinding": validate_binding(lease.get("gpuBinding"))})


def validate_gpu_evidence(lease, snapshot):
    """Validate original custody; UNKNOWN never permits dropping the GPU pin.

A RELEASED assertion is accepted only alongside matching original process stop
and explicit device observation. Digest fields bind evidence, not its issuer.
"""
    expected = evidence_fingerprint(lease)
    _require(type(snapshot) is dict)
    _require(validate_binding(snapshot.get("gpuBinding")) == validate_binding(lease["gpuBinding"]))
    evidence = snapshot.get("gpuEvidence")
    _require(type(evidence) is dict and set(evidence) == {"schema", "bindingFingerprint", "state", "releaseProof"})
    _require(type(evidence["schema"]) is int and evidence["schema"] == 1
             and evidence["bindingFingerprint"] == expected
             and type(evidence["state"]) is str and evidence["state"] in {"HELD", "UNKNOWN", "RELEASED"})
    proof = evidence["releaseProof"]
    if evidence["state"] != "RELEASED":
        _require(proof is None and snapshot.get("state") != "RECLAIMED" and snapshot.get("released") is not True)
    else:
        _require(snapshot.get("state") == "RECLAIMED" and snapshot.get("released") is True)
        _require(type(proof) is dict and set(proof) == {"kind", "processBindingFingerprint", "deviceObservationSha256"})
        proof = cast(dict, proof)
        _require(proof["kind"] in ("never-dispatched", "original-process-stopped-and-device-released")
                 and _hash(proof["processBindingFingerprint"]) and _hash(proof["deviceObservationSha256"]))
        binding = snapshot.get("processBinding")
        _require(type(binding) is dict and set(binding) == {"taskId", "nativeRunId", "planId", "bindingFingerprint"})
        _require(binding["bindingFingerprint"] == proof["processBindingFingerprint"]
                 and binding["taskId"] == lease["localTaskId"] and binding["nativeRunId"] == lease["nativeRunId"]
                 and binding["planId"] == lease["planId"] and lease.get("processBinding") in (None, binding))
        stop = snapshot.get("stopEvidence")
        _require(type(stop) is dict and set(stop) == {"allStopped", "kind"} and stop["allStopped"] is True)
        kinds = ("never-dispatched",) if proof["kind"] == "never-dispatched" else (
            "original-root-reaped-and-no-live-process-group-members", "original-delegated-cgroup-empty-and-removed")
        _require(stop["kind"] in kinds)
    previous = lease.get("gpuEvidence")
    if previous is not None:
        _require(type(previous) is dict and previous.get("bindingFingerprint") == expected)
        if previous.get("state") == "RELEASED":
            _require(previous == evidence)
    return deepcopy(evidence)
