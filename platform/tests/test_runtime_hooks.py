"""Synthetic boundary tests; these do not prove a live provider integration."""
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from agent_factory.runtime_hooks import (
    cancel_owned_runtime, effect_unresolved, execution_classification,
    native_ended_reason, project_runtime_evidence, reconcile_runtime_capacity,
)
from agent_factory.store import Store


class RuntimeHookTests(unittest.TestCase):
    def test_effect_stop_requires_literal_positive_proof(self):
        for status in ("UNKNOWN", "DONE", "CANCELLED"):
            for proof in (None, {}, {"allStopped": False}, {"allStopped": 1}, {"allStopped": "true"}, {"allStopped": True}):
                with self.subTest(status=status, proof=proof):
                    effect = {"effect_key": "run:orx-experiment-launch-v1", "status": status,
                              "result": {"stopEvidence": proof}}
                    self.assertEqual(effect_unresolved(effect), not (status in {"DONE", "CANCELLED"} and
                                     isinstance(proof, dict) and proof.get("allStopped") is True))
        self.assertFalse(effect_unresolved({"effect_key": "run:ordinary-tool", "status": "DONE"}))
        self.assertTrue(effect_unresolved({"effect_key": "run:ordinary-tool", "status": "UNKNOWN"}))

    def test_classification_never_uses_deployment_mode_as_evidence(self):
        for demo in (True, False):
            base = {"demo": demo, "syntheticFixture": True,
                    "executionBindings": {"model": {"adapterId": "provider-registered"}}}
            self.assertEqual(execution_classification(base), {"executionKind": "native-agent", "syntheticFixture": False})
            self.assertEqual(execution_classification({**base, "nativeComponent": {"kind": "workflow"}})["executionKind"], "native-workflow")
            base["executionBindings"]["model"]["adapterId"] = "local-synthetic-model-v1"
            self.assertTrue(execution_classification(base)["syntheticFixture"])
        self.assertTrue(execution_classification({"syntheticFixture": True})["syntheticFixture"])
        self.assertFalse(execution_classification({})["syntheticFixture"])

    def test_upgrade_reconciliation_remains_exact_and_positive(self):
        store = Mock()
        reconcile_runtime_capacity(store)
        statement = store.sql.call_args.args[0]
        self.assertIn("effect.effect_key=task.run_id || :suffix", statement)
        self.assertIn("IS DISTINCT FROM 'true'::jsonb", statement)
        self.assertEqual(store.sql.call_args.kwargs["suffix"], ":orx-experiment-launch-v1")

    def test_native_completion_is_not_effect_completion(self):
        store = SimpleNamespace(workflow=None, effects=lambda _: [
            {"effect_key": "run:orx-experiment-launch-v1", "status": "DONE", "result": {}}])
        self.assertEqual(native_ended_reason(store, {"id": "task", "run_id": "run"}), "native-ended-unresolved-experiment")
        self.assertIsNone(native_ended_reason(store, {"id": "other", "run_id": "other-run"}))

    def test_terminal_storage_release_rechecks_adapter_stop_proof(self):
        store = Store.__new__(Store)
        store.process_runtime = store.workflow = None
        store.effects = Mock(return_value=[{"effect_key": "run:orx-experiment-launch-v1", "status": "DONE", "result": {}}])
        store.storage = Mock()
        store.sql = Mock()
        store.event = Mock()
        task = {"id": "task", "terminal": False, "body": {"lastStatus": "running"}}
        store._observed_locked(task, "completed", True)
        store.storage.release.assert_not_called()
        self.assertFalse(store.sql.call_args.kwargs["terminal"])
        store.effects.return_value[0]["result"] = {"stopEvidence": {"allStopped": True}}
        store._observed_locked(task, "completed", True)
        store.storage.release.assert_called_once_with("task")

    def test_missing_artifact_provenance_is_unknown_not_synthetic(self):
        store = Store.__new__(Store)
        store.settings = SimpleNamespace(experiment_output_bytes=4096)
        store.task = Mock(return_value={"id": "task"})
        store.remote_bindings = None
        store.sql = Mock()
        store.event = Mock()
        artifact = store.artifact_write("run", "output.json", "{}")
        self.assertEqual(artifact["provenance"], {"evidenceKind": "unverified", "verificationStatus": "unverified"})
        artifact = store.artifact_write("run", "fixture.json", "{}", metadata={"syntheticFixture": True})
        self.assertEqual(artifact["provenance"], {"syntheticFixture": True})
        self.assertEqual(store.artifact_write("run", "empty.json", "{}", metadata={})["provenance"], {})

    def test_legacy_evidence_projection_retains_fields_without_demo_claim(self):
        store = SimpleNamespace(comparisons=None)
        task = {"id": "task", "owner_id": "alice"}
        experiment = {"status": "UNKNOWN", "stopEvidence": {"allStopped": False}}
        with patch("agent_factory.orx_experiment_tools.inspect_orx_experiment", return_value=experiment), \
             patch("agent_factory.synthesis_runtime.inspect_synthesis_evidence", return_value=None):
            for demo in (True, False):
                job = {"deploymentMode": "demo" if demo else "production", "verificationStatus": "unverified"}
                result, evaluation = project_runtime_evidence(SimpleNamespace(demo=demo), store, task, {}, [], job)
                self.assertEqual(result["orxExperiment"], experiment)
                self.assertIsNone(evaluation)
                self.assertEqual(job["evidenceKind"], "toy_local_evaluation")
                self.assertEqual(job["executionKind"], "local-process")
                self.assertEqual(job["verificationStatus"], "unverified")
                self.assertEqual(job["deploymentMode"], "demo" if demo else "production")


class RuntimeCleanupTests(unittest.IsolatedAsyncioTestCase):
    async def test_cleanup_delegates_existing_task_identity_only(self):
        settings = object()
        workflow = SimpleNamespace(cancel_task=AsyncMock())
        store = SimpleNamespace(settings=settings, workflow=workflow)
        task = {"id": "original-task", "owner_id": "alice"}
        with patch("agent_factory.orx_experiment_tools.reclaim_orx_experiment", new_callable=AsyncMock) as reclaim:
            await cancel_owned_runtime(store, task)
            reclaim.assert_awaited_once_with(settings, store, "original-task")
            workflow.cancel_task.assert_awaited_once_with("alice", "original-task")

    async def test_uncertain_cleanup_propagates_without_releasing_anything(self):
        store = SimpleNamespace(settings=object(), workflow=SimpleNamespace(cancel_task=AsyncMock()))
        with patch("agent_factory.orx_experiment_tools.reclaim_orx_experiment", new_callable=AsyncMock,
                   side_effect=ValueError("Original binding is uncertain")):
            with self.assertRaises(ValueError):
                await cancel_owned_runtime(store, {"id": "task", "owner_id": "alice"})
            store.workflow.cancel_task.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
