"""Offline process profile boundaries; no process launch, PostgreSQL or provider."""
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
import unittest
from unittest.mock import AsyncMock, Mock

from agno.models.message import Message
from agno.run import RunContext

from agent_factory.process_runtime_profile import (APPLICATION_ID, MODEL_ID, PERMISSION,
    TOOL_NAME, ProcessFixtureModel, process_settings, publish_process_application, registrations)


class ProcessProfile(unittest.IsolatedAsyncioTestCase):
    def context(self) -> Any:
        run = RunContext(user_id="alice", session_id="session-1", run_id="run-1")
        return SimpleNamespace(spec={"config": {"targetRef": "reviewed-target"}}, run_context=run,
            settings=SimpleNamespace(demo=True), plan={"ownerId": "alice", "application": APPLICATION_ID,
                "applicationRef": {"id": APPLICATION_ID}, "mode": "controlled-fixture", "tools": [TOOL_NAME],
                "capabilities": [PERMISSION]}, store=SimpleNamespace(authorize_tool=Mock(),
                process_runtime=SimpleNamespace(run=AsyncMock(return_value={"leaseId": "original-lease", "receiptId": "original-receipt"}))))

    async def test_no_argument_tool_checks_authority_and_preserves_service_receipt(self):
        context = self.context()
        entry = next(e for e in registrations(target_ref="reviewed-target") if e.kind == "tool")
        function = entry.factory(context)
        result = json.loads(await function.entrypoint(run_context=context.run_context))
        self.assertEqual(result, {"leaseId": "original-lease", "receiptId": "original-receipt"})
        context.store.authorize_tool.assert_called_once_with(context.run_context, TOOL_NAME)
        context.store.process_runtime.run.assert_awaited_once_with(context.run_context, {"targetRef": "reviewed-target"})
        self.assertEqual(entry.permissions, ("compute:local",))
        self.assertIsNone(entry.connection_kind)
        with self.assertRaises((TypeError, ValueError)):
            await function.entrypoint(run_context=context.run_context, argv=["unapproved"])

    async def test_foreign_context_and_revocation_prevent_service_call(self):
        for foreign in [RunContext(user_id="bob", session_id="session-1", run_id="run-1"),
                        RunContext(user_id="alice", session_id="other", run_id="run-1"),
                        RunContext(user_id="alice", session_id="session-1", run_id="other")]:
            context = self.context()
            function = registrations(target_ref="reviewed-target")[0].factory(context)
            with self.assertRaisesRegex(ValueError, "PROCESS_TOOL_CONTEXT_INVALID"):
                await function.entrypoint(run_context=foreign)
            context.store.process_runtime.run.assert_not_awaited()
        context = self.context()
        context.store.authorize_tool.side_effect = ValueError("revoked")
        function = registrations(target_ref="reviewed-target")[0].factory(context)
        with self.assertRaisesRegex(ValueError, "revoked"):
            await function.entrypoint(run_context=context.run_context)
        context.store.process_runtime.run.assert_not_awaited()

    def test_exact_inert_target_pin_and_environment(self):
        entries = registrations(target_ref="reviewed-target")
        self.assertEqual([e.kind for e in entries], ["tool", "environment"])
        self.assertTrue(all(not e.demo_only for e in entries))
        for entry in entries:
            assert entry.validator is not None
            entry.validator({"targetRef": "reviewed-target"})
            for value in [{}, {"targetRef": "other"}, {"targetRef": "reviewed-target", "argv": ["anything"]}]:
                with self.assertRaises(ValueError):
                    entry.validator(value)
        limits = entries[1].factory(self.context())
        self.assertEqual((limits.runtime_id, limits.timeout_seconds, limits.output_bytes, limits.memory_bytes),
                         ("bounded-process-v1", 5, 65536, 128 * 1024 * 1024))
        for invalid in ["../path", "https://host", "x"*121, True]:
            with self.assertRaises(ValueError):
                registrations(target_ref=invalid)

    def test_fixture_is_explicit_demo_scoped_and_no_provider(self):
        entry = next(e for e in registrations(target_ref="reviewed-target", include_fixture_model=True) if e.kind == "model")
        self.assertTrue(entry.demo_only)
        context = self.context()
        model = entry.factory(context)
        self.assertIsInstance(model, ProcessFixtureModel)
        self.assertEqual(model.id, MODEL_ID)
        response = model.invoke([Message(role="user", content="run")])
        self.assertEqual(response.tool_calls[0]["function"], {"name": TOOL_NAME, "arguments": "{}"})
        response = model.invoke([Message(role="tool", tool_name=TOOL_NAME, content="receipt")])
        self.assertEqual(json.loads(response.content)["modelExecution"], "controlled-fixture")
        for changes in [{"mode": "production"}, {"ownerId": "bob"}, {"delegation": {"parent": "other"}}]:
            modified = self.context()
            modified.plan.update(changes)
            with self.assertRaises(ValueError):
                entry.factory(modified)
        context.settings.demo = False
        with self.assertRaises(ValueError):
            entry.factory(context)

    def test_explicit_fixture_settings(self):
        settings = process_settings(db_url="postgresql://synthetic", workspace=Path("/tmp/synthetic-process-profile"),
            target_ref="reviewed-target", remote_targets={"reviewed-target": object()})
        self.assertEqual(settings.runtime_tool_contract, "bounded-process-v1")
        self.assertEqual(settings.temporary_policy, "admin-review")
        self.assertEqual(settings.usage_pricing[0].local_model_type, ProcessFixtureModel)

    def test_publication_requires_distinct_operator_review(self):
        auth, governance, applications = Mock(), Mock(), Mock()
        governance.create_draft.side_effect = lambda author, definition, key: {**definition, "version": 1, "sha256": "a"*64}
        governance.request_publication.return_value = {"id": "review"}
        applications.create_draft.side_effect = lambda author, definition, key: {**definition, "version": 1, "sha256": "b"*64}
        applications.request_publication.return_value = {"id": "app-review"}
        state = {"auth": auth, "material_governance": governance, "applications": applications}
        with self.assertRaises(ValueError):
            publish_process_application(state, target_ref="reviewed-target", author="admin", reviewer="admin")
        auth.require.assert_not_called()
        result = publish_process_application(state, target_ref="reviewed-target", author="author", reviewer="reviewer")
        mode = result["modes"]["controlled-fixture"]
        self.assertEqual(mode["connectionRequirements"], [])
        self.assertEqual(mode["toolOrder"], [TOOL_NAME])
        self.assertEqual(len(mode["materialRefs"]), 4)
        self.assertEqual(governance.decide_publication.call_count, 4)


if __name__ == "__main__":
    unittest.main()
