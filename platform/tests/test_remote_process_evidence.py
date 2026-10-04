"""Pure handoff projection checks; no database, process or network effects."""
from copy import deepcopy
import unittest

from agent_factory.remote_process_evidence import project_process_evidence, validate_process_evidence


def lease():
    return {"id": "lease1", "ownerId": "receiver-alice", "localTaskId": "task1", "planId": "plan1",
        "nativeRunId": "native1", "fingerprint": "a" * 64, "providerJobId": "custody1",
        "processBinding": {"taskId": "task1", "nativeRunId": "native1", "planId": "plan1", "bindingFingerprint": "b" * 64},
        "enforcement": {"cpu": "per-process-RLIMIT_CPU", "memory": "per-process-RLIMIT_AS",
            "fileSize": "per-file-RLIMIT_FSIZE", "wall": "cooperative-process-group-guardian",
            "aggregateQuota": False, "hostileCodeSandbox": False, "networkIsolation": False},
        "stopEvidence": None, "state": "RUNNING", "capacityHeld": True, "executionStatus": "RUNNING", "exitCode": None,
        "poolId": "receiver-pool", "poolFingerprint": "c" * 64,
        "limits": {"cpu": 1, "memoryMb": 128, "diskMb": 1, "seconds": 3}}


def receipt(value=None):
    return {"id": "handoff1", "remoteOwnerId": "receiver-alice", "remoteTaskId": "task1", "remotePlanId": "plan1",
            "remoteRunId": "native1", "processLeases": project_process_evidence([lease() if value is None else value])}


def reclaimed():
    value = lease()
    value.update(state="RECLAIMED", capacityHeld=False, executionStatus="LIMIT_STOPPED", exitCode=-9,
        stopEvidence={"allStopped": True, "kind": "original-root-reaped-and-no-live-process-group-members"})
    return value


class RemoteProcessEvidenceTests(unittest.TestCase):
    def denied(self, value, previous=None):
        with self.assertRaisesRegex(ValueError, '^REMOTE_PROCESS_EVIDENCE_INVALID$'):
            validate_process_evidence(value, previous)

    def test_projection_excludes_operator_paths_pids_argv_and_preserves_receiver_identity(self):
        value = {**lease(), "argv": ["private"], "root": "/private", "pid": 1234, "configuration": {"secret": "synthetic"}}
        result = project_process_evidence([value])
        self.assertEqual(result["leases"], [lease()])
        self.assertEqual(validate_process_evidence(receipt())["leases"][0]["ownerId"], "receiver-alice")
        result["leases"][0]["limits"]["cpu"] = 99
        self.assertEqual(value["limits"]["cpu"], 1)

    def test_exact_receiver_scope_rejects_cross_owner_task_plan_or_native_run(self):
        for key in ("remoteOwnerId", "remoteTaskId", "remotePlanId", "remoteRunId"):
            value = receipt(); value[key] = "foreign"
            with self.subTest(field=key): self.denied(value)
        value = receipt(); value["processLeases"]["leases"][0]["processBinding"]["taskId"] = "foreign"
        self.denied(value)

    def test_unknown_early_hold_can_acquire_original_process_proof_but_cannot_release(self):
        early = lease()
        early.update(state="UNKNOWN", executionStatus="UNKNOWN", providerJobId=None, processBinding=None, enforcement=None)
        prior = receipt(early)
        self.assertTrue(validate_process_evidence(prior)["leases"][0]["capacityHeld"])
        validate_process_evidence(receipt(), prior)
        for change in ({"capacityHeld": False}, {"state": "RECLAIMED"}, {"executionStatus": "COMPLETED"},
                       {"stopEvidence": {"allStopped": True, "kind": "never-dispatched"}}):
            value = deepcopy(prior); value["processLeases"]["leases"][0].update(change)
            self.denied(value)

    def test_fixed_schema_bounds_and_strict_boolean_and_integer_types(self):
        for key, replacement in (("schema", True), ("complete", 1), ("leases", {}), ("leases", [lease(), lease()])):
            value = receipt(); value["processLeases"][key] = replacement
            self.denied(value)
        for field, replacement in (("capacityHeld", 1), ("exitCode", True), ("exitCode", 256), ("state", "arbitrary")):
            value = receipt(); value["processLeases"]["leases"][0][field] = replacement
            self.denied(value)
        for replacement in (True, 0, -1, 2**31, 1.5):
            value = receipt(); value["processLeases"]["leases"][0]["limits"]["cpu"] = replacement
            self.denied(value)
        value = receipt(); value["processLeases"]["leases"][0]["enforcement"]["aggregateQuota"] = 0
        self.denied(value)
        value = receipt(); value["processLeases"]["leases"][0]["path"] = "/operator-only"
        self.denied(value)

    def test_reclaimed_requires_positive_proof_and_preserves_failed_execution(self):
        value = receipt(reclaimed())
        checked = validate_process_evidence(value, receipt())["leases"][0]
        self.assertEqual((checked["state"], checked["executionStatus"], checked["exitCode"]), ("RECLAIMED", "LIMIT_STOPPED", -9))
        for change in ({"stopEvidence": None}, {"capacityHeld": True}, {"executionStatus": "UNKNOWN"},
                       {"stopEvidence": {"allStopped": 1, "kind": "never-dispatched"}}):
            invalid = deepcopy(value); invalid["processLeases"]["leases"][0].update(change)
            self.denied(invalid)
        invalid = deepcopy(value)
        invalid["processLeases"]["leases"][0]["stopEvidence"]["kind"] = "never-dispatched"
        self.denied(invalid)
        invalid = deepcopy(value)
        invalid["processLeases"]["leases"][0].update(state="COMPLETED", capacityHeld=True)
        self.denied(invalid)
        validate_process_evidence(value, value)
        self.denied(receipt(), value)

    def test_existing_lease_and_all_bound_identity_pins_cannot_change_or_disappear(self):
        old = receipt()
        for field in ("id", "fingerprint", "providerJobId", "poolId", "poolFingerprint"):
            value = receipt(); value["processLeases"]["leases"][0][field] = "d" * 64
            self.denied(value, old)
        value = receipt(); value["processLeases"]["leases"][0]["processBinding"]["bindingFingerprint"] = "d" * 64
        self.denied(value, old)
        value = receipt(); value["processLeases"]["leases"][0]["limits"]["cpu"] = 2
        self.denied(value, old)
        value = receipt(); value["processLeases"]["leases"] = []
        self.denied(value, old)
        value = receipt(); value["id"] = "other-handoff"
        self.denied(value, old)

    def test_empty_pre_dispatch_evidence_does_not_claim_execution(self):
        value = {**receipt(), "remoteRunId": None, "processLeases": project_process_evidence([])}
        self.assertEqual(validate_process_evidence(value)["leases"], [])
        validate_process_evidence(receipt(), value)
        for malformed in ({}, {"processLeases": None}, {"processLeases": {"schema": 1, "complete": False, "leases": []}}):
            self.denied(malformed)

    def test_nested_operator_fields_are_rejected_and_terminal_evidence_cannot_be_rewritten(self):
        value = lease(); value["processBinding"]["path"] = "/private"
        with self.assertRaises(ValueError): project_process_evidence([value])
        value = reclaimed(); value.update(state="FAILED", capacityHeld=True)
        prior = receipt(value)
        validate_process_evidence(receipt(reclaimed()), prior)
        changed = receipt(reclaimed()); changed["processLeases"]["leases"][0]["executionStatus"] = "COMPLETED"
        self.denied(changed, prior)


if __name__ == '__main__':
    unittest.main()
