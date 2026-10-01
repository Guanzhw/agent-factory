"""Black-box HTTP scenarios against a disposable synthetic contract adapter.

No test imports the Agno application. Passing these tests is harness/reference
validation only; run equivalent scenarios against a production adapter before
claiming backend acceptance.
"""
import copy
import concurrent.futures
from pathlib import Path
import tempfile
import unittest
import uuid

from fixture_runtime import ACTORS, CONTROL_TOKEN, DEFAULT_RESERVATION, FixtureServer
from protocol import (ContractClient, ContractError, Projection, ProtocolViolation,
                      SnapshotRequired, UnknownAcknowledgement, verify_artifact)


class RuntimeContractTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="factory-contract-")
        self.server = FixtureServer(Path(self.directory.name) / "fixture.sqlite").start()
        self.clients()

    def tearDown(self):
        self.server.stop()
        self.directory.cleanup()

    def clients(self):
        self.alice = ContractClient(self.server.url, "fixture-alice-a")
        self.bob = ContractClient(self.server.url, "fixture-bob")
        self.other_task = ContractClient(self.server.url, "fixture-alice-b")
        self.other_tenant = ContractClient(self.server.url, "fixture-other-tenant")
        self.control = ContractClient(self.server.url, CONTROL_TOKEN)

    def restart(self):
        self.server.restart()
        self.clients()

    def command(self, path, body=None, key=None, client=None):
        return (client or self.alice).post(path, body or {}, key or uuid.uuid4().hex)

    def inject(self, op, **values):
        return self.control.post("/_test/control", dict(op=op, **values))

    def session(self, client=None):
        return self.command("/v1/sessions", client=client)["session_id"]

    def create_run(self, client=None, session=None, key=None, **overrides):
        session = session or self.session(client)
        return self.command(f"/v1/sessions/{session}/runs",
                            dict(input="Synthetic research", **overrides), key, client)

    def rid(self, run):
        return run["run_id"]

    def snapshot(self, run):
        return self.alice.get(f"/v1/runs/{self.rid(run)}/snapshot")

    def resources(self, client=None):
        return (client or self.alice).get("/v1/resources")["reserved"]

    def rejects(self, code, call):
        with self.assertRaises(ContractError) as caught:
            call()
        self.assertEqual(caught.exception.code, code)
        return caught.exception.status

    def cleaned(self, run):
        rid = self.rid(run)
        self.inject("complete", run_id=rid)
        self.inject("cleanup_evidence", run_id=rid,
                    processes=dict(runtime=0, tool=0, browser=0, mcp=0, experiment=0),
                    temporary_data_clean=True)
        return self.command(f"/v1/runs/{rid}/reclaim")

    def test_contract_is_explicitly_synthetic(self):
        self.assertEqual(self.alice.get("/v1/health"),
                         dict(contract="factory-runtime-test/v1", fixture=True))

    def test_identity_cannot_be_taken_from_request_body(self):
        self.rejects("unknown_fields", lambda: self.command("/v1/sessions", {"user_id": "bob"}))
        bad = ContractClient(self.server.url, "unknown")
        self.rejects("unauthenticated", lambda: bad.get("/v1/health"))

    def test_sessions_attach_detach_do_not_create_compute_or_cancel_run(self):
        sid = self.session()
        self.assertEqual(self.resources()["slots"], 0)
        self.command(f"/v1/sessions/{sid}/attach")
        run = self.create_run(session=sid)
        self.command(f"/v1/sessions/{sid}/detach")
        self.assertEqual(self.snapshot(run)["state"]["execution_state"], "running")
        self.assertEqual(self.inject("inspect")["environment_creations"], 0)
        self.assertEqual(self.resources()["slots"], 1)

    def test_missing_idempotency_key_is_rejected(self):
        self.rejects("idempotency_key_required", lambda: self.alice.post("/v1/sessions", {}))

    def test_concurrent_duplicates_create_one_run_and_one_reservation(self):
        sid = self.session()
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.create_run(session=sid, key="same-command"), range(8)))
        self.assertEqual(len({r["run_id"] for r in results}), 1)
        self.assertEqual(len(self.inject("inspect")["runs"]), 1)
        self.assertEqual(self.resources(), DEFAULT_RESERVATION)

    def test_effect_command_duplicate_is_not_reexecuted(self):
        run = self.create_run()
        path = f"/v1/runs/{self.rid(run)}/step"
        self.inject("drop_next_response", path=path)
        with self.assertRaises(UnknownAcknowledgement):
            self.command(path, key="one-effect")
        self.restart()
        receipt = self.alice.get("/v1/operations/one-effect")
        self.assertEqual(receipt["result"]["state"]["effects"], 1)
        self.assertEqual(self.command(path, key="one-effect"), receipt["result"])
        self.assertEqual(self.inject("inspect")["effects"], 1)

    def test_lost_session_creation_ack_does_not_create_second_session_or_compute(self):
        self.inject("drop_next_response", path="/v1/sessions")
        with self.assertRaises(UnknownAcknowledgement):
            self.command("/v1/sessions", key="session-unknown")
        self.restart()
        receipt = self.alice.get("/v1/operations/session-unknown")
        self.assertIn("session_id", receipt["result"])
        self.assertEqual(len(self.inject("inspect")["sessions"]), 1)
        self.assertEqual(self.inject("inspect")["environment_creations"], 0)
        self.assertEqual(self.resources()["slots"], 0)

    def test_changed_payload_and_route_cannot_reuse_idempotency_key(self):
        sid = self.session()
        run = self.create_run(session=sid, key="original")
        self.rejects("idempotency_conflict", lambda: self.create_run(
            session=sid, key="original", reservation=dict(slots=1, cpu_millis=600, memory_mib=512)))
        self.rejects("idempotency_conflict", lambda: self.command(
            f"/v1/runs/{self.rid(run)}/cancel", key="original"))

    def test_idempotency_namespace_is_scoped(self):
        a = self.command("/v1/sessions", key="same")
        b = self.command("/v1/sessions", key="same", client=self.bob)
        self.assertNotEqual(a["session_id"], b["session_id"])
        self.assertEqual(self.alice.get("/v1/operations/same")["result"], a)
        self.assertEqual(self.bob.get("/v1/operations/same")["result"], b)

    def test_lost_ack_reconciles_after_restart_without_retry_or_release(self):
        sid = self.session()
        path = f"/v1/sessions/{sid}/runs"
        self.inject("drop_next_response", path=path)
        with self.assertRaises(UnknownAcknowledgement):
            self.command(path, {"input": "Synthetic research"}, "unknown-create")
        self.assertEqual(self.resources(), DEFAULT_RESERVATION)
        self.assertEqual(len(self.inject("inspect")["runs"]), 1)
        self.restart()
        operation = self.alice.get("/v1/operations/unknown-create")
        self.assertEqual(operation["state"], "accepted")
        self.assertEqual(self.resources(), DEFAULT_RESERVATION)
        self.assertEqual(len(self.inject("inspect")["runs"]), 1)
        self.assertEqual(self.snapshot(operation["result"])["state"]["execution_state"], "running")

    def test_server_error_or_malformed_ack_is_unknown_not_rejected(self):
        sid = self.session()
        path = f"/v1/sessions/{sid}/runs"
        for fault in ("server_error", "invalid_json", "invalid_array", "oversized_json"):
            with self.subTest(fault=fault):
                self.inject("drop_next_response", path=path, fault=fault)
                with self.assertRaises(UnknownAcknowledgement):
                    self.command(path, {"input": "Synthetic research"}, fault)
                operation = self.alice.get(f"/v1/operations/{fault}")
                self.assertEqual(operation["state"], "accepted")
                self.cleaned(operation["result"])
        self.assertEqual(len(self.inject("inspect")["runs"]), 4)
        self.assertEqual(self.resources()["slots"], 0)

    def test_absent_operation_is_unresolved_not_permission_to_resubmit(self):
        self.rejects("operation_unresolved", lambda: self.alice.get("/v1/operations/not-seen"))
        self.assertEqual(len(self.inject("inspect")["runs"]), 0)

    def test_unknown_cancel_keeps_capacity_until_terminal_cleanup_evidence(self):
        run = self.create_run()
        path = f"/v1/runs/{self.rid(run)}/cancel"
        self.inject("drop_next_response", path=path)
        with self.assertRaises(UnknownAcknowledgement):
            self.command(path, key="cancel-unknown")
        self.restart()
        op = self.alice.get("/v1/operations/cancel-unknown")
        self.assertEqual(op["result"]["state"]["execution_state"], "cancel_requested")
        self.assertEqual(self.resources(), DEFAULT_RESERVATION)

    def test_all_fact_and_action_routes_enforce_user_task_and_tenant_scope(self):
        run = self.create_run()
        rid = self.rid(run)
        for other in (self.bob, self.other_task, self.other_tenant):
            for suffix in ("snapshot", "events?after=0", "artifacts/report"):
                with self.subTest(actor=other.token, suffix=suffix):
                    status = self.rejects("not_found", lambda: other.get(f"/v1/runs/{rid}/{suffix}"))
                    self.assertEqual(status, 404)
            self.rejects("not_found", lambda: self.command(f"/v1/runs/{rid}/cancel", client=other))
            self.rejects("not_found", lambda: self.create_run(client=other, parent_run_id=rid))

    def test_revocation_blocks_reads_new_actions_and_idempotent_replay(self):
        run = self.create_run(key="before-revoke")
        self.command(f"/v1/runs/{self.rid(run)}/step", key="one-step")
        self.inject("revoke", actor="fixture-alice-a")
        self.rejects("revoked", lambda: self.snapshot(run))
        self.rejects("revoked", lambda: self.command(f"/v1/runs/{self.rid(run)}/step", key="one-step"))
        self.rejects("revoked", lambda: self.alice.get("/v1/operations/before-revoke"))
        state = self.inject("inspect")
        self.assertEqual(state["effects"], 1)
        self.assertEqual(state["runs"][self.rid(run)]["execution_state"], "running")
        self.assertEqual(state["runs"][self.rid(run)]["cleanup_state"], "pending")

    def test_question_is_not_an_approval_and_never_executes_a_side_effect(self):
        run = self.create_run()
        wait = self.inject("wait", run_id=self.rid(run), kind="question")["state"]["wait"]
        path = f"/v1/runs/{self.rid(run)}/reply"
        self.rejects("interaction_kind_mismatch", lambda: self.command(path, dict(
            interaction_id=wait["interaction_id"], kind="approval", approve=True, binding="v1")))
        self.command(path, dict(interaction_id=wait["interaction_id"], kind="question", answer="continue"))
        state = self.snapshot(run)["state"]
        self.assertNotIn("approval_outcome", state)
        self.assertEqual(state["effects"], 0)

    def test_approval_binding_expiry_and_replay_are_checked(self):
        run = self.create_run()
        wait = self.inject("wait", run_id=self.rid(run), kind="approval", binding="target-and-params-v1")["state"]["wait"]
        path = f"/v1/runs/{self.rid(run)}/reply"
        body = dict(interaction_id=wait["interaction_id"], kind="approval", approve=True, binding="wrong")
        self.rejects("approval_binding_changed", lambda: self.command(path, body))
        body["binding"] = wait["binding"]
        first = self.command(path, body, "reply-once")
        self.assertEqual(self.command(path, body, "reply-once"), first)
        self.rejects("no_pending_interaction", lambda: self.command(path, body))
        self.assertEqual(self.inject("inspect")["effects"], 0)
        self.rejects("not_found", lambda: self.command("/v1/definitions/publish", {}))

    def test_pending_and_expired_interactions_survive_restart(self):
        run = self.create_run()
        wait = self.inject("wait", run_id=self.rid(run), kind="approval", binding="v1", expired=True)["state"]["wait"]
        self.restart()
        self.assertEqual(self.snapshot(run)["state"]["wait"], wait)
        self.rejects("expired_interaction", lambda: self.command(f"/v1/runs/{self.rid(run)}/reply", dict(
            interaction_id=wait["interaction_id"], kind="approval", approve=True, binding="v1")))
        self.assertEqual(self.resources(), DEFAULT_RESERVATION)

    def test_stale_interaction_cannot_answer_new_question(self):
        run = self.create_run()
        old = self.inject("wait", run_id=self.rid(run), kind="question")["state"]["wait"]
        self.inject("wait", run_id=self.rid(run), kind="question")
        self.rejects("stale_interaction", lambda: self.command(f"/v1/runs/{self.rid(run)}/reply", dict(
            interaction_id=old["interaction_id"], kind="question", answer="yes")))

    def test_late_reply_cannot_resurrect_cancelled_or_reclaimed_execution(self):
        run = self.create_run()
        rid = self.rid(run)
        wait = self.inject("wait", run_id=rid, kind="question")["state"]["wait"]
        body = dict(interaction_id=wait["interaction_id"], kind="question", answer="continue")
        self.command(f"/v1/runs/{rid}/cancel")
        self.rejects("no_pending_interaction", lambda: self.command(f"/v1/runs/{rid}/reply", body))
        self.cleaned(run)
        self.restart()
        self.rejects("no_pending_interaction", lambda: self.command(f"/v1/runs/{rid}/reply", body))
        self.rejects("not_runnable", lambda: self.command(f"/v1/runs/{rid}/step"))
        self.assertEqual(self.snapshot(run)["state"]["execution_state"], "completed")
        self.assertEqual(self.resources()["slots"], 0)
        self.assertEqual(self.inject("inspect")["effects"], 0)

    def test_expired_parent_lease_cannot_spawn_child(self):
        parent = self.create_run()
        self.inject("expire_lease", run_id=self.rid(parent))
        self.rejects("parent_not_running", lambda: self.create_run(parent_run_id=self.rid(parent)))
        self.assertEqual(len(self.inject("inspect")["runs"]), 1)
        self.assertEqual(self.resources(), DEFAULT_RESERVATION)

    def test_terminal_execution_does_not_imply_business_success_or_reclamation(self):
        run = self.create_run()
        state = self.inject("complete", run_id=self.rid(run), business_state="failed")["state"]
        self.assertEqual(state["execution_state"], "completed")
        self.assertEqual(state["business_state"], "failed")
        self.assertEqual(self.resources(), DEFAULT_RESERVATION)
        self.rejects("cleanup_unverified", lambda: self.command(f"/v1/runs/{self.rid(run)}/reclaim"))

    def test_reclaim_requires_every_process_category_and_temporary_data_clean(self):
        run = self.create_run()
        self.inject("complete", run_id=self.rid(run))
        empty = dict(runtime=0, tool=0, browser=0, mcp=0, experiment=0)
        for category in empty:
            with self.subTest(category=category):
                self.inject("cleanup_evidence", run_id=self.rid(run),
                            processes={**empty, category: 1}, temporary_data_clean=True)
                self.rejects("cleanup_unverified", lambda: self.command(f"/v1/runs/{self.rid(run)}/reclaim"))
                self.assertEqual(self.resources(), DEFAULT_RESERVATION)
        self.inject("cleanup_evidence", run_id=self.rid(run), processes=empty, temporary_data_clean=False)
        self.rejects("cleanup_unverified", lambda: self.command(f"/v1/runs/{self.rid(run)}/reclaim"))
        self.cleaned(run)
        self.assertEqual(self.resources(), dict(slots=0, cpu_millis=0, memory_mib=0))
        self.command(f"/v1/runs/{self.rid(run)}/reclaim")
        self.assertEqual(self.resources()["slots"], 0)

    def test_waiting_and_lease_expiry_do_not_release_capacity_or_repeat_effects(self):
        run = self.create_run()
        self.command(f"/v1/runs/{self.rid(run)}/step")
        self.inject("expire_lease", run_id=self.rid(run))
        self.rejects("not_runnable", lambda: self.command(f"/v1/runs/{self.rid(run)}/step"))
        self.inject("wait", run_id=self.rid(run), kind="question")
        self.restart()
        self.assertEqual(self.resources(), DEFAULT_RESERVATION)
        self.assertEqual(self.inject("inspect")["effects"], 1)
        self.assertTrue(self.snapshot(run)["state"]["lease_expired"])

    def test_parent_child_share_root_budget_and_parent_cannot_reclaim_early(self):
        parent = self.create_run(reservation=dict(slots=1, cpu_millis=500, memory_mib=1024))
        child = self.create_run(parent_run_id=self.rid(parent), reservation=dict(slots=1, cpu_millis=500, memory_mib=1024))
        self.rejects("resource_budget_exceeded", lambda: self.create_run(parent_run_id=self.rid(parent)))
        self.assertEqual(self.resources()["memory_mib"], 2048)
        self.inject("complete", run_id=self.rid(parent))
        self.inject("cleanup_evidence", run_id=self.rid(parent),
                    processes=dict(runtime=0, tool=0, browser=0, mcp=0, experiment=0), temporary_data_clean=True)
        self.rejects("children_not_reclaimed", lambda: self.command(f"/v1/runs/{self.rid(parent)}/reclaim"))
        self.cleaned(child)
        self.command(f"/v1/runs/{self.rid(parent)}/reclaim")
        self.assertEqual(self.resources()["slots"], 0)

    def test_depth_limit_and_lifetime_child_count_do_not_reset_with_cleanup(self):
        parent = self.create_run()
        child = self.create_run(parent_run_id=self.rid(parent))
        grandchild = self.create_run(parent_run_id=self.rid(child))
        self.rejects("depth_limit", lambda: self.create_run(parent_run_id=self.rid(grandchild)))
        self.cleaned(grandchild)
        self.cleaned(child)
        third = self.create_run(parent_run_id=self.rid(parent))
        self.cleaned(third)
        self.rejects("child_limit", lambda: self.create_run(parent_run_id=self.rid(parent)))

    def test_user_budget_spans_sessions_and_tasks_without_consuming_other_users_quota(self):
        for _ in range(3):
            self.create_run(reservation=dict(slots=1, cpu_millis=1000, memory_mib=512))
        self.rejects("resource_budget_exceeded", lambda: self.create_run(client=self.other_task))
        bob = self.create_run(client=self.bob)
        self.assertEqual(bob["scope"]["user_id"], "bob")
        self.assertEqual(self.resources(self.bob), DEFAULT_RESERVATION)

    def test_invalid_or_injected_reservation_cannot_bypass_limits(self):
        for reservation in (
            dict(slots=-1, cpu_millis=500, memory_mib=512),
            dict(slots=True, cpu_millis=500, memory_mib=512),
            dict(slots=1, cpu_millis=0, memory_mib=512),
            dict(slots=1, cpu_millis=500, memory_mib=512, unlimited=True),
        ):
            with self.subTest(reservation=reservation):
                self.rejects("invalid_request", lambda: self.create_run(reservation=reservation))
        self.rejects("unknown_fields", lambda: self.create_run(endpoint="https://untrusted.invalid"))
        self.assertEqual(self.resources()["slots"], 0)

    def test_event_replay_dedup_gap_and_snapshot_reconciliation(self):
        run = self.create_run()
        rid = self.rid(run)
        projection = Projection(ACTORS["fixture-alice-a"], rid)
        self.assertTrue(projection.snapshot(run))
        self.command(f"/v1/runs/{rid}/step")
        self.command(f"/v1/runs/{rid}/step")
        events = self.alice.get(f"/v1/runs/{rid}/events?after=1")["events"]
        with self.assertRaises(SnapshotRequired):
            projection.event(events[1])
        self.assertEqual(projection.sequence, 1)
        self.assertTrue(projection.snapshot(self.snapshot(run)))
        for event in reversed(events):
            self.assertFalse(projection.event(event))
        self.assertFalse(projection.snapshot(run))
        self.assertEqual(projection.state["effects"], 2)
        self.inject("expire_events", run_id=rid)
        self.assertTrue(self.alice.get(f"/v1/runs/{rid}/events?after=0")["snapshot_required"])

    def test_client_rejects_cross_scope_frames_even_if_transport_is_buggy(self):
        run = self.create_run()
        projection = Projection(ACTORS["fixture-alice-a"], self.rid(run))
        for field, value in (("scope", ACTORS["fixture-bob"].as_dict()), ("run_id", "other-run"), ("sequence", True)):
            bad = copy.deepcopy(run)
            bad[field] = value
            with self.subTest(field=field), self.assertRaises(ProtocolViolation):
                projection.snapshot(bad)
        self.assertEqual(projection.sequence, 0)

    def test_projection_rejects_cross_scope_or_inconsistent_inner_state(self):
        run = self.create_run()
        for field, value in (("scope", ACTORS["fixture-bob"].as_dict()),
                             ("run_id", "other-run"), ("sequence", 999)):
            for method in ("snapshot", "event"):
                projection = Projection(ACTORS["fixture-alice-a"], self.rid(run))
                bad = copy.deepcopy(run)
                bad["state"][field] = value
                with self.subTest(field=field, method=method), self.assertRaises(ProtocolViolation):
                    getattr(projection, method)(bad)
                self.assertEqual(projection.sequence, 0)

    def test_artifact_digest_size_and_scope_are_verified(self):
        run = self.create_run()
        rid = self.rid(run)
        artifact = self.alice.get(f"/v1/runs/{rid}/artifacts/report")
        scope = ACTORS["fixture-alice-a"]
        self.assertIn(b"Synthetic", verify_artifact(artifact, scope, rid))
        for field, value in (("content", "tampered"), ("sha256", "0" * 64),
                             ("scope", ACTORS["fixture-bob"].as_dict())):
            with self.subTest(field=field), self.assertRaises(ProtocolViolation):
                verify_artifact({**artifact, field: value}, scope, rid)

    def test_harness_detects_known_broken_premature_release_mutant(self):
        self.server.stop()
        self.server = FixtureServer(Path(self.directory.name) / "mutant.sqlite", mutant="release_on_cancel").start()
        self.clients()
        run = self.create_run()
        before = self.resources()
        self.command(f"/v1/runs/{self.rid(run)}/cancel")
        with self.assertRaises(AssertionError):
            self.assertEqual(self.resources(), before, "Cancellation must not free unverified resources")

    def test_remote_urls_and_embedded_credentials_are_rejected(self):
        for url in ("https://example.com", "http://localhost", "http://127.0.0.1/path",
                    "http://user:secret@127.0.0.1", "http://127.0.0.1#fragment"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                ContractClient(url, "fixture-token")


if __name__ == "__main__":
    unittest.main(verbosity=2)
