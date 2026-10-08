"""Pure GPU custody contracts: no device, process, network or database access."""
from copy import deepcopy
from dataclasses import FrozenInstanceError
import unittest

from agent_factory.gpu_custody import GpuBinding, evidence_fingerprint, validate_binding, validate_gpu_evidence


def fixture():
    binding = GpuBinding("a" * 64, "b" * 64).to_dict()
    lease = {"id": "lease1", "ownerId": "alice", "localTaskId": "task1", "nativeRunId": "run1",
             "planId": "plan1", "fingerprint": "c" * 64, "gpuBinding": binding}
    snapshot = {"state": "UNKNOWN", "released": False, "gpuBinding": deepcopy(binding),
                "gpuEvidence": {"schema": 1, "bindingFingerprint": evidence_fingerprint(lease),
                                "state": "UNKNOWN", "releaseProof": None}}
    return lease, snapshot


def released():
    lease, snapshot = fixture()
    snapshot.update(state="RECLAIMED", released=True,
        processBinding={"taskId": "task1", "nativeRunId": "run1", "planId": "plan1", "bindingFingerprint": "d" * 64},
        stopEvidence={"allStopped": True, "kind": "original-root-reaped-and-no-live-process-group-members"})
    snapshot["gpuEvidence"].update(state="RELEASED", releaseProof={
        "kind": "original-process-stopped-and-device-released", "processBindingFingerprint": "d" * 64,
        "deviceObservationSha256": "e" * 64})
    return lease, snapshot


class GpuCustodyTests(unittest.TestCase):
    def denied(self, lease, snapshot):
        with self.assertRaisesRegex(ValueError, "^GPU_CUSTODY_INVALID$"):
            validate_gpu_evidence(lease, snapshot)

    def test_binding_is_frozen_and_identity_is_namespace_scoped(self):
        binding = GpuBinding("a" * 64, "b" * 64)
        self.assertEqual(validate_binding(binding.to_dict()), binding.to_dict())
        self.assertNotEqual(binding.identity_key, GpuBinding("c" * 64, "b" * 64).identity_key)
        with self.assertRaises(FrozenInstanceError):
            setattr(binding, "device_id", "c" * 64)

    def test_binding_rejects_extra_fields_booleans_and_raw_identity(self):
        for patch in ({"schema": True}, {"quotaEnforced": 0}, {"deviceIsolationEnforced": True},
                      {"deviceId": "GPU-real-device"}, {"receiverNamespace": "A" * 64}, {"extra": 1}):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                validate_binding(GpuBinding("a" * 64, "b" * 64).to_dict() | patch)

    def test_unknown_requires_binding_even_without_process_job(self):
        lease, snapshot = fixture()
        self.assertEqual(validate_gpu_evidence(lease, snapshot)["state"], "UNKNOWN")
        snapshot.pop("gpuBinding")
        self.denied(lease, snapshot)

    def test_all_original_identity_fields_are_bound(self):
        for key in ("id", "ownerId", "localTaskId", "nativeRunId", "planId", "fingerprint"):
            lease, snapshot = fixture()
            lease[key] = "f" * 64
            self.denied(lease, snapshot)
        lease, snapshot = fixture()
        snapshot["gpuBinding"]["deviceId"] = "f" * 64
        self.denied(lease, snapshot)

    def test_cancel_timeout_disconnect_still_hold(self):
        for state in ("CANCEL_REQUESTED", "FAILED", "UNKNOWN", "RECLAIMING"):
            lease, snapshot = fixture()
            snapshot.update(state=state, connected=False)
            snapshot["gpuEvidence"]["state"] = "HELD"
            self.assertEqual(validate_gpu_evidence(lease, snapshot)["state"], "HELD")
            snapshot["released"] = True
            self.denied(lease, snapshot)

    def test_release_requires_exact_positive_stop_and_device_proof(self):
        lease, snapshot = released()
        self.assertEqual(validate_gpu_evidence(lease, snapshot)["state"], "RELEASED")
        for patch in ({"released": 1}, {"state": "COMPLETED"}, {"stopEvidence": None},
                      {"stopEvidence": {"allStopped": 1, "kind": "original-root-reaped-and-no-live-process-group-members"}}):
            self.denied(lease, snapshot | patch)
        for key, value in (("processBindingFingerprint", "f" * 64), ("deviceObservationSha256", ""), ("kind", "idle")):
            changed = deepcopy(snapshot)
            changed["gpuEvidence"]["releaseProof"][key] = value
            self.denied(lease, changed)

    def test_never_dispatched_and_aggregate_proofs_are_distinct(self):
        lease, snapshot = released()
        snapshot["gpuEvidence"]["releaseProof"]["kind"] = "never-dispatched"
        self.denied(lease, snapshot)
        snapshot["stopEvidence"]["kind"] = "never-dispatched"
        validate_gpu_evidence(lease, snapshot)
        snapshot["gpuEvidence"]["releaseProof"]["kind"] = "original-process-stopped-and-device-released"
        self.denied(lease, snapshot)
        snapshot["stopEvidence"]["kind"] = "original-delegated-cgroup-empty-and-removed"
        validate_gpu_evidence(lease, snapshot)

    def test_release_proof_and_original_process_binding_cannot_drift(self):
        lease, snapshot = released()
        lease["processBinding"] = deepcopy(snapshot["processBinding"])
        lease["gpuEvidence"] = validate_gpu_evidence(lease, snapshot)
        changed = deepcopy(snapshot)
        changed["gpuEvidence"]["releaseProof"]["deviceObservationSha256"] = "f" * 64
        self.denied(lease, changed)
        changed = deepcopy(snapshot)
        changed["processBinding"]["bindingFingerprint"] = "f" * 64
        changed["gpuEvidence"]["releaseProof"]["processBindingFingerprint"] = "f" * 64
        self.denied(lease, changed)

    def test_malformed_evidence_and_held_release_are_rejected(self):
        for patch in ({"schema": True}, {"state": []}, {"extra": 1}, {"releaseProof": {}}):
            lease, snapshot = fixture()
            snapshot["gpuEvidence"].update(patch)
            self.denied(lease, snapshot)
        lease, snapshot = fixture()
        snapshot["state"] = "RECLAIMED"
        self.denied(lease, snapshot)

    def test_returned_evidence_is_detached(self):
        lease, snapshot = released()
        value = validate_gpu_evidence(lease, snapshot)
        value["releaseProof"]["deviceObservationSha256"] = "f" * 64
        self.assertEqual(snapshot["gpuEvidence"]["releaseProof"]["deviceObservationSha256"], "e" * 64)

    def test_owner_accepts_email_and_unicode_without_normalization(self):
        fingerprints = []
        for owner in ("alice@example.org", "研究员甲", "é", "e\u0301"):
            lease, snapshot = fixture()
            lease["ownerId"] = owner
            snapshot["gpuEvidence"]["bindingFingerprint"] = evidence_fingerprint(lease)
            validate_gpu_evidence(lease, snapshot)
            fingerprints.append(evidence_fingerprint(lease))
        self.assertNotEqual(fingerprints[-1], fingerprints[-2])

    def test_owner_rejects_controls_empty_and_oversize(self):
        for owner in ("", "x" * 201, "alice\n", "a\x00b", "a\x1fb", "a\x7fb"):
            lease, _ = fixture()
            lease["ownerId"] = owner
            with self.subTest(owner=repr(owner)), self.assertRaisesRegex(ValueError, "^GPU_CUSTODY_INVALID$"):
                evidence_fingerprint(lease)
