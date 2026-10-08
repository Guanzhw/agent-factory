"""Pure receipt validation: no PostgreSQL, provider calls or subprocesses."""
import copy
from types import SimpleNamespace
from typing import Any
import unittest
from unittest.mock import Mock

from agent_factory.resources import PersistentResourceService


class ProcessReceiptValidation(unittest.TestCase):
    def setUp(self):
        self.binding = {"taskId": "task-original", "nativeRunId": "native-original",
                        "planId": "plan-original", "bindingFingerprint": "b" * 64}
        self.lease = {"id": "lease-original", "ownerId": "alice", "fingerprint": "a" * 64,
                      "localTaskId": "task-original", "nativeRunId": "native-original", "planId": "plan-original",
                      "providerJobId": "job-original", "processBinding": copy.deepcopy(self.binding),
                      "connectionRef": "target-original", "state": "RUNNING", "capacityHeld": True}
        self.snapshot = {"leaseId": "lease-original", "ownerId": "alice", "fingerprint": "a" * 64,
                         "providerJobId": "job-original", "processBinding": copy.deepcopy(self.binding),
                         "state": "RECLAIMED", "released": True, "executionStatus": "COMPLETED", "exitCode": 0,
                         "enforcement": {"cpu": "per-process-RLIMIT_CPU", "memory": "per-process-RLIMIT_AS",
                            "fileSize": "per-file-RLIMIT_FSIZE", "wall": "cooperative-process-group-guardian",
                            "aggregateQuota": False, "hostileCodeSandbox": False, "networkIsolation": False},
                         "stopEvidence": {"allStopped": True, "kind": "original-root-reaped-and-no-live-process-group-members"}}

    def reject(self, snapshot):
        with self.assertRaises(ValueError):
            PersistentResourceService.process_snapshot(self.lease, snapshot)

    def test_exact_original_receipt_preserves_identity_and_outcome(self):
        checked = PersistentResourceService.process_snapshot(self.lease, self.snapshot)
        self.assertEqual(checked["providerJobId"], "job-original")
        self.assertEqual(checked["processBinding"], self.binding)
        self.assertEqual(checked["stopEvidence"], self.snapshot["stopEvidence"])
        self.assertEqual((checked["executionStatus"], checked["exitCode"]), ("COMPLETED", 0))
        self.assertEqual(self.lease["state"], "RUNNING")
        self.assertTrue(self.lease["capacityHeld"])

    def test_foreign_lease_owner_job_and_plan_binding_rejected(self):
        for key in ("leaseId", "ownerId", "fingerprint", "providerJobId"):
            with self.subTest(key=key):
                self.reject({**self.snapshot, key: "foreign"})
        for key in ("taskId", "nativeRunId", "planId", "bindingFingerprint"):
            with self.subTest(binding=key):
                self.reject({**self.snapshot, "processBinding": {**self.binding, key: "c" * 64}})
        for binding in [None, {}, {**self.binding, "untrusted": True}, {**self.binding, "bindingFingerprint": True}]:
            with self.subTest(binding=binding):
                self.reject({**self.snapshot, "processBinding": binding})

    def test_first_trusted_receipt_pins_identity_against_later_changes(self):
        initial = {**self.lease, "providerJobId": None, "processBinding": None}
        first = PersistentResourceService.process_snapshot(initial, self.snapshot)
        pinned = {**initial, **first}
        for changes in [{"providerJobId": "replacement-job"},
                        {"processBinding": {**self.binding, "bindingFingerprint": "c" * 64}}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                PersistentResourceService.process_snapshot(pinned, {**self.snapshot, **changes})
        self.assertEqual(PersistentResourceService.process_snapshot(pinned, self.snapshot), first)

    def test_unknown_without_receipt_never_confirms_release(self):
        snapshot = {"leaseId": "lease-original", "ownerId": "alice", "fingerprint": "a" * 64,
                    "state": "UNKNOWN", "released": True}
        self.assertEqual(PersistentResourceService.process_snapshot(self.lease, snapshot), {})
        service: Any = object.__new__(PersistentResourceService)
        service.inspect = Mock(return_value=copy.deepcopy(self.lease))
        service._authorize = Mock(return_value=SimpleNamespace(axis="provider"))
        updates = []
        def update(owner, lease_id, state, changes):
            updates.append((state, changes))
            return {**self.lease, **changes, "state": state, "capacityHeld": state != "RECLAIMED"}
        service._update = Mock(side_effect=update)
        observed = service._observe("alice", "lease-original", snapshot)
        self.assertEqual(observed["state"], "UNKNOWN")
        self.assertTrue(observed["capacityHeld"])
        self.assertEqual(len(updates), 1)
        self.assertNotIn("released", updates[0][1])
        self.assertEqual(observed["providerJobId"], "job-original")

    def test_reclaimed_needs_positive_original_stop_and_terminal_execution(self):
        for stop in [None, {}, {"allStopped": False, "kind": "original-root-reaped-and-no-live-process-group-members"},
                     {"allStopped": 1, "kind": "original-root-reaped-and-no-live-process-group-members"},
                     {"allStopped": True, "kind": "pid-not-found"},
                     {"allStopped": True, "kind": "original-root-reaped-and-no-live-process-group-members", "extra": True}]:
            with self.subTest(stop=stop):
                self.reject({**self.snapshot, "stopEvidence": stop})
        for state in ["PREPARED", "DISPATCHING", "RUNNING", "UNKNOWN"]:
            with self.subTest(execution=state):
                self.reject({**self.snapshot, "executionStatus": state})
        for released in [None, False, 1, "true"]:
            with self.subTest(released=released):
                self.reject({**self.snapshot, "released": released})
        for terminal in ["COMPLETED", "FAILED", "CANCEL_CONFIRMED"]:
            self.reject({**self.snapshot, "state": terminal, "stopEvidence": None})

    def test_failed_and_limit_stopped_preserve_exact_exit_code(self):
        for outcome, exit_code in [("FAILED", 17), ("LIMIT_STOPPED", -9), ("CANCELLED", -15)]:
            with self.subTest(outcome=outcome):
                checked = PersistentResourceService.process_snapshot(self.lease,
                    {**self.snapshot, "executionStatus": outcome, "exitCode": exit_code})
                self.assertEqual((checked["executionStatus"], checked["exitCode"]), (outcome, exit_code))

    def test_unknown_outcome_enum_and_non_integer_or_unbounded_exit_code_rejected(self):
        for outcome in ["SUCCEEDED", "reclaimed", None, True, 0]:
            with self.subTest(outcome=outcome):
                self.reject({**self.snapshot, "executionStatus": outcome})
        for code in [True, False, 0.0, "0", 256, -256, 2**63]:
            with self.subTest(code=code):
                self.reject({**self.snapshot, "exitCode": code})

    def test_enforcement_claims_cannot_be_changed(self):
        for key, value in [("cpu", "aggregate-cgroup"), ("aggregateQuota", True), ("hostileCodeSandbox", True),
                           ("networkIsolation", True), ("aggregateQuota", 0), ("hostileCodeSandbox", 0), ("networkIsolation", 0)]:
            with self.subTest(key=key):
                self.reject({**self.snapshot, "enforcement": {**self.snapshot["enforcement"], key: value}})


if __name__ == "__main__":
    unittest.main()
