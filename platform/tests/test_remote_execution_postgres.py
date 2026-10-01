"""Public product HTTP contracts with two actual apps and native PostgreSQL queues.

Only provider output and inter-app transport are synthetic: authenticated routes,
durable native admission, HITL, scoped delegation and fixed experiments are real.
Controlled ASGI does not establish deployed-host, TLS or production identity proof.
"""
import hashlib
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock
from uuid import uuid4

from fastapi.testclient import TestClient
import httpx
from sqlalchemy import MetaData, Table, func, inspect, select

from pg_fixture import IsolatedPostgres
from agent_factory.config import Settings
from agent_factory.main import create_app
from agent_factory.remote_handoff import HandoffTarget, TrustedOrigin


class ControlledDispatchLoss(httpx.AsyncBaseTransport):
    """Lose delivery or the real reply once; other traffic reaches the real app."""
    def __init__(self, app, *, before_delivery=False, suffix="/dispatch"):
        self.inner = httpx.ASGITransport(app=app)
        self.before_delivery, self.suffix = before_delivery, suffix
        self.attempts = 0

    async def handle_async_request(self, request):
        matched = request.method == "POST" and request.url.path.endswith(self.suffix)
        if matched:
            self.attempts += 1
            if self.attempts == 1 and self.before_delivery:
                raise httpx.ReadTimeout("Controlled request loss before receiver delivery", request=request)
        response = await self.inner.handle_async_request(request)
        if matched and self.attempts == 1:
            await response.aread()
            raise httpx.ReadTimeout("Controlled reply loss after actual receiver handling", request=request)
        return response


