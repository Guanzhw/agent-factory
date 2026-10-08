"""PostgreSQL reservations and actual Agno provider primitive hooks.

All provider output and prices are controlled original fixtures. No provider
network, real credentials, paid calls, or production grants are involved.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Lock
import time
import unittest
from uuid import uuid4

from agno.db.postgres import PostgresDb
from agno.exceptions import ModelProviderError
from agno.metrics import MessageMetrics
from agno.models.message import Message
from agno.models.response import ModelResponse
from agno.run import RunContext
from agno.run.agent import RunOutput
from fastapi import HTTPException

from agent_factory.auth import AuthService
from agent_factory.config import Settings
from agent_factory.delegation import DelegationService
from agent_factory.demo_model import DemoModel
from agent_factory.execution_bindings import default_bindings
from agent_factory.model_dispatch import DelegatingModel
from agent_factory.runtime import build_runtime
from agent_factory.store import Store, canonical, digest, now
from agent_factory.usage_ledger import PricingRevision, UsageEvidence, UsageLedger, UsagePolicy, native_response_usage
from pg_fixture import IsolatedPostgres


class ControlledModel(DemoModel):
    def __init__(self, records, scenario="success", gate=None, entered=None, after=None):
        super().__init__(id="controlled-ledger-model-v1", provider="controlled-ledger", retries=1, delay_between_retries=0)
        self.records, self.scenario, self.gate, self.entered, self.after = records, scenario, gate, entered, after
        self.calls = 0

    def answer(self):
        self.calls += 1
        self.records.append(self.scenario)
        if self.entered:
            self.entered.set()
        if self.gate and not self.gate.wait(5):
            raise RuntimeError("Controlled provider gate deadline")
        if self.scenario == "retry" and self.calls == 1:
            raise ModelProviderError("Controlled retry without authoritative usage", status_code=503)
        if self.scenario == "unknown":
            return ModelResponse(role="assistant", content="Controlled unknown usage")
        result = ModelResponse(role="assistant", content="Controlled native provider result",
            response_usage=MessageMetrics(input_tokens=3, output_tokens=2, total_tokens=5))
        if self.after:
            self.after()
        return result

    def invoke(self, messages, **kwargs):
        return self.answer()

    async def ainvoke(self, messages, **kwargs):
        return self.answer()

    def invoke_stream(self, messages, **kwargs):
        self.records.append("stream")
        yield ModelResponse(role="assistant", content="controlled partial")
        if self.scenario == "partial":
            raise RuntimeError("Controlled partial stream interruption")
        yield ModelResponse(role="assistant", content="controlled final",
            response_usage=MessageMetrics(input_tokens=3, output_tokens=2, total_tokens=5))

    async def ainvoke_stream(self, messages, **kwargs):
        self.records.append("astream")
        yield ModelResponse(role="assistant", content="controlled partial")
        await asyncio.sleep(0)
        if self.scenario == "partial":
            raise RuntimeError("Controlled partial async stream interruption")
        yield ModelResponse(role="assistant", content="controlled final",
            response_usage=MessageMetrics(input_tokens=3, output_tokens=2, total_tokens=5))


def controlled_request_guard(model, arguments, kwargs, commitment):
    # Fixed actual fixture counts are always input3/output2, with no network or
    # SDK retry. Only Agno's public retry loop may call the primitive again.
    if not isinstance(model, ControlledModel) or commitment["perAttemptInputTokens"] < 3 or commitment["perAttemptOutputTokens"] < 2:
        raise HTTPException(409, "Controlled fixture request exceeds approved bounds")


def price(**changes):
    return replace(PricingRevision("controlled-ledger-model-v1", "1", "controlled-ledger", "controlled-ledger-model-v1",
        "synthetic-prices-v1", input_micros_per_million=1_000_000, output_micros_per_million=2_000_000,
        per_attempt_input_tokens=4, per_attempt_output_tokens=6, usage_reader=native_response_usage,
        request_guard=controlled_request_guard), **changes)


@unittest.skipUnless(os.getenv("FACTORY_TEST_DATABASE_URL"), "Requires disposable loopback PostgreSQL")
class UsageLedgerPostgresTests(unittest.TestCase):
    def setUp(self):
        self.database = IsolatedPostgres(os.environ["FACTORY_TEST_DATABASE_URL"]).__enter__()
        self.addCleanup(self.database.__exit__, None, None, None)
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.settings = Settings(db_url=self.database.url, workspace=Path(self.directory.name), max_user_tasks=100, max_total_tasks=100)
        self.store = Store(self.database.url, self.settings)
        self.addCleanup(self.store.engine.dispose)
        self.db = PostgresDb(db_url=self.database.url, id="controlled-ledger-native-postgres")
        self.addCleanup(self.db.db_engine.dispose)
        self.store.native_db = self.db
        self.auth = AuthService(self.settings, self.db)
        self.auth.initialize_demo()
        self.store.auth = self.auth
        self.records, self.options = [], {}
        self.bindings = default_bindings(self.settings, self.store)
        self.bindings.register("model", "controlled-ledger-model-v1", "1", lambda context: ControlledModel(self.records, **self.options))
        self.store.execution_bindings = self.bindings
        self.policy = UsagePolicy(revision="controlled-usage-policy-v1", task_token_limit=40, task_amount_micros=64,
            user_token_limit=80, user_amount_micros=128)
        self.ledger = UsageLedger(self.store, (price(),), self.policy)
        self.store.usage_ledger = self.ledger

    def set_policy(self, **changes):
        self.policy = replace(self.policy, revision="controlled-usage-policy-v2", **changes)
        self.ledger = UsageLedger(self.store, (price(),), self.policy)
        self.store.usage_ledger = self.ledger

    def material(self, identifier, kind, adapter):
        value = {"id": identifier, "version": 1, "kind": kind, "content": "Original controlled ledger fixture",
            "permissions": [], "runtimeBinding": {"adapterId": adapter, "revision": "1", "config": {}}}
        return {**value, "sha256": digest(value)}

    def plan(self, *, owner="alice", tokens=None, amount=None, extra=None, model_adapter="controlled-ledger-model-v1", legacy=False):
        materials = [self.material("ledger-model", "model", model_adapter),
            self.material("ledger-environment", "environment", "local-bounded-environment-v1")]
        value = {"id": str(uuid4()), "ownerId": owner, "application": "controlled-ledger-fixture", "mode": "direct",
            "normalizedGoal": "Controlled no-network provider accounting", "instructions": ["Original fixture only"],
            "tools": [], "capabilities": [], "materials": materials, "status": "ready", "syntheticFixture": True,
            "config": {}, "budget": {"toolCalls": 8, "maxDepth": 2, "maxChildren": 4, "experimentSeconds": 8, "outputBytes": 65536, "depth": 0},
            "policy": "bounded-synthetic", "createdAt": now(), "executionBindings": self.bindings.build(materials, owner)}
        if extra:
            value.update(extra)
        if not legacy:
            value["usageBudget"] = self.ledger.commitment_for(value, token_limit=tokens, amount_micros=amount)
        value["fingerprint"] = digest(value)
        return self.store.save_plan(value)

    def task(self, plan, *, accepted=True):
        task, _ = self.store.reserve_task(plan, str(uuid4()))
        run = str(uuid4())
        if accepted:
            self.store.accept(task["id"], run)
        envelope = {"plan_ref": plan["id"], "user_id": plan["ownerId"], "task_id": task["id"], "request_id": task["request_id"]}
        context = RunContext(run_id=run, session_id=task["id"], user_id=plan["ownerId"], session_state={"factory_envelope": envelope})
        return self.store.task(task["id"]), context

    def selected(self, context):
        response = RunOutput(run_id=context.run_id, session_id=context.session_id, user_id=context.user_id, session_state=context.session_state)
        return DelegatingModel(self.bindings)._select((), {"run_response": response})

    def invoke(self, model):
        return model.invoke(messages=[Message(role="user", content="Controlled input")])

    def projection(self, task):
        return self.ledger.inspect(task["owner_id"], task["id"])

    def test_01_native_agent_model_response_records_one_actual_attempt(self):
        plan = self.plan()
        task, context = self.task(plan, accepted=False)
        executor, _ = build_runtime(self.settings, self.store, self.db)
        output = executor.run("Controlled native Agent response", session_id=task["id"], user_id="alice", session_state=context.session_state)
        self.assertEqual(output.content, "Controlled native provider result")
        state = self.projection(task)
        self.assertEqual(len(state["attempts"]), 1)
        self.assertEqual(state["attempts"][0]["state"], "SETTLED")
        self.assertEqual(state["scopes"][0]["settledTokens"], 5)
        self.assertEqual(state["scopes"][0]["settledAmountMicros"], 7)
        self.assertEqual(state["scopes"][0]["heldTokens"], 0)
        self.assertEqual(self.store.task(task["id"])["run_id"], output.run_id)

    def test_02_concurrent_actual_provider_admission_enforces_user_ceiling(self):
        self.set_policy(user_token_limit=20, user_amount_micros=32)
        tasks = [self.task(self.plan()) for _ in range(4)]
        gates, entered = Event(), [Event(), Event()]
        count, lock = [0], Lock()
        def factory(context):
            with lock:
                index = count[0]
                count[0] += 1
            return ControlledModel(self.records, gate=gates, entered=entered[index] if index < 2 else None)
        self.bindings._adapters[("model", "controlled-ledger-model-v1", "1")] = replace(
            self.bindings._adapters[("model", "controlled-ledger-model-v1", "1")], factory=factory)
        models = [self.selected(context) for _, context in tasks]
        with ThreadPoolExecutor(max_workers=4) as workers:
            futures = [workers.submit(self.invoke, model) for model in models]
            try:
                deadline = time.monotonic() + 4
                while len(self.records) < 2 and time.monotonic() < deadline:
                    Event().wait(.01)
                self.assertEqual(len(self.records), 2)
                user = next(s for s in self.projection(tasks[0][0])["scopes"] if s["scope"] == "user")
                self.assertEqual(user["heldTokens"], 20)
                self.assertEqual(user["heldAmountMicros"], 32)
                deadline = time.monotonic() + 4
                while sum(f.done() for f in futures) < 2 and time.monotonic() < deadline:
                    Event().wait(.01)
                self.assertEqual(sum(f.done() for f in futures), 2)
            finally:
                gates.set()
            results = []
            for future in futures:
                try:
                    results.append(future.result())
                except HTTPException as denied:
                    self.assertEqual(denied.status_code, 429)
                    results.append("denied")
        self.assertEqual(results.count("denied"), 2)
        self.assertEqual(len(self.records), 2)

    def test_03_retry_is_two_separately_reserved_provider_attempts(self):
        self.options["scenario"] = "retry"
        task, context = self.task(self.plan())
        model = self.selected(context)
        output = model._invoke_with_retry(messages=[Message(role="user", content="Controlled retry")])
        self.assertEqual(output.content, "Controlled native provider result")
        state = self.projection(task)
        self.assertEqual([a["state"] for a in state["attempts"]], ["UNKNOWN", "SETTLED"])
        self.assertEqual(len(self.records), 2)
        self.assertEqual(state["scopes"][0]["heldTokens"], 10)
        self.assertEqual(state["scopes"][0]["settledTokens"], 5)

    def test_04_unknown_retry_hold_blocks_next_actual_attempt(self):
        self.options["scenario"] = "retry"
        task, context = self.task(self.plan(tokens=10, amount=16))
        with self.assertRaises(HTTPException) as denied:
            self.selected(context)._invoke_with_retry(messages=[Message(role="user", content="Bounded retry")])
        self.assertEqual(denied.exception.status_code, 429)
        self.assertEqual(len(self.records), 1)
        self.assertEqual(self.projection(task)["attempts"][0]["state"], "UNKNOWN")

    def test_05_partial_stream_cancellation_holds_then_authoritative_recovery_settles(self):
        self.options["scenario"] = "partial"
        task, context = self.task(self.plan())
        with self.assertRaises(RuntimeError):
            list(self.selected(context).invoke_stream(messages=[Message(role="user", content="Partial stream")]))
        self.store.request_cancel(task["id"])
        state = self.projection(task)
        self.assertTrue(state["hasUnknown"])
        self.assertEqual(state["scopes"][0]["heldAmountMicros"], 16)
        attempt = state["attempts"][0]["id"]
        self.ledger.finish_attempt(attempt, UsageEvidence(3, 2, "controlled-authoritative-recovery"))
        replay = self.ledger.finish_attempt(attempt, UsageEvidence(3, 2, "controlled-authoritative-recovery"))
        self.assertTrue(replay["idempotent"])
        self.assertEqual(self.projection(task)["scopes"][0]["settledAmountMicros"], 7)
        with self.assertRaises(HTTPException):
            self.ledger.finish_attempt(attempt, UsageEvidence(3, 3, "controlled-authoritative-recovery"))

    def test_06_async_and_async_stream_actual_hooks(self):
        task, context = self.task(self.plan())
        async def run():
            response = await self.selected(context).ainvoke(messages=[Message(role="user", content="Async")])
            values = [v async for v in self.selected(context).ainvoke_stream(messages=[Message(role="user", content="Stream")])]
            return response, values
        response, values = asyncio.run(run())
        self.assertEqual(response.content, "Controlled native provider result")
        self.assertEqual(len(values), 2)
        attempts = self.projection(task)["attempts"]
        self.assertEqual([a["state"] for a in attempts], ["SETTLED", "SETTLED"])
        self.assertEqual([a["streaming"] for a in attempts], [False, True])

    def test_07_revocation_after_response_preserves_settlement_and_denies_next_attempt(self):
        self.auth.authorization.define_role("controlled-ledger-denied", [])
        self.options["after"] = lambda: self.db.replace_authz_subject_roles("alice", "controlled-ledger-denied")
        task, context = self.task(self.plan())
        model = self.selected(context)
        with self.assertRaises(HTTPException):
            self.invoke(model)
        state = self.projection(task)
        self.assertEqual(state["attempts"][0]["state"], "SETTLED")
        self.assertEqual(state["scopes"][0]["settledAmountMicros"], 7)
        with self.assertRaises(HTTPException):
            self.invoke(model)
        self.assertEqual(len(self.records), 1)

    def test_08_restart_does_not_release_unknown_reservation_or_user_cap(self):
        self.options["scenario"] = "unknown"
        task, context = self.task(self.plan(tokens=10, amount=16))
        self.invoke(self.selected(context))
        before = self.projection(task)
        restarted = Store(self.database.url, self.settings)
        self.addCleanup(restarted.engine.dispose)
        ledger = UsageLedger(restarted, (price(),), self.policy)
        self.assertEqual(ledger.inspect("alice", task["id"]), before)
        with self.assertRaises(HTTPException):
            ledger.begin_attempt(context, self.store.plan(task["plan_id"]), ControlledModel(self.records))
        self.assertEqual(len(self.records), 1)

    def test_09_pricing_model_currency_and_policy_changes_cannot_reuse_approval(self):
        task, context = self.task(self.plan())
        self.invoke(self.selected(context))
        original = self.projection(task)
        changed = UsageLedger(self.store, (price(revision="synthetic-prices-v2", output_micros_per_million=3_000_000),), self.policy)
        self.store.usage_ledger = changed
        self.assertEqual(changed.inspect("alice", task["id"]), original)
        with self.assertRaises(HTTPException):
            self.invoke(self.selected(context))
        self.assertEqual(len(self.records), 1)
        with self.assertRaises(ValueError):
            UsageLedger(self.store, (price(output_micros_per_million=3_000_000),), self.policy)
        self.store.usage_ledger = self.ledger
        model = self.selected(context)
        model.id = "unapproved-model-v2"
        with self.assertRaises(HTTPException):
            self.invoke(model)
        self.assertEqual(len(self.records), 1)

    def test_10_legacy_zero_migration_preserves_plan_bytes_and_nonlocal_fails(self):
        self.set_policy(task_token_limit=100_000, user_token_limit=1_000_000)
        ledger = UsageLedger(self.store, policy=self.policy)
        self.store.usage_ledger = ledger
        self.ledger = ledger
        plan = self.plan(model_adapter="local-synthetic-model-v1", legacy=True)
        before = self.store.sql("SELECT body,hash FROM af_plans WHERE id=:id", id=plan["id"])[0]
        task, context = self.task(plan)
        self.invoke(self.selected(context))
        after = self.store.sql("SELECT body,hash FROM af_plans WHERE id=:id", id=plan["id"])[0]
        self.assertEqual(after, before)
        self.assertEqual(self.projection(task)["migration"]["sourcePlanSha256"], digest(plan))
        self.assertEqual(self.projection(task)["scopes"][0]["settledAmountMicros"], 0)
        other = self.plan(legacy=True)
        task, context = self.task(other)
        with self.assertRaises(HTTPException):
            self.invoke(self.selected(context))

    def test_11_root_and_all_ancestors_share_actual_postgres_reservations(self):
        service = DelegationService(self.settings, self.store, self.auth, None)
        service.initialize()
        self.store.delegation = service
        root, root_context = self.task(self.plan(tokens=20, amount=32))
        parent_plan = self.plan(extra={"delegation": {"parentTaskId": root["id"], "rootTaskId": root["id"], "depth": 1}})
        parent, parent_context = self.task(parent_plan)
        child_plan = self.plan(extra={"delegation": {"parentTaskId": parent["id"], "rootTaskId": root["id"], "depth": 2}})
        child, child_context = self.task(child_plan)
        for task, parent_task, depth in ((parent, root, 1), (child, parent, 2)):
            self.store.sql("INSERT INTO af_delegation_links VALUES(:owner,:parent,:request,:root,:depth,:fp,:plan,:child,:at)",
                id=str(uuid4()), owner="alice", parent=parent_task["id"], request=str(uuid4()), root=root["id"],
                depth=depth, fp="controlled-original-link", plan=task["plan_id"], child=task["id"], at=now())
        self.options["scenario"] = "unknown"
        self.invoke(self.selected(child_context))
        self.invoke(self.selected(parent_context))
        with self.assertRaises(HTTPException) as exhausted:
            self.invoke(self.selected(root_context))
        self.assertEqual(exhausted.exception.status_code, 429)
        state = self.projection(child)
        self.assertEqual([(s["scope"], s["heldTokens"]) for s in state["scopes"]], [("task", 10), ("ancestor", 20), ("root", 20), ("user", 20)])
        self.assertEqual(len(self.records), 2)

    def test_12_provider_admission_never_runs_inside_uncommitted_outer_transaction(self):
        task, context = self.task(self.plan())
        model = self.selected(context)
        with self.store.transaction():
            with self.assertRaises(RuntimeError):
                self.invoke(model)
        self.assertEqual(self.records, [])
        self.assertEqual(self.projection(task)["attempts"], [])

    def test_13_actual_usage_exceeding_quote_is_charged_and_blocks_further_work(self):
        task, context = self.task(self.plan(tokens=10, amount=16))
        identity = self.ledger.begin_attempt(context, self.store.plan(task["plan_id"]), ControlledModel(self.records))
        self.ledger.finish_attempt(identity, UsageEvidence(12, 3, "controlled-overage-evidence"))
        state = self.projection(task)
        self.assertEqual(state["scopes"][0]["settledTokens"], 15)
        self.assertEqual(state["scopes"][0]["settledAmountMicros"], 18)
        with self.assertRaises(HTTPException):
            self.invoke(self.selected(context))

    def test_14_remote_actual_model_accounting_unknown_then_positive_stop_never_resets_origin_cap(self):
        source, source_context = self.task(self.plan(tokens=20, amount=32))
        receiver_plan = self.plan(tokens=20, amount=32, extra={"remoteHandoff": {"originRef": "controlled-origin", "originTaskId": source["id"]}})
        receiver, context = self.task(receiver_plan)
        quote = self.ledger.prepare_remote_commitment(receiver_plan, receiver_plan["executionBindings"])
        grant = self.ledger.allocate_remote("alice", source["id"], str(uuid4()), origin_ref="controlled-origin", target_ref="controlled-target",
            receiver_owner="alice", receiver_task_id=receiver["id"], receiver_plan_sha256=digest(receiver_plan), receiver_commitment=quote)
        # Same database fixtures cannot share an origin/receiver grant ID; a real
        # independent receiver DB is required, so clone the immutable source
        # allocation into an isolated receiver below rather than reset its row.
        database = IsolatedPostgres(os.environ["FACTORY_TEST_DATABASE_URL"]).__enter__()
        self.addCleanup(database.__exit__, None, None, None)
        receiver_store = Store(database.url, self.settings)
        self.addCleanup(receiver_store.engine.dispose)
        receiver_store.save_plan(receiver_plan)
        receiver_store.sql("INSERT INTO af_tasks(id,owner_id,plan_id,request_id,fingerprint,run_id,admission,body) VALUES(:id,'alice',:plan,:request,:fp,:run,'accepted',CAST(:body AS JSONB))",
            id=receiver["id"], plan=receiver_plan["id"], request=receiver["request_id"], fp=receiver["fingerprint"], run=context.run_id, body=canonical(receiver["body"]))
        receiver_ledger = UsageLedger(receiver_store, (price(),), self.policy)
        receiver_store.usage_ledger = receiver_ledger
        receiver_ledger.prepare_remote_commitment(receiver_plan, receiver_plan["executionBindings"])
        receiver_ledger.import_remote_grant("alice", receiver["id"], grant, expected_origin_ref="controlled-origin",
            expected_target_ref="controlled-target", expected_origin_task_id=source["id"], expected_origin_owner="alice",
            expected_source_plan_sha256=digest(self.store.plan(source["plan_id"])), expected_source_commitment_sha256=grant["sourceCommitmentSha256"])
        model = ControlledModel(self.records, scenario="unknown")
        DelegatingModel._guard_provider_calls(model, lambda: None, ledger=receiver_ledger, plan=receiver_plan, context=context)
        self.invoke(model)
        statement = receiver_ledger.remote_statement("alice", receiver["id"], grant["id"], all_stopped=True)
        held = self.ledger.apply_remote_statement("alice", source["id"], statement)
        self.assertFalse(held["releasedUnused"])
        self.assertEqual(self.projection(source)["scopes"][0]["heldTokens"], 20)
        receiver_attempt = receiver_ledger.inspect("alice", receiver["id"])["attempts"][0]["id"]
        receiver_ledger.finish_attempt(receiver_attempt, UsageEvidence(3, 2, "controlled-remote-authoritative-recovery"))
        final = receiver_ledger.remote_statement("alice", receiver["id"], grant["id"], all_stopped=True)
        result = self.ledger.apply_remote_statement("alice", source["id"], final)
        self.assertTrue(result["releasedUnused"])
        self.assertTrue(self.ledger.apply_remote_statement("alice", source["id"], final)["idempotent"])
        state = self.projection(source)["scopes"][0]
        self.assertEqual((state["tokenLimit"], state["settledTokens"], state["heldTokens"]), (20, 5, 0))
        self.assertEqual((state["amountMicrosLimit"], state["settledAmountMicros"]), (32, 7))
        # Replaying allocation/import cannot renew a closed grant or user cap.
        replay = self.ledger.allocate_remote("alice", source["id"], grant["id"], origin_ref="controlled-origin", target_ref="controlled-target",
            receiver_owner="alice", receiver_task_id=receiver["id"], receiver_plan_sha256=digest(receiver_plan), receiver_commitment=quote)
        self.assertEqual(replay, grant)
        receiver_ledger.import_remote_grant("alice", receiver["id"], replay, expected_origin_ref="controlled-origin",
            expected_target_ref="controlled-target", expected_origin_task_id=source["id"])
        with self.assertRaises(HTTPException):
            self.invoke(model)
        self.assertEqual(self.projection(source)["scopes"][0]["settledTokens"], 5)

    def test_15_positive_remote_no_dispatch_reclaims_unused_hold_but_not_cap(self):
        source, _ = self.task(self.plan(tokens=20, amount=32))
        receiver_plan = self.plan(tokens=20, amount=32)
        receiver, _ = self.task(receiver_plan)
        quote = receiver_plan["usageBudget"]
        grant = self.ledger.allocate_remote("alice", source["id"], str(uuid4()), origin_ref="controlled-origin", target_ref="controlled-target",
            receiver_owner="alice", receiver_task_id=receiver["id"], receiver_plan_sha256=digest(receiver_plan), receiver_commitment=quote)
        receipt = {"id": grant["id"], "originOwnerId": "alice", "originTaskId": source["id"], "remoteOwnerId": "alice",
            "remoteTaskId": receiver["id"], "receiverPlanSha256": digest(receiver_plan), "receiverUsageCommitment": quote,
            "state": "CANCELLED_NO_DISPATCH", "remoteRunId": None, "native": None, "allStopped": True}
        with self.assertRaises(HTTPException):
            self.ledger.reclaim_remote_no_dispatch("alice", source["id"], grant["id"], {**receipt, "allStopped": False})
        self.assertEqual(self.projection(source)["scopes"][0]["heldTokens"], 20)
        result = self.ledger.reclaim_remote_no_dispatch("alice", source["id"], grant["id"], receipt)
        self.assertTrue(result["releasedUnused"])
        self.assertTrue(self.ledger.reclaim_remote_no_dispatch("alice", source["id"], grant["id"], receipt)["idempotent"])
        state = self.projection(source)["scopes"][0]
        self.assertEqual((state["tokenLimit"], state["heldTokens"], state["settledTokens"]), (20, 0, 0))

    def test_16_historical_read_survives_policy_rotation_without_new_account_bucket(self):
        task, context = self.task(self.plan())
        self.invoke(self.selected(context))
        original = self.projection(task)
        rotated = UsageLedger(self.store, (price(),), replace(self.policy, revision="controlled-policy-rotation", user_token_limit=160))
        self.assertEqual(rotated.inspect("alice", task["id"]), original)
        self.store.usage_ledger = rotated
        with self.assertRaises(HTTPException):
            self.invoke(self.selected(context))
        self.assertEqual(self.store.sql("SELECT COUNT(*) AS n FROM af_usage_accounts WHERE id LIKE 'user:%'")[0]["n"], 1)

    def test_17_closing_partial_async_stream_retains_reservation(self):
        task, context = self.task(self.plan())
        async def partial():
            iterator = self.selected(context).ainvoke_stream(messages=[Message(role="user", content="Close partial async stream")])
            await anext(iterator)
            await iterator.aclose()
        asyncio.run(partial())
        state = self.projection(task)
        self.assertEqual(state["attempts"][0]["state"], "UNKNOWN")
        self.assertEqual(state["scopes"][0]["heldTokens"], 10)

    def test_18_currency_rotation_cannot_change_historical_charge_or_admit_old_plan(self):
        task, context = self.task(self.plan())
        self.invoke(self.selected(context))
        original = self.projection(task)
        rotated = UsageLedger(self.store, (price(revision="synthetic-cny-v1", currency="CNY"),),
            replace(self.policy, revision="controlled-cny-policy-v1", currency="CNY"))
        self.assertEqual(rotated.inspect("alice", task["id"]), original)
        self.store.usage_ledger = rotated
        with self.assertRaises(HTTPException):
            self.invoke(self.selected(context))
        self.assertEqual(len(self.records), 1)

    def test_19_shared_amount_cap_denies_attempt_while_token_capacity_remains(self):
        self.set_policy(user_token_limit=80, user_amount_micros=16)
        self.options["scenario"] = "unknown"
        first, context = self.task(self.plan())
        second, other_context = self.task(self.plan())
        self.invoke(self.selected(context))
        with self.assertRaises(HTTPException) as no_money:
            self.invoke(self.selected(other_context))
        self.assertEqual(no_money.exception.status_code, 429)
        user = next(s for s in self.projection(first)["scopes"] if s["scope"] == "user")
        self.assertEqual((user["heldTokens"], user["tokenLimit"], user["heldAmountMicros"], user["amountMicrosLimit"]), (10, 80, 16, 16))
        self.assertEqual(self.projection(second)["attempts"], [])
        self.assertEqual(len(self.records), 1)


if __name__ == "__main__":
    unittest.main()
