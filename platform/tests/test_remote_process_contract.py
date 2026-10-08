"""Effective receiver bindings and wire vocabulary do not rewrite or grant plans."""
import copy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from fastapi import HTTPException
from pydantic import ValidationError

from agent_factory.plan_policy import tools_for_contract
from agent_factory.process_runtime import ProcessRuntimeService, EFFECT, TOOL
from agent_factory.remote_authority import AuthorityScope


class RemoteProcessContractTests(unittest.TestCase):
    def test_effective_target_uses_original_native_context_without_rewriting_source(self):
        plan = {"id": "receiver-plan", "executionBindings": {"tools": [
            {"toolName": TOOL, "config": {"targetRef": "origin-process"}}]}}
        original = copy.deepcopy(plan)
        task = {"id": "receiver-task", "owner_id": "receiver-alice", "plan_id": "receiver-plan",
                "run_id": "receiver-native", "request_id": "receiver-request"}
        bindings = Mock()
        bindings.manifest.return_value = {"tools": [{"toolName": TOOL, "config": {"targetRef": "receiver-process"}}]}
        store = SimpleNamespace(execution_bindings=bindings, authorize_tool=Mock())
        runtime = ProcessRuntimeService(store, None, None)
        execution = {"nativeRunId": "receiver-native", "effectKey": EFFECT}
        runtime.validate_execution("receiver-alice", task, plan, "receiver-process", execution)
        context = bindings.manifest.call_args.kwargs["context"]
        self.assertEqual((context.user_id, context.session_id, context.run_id),
                         ("receiver-alice", "receiver-task", "receiver-native"))
        self.assertEqual(context.session_state["factory_envelope"]["plan_ref"], "receiver-plan")
        self.assertEqual(plan, original)
        with self.assertRaises(HTTPException):
            runtime.validate_execution("receiver-alice", task, plan, "origin-process", execution)
        bindings.manifest.side_effect = HTTPException(409, "Original receiver proof revoked")
        with self.assertRaises(HTTPException):
            runtime.validate_execution("receiver-alice", task, plan, "receiver-process", execution)
        self.assertEqual(plan, original)

    def test_transport_vocabulary_requires_exact_capability_without_enabling_legacy_tool(self):
        budget = {"toolCalls": 2, "maxDepth": 1, "maxChildren": 1, "experimentSeconds": 5, "outputBytes": 65536}
        scope = AuthorityScope(tools=[TOOL], capabilities=["compute:local"], budget=budget)
        self.assertEqual(scope.tools, [TOOL])
        self.assertNotIn(TOOL, tools_for_contract("legacy-v1"))
        self.assertEqual(tools_for_contract("bounded-process-v1")[TOOL], "compute:local")
        for tools, capabilities in [([TOOL], ["research:read"]), ([TOOL], ["compute:local", "research:read"]),
                                    (["arbitrary_process"], ["compute:local"])]:
            with self.subTest(tools=tools, capabilities=capabilities), self.assertRaises(ValidationError):
                AuthorityScope(tools=tools, capabilities=capabilities, budget=budget)


if __name__ == "__main__":
    unittest.main()