@unittest.skipUnless(os.getenv("FACTORY_TEST_DATABASE_URL"), "Requires disposable loopback PostgreSQL")
class RemoteExecutionProductPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.origin_db = IsolatedPostgres(os.environ["FACTORY_TEST_DATABASE_URL"]).__enter__()
        cls.addClassCleanup(cls.origin_db.__exit__, None, None, None)
        cls.receiver_db = IsolatedPostgres(os.environ["FACTORY_TEST_DATABASE_URL"]).__enter__()
        cls.addClassCleanup(cls.receiver_db.__exit__, None, None, None)
        cls.workspace = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.workspace.cleanup)
        cls.origin_settings = Settings(db_url=cls.origin_db.url, workspace=Path(cls.workspace.name) / "origin",
                                       max_workers=1, max_user_tasks=12, max_total_tasks=24)
        cls.origin_app = create_app(cls.origin_settings)
        cls.origin = cls.origin_app.app.state.factory
        cls.handoff = cls.origin["handoff_client"]
        trusted = TrustedOrigin("origin-product-fixture", {"alice": "bob"}, cls.handoff.authority_callback)
        cls.receiver_settings = Settings(db_url=cls.receiver_db.url, workspace=Path(cls.workspace.name) / "receiver",
                                         max_workers=1, max_user_tasks=12, max_total_tasks=24,
                                         handoff_origins={trusted.reference: trusted})
        # Main creates and registers the receiver itself. No manually appended router.
        cls.receiver_app = create_app(cls.receiver_settings)
        cls.receiver = cls.receiver_app.app.state.factory
        for state in (cls.origin, cls.receiver):
            cls.addClassCleanup(state["store"].engine.dispose)
            cls.addClassCleanup(state["store"].native_db.db_engine.dispose)
        cls.target = HandoffTarget("receiver-fixture", trusted.reference, "http://receiver.factory.invalid",
                                   {"alice": "bob"},
                                   lambda owner: {"Authorization": "Bearer " + cls.receiver["auth"]._issue_native_token("bob")},
                                   transport=httpx.ASGITransport(app=cls.receiver_app))
        # Operator-installed cyclic fixture connection, before any HTTP request.
        cls.handoff.targets[cls.target.reference] = cls.target
        cls.origin_client = TestClient(cls.origin_app).__enter__()
        cls.addClassCleanup(cls.origin_client.__exit__, None, None, None)
        cls.receiver_client = TestClient(cls.receiver_app).__enter__()
        cls.addClassCleanup(cls.receiver_client.__exit__, None, None, None)

    def setUp(self):
        self.requests = []
        self.handoff.targets.clear()
        self.handoff.targets[self.target.reference] = self.target
        for state, owner in ((self.origin, "alice"), (self.receiver, "bob")):
            state["auth"].authorization.unassign(owner, "fixture-product-reader")
            state["auth"].authorization.assign(owner, "factory-user")

    def tearDown(self):
        self.handoff.targets.clear()
        self.handoff.targets[self.target.reference] = self.target
        for state, owner in ((self.origin, "alice"), (self.receiver, "bob")):
            state["auth"].authorization.unassign(owner, "fixture-product-reader")
            state["auth"].authorization.assign(owner, "factory-user")
        # Only cancel this test's owned original reservations through product APIs.
        # Unknown is retained by the application; no table clearing or fake stop.
        for request_id in self.requests:
            found = self.origin["store"].sql("SELECT id FROM af_tasks WHERE owner_id='alice' AND request_id=:key", key=request_id)
            if found:
                identifier = found[0]["id"]
                self.origin_client.post(f"/api/factory/jobs/{identifier}/cancel", headers=self.headers())
                deadline = time.monotonic() + 8
                while time.monotonic() < deadline:
                    response = self.origin_client.get(f"/api/factory/jobs/{identifier}", headers=self.headers())
                    if response.status_code != 200 or response.json()["job"]["status"] in {"completed", "canceled", "failed", "unknown"}:
                        break
                    time.sleep(.03)

    def headers(self, owner="alice", state=None):
        state = state or self.origin
        return {"Authorization": "Bearer " + state["auth"]._issue_native_token(owner)}

    def request(self, method, path, *, expected=200, owner="alice", **kwargs):
        response = self.origin_client.request(method, "/api/factory" + path, headers=self.headers(owner), **kwargs)
        self.assertEqual(response.status_code, expected, response.text)
        return response

    def plan(self, goal="Controlled public checksum evidence", mode="literature", application="checksum"):
        return self.request("POST", "/plans", expected=201,
                            json={"topic": goal, "mode": mode, "application": application, "requestId": str(uuid4())}).json()

    def submit(self, plan, key=None):
        body = {"planId": plan["id"], "requestId": key or str(uuid4()), "executionTargetRef": self.target.reference}
        self.requests.append(body["requestId"])
        return self.request("POST", "/instances", expected=202, json=body).json(), body

    def wait(self, task_id, states):
        deadline = time.monotonic() + 15
        last = None
        while time.monotonic() < deadline:
            last = self.request("GET", "/jobs/" + task_id).json()
            if last["job"]["status"] in states:
                return last
            time.sleep(.03)
        self.fail(f"Product task did not reach {states}: {last}")

    def ticket_count(self, state, task_id=None):
        db = state["store"].native_db
        if not inspect(db.db_engine).has_table(db.job_table_name, schema=db.db_schema):
            return 0
        table = Table(db.job_table_name, MetaData(), schema=db.db_schema, autoload_with=db.db_engine)
        query = select(func.count()).select_from(table)
        if task_id:
            query = query.where(table.c.session_id == task_id)
        with db.db_engine.connect() as connection:
            return connection.execute(query).scalar()

    def placement(self, task_id):
        return self.handoff._row("alice", task_id)

    def install_transport(self, transport):
        old = self.target
        self.handoff.targets[old.reference] = HandoffTarget(old.reference, old.origin_ref, old.base_url,
                                                            old.identity_map, old.headers, transport,
                                                            configuration_revision=old.configuration_revision)

    def test_01_trusted_target_discovery_and_rejected_user_connection(self):
        self.assertIs(self.origin["store"].remote_execution.client, self.handoff)
        self.assertIsNotNone(self.receiver["handoff_receiver"])
        self.assertNotEqual(self.origin_db.name, self.receiver_db.name)
        targets = self.request("GET", "/execution-targets").json()
        self.assertEqual(targets, [{"id": self.target.reference, "name": self.target.reference,
                                   "kind": "remote-factory", "connectivityVerified": False}])
        self.assertNotIn(self.target.base_url, str(targets))
        self.assertEqual(self.request("GET", "/execution-targets", owner="bob").json(), [])
        plan = self.plan()
        for fields, status in (({"executionTargetRef": "untrusted-fixture"}, 404),
                               ({"executionTargetRef": self.target.reference, "url": "http://user-chosen.invalid"}, 422),
                               ({"executionTargetRef": self.target.reference, "token": "synthetic-forged-token"}, 422)):
            self.request("POST", "/instances", expected=status,
                         json={"planId": plan["id"], "requestId": str(uuid4()), **fields})
        self.assertEqual(self.origin["store"].sql("SELECT COUNT(*) AS n FROM af_tasks")[0]["n"], 0)
        self.assertEqual(self.ticket_count(self.origin), 0)
        self.assertEqual(self.ticket_count(self.receiver), 0)

    def test_02_one_receiver_ticket_original_receipt_and_hashed_owner_scoped_artifact(self):
        plan = self.plan("Controlled remote checksum bytes")
        with mock.patch.object(self.receiver["bridge"], "submit", wraps=self.receiver["bridge"].submit) as submit:
            job, body = self.submit(plan)
            again = self.request("POST", "/instances", expected=202, json=body).json()
            self.assertEqual(again["id"], job["id"])
            self.assertEqual(submit.await_count, 1)
        detail = self.wait(job["id"], {"completed", "failed", "unknown"})
        self.assertEqual(detail["job"]["status"], "completed", detail)
        self.assertEqual(detail["job"]["ownerId"], "alice")
        self.assertEqual(detail["job"]["planId"], plan["id"])
        placement = detail["job"]["executionPlacement"]
        self.assertNotEqual(placement["remoteTaskId"], job["id"])
        self.assertEqual(placement["targetRef"], self.target.reference)
        self.assertEqual(self.ticket_count(self.origin), 0)
        self.assertEqual(self.ticket_count(self.receiver, placement["remoteTaskId"]), 1)
        origin_task = self.origin["store"].task(job["id"], "alice")
        self.assertIsNone(origin_task["run_id"])
        self.assertTrue(origin_task["terminal"])
        with mock.patch.object(self.handoff, "_request", side_effect=AssertionError("Local original-key receipt must not call receiver")):
            receipt = self.request("GET", "/requests/" + body["requestId"]).json()
        self.assertEqual(receipt["taskId"], job["id"])
        self.assertEqual(receipt["planId"], plan["id"])
        self.assertEqual(receipt["executionTargetRef"], self.target.reference)
        self.assertIsNone(receipt["runId"])
        artifact = detail["artifacts"][0]
        self.assertEqual(artifact["jobId"], job["id"])
        path = f'/jobs/{job["id"]}/artifacts/{artifact["id"]}'
        response = self.request("GET", path)
        self.assertEqual(hashlib.sha256(response.content).hexdigest(), artifact["sha256"])
        self.assertEqual(response.headers["X-Content-SHA256"], artifact["sha256"])
        self.assertEqual(response.json()["sha256"], hashlib.sha256(plan["normalizedGoal"].encode()).hexdigest())
        for protected in ("/jobs/" + job["id"], path, "/requests/" + body["requestId"]):
            self.request("GET", protected, owner="bob", expected=404)
        receiver_receipt = self.placement(job["id"])["body"]["receipt"]
        imported = self.receiver_client.post("/api/factory/instances", headers=self.headers("bob", self.receiver),
                                             json={"planId": receiver_receipt["remotePlanId"], "requestId": str(uuid4())})
        self.assertEqual(imported.status_code, 403, imported.text)
        raw = self.receiver_client.post("/agents/factory-executor/runs", headers=self.headers("bob", self.receiver),
                                        data={"message": "Controlled bypass attempt", "background": "true"})
        self.assertEqual(raw.status_code, 403, raw.text)
        self.request("POST", "/instances", expected=409,
                     json={"planId": plan["id"], "requestId": body["requestId"]})

    def test_03_native_question_stale_action_then_receiver_continuation(self):
        job, _ = self.submit(self.plan("sort", application="research"))
        detail = self.wait(job["id"], {"waiting_input", "failed"})
        self.assertEqual(detail["job"]["status"], "waiting_input", detail)
        question = detail["job"]["questionDetail"]
        body = {"questionId": question["id"], "version": question["version"] + 1,
                "answer": "Controlled synthetic sorting comparison scope"}
        self.request("POST", f'/jobs/{job["id"]}/answer', expected=409, json=body)
        self.assertEqual(self.wait(job["id"], {"waiting_input"})["job"]["questionDetail"], question)
        body["version"] = question["version"]
        self.request("POST", f'/jobs/{job["id"]}/answer', json=body)
        detail = self.wait(job["id"], {"completed", "failed"})
        self.assertEqual(detail["job"]["status"], "completed", detail)
        self.assertTrue(any(event["type"] == "question_answered" for event in detail["events"]))
        self.assertTrue(all(event["jobId"] == job["id"] for event in detail["events"]))
        self.assertEqual(self.ticket_count(self.origin), 0)

    def test_04_child_proxy_tree_scope_duplicate_and_root_cascade(self):
        root, _ = self.submit(self.plan("sort", application="research"))
        self.wait(root["id"], {"waiting_input"})
        body = {"goal": "sort", "mode": "literature", "requestId": str(uuid4())}
        path = f'/jobs/{root["id"]}/children'
        child = self.request("POST", path, expected=202, json=body).json()
        duplicate = self.request("POST", path, expected=202, json=body).json()
        child_id = child["job"]["id"]
        self.assertEqual(duplicate["job"]["id"], child_id)
        self.assertTrue(duplicate["duplicate"])
        self.assertTrue(child_id.startswith(root["id"] + "~"))
        self.assertEqual(child["childTask"]["id"], child_id)
        self.assertEqual(child["link"]["parent_id"], root["id"])
        self.assertEqual(child["link"]["root_id"], root["id"])
        self.assertEqual(child["link"]["child_id"], child_id)
        self.wait(child_id, {"waiting_input"})
        children = self.request("GET", path).json()
        self.assertEqual([fact["taskId"] for fact in children], [child_id])
        self.assertEqual(children[0]["link"]["parent_id"], root["id"])
        self.assertEqual(children[0]["link"]["child_id"], child_id)
        foreign, _ = self.submit(self.plan("sort", application="research"))
        self.wait(foreign["id"], {"waiting_input"})
        foreign_remote_id = self.placement(foreign["id"])["body"]["receipt"]["remoteTaskId"]
        self.request("GET", f'/jobs/{root["id"]}~{foreign_remote_id}', expected=404)
        self.request("GET", "/jobs/" + child_id, owner="bob", expected=404)
        self.request("POST", f'/jobs/{root["id"]}/cancel')
        stopped = self.wait(root["id"], {"canceled", "failed", "unknown"})
        self.assertEqual(stopped["job"]["status"], "canceled", stopped)
        self.assertTrue(stopped["snapshot"]["delegation"]["allStopped"])
        self.assertEqual(stopped["snapshot"]["delegation"]["parent"]["taskId"], root["id"])
        self.assertEqual(stopped["snapshot"]["delegation"]["children"][0]["taskId"], child_id)
        self.assertEqual(self.wait(child_id, {"canceled", "failed"})["job"]["status"], "canceled")
        remote_child_id = child_id.split("~", 1)[1]
        self.assertEqual(self.ticket_count(self.receiver, remote_child_id), 1)
        self.assertEqual(self.ticket_count(self.origin), 0)

    def test_05_lost_receiver_reply_read_only_recovery_without_second_dispatch(self):
        transport = ControlledDispatchLoss(self.receiver_app)
        self.install_transport(transport)
        job, body = self.submit(self.plan("sort", application="research"))
        self.wait(job["id"], {"waiting_input"})
        self.assertEqual(transport.attempts, 1)
        for state, owner in ((self.origin, "alice"), (self.receiver, "bob")):
            state["auth"].authorization.define_role("fixture-product-reader", ["agents:factory-executor:read",
                                                     "sessions:read", "components:read", "registry:read"])
            state["auth"].authorization.unassign(owner, "factory-user")
            state["auth"].authorization.assign(owner, "fixture-product-reader")
        receipt = self.request("GET", "/requests/" + body["requestId"]).json()
        self.assertEqual(receipt["taskId"], job["id"])
        self.assertEqual(receipt["executionTargetRef"], self.target.reference)
        detail = self.request("GET", "/jobs/" + job["id"]).json()
        self.assertEqual(detail["job"]["status"], "waiting_input")
        self.assertTrue(detail["snapshot"].get("run", detail["snapshot"]).get("readOnly"))
        self.assertEqual(self.request("GET", f'/jobs/{job["id"]}/children').json(), [])
        self.request("POST", f'/jobs/{job["id"]}/cancel', expected=403)
        self.request("POST", "/instances", expected=403, json=body)
        self.assertEqual(transport.attempts, 1)
        remote_id = detail["job"]["executionPlacement"]["remoteTaskId"]
        self.assertEqual(self.ticket_count(self.receiver, remote_id), 1)
        self.assertFalse(self.origin["store"].task(job["id"])["cancel_requested"])

    def test_06_lost_request_before_delivery_retains_unknown_and_never_replays(self):
        transport = ControlledDispatchLoss(self.receiver_app, before_delivery=True)
        self.install_transport(transport)
        job, body = self.submit(self.plan("sort", application="research"))
        self.assertEqual(job["status"], "unknown", job)
        for _ in range(2):
            duplicate = self.request("POST", "/instances", expected=202, json=body).json()
            self.assertEqual(duplicate["id"], job["id"])
            self.assertEqual(duplicate["status"], "unknown")
            self.request("GET", "/jobs/" + job["id"])
        self.assertEqual(transport.attempts, 1)
        row = self.placement(job["id"])
        self.assertEqual(row["state"], "DISPATCH_UNKNOWN")
        self.assertTrue(row["body"]["dispatchAttempted"])
        self.assertFalse(self.origin["store"].task(job["id"])["terminal"])
        self.assertEqual(self.ticket_count(self.receiver, row["body"]["receipt"]["remoteTaskId"]), 0)
        self.request("POST", f'/jobs/{job["id"]}/cancel')
        stopped = self.wait(job["id"], {"canceled", "failed"})
        self.assertEqual(stopped["job"]["status"], "canceled", stopped)
        self.assertEqual(stopped["snapshot"]["remoteHandoff"]["state"], "CANCELLED_NO_DISPATCH")
        self.assertTrue(stopped["snapshot"]["remoteHandoff"]["allStopped"])
        self.assertTrue(self.origin["store"].task(job["id"])["terminal"])
        self.assertEqual(transport.attempts, 1)

    def test_07_remote_artifact_hash_mismatch_is_rejected(self):
        job, _ = self.submit(self.plan("Controlled artifact integrity fixture"))
        detail = self.wait(job["id"], {"completed", "failed"})
        self.assertEqual(detail["job"]["status"], "completed", detail)
        artifact = detail["artifacts"][0]
        original = self.receiver["store"].artifact
        def corrupt(*args):
            metadata, raw = original(*args)
            return metadata, raw + b"controlled-integrity-failure"
        with mock.patch.object(self.receiver["store"], "artifact", side_effect=corrupt):
            self.request("GET", f'/jobs/{job["id"]}/artifacts/{artifact["id"]}', expected=409)

    def test_08_native_remote_approval_running_experiment_and_complete_cleanup(self):
        job, _ = self.submit(self.plan("Controlled remote synthetic sorting experiment", "experiment", "research"))
        detail = self.wait(job["id"], {"waiting_approval", "failed"})
        self.assertEqual(detail["job"]["status"], "waiting_approval", detail)
        approval = detail["job"]["approvalDetail"]
        body = {"requirementId": approval["id"], "version": approval["version"], "approved": True}
        self.request("POST", f'/jobs/{job["id"]}/approve', expected=409, json={**body, "version": body["version"] + 1})
        self.request("POST", f'/jobs/{job["id"]}/approve', json=body)
        remote_id = self.placement(job["id"])["body"]["receipt"]["remoteTaskId"]
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if any(event["type"] == "compute_started" for event in self.receiver["store"].events(remote_id)):
                break
            time.sleep(.02)
        else:
            self.fail("Actual fixed receiver experiment process did not start")
        self.request("POST", f'/jobs/{job["id"]}/cancel')
        stopped = self.wait(job["id"], {"canceled", "failed", "unknown"})
        self.assertEqual(stopped["job"]["status"], "canceled", stopped)
        self.assertTrue(stopped["snapshot"]["delegation"]["allStopped"])
        self.assertEqual([effect["status"] for effect in stopped["snapshot"]["effects"]], ["CANCELLED"])
        self.assertTrue(any(event["type"] == "compute_stopped" and event["data"].get("cleanupComplete")
                            for event in stopped["events"]))
        self.assertFalse(any(event["type"] == "experiment_completed" for event in stopped["events"]))
        self.assertEqual(self.ticket_count(self.origin), 0)


if __name__ == "__main__":
    unittest.main()
