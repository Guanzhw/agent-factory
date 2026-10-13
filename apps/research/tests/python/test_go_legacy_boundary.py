"""Offline shared-model dependency boundary and historical replay safeguards."""
import builtins
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from agno.exceptions import InputCheckError
from agno.run.agent import RunOutput
from fastapi import HTTPException

from agent_factory.execution_bindings import ExecutionBindings
from agent_factory.go_legacy import APPLICATION_ID, MODEL_ADAPTER_IDS, is_go_plan
from agent_factory.model_dispatch import DelegatingModel
from agent_factory.store import digest
from agent_factory_research.model_compatibility import ResearchDelegatingModel
from agent_factory_research.synthetic_runtime import ResearchExecutionBindings


HEAVY_MODULES = {"go_development", "go_live", "go_project_campaign", "opencode_go"}


def forbid_campaign_imports(name, globals=None, locals=None, fromlist=(), level=0):
    if name.rsplit(".", 1)[-1] in HEAVY_MODULES:
        raise AssertionError("Ordinary model path imported a historical campaign")
    return ORIGINAL_IMPORT(name, globals, locals, fromlist, level)


ORIGINAL_IMPORT = builtins.__import__


class GoLegacyBoundaryTests(unittest.TestCase):
    def fixture(self, adapter="owner-chat-completions-v1", *, bindings_type=ResearchExecutionBindings):
        settings = SimpleNamespace(demo=False, fee_management_enabled=True, platform_paid_models_enabled=True)
        task = {"id": "synthetic-session", "owner_id": "alice", "run_id": "synthetic-run",
                "plan_id": "synthetic-plan", "request_id": "synthetic-request", "cancel_requested": False}
        store = SimpleNamespace(task=Mock(return_value=task), cancellation_requested=Mock(return_value=False),
            require_plan_execution=Mock(), has_failures=Mock(return_value=False), event=Mock())
        bindings = bindings_type(settings, store)
        materials = []
        for kind, identifier in (("model", adapter), ("environment", "synthetic-environment-v1")):
            bindings.register(kind, identifier, "1", Mock(side_effect=AssertionError("No model construction")))
            material = {"id": "synthetic-" + kind, "version": 1, "kind": kind,
                        "runtimeBinding": {"adapterId": identifier, "revision": "1", "config": {}}}
            material["sha256"] = digest(material)
            materials.append(material)
        plan = {"id": task["plan_id"], "ownerId": "alice", "application": "synthetic-application",
                "materials": materials, "tools": [], "executionBindings": bindings.build(materials, "alice")}
        store.resolve_run = Mock(return_value=plan)
        store.plan = Mock(return_value=plan)
        response = RunOutput(run_id=task["run_id"], session_id=task["id"], user_id="alice")
        return bindings, plan, response

    def test_shared_module_imports_do_not_load_campaigns(self):
        source = "\n".join([
            "import sys",
            "from agent_factory import go_legacy, billing_mode, model_dispatch, execution_bindings",
            "blocked = " + repr(HEAVY_MODULES),
            "assert not [name for name in sys.modules if name.startswith('agent_factory.') and name.rsplit('.', 1)[-1] in blocked]",
            "assert not [name for name in sys.modules if name == 'agent_factory_research' or name.startswith('agent_factory_research.')]",
        ])
        result = subprocess.run([sys.executable, "-c", source], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_ordinary_recheck_and_dispatch_do_not_import_campaigns(self):
        with patch("builtins.__import__", side_effect=forbid_campaign_imports):
            bindings, plan, response = self.fixture()
            self.assertEqual(bindings.recheck(plan), plan["executionBindings"])
            selected = ResearchDelegatingModel(bindings)._prepare_selection((), {"run_response": response})
            self.assertEqual(selected[-1].spec["adapterId"], "owner-chat-completions-v1")
            self.assertFalse(ResearchDelegatingModel(bindings)._stop_development_replay(response))
        bindings.store.has_failures.assert_not_called()
        bindings.store.require_plan_execution.assert_called_once()

    def test_core_ordinary_recheck_and_dispatch_do_not_import_research(self):
        def forbid_research_and_campaigns(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "agent_factory_research" or name.startswith("agent_factory_research.") or name.rsplit(".", 1)[-1] in {
                "inference_wait", "synthesis_runtime", "comparison_workflow",
            }:
                raise AssertionError("Core model path imported a research application")
            return forbid_campaign_imports(name, globals, locals, fromlist, level)

        with patch("builtins.__import__", side_effect=forbid_research_and_campaigns):
            bindings, plan, response = self.fixture(bindings_type=ExecutionBindings)
            self.assertEqual(bindings.recheck(plan), plan["executionBindings"])
            selected = DelegatingModel(bindings)._prepare_selection((), {"run_response": response})
            self.assertEqual(selected[-1].spec["adapterId"], "owner-chat-completions-v1")
        bindings.store.has_failures.assert_not_called()
        bindings.store.require_plan_execution.assert_called_once()

    def test_legacy_preflight_remains_after_integrity_checks_with_original_plan(self):
        bindings, plan, _ = self.fixture(MODEL_ADAPTER_IDS["gpt-6-luna"])
        with patch("agent_factory.go_development.preflight_plan", side_effect=HTTPException(409, "synthetic-denial")) as preflight:
            with self.assertRaises(HTTPException) as denied:
                bindings.recheck(plan)
            self.assertEqual(denied.exception.detail, "synthetic-denial")
            preflight.assert_called_once_with(bindings.settings, plan, bindings.connections, None)
            preflight.reset_mock()
            plan["executionBindings"]["sha256"] = "changed"
            with self.assertRaises(HTTPException) as integrity:
                bindings.recheck(plan)
            self.assertTrue(integrity.exception.detail.startswith("BINDING_MANIFEST_INTEGRITY"))
            preflight.assert_not_called()

    def test_legacy_failure_still_denies_replay_without_campaign_dependency(self):
        bindings, plan, response = self.fixture(MODEL_ADAPTER_IDS["deepseek-flash"])
        response.model_provider = "opencode-go-development"
        dispatcher = ResearchDelegatingModel(bindings)
        with patch("builtins.__import__", side_effect=forbid_campaign_imports):
            self.assertTrue(dispatcher._stop_development_replay(response))
            bindings.store.event.assert_called_once()
            self.assertEqual(bindings.store.event.call_args.args[3]["code"], "GO_TASK_STOPPED")
            bindings.store.has_failures.return_value = True
            self.assertTrue(dispatcher._stop_development_replay(response))
            self.assertEqual(bindings.store.event.call_count, 1)
            with self.assertRaisesRegex(InputCheckError, "GO_TASK_STOPPED"):
                dispatcher._prepare_selection((), {"run_response": response})
        bindings.store.require_plan_execution.assert_not_called()

    def test_historical_identifiers_and_public_imports_remain_compatible(self):
        from agent_factory import go_development
        self.assertIs(go_development.MODEL_ADAPTER_IDS, MODEL_ADAPTER_IDS)
        self.assertIs(go_development.is_go_plan, is_go_plan)
        self.assertEqual(go_development.APPLICATION_ID, APPLICATION_ID)
        self.assertTrue(is_go_plan({"application": APPLICATION_ID}))
        for identifier in MODEL_ADAPTER_IDS.values():
            self.assertTrue(is_go_plan({"executionBindings": {"model": {"adapterId": identifier}}}))
            self.assertFalse(is_go_plan({"executionBindings": {"model": {"adapterId": identifier + "-other"}}}))
        self.assertFalse(is_go_plan({"executionBindings": {"model": {
            "adapterId": "owner-chat-completions-v1", "config": {"model": "gpt-6-luna"}}}}))


if __name__ == "__main__":
    unittest.main()
