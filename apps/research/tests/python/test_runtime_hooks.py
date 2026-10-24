"""Synthetic boundary tests; these do not prove a live provider integration."""
from contextlib import contextmanager, nullcontext
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from agent_factory.runtime_hooks import (
    cancel_owned_runtime, effect_unresolved, execution_classification,
    native_ended_reason,
)
from agent_factory.store import Store
from agent_factory.application_runtime import ApplicationRuntimeRegistry
from agent_factory_research.runtime_registration import ResearchApplicationHooks
from agent_factory_research.research_runtime_hooks import ResearchRuntimeHooks

project_runtime_evidence = ResearchRuntimeHooks.project
reconcile_runtime_capacity = ResearchRuntimeHooks.reconcile_capacity


def install_runtime(store, task=None):
    original = task or {'id': 'task', 'run_id': 'run', 'owner_id': 'alice', 'plan_id': 'plan'}
    store.task = Mock(return_value=original)
    store.plan = Mock(return_value={'application': 'research'})
    store.application_runtime = ApplicationRuntimeRegistry(store)
    store.application_runtime.register('research', ResearchApplicationHooks(), legacy_applications=('research',),
                                       effects=('orx-experiment-launch-v1',))


class RuntimeHookTests(unittest.TestCase):
    def test_effect_stop_requires_literal_positive_proof(self):
        store = SimpleNamespace(effects=lambda _: [])
        install_runtime(store)
        for status in ("UNKNOWN", "DONE", "CANCELLED"):
            for proof in (None, {}, {"allStopped": False}, {"allStopped": 1}, {"allStopped": "true"}, {"allStopped": True}):
                with self.subTest(status=status, proof=proof):
                    effect = {"effect_key": "run:orx-experiment-launch-v1", "status": status,
                              "result": {"stopEvidence": proof}}
                    self.assertEqual(effect_unresolved(effect, store), not (status in {"DONE", "CANCELLED"} and
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
        install_runtime(store)
        self.assertEqual(native_ended_reason(store, {"id": "task", "run_id": "run", "owner_id": "alice", "plan_id": "plan"}), "native-ended-unresolved-experiment")
        self.assertIsNone(native_ended_reason(store, {"id": "other", "run_id": "other-run", "owner_id": "alice", "plan_id": "plan"}))

    def test_terminal_storage_release_rechecks_adapter_stop_proof(self):
        store = Store.__new__(Store)
        store.process_runtime = store.workflow = None
        store.effects = Mock(return_value=[{"effect_key": "run:orx-experiment-launch-v1", "status": "DONE", "result": {}}])
        store.storage = Mock()
        store.sql = Mock()
        store.event = Mock()
        task = {"id": "task", "run_id": "run", "owner_id": "alice", "plan_id": "plan",
                "terminal": False, "body": {"lastStatus": "running"}}
        install_runtime(store, task)
        store._observed_locked(task, "completed", True)
        store.storage.release.assert_not_called()
        # Unconfirmed stop keeps the existing nonterminal row. A fresh display
        # summary is allowed, but it must not write terminal=True or free storage.
        terminal_updates = [call for call in store.sql.call_args_list if "terminal" in call.kwargs]
        self.assertEqual(terminal_updates, [])
        summary_updates = [call for call in store.sql.call_args_list if "body" in call.kwargs]
        self.assertEqual(len(summary_updates), 1)
        summary = json.loads(summary_updates[0].kwargs["body"])
        self.assertEqual(summary["lastStatus"], "completed")
        self.assertIsInstance(summary["observedAt"], str)
        self.assertFalse(task["terminal"])
        store.sql.reset_mock()
        store.effects.return_value[0]["result"] = {"stopEvidence": {"allStopped": True}}
        store._observed_locked(task, "completed", True)
        store.storage.release.assert_called_once_with("task")
        terminal_updates = [call for call in store.sql.call_args_list if "terminal" in call.kwargs]
        self.assertEqual(len(terminal_updates), 1)
        self.assertEqual(terminal_updates[0].kwargs, {"id": "task", "terminal": True})

    def test_summary_observation_cannot_release_storage_or_reopen_terminal_task(self):
        for terminal in (False, True):
            with self.subTest(terminal=terminal):
                store = Store.__new__(Store)
                store.storage = Mock()
                store.transaction = lambda: nullcontext()
                store.event = Mock()
                task = {"id": "task", "owner_id": "alice", "terminal": terminal,
                        "body": {"lastStatus": "running"}}
                store.sql = Mock(side_effect=lambda statement, **params: [task] if statement.startswith("SELECT") else [])
                store.observe_summary(task, "completed")
                store.storage.release.assert_not_called()
                self.assertIs(task["terminal"], terminal)
                self.assertFalse(any("terminal" in call.kwargs for call in store.sql.call_args_list))
                updates = [call for call in store.sql.call_args_list if "body" in call.kwargs]
                self.assertEqual(len(updates), 0 if terminal else 1)
                if terminal:
                    store.event.assert_not_called()
                else:
                    self.assertEqual(json.loads(updates[0].kwargs["body"])["lastStatus"], "completed")

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
        with patch("agent_factory_research.orx_experiment_tools.inspect_orx_experiment", return_value=experiment), \
             patch("agent_factory_research.synthesis_runtime.inspect_synthesis_evidence", return_value=None):
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
        install_runtime(store)
        task = {"id": "original-task", "owner_id": "alice", "plan_id": "plan"}
        with patch("agent_factory_research.orx_experiment_tools.reclaim_orx_experiment", new_callable=AsyncMock) as reclaim:
            await cancel_owned_runtime(store, task)
            reclaim.assert_awaited_once_with(settings, store, "original-task")
            workflow.cancel_task.assert_awaited_once_with("alice", "original-task")

    async def test_uncertain_cleanup_propagates_without_releasing_anything(self):
        store = SimpleNamespace(settings=object(), workflow=SimpleNamespace(cancel_task=AsyncMock()))
        install_runtime(store)
        with patch("agent_factory_research.orx_experiment_tools.reclaim_orx_experiment", new_callable=AsyncMock,
                   side_effect=ValueError("Original binding is uncertain")):
            with self.assertRaises(ValueError):
                await cancel_owned_runtime(store, {"id": "task", "owner_id": "alice", "plan_id": "plan"})
            store.workflow.cancel_task.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()


class ResearchCancellationTransactionTests(unittest.TestCase):
    def test_wait_and_native_cancel_are_published_in_one_transaction(self):
        from agent_factory.lifecycle_observer import FactoryLifecycleObserver
        depth = 0
        observations = []

        @contextmanager
        def transaction():
            nonlocal depth
            depth += 1
            try:
                yield
            finally:
                depth -= 1

        def sql(statement, **params):
            self.assertGreater(depth, 0)
            observations.append((statement, params))
            return [{'id': 'original'}]

        store = SimpleNamespace(transaction=transaction, sql=sql, event=Mock())
        store.effects = lambda _: []
        install_runtime(store)
        observer = FactoryLifecycleObserver(store, None, None, lambda: None)
        observer._mark_cancel({'id': 'original', 'owner_id': 'alice', 'run_id': 'run', 'plan_id': 'plan'}, 'current-authority-ended')
        self.assertEqual(len(observations), 2)
        self.assertIn('af_inference_waits', observations[0][0])
        self.assertEqual(observations[0][1], {'task': 'original'})
        self.assertIn('af_tasks', observations[1][0])
        self.assertEqual(observations[1][1], {'id': 'original', 'owner': 'alice'})
        self.assertEqual(store.event.call_count, 2)
        self.assertEqual(depth, 0)
