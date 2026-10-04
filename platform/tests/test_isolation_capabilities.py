"""Synthetic read-only prerequisites never manufacture aggregate enforcement."""
import json
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from typing import Any
import unittest
from unittest.mock import Mock, patch

from agent_factory.isolation_capabilities import (
    BACKEND, SUPPORTED_SCOPES, UNSUPPORTED_SCOPES, IsolationCapabilityError,
    _OBSERVATIONS, isolation_capabilities, require_isolation,
)
from agent_factory.process_enforcement import ProcessLimits, ProcessSpec
from agent_factory.process_provider import ProcessResourceProvider


class IsolationCapabilityTests(unittest.TestCase):
    def observed(self, **changes):
        return {**dict.fromkeys(_OBSERVATIONS, True), "cgroupReadOnlyMountObserved": False, **changes}

    def test_all_visible_prerequisites_never_grant_aggregate_backend(self):
        with patch("agent_factory.isolation_capabilities._observe", return_value=self.observed()):
            result = isolation_capabilities()
            self.assertEqual(result["backend"], BACKEND)
            self.assertEqual(result["supportedScopes"], list(SUPPORTED_SCOPES))
            for field in ("aggregateEnforcementVerified", "taskOwnedBackendSupported", "containerRuntimeEnforcementVerified"):
                self.assertIs(result[field], False)
            for scope in UNSUPPORTED_SCOPES:
                with self.subTest(scope=scope), self.assertRaises(IsolationCapabilityError) as denied:
                    require_isolation([scope])
                self.assertEqual(denied.exception.code, "ISOLATION_SCOPE_UNSUPPORTED")

    def test_read_only_mount_and_missing_delegation_report_precise_blockers(self):
        with patch("agent_factory.isolation_capabilities._observe", return_value=self.observed(
                cgroupReadOnlyMountObserved=True, delegatedSubtreeWritableObserved=False, userSystemdBusObserved=False)):
            result = isolation_capabilities()
        self.assertIn("CGROUP_MOUNT_READ_ONLY", result["prerequisiteReasons"])
        self.assertIn("DELEGATED_SUBTREE_WRITE_AUTHORITY_NOT_OBSERVED", result["prerequisiteReasons"])
        self.assertIn("USER_SYSTEMD_BUS_NOT_OBSERVED", result["prerequisiteReasons"])
        self.assertTrue(result["cooperativeRuntimeAvailable"])

    def test_native_facilities_missing_deny_even_empty_scope_requests(self):
        for field in ("linux", "posixProcessFacilitiesObserved", "rlimitFacilitiesObserved", "procIdentityReadable"):
            with self.subTest(field=field), patch("agent_factory.isolation_capabilities._observe",
                    return_value=self.observed(**{field: False})):
                self.assertEqual(isolation_capabilities()["supportedScopes"], [])
                with self.assertRaises(IsolationCapabilityError) as denied:
                    require_isolation([])
                self.assertEqual(denied.exception.code, "ISOLATION_FACILITIES_UNAVAILABLE")

    def test_requirement_fresh_probe_and_no_scope_downgrade(self):
        with patch("agent_factory.isolation_capabilities._observe", side_effect=[self.observed(), self.observed(linux=False)]) as probe:
            self.assertTrue(require_isolation(SUPPORTED_SCOPES)["cooperativeRuntimeAvailable"])
            with self.assertRaises(IsolationCapabilityError):
                require_isolation(SUPPORTED_SCOPES)
            self.assertEqual(probe.call_count, 2)
        with self.assertRaises(IsolationCapabilityError):
            require_isolation([SUPPORTED_SCOPES[0], "aggregate-memory"])

    def test_unknown_policy_values_never_echo_paths_or_exception_text(self):
        sentinel = "private-value-not-to-be-exposed"
        for value in (sentinel, [sentinel], [True], {"scope": sentinel}, None):
            with self.subTest(value=value), self.assertRaises(IsolationCapabilityError) as denied:
                require_isolation(value)
            self.assertNotIn(sentinel, str(denied.exception))
        with self.assertRaises(IsolationCapabilityError) as denied:
            require_isolation([], backend=sentinel)
        self.assertNotIn(sentinel, str(denied.exception))

    def test_report_projects_only_exact_boolean_observations(self):
        sentinel = "/host/private-path-and-limit"
        data = self.observed()
        data.update(extra=sentinel, cpuControllerObserved=sentinel, pidsControllerObserved=1)
        with patch("agent_factory.isolation_capabilities._observe", return_value=data):
            result = isolation_capabilities()
        self.assertNotIn(sentinel, json.dumps(result))
        self.assertEqual(set(result["observations"]), set(_OBSERVATIONS))
        self.assertTrue(all(type(value) is bool for value in result["observations"].values()))
        self.assertFalse(result["observations"]["cpuControllerObserved"])
        self.assertFalse(result["observations"]["pidsControllerObserved"])

    def test_unsupported_platform_probe_does_not_read_host_files(self):
        with patch("agent_factory.isolation_capabilities.sys.platform", "win32"), patch(
                "agent_factory.isolation_capabilities._read") as read:
            report = isolation_capabilities()
        read.assert_not_called()
        self.assertFalse(report["cooperativeRuntimeAvailable"])

    def test_read_only_mount_overrides_apparent_access_without_writing(self):
        def read(path):
            if str(path) == "/proc/self/mountinfo":
                return "1 2 0:3 / /sys/fs/cgroup ro,nosuid - cgroup2 cgroup2 rw,nsdelegate"
            if str(path).endswith("cgroup.controllers"):
                return "cpu memory pids"
            return "synthetic-readable-identity"
        with patch("agent_factory.isolation_capabilities.sys.platform", "linux"), patch(
                "agent_factory.isolation_capabilities._read", side_effect=read), patch(
                "agent_factory.isolation_capabilities.os.access", return_value=True), patch(
                "agent_factory.isolation_capabilities.os.getuid", return_value=1000, create=True), patch(
                "agent_factory.isolation_capabilities._socket_access", return_value=False):
            report = isolation_capabilities()
        self.assertTrue(report["observations"]["cgroupReadOnlyMountObserved"])
        self.assertFalse(report["observations"]["delegatedSubtreeWritableObserved"])
        self.assertFalse(report["aggregateEnforcementVerified"])

    def test_provider_aggregate_requirement_denies_before_root_or_directory_access(self):
        with patch("agent_factory.process_provider.LocalWorkspaceProvider") as workspace:
            with self.assertRaises(IsolationCapabilityError) as denied:
                ProcessResourceProvider(Mock(), Path("synthetic-unused-root"),
                    ProcessSpec("/synthetic/program", "a" * 64, ()), ProcessLimits(),
                    required_isolation=("aggregate-memory",))
            workspace.assert_not_called()
        self.assertEqual(denied.exception.code, "ISOLATION_SCOPE_UNSUPPORTED")


class IsolationCleanupBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_custody_cancel_and_reclaim_do_not_reapply_admission_requirements(self):
        # An already admitted provider, with purely mocked custody/OS evidence.
        # This proves call placement, not kernel enforcement or custody validity.
        provider: Any = object.__new__(ProcessResourceProvider)
        provider.required_isolation = ("per-process-cpu-time",)
        provider._root_guard = SimpleNamespace(_operation_lock=lambda: nullcontext())
        provider._transaction = lambda: nullcontext()
        record = {"binding": {"id": "lease", "ownerId": "alice", "fingerprint": "a" * 64,
                    "localTaskId": "task", "nativeRunId": "run", "planId": "plan"},
            "bindingHash": "b" * 64, "released": False, "allStopped": False, "stopKind": None,
            "state": "RUNNING", "executionStatus": "RUNNING", "exitCode": None}
        stopped = {"state": "CANCELLED", "stoppedProof": True,
            "stopReceipt": {"kind": "original-group-stopped"}, "exitCode": -9}
        adapter = Mock()
        adapter.cancel.return_value = stopped
        provider._load = Mock(return_value=record)
        provider._save = Mock()
        provider._adapter = Mock(side_effect=lambda value: nullcontext((adapter, stopped)))
        provider._validate_process = Mock()
        with patch("agent_factory.process_provider.require_isolation",
                side_effect=IsolationCapabilityError("ISOLATION_FACILITIES_UNAVAILABLE")) as admission:
            cancelled = await provider.cancel("lease", "alice")
            self.assertEqual(cancelled["state"], "CANCEL_CONFIRMED")
            self.assertTrue(cancelled["capacityHeld"])
            released = await provider.reclaim("lease", "alice")
            self.assertEqual(released["state"], "RECLAIMED")
            self.assertFalse(released["capacityHeld"])
            admission.assert_not_called()
        adapter.cancel.assert_called_once_with(owner_id="alice")
        self.assertEqual(provider._save.call_count, 2)


if __name__ == "__main__":
    unittest.main()
