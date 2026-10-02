"""Real native Agno loops; authority persistence/provider output are fixtures.

No provider network, credentials, deployment or resource allocation is exercised.
Concurrency uses one executor and two native persisted SQLite sessions. Fixed
experiment tests spawn the existing allowlisted local synthetic subprocess only.
"""
import asyncio
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from agno.db.sqlite import SqliteDb
from agno.exceptions import InputCheckError
from agno.models.response import ModelResponse
from agno.run import RunContext
from agno.run.base import RunStatus
from fastapi import HTTPException

from agent_factory.demo_model import DemoModel
from agent_factory.execution_bindings import KnowledgeContext, default_bindings
from agent_factory.runtime import build_runtime
from agent_factory.store import digest
from test_runtime_contract import ContractStore, attach_fixture_bindings


class MultiPlanStore(ContractStore):
    def __init__(self):
        super().__init__(application="checksum")
        self.plans = {}
        self.model_revoked = False

    def bind_run(self, context):
        plan = self.plans[context.session_state["factory_envelope"]["plan_ref"]]
        if context.user_id != plan["ownerId"]:
            raise InputCheckError("Fixture owner mismatch")
        self.bindings.setdefault(context.run_id, copy.deepcopy(plan))
        self.tasks[context.session_id] = {"id": context.session_id, "owner_id": context.user_id,
            "plan_id": plan["id"], "request_id": "fixture-" + context.session_id,
            "run_id": context.run_id, "cancel_requested": False}
        return self.resolve_run(context)

    def require_plan_execution(self, owner, plan, *, run_context=None):
        if self.model_revoked or owner != plan["ownerId"]:
            raise PermissionError("Controlled current model authority was revoked")


class ChoiceModel(DemoModel):
    def __init__(self, label, records, barrier=None):
        super().__init__(id=label)
        self.records, self.barrier = records, barrier

    async def ainvoke(self, messages, **kwargs):
        if self.barrier:
            await asyncio.wait_for(self.barrier.wait(), 5)
        content = "\n".join(str(message.content) for message in messages)
        self.records.append((self.id, content))
        return ModelResponse(role="assistant", content=json.dumps({"selected": self.id, "evidenceKind": "controlled-adapter"}))


    async def ainvoke_stream(self, messages, **kwargs):
        yield await self.ainvoke(messages, **kwargs)


class OpaqueConnections:
    def __init__(self):
        self.handle = SimpleNamespace(value="synthetic-opaque-handle-never-prompt")
        self.available = True
        self.calls = []
        self.pin = {"ref": "fixture-user-connection", "version": 1, "fingerprint": "a" * 64,
                    "kind": "fixture-provider", "revision": "1", "capabilities": ["model:invoke"], "taskId": None}

    def preflight(self, owner, ref, **kwargs):
        self.calls.append((owner, ref, kwargs))
        if not self.available or owner != "test-user" or ref != self.pin["ref"]:
            raise HTTPException(409, "Controlled exact user connection unavailable")
        for argument, field in (("expected_version", "version"), ("expected_revision", "revision"),
                                ("expected_fingerprint", "fingerprint"), ("expected_kind", "kind")):
            if kwargs[argument] != self.pin[field]:
                raise HTTPException(409, "Controlled exact connection pin mismatch")
        return copy.deepcopy(self.pin)

    def resolve(self, owner, ref, **kwargs):
        self.preflight(owner, ref, **kwargs)
        return self.handle


class ExecutionBindingRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.settings = SimpleNamespace(demo=True, runtime_directory=Path(self.directory.name) / "runtime",
            max_tool_calls=8, experiment_timeout_seconds=5, experiment_output_bytes=65536)
        self.store = MultiPlanStore()
        self.db = SqliteDb(db_file=str(Path(self.directory.name) / "native.sqlite"), id="material-binding-fixture")
        self.registry = default_bindings(self.settings, self.store)
        self.store.execution_bindings = self.registry

    async def asyncTearDown(self):
        self.db.db_engine.dispose()
        self.directory.cleanup()

    def material(self, identifier, kind, adapter, *, content="Controlled original fixture", config=None, permissions=()):
        value = {"id": identifier, "version": 1, "kind": kind, "content": content, "permissions": list(permissions),
                 "runtimeBinding": {"adapterId": adapter, "revision": "1", "config": config or {}}}
        value["sha256"] = digest(value)
        return value

    def plan(self, identifier, model_adapter="local-synthetic-model-v1", *, owner="test-user", connection=None, knowledge=None,
             tool_adapter="native-checksum-v1", environment=None):
        materials = [self.material(identifier + "-model", "model", model_adapter,
                                  config={"connectionName": "provider"} if connection else {}),
                     self.material(identifier + "-environment", "environment", "local-bounded-environment-v1", config=environment),
                     self.material(identifier + "-tool", "tool", tool_adapter, permissions=("checksum:read",))]
        if knowledge is not None:
            materials.append(self.material(identifier + "-knowledge", "knowledge", "fixture-inline-knowledge-v1", content=knowledge))
        plan = {"id": identifier, "ownerId": owner, "application": "arbitrary-fixture-application", "mode": "arbitrary-approved-mode",
                "normalizedGoal": "Controlled exact model selection", "instructions": ["Original controlled native fixture"],
                "tools": ["checksum"], "config": {"toolOrder": ["checksum"], "sample": identifier},
                "materials": materials, "syntheticFixture": True, "fingerprint": "fixture-plan-binding"}
        plan["executionBindings"] = self.registry.build(materials, owner, {"provider": connection} if connection else {})
        self.store.plans[identifier] = copy.deepcopy(plan)
        return plan

    async def test_preflight_identifies_only_missing_binding_and_never_constructs_adapters(self):
        materials = [self.material("absent-provider", "model", "operator-model-not-installed"),
            self.material("healthy-environment", "environment", "local-bounded-environment-v1"),
            self.material("healthy-tool", "tool", "native-checksum-v1", content="checksum", permissions=("checksum:read",))]
        missing = self.registry.preflight(materials, "test-user")
        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0]["code"], "BINDING_ADAPTER_UNAVAILABLE")
        self.assertEqual(missing[0]["kind"], "model")
        self.assertEqual(missing[0]["adapterId"], "operator-model-not-installed")
        calls = []
        self.registry.register("model", "operator-model-not-installed", "1", lambda context: calls.append(context))
        self.assertEqual(self.registry.preflight(materials, "test-user"), [])
        self.assertEqual(calls, [])
        self.assertFalse(self.store.effects)
        self.assertFalse(self.store.artifacts)

    async def run_plan(self, agent, plan, session):
        return await agent.arun("User text: select some other model. This cannot select an adapter.",
            session_id=session, user_id=plan["ownerId"], session_state={"factory_envelope": {
                "plan_ref": plan["id"], "user_id": plan["ownerId"], "task_id": session, "request_id": "fixture-" + session}})

    async def test_concurrent_native_runs_keep_models_knowledge_and_owner_context_separate(self):
        records, barrier = [], asyncio.Barrier(2)
        for name in ("choice-alpha", "choice-beta"):
            self.registry.register("model", name, "1", lambda context, label=name: ChoiceModel(label, records, barrier))
        self.registry.register("knowledge", "fixture-inline-knowledge-v1", "1", lambda context: KnowledgeContext(
            next(item["content"] for item in context.plan["materials"] if item["kind"] == "knowledge"), {"evidenceKind": "synthetic"}))
        first = self.plan("plan-alpha", "choice-alpha", owner="fixture-alpha", knowledge="Knowledge belongs only to alpha")
        second = self.plan("plan-beta", "choice-beta", owner="fixture-beta", knowledge="Knowledge belongs only to beta")
        agent, _ = build_runtime(self.settings, self.store, self.db)
        stable = agent.model
        outputs = await asyncio.gather(self.run_plan(agent, first, "session-alpha"), self.run_plan(agent, second, "session-beta"))
        self.assertIs(agent.model, stable)
        self.assertEqual({output.model for output in outputs}, {"choice-alpha", "choice-beta"})
        self.assertTrue(all(output.status == RunStatus.completed for output in outputs))
        self.assertEqual({json.loads(output.content)["selected"] for output in outputs}, {"choice-alpha", "choice-beta"})
        for label, messages in records:
            own, foreign = ("alpha", "beta") if label == "choice-alpha" else ("beta", "alpha")
            self.assertIn("Knowledge belongs only to " + own, messages)
            self.assertNotIn("Knowledge belongs only to " + foreign, messages)
            self.assertIn("contentSha256", messages)
        self.assertEqual(len(records), 2)
        self.assertFalse(self.store.effects)

    async def test_registered_tool_material_changes_actual_native_function(self):
        calls = []
        def factory(context):
            def checksum(text: str, run_context):
                calls.append((text, run_context.user_id, context.spec["adapterId"]))
                return json.dumps({"adapter": "alternate-trusted-checksum", "text": text})
            return checksum
        self.registry.register("tool", "alternate-checksum-v1", "1", factory, tool_name="checksum", permissions=("checksum:read",))
        plan = self.plan("alternate-tool", tool_adapter="alternate-checksum-v1")
        agent, _ = build_runtime(self.settings, self.store, self.db)
        output = await self.run_plan(agent, plan, "alternate-tool-session")
        self.assertEqual(output.status, RunStatus.completed)
        self.assertEqual(calls, [("alternate-tool", "test-user", "alternate-checksum-v1")])
        self.assertEqual(json.loads(output.content)["results"]["checksum"]["adapter"], "alternate-trusted-checksum")
        self.assertFalse(self.store.artifacts)

    async def test_each_provider_turn_rechecks_current_authority_after_actual_native_tool(self):
        invocations = []
        class CountingModel(DemoModel):
            async def ainvoke(self, messages, **kwargs):
                invocations.append("invoke")
                return await super().ainvoke(messages, **kwargs)
        self.registry.register("model", "guarded-model-v1", "1", lambda context: CountingModel())
        def factory(context):
            def checksum(text: str, run_context):
                self.store.model_revoked = True
                return json.dumps({"computed": text})
            return checksum
        self.registry.register("tool", "revoking-checksum-v1", "1", factory, tool_name="checksum", permissions=("checksum:read",))
        plan = self.plan("current-model-guard", "guarded-model-v1", tool_adapter="revoking-checksum-v1")
        agent, _ = build_runtime(self.settings, self.store, self.db)
        output = await self.run_plan(agent, plan, "current-model-guard-session")
        self.assertEqual(output.status, RunStatus.error)
        self.assertEqual(invocations, ["invoke"])
        self.assertFalse(self.store.effects)
        self.assertFalse(self.store.artifacts)

    async def test_authority_revoked_while_native_provider_waits_denies_its_final_completion(self):
        records, started, release = [], asyncio.Event(), asyncio.Event()
        class WaitingModel(ChoiceModel):
            async def ainvoke(self, messages, **kwargs):
                started.set()
                await asyncio.wait_for(release.wait(), 5)
                return await super().ainvoke(messages, **kwargs)
        self.registry.register("model", "inflight-controlled-model-v1", "1", lambda context: WaitingModel("inflight-controlled", records))
        plan = self.plan("inflight-authority", "inflight-controlled-model-v1")
        agent, _ = build_runtime(self.settings, self.store, self.db)
        pending = asyncio.create_task(self.run_plan(agent, plan, "inflight-authority-session"))
        await asyncio.wait_for(started.wait(), 5)
        self.store.model_revoked = True
        release.set()
        output = await asyncio.wait_for(pending, 5)
        self.assertEqual(output.status, RunStatus.error)
        self.assertIn("authority was revoked", str(output.content))
        self.assertEqual(len(records), 1)
        saved = self.db.get_session("inflight-authority-session", user_id="test-user")
        self.assertEqual(saved.runs[0].status, RunStatus.error)
        self.assertFalse(self.store.effects)
        self.assertFalse(self.store.artifacts)

    async def test_unavailable_forged_and_unadopted_bindings_have_no_demo_fallback(self):
        records = []
        self.registry.register("model", "declared-model-v1", "1", lambda context: ChoiceModel("declared", records))
        plan = self.plan("unavailable", "declared-model-v1")
        self.registry.withdraw("model", "declared-model-v1", "1")
        agent, _ = build_runtime(self.settings, self.store, self.db)
        output = await self.run_plan(agent, plan, "unavailable-session")
        self.assertEqual(output.status, RunStatus.error)
        self.assertEqual(records, [])
        legitimate = self.plan("forged")
        forged = copy.deepcopy(legitimate)
        forged["executionBindings"]["model"]["adapterId"] = "another-installed-provider"
        forged["executionBindings"]["sha256"] = digest({key: value for key, value in forged["executionBindings"].items() if key != "sha256"})
        self.registry.register("model", "another-installed-provider", "1", lambda context: ChoiceModel("unwanted", records))
        with self.assertRaises(HTTPException):
            self.registry.inspect(forged)
        old = copy.deepcopy(legitimate); old.pop("executionBindings")
        with self.assertRaises(HTTPException) as unadopted:
            self.registry.inspect(old)
        self.assertIn("LEGACY_PROOF_REQUIRED", unadopted.exception.detail)
        self.assertFalse(records)
        self.assertFalse(self.store.effects)

    async def test_opaque_connection_pin_rechecks_and_never_enters_model_messages(self):
        connections, records, handles = OpaqueConnections(), [], []
        self.registry.connections = connections
        def factory(context):
            handles.append(context.connection)
            return ChoiceModel("connection-model", records)
        self.registry.register("model", "connection-model-v1", "1", factory, connection_kind="fixture-provider",
                               required_capabilities=("model:invoke",))
        plan = self.plan("connection-plan", "connection-model-v1", connection=connections.pin)
        agent, _ = build_runtime(self.settings, self.store, self.db)
        output = await self.run_plan(agent, plan, "connection-session")
        self.assertEqual(output.status, RunStatus.completed)
        self.assertEqual(handles, [connections.handle])
        self.assertNotIn(connections.handle.value, records[0][1])
        self.assertTrue(any(call[2]["task_id"] == "connection-session" for call in connections.calls))
        connections.available = False
        denied = await self.run_plan(agent, plan, "connection-denied-session")
        self.assertEqual(denied.status, RunStatus.error)
        self.assertEqual(len(records), 1)
        self.assertFalse(self.store.effects)

    async def test_retained_tool_rechecks_owner_current_authority_and_exact_run_before_direct_call(self):
        calls = []
        def factory(context):
            def checksum(text: str, run_context):
                calls.append((text, run_context.session_id))
                return json.dumps({"selected": "guarded-direct-tool", "text": text})
            return checksum
        self.registry.register("tool", "guarded-direct-checksum-v1", "1", factory,
            tool_name="checksum", permissions=("checksum:read",))
        plan = self.plan("retained-direct", tool_adapter="guarded-direct-checksum-v1")
        agent, _ = build_runtime(self.settings, self.store, self.db)
        output = await self.run_plan(agent, plan, "retained-session")
        self.assertEqual(output.status, RunStatus.completed)
        context = RunContext(run_id=output.run_id, session_id="retained-session", user_id="test-user", session_state={})
        selected = self.registry.tools_for(plan, context)[0]
        self.assertEqual(json.loads(selected("explicit direct input", context))["selected"], "guarded-direct-tool")
        original_calls = list(calls)
        wrong = RunContext(run_id=output.run_id, session_id="another-session", user_id="another-owner", session_state={})
        with self.assertRaises(HTTPException) as identity:
            selected("wrong binding", wrong)
        self.assertEqual(identity.exception.status_code, 403)
        self.store.model_revoked = True
        with self.assertRaises(PermissionError):
            selected("current authority revoked", context)
        self.assertEqual(calls, original_calls)
        self.assertFalse(self.store.effects)
        self.assertFalse(self.store.artifacts)

    async def test_shared_model_factory_is_rejected_before_a_second_native_provider_response(self):
        records = []
        shared = ChoiceModel("wrongly-shared-controlled-model", records)
        self.registry.register("model", "incorrect-shared-model-v1", "1", lambda context: shared)
        plan = self.plan("shared-model", "incorrect-shared-model-v1")
        agent, _ = build_runtime(self.settings, self.store, self.db)
        first = await self.run_plan(agent, plan, "shared-model-first")
        second = await self.run_plan(agent, plan, "shared-model-second")
        self.assertEqual(first.status, RunStatus.completed)
        self.assertEqual(second.status, RunStatus.error)
        self.assertIn("separate instances", str(second.content))
        self.assertEqual(len(records), 1)
        self.assertFalse(self.store.effects)

    async def test_streamed_native_response_uses_selected_adapter_and_persists_actual_model(self):
        records = []
        self.registry.register("model", "stream-selected-model-v1", "1", lambda context: ChoiceModel("stream-selected", records))
        plan = self.plan("stream-plan", "stream-selected-model-v1")
        agent, _ = build_runtime(self.settings, self.store, self.db)
        events = [event async for event in agent.arun("controlled streamed native response", stream=True,
            stream_events=True, session_id="stream-session", user_id=plan["ownerId"], session_state={"factory_envelope": {
                "plan_ref": plan["id"], "user_id": plan["ownerId"], "task_id": "stream-session", "request_id": "fixture-stream-session"}})]
        complete = next(event for event in events if event.event == "RunCompleted")
        self.assertEqual(json.loads(complete.content)["selected"], "stream-selected")
        saved = self.db.get_session("stream-session", user_id="test-user")
        self.assertIsNotNone(saved)
        self.assertEqual(saved.runs[0].model, "stream-selected")
        self.assertEqual(saved.runs[0].status, RunStatus.completed)
        self.assertEqual(len(records), 1)
        self.assertFalse(self.store.effects)
        self.assertFalse(self.store.artifacts)

    async def test_binding_recheck_uses_exact_persisted_identity_for_trusted_state_free_context(self):
        plan = self.plan("trusted-internal-context")
        agent, _ = build_runtime(self.settings, self.store, self.db)
        output = await self.run_plan(agent, plan, "trusted-internal-session")
        context = SimpleNamespace(run_id=output.run_id, session_id="trusted-internal-session", user_id="test-user")
        self.assertEqual(self.registry.recheck(plan, context)["sha256"], plan["executionBindings"]["sha256"])
        context.run_id = "unrelated-native-run"
        with self.assertRaises(HTTPException) as wrong_run:
            self.registry.recheck(plan, context)
        self.assertEqual(wrong_run.exception.status_code, 403)
        context.run_id = output.run_id
        context.session_state = {"factory_envelope": {"plan_ref": "another-plan"}}
        with self.assertRaises(HTTPException) as wrong_envelope:
            self.registry.recheck(plan, context)
        self.assertEqual(wrong_envelope.exception.status_code, 403)

    async def test_registry_descriptors_are_redacted_mode_specific_and_do_not_construct_adapters(self):
        constructed = []
        def factory(context):
            constructed.append(context.connection)
            raise AssertionError("Metadata must not construct a provider")
        self.registry.register("model", "metadata-only-controlled-v1", "1", factory,
            connection_kind="model", required_capabilities=("model:invoke",), permissions=("model:invoke",))
        self.registry.register("model", "metadata-synthetic-v1", "1", factory, demo_only=True)
        self.settings.demo = False
        descriptors = self.registry.describe()
        self.assertEqual(descriptors, self.registry.describe())
        fields = {"kind", "adapterId", "revision", "toolName", "connectionKind", "requiredCapabilities", "permissions", "demoOnly", "availableForMode"}
        self.assertTrue(all(set(item) == fields for item in descriptors))
        provider = next(item for item in descriptors if item["adapterId"] == "metadata-only-controlled-v1")
        synthetic = next(item for item in descriptors if item["adapterId"] == "metadata-synthetic-v1")
        self.assertEqual(provider["requiredCapabilities"], ["model:invoke"])
        self.assertTrue(provider["availableForMode"])
        self.assertFalse(synthetic["availableForMode"])
        self.assertFalse(constructed)
        self.registry.withdraw("model", "metadata-only-controlled-v1", "1")
        self.assertFalse(any(item["adapterId"] == "metadata-only-controlled-v1" for item in self.registry.describe()))

    async def test_selected_environment_limits_actual_fixed_process_and_retains_unknown_outcome(self):
        store = ContractStore(mode="experiment", config={"experimentDurationSeconds": 3})
        attach_fixture_bindings(self.settings, store, store.plan)
        environment = next(item for item in store.plan["materials"] if item["kind"] == "environment")
        environment["runtimeBinding"] = {"adapterId": "local-bounded-environment-v1", "revision": "1",
            "config": {"runtimeId": "selected-tight-fixture", "timeoutSeconds": .15, "outputBytes": 4096,
                       "memoryBytes": 64 * 1024 * 1024, "processLimit": 1, "cpuPercent": 5}}
        environment["sha256"] = digest({key: value for key, value in environment.items() if key != "sha256"})
        store.plan["executionBindings"] = store.execution_bindings.build(store.plan["materials"], store.plan["ownerId"])
        agent, _ = build_runtime(self.settings, store, self.db)
        initial = await agent.arun("Controlled fixed experiment", user_id="test-user", session_id="environment-session")
        self.assertEqual(initial.status, RunStatus.paused)
        initial.requirements[0].confirm()
        resumed = await agent.acontinue_run(run_id=initial.run_id, session_id="environment-session", user_id="test-user", requirements=initial.requirements)
        self.assertEqual(json.loads(resumed.content)["status"], "failed")
        started = next(event for event in store.events if event["type"] == "compute_started")["data"]
        self.assertEqual(started["runtimeId"], "selected-tight-fixture")
        self.assertEqual(started["wallClockLimitSeconds"], .15)
        self.assertEqual(started["memoryLimitBytes"], 64 * 1024 * 1024)
        self.assertEqual(started["processLimit"], 1)
        self.assertEqual(started["outputLimitBytes"], 4096)
        stopped = next(event for event in store.events if event["type"] == "compute_stopped")["data"]
        self.assertTrue(stopped["cleanupComplete"])
        self.assertEqual(store.effects[(initial.run_id, "experiment:bounded-sort-v1")]["status"], "unknown")
        self.assertFalse(any(artifact["name"] == "synthetic-experiment.json" for artifact in store.artifacts))


if __name__ == "__main__":
    unittest.main()
