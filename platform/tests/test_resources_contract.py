"""Persistent state contract + actual local Agno metadata route attachment.

Lifecycle/compute peers are explicitly synthetic httpx/provider fixtures. These
tests do not certify external execution, credentials, isolation or OS quotas.
"""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from urllib.parse import parse_qs
from uuid import uuid4

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS
from fastapi import HTTPException
import httpx
from sqlalchemy import create_engine, text

from agent_factory.demo_model import DemoModel
from agent_factory.resources import PersistentResourceService, RemoteTarget
from agent_factory.store import canonical


class AuthFixture:
    def __init__(self):
        self.revoked = set()

    def require(self, owner, action):
        if owner not in {"alice", "bob"} or owner in self.revoked or action != "run":
            raise HTTPException(403, "Current authority denied")


class DiskStoreFixture:
    """Actual disk SQL persistence using the resource/lease columns; SQLite here.

Production Store uses PostgreSQL and its global advisory lock. This portable
fixture does not claim PostgreSQL locking, native scheduling or native auth.
"""
    def __init__(self, path):
        self.engine = create_engine(f"sqlite:///{path}")
        for statement in [
            "CREATE TABLE IF NOT EXISTS af_resources(id TEXT PRIMARY KEY,owner_id TEXT,body TEXT)",
            "CREATE TABLE IF NOT EXISTS af_leases(id TEXT PRIMARY KEY,owner_id TEXT,target_id TEXT,request_id TEXT,fingerprint TEXT,state TEXT,body TEXT,UNIQUE(owner_id,request_id))",
            "CREATE TABLE IF NOT EXISTS fixture_tasks(id TEXT PRIMARY KEY,owner_id TEXT,plan_id TEXT,body TEXT)",
            "CREATE TABLE IF NOT EXISTS fixture_plans(id TEXT PRIMARY KEY,owner_id TEXT,body TEXT)",
            "CREATE TABLE IF NOT EXISTS fixture_audit(actor TEXT,action TEXT,target TEXT,body TEXT)",
            "CREATE TABLE IF NOT EXISTS fixture_artifacts(id TEXT PRIMARY KEY,task_id TEXT,body TEXT,content BLOB)",
        ]:
            self.sql(statement)

    def sql(self, statement, **params):
        with self.engine.begin() as conn:
            result = conn.execute(text(statement), params)
            return [dict(row) for row in result.mappings()] if result.returns_rows else []

    def task(self, task_id, owner=None):
        rows = self.sql("SELECT * FROM fixture_tasks WHERE id=:id", id=task_id)
        if not rows or owner is not None and rows[0]["owner_id"] != owner:
            raise HTTPException(404, "Scoped task not found")
        return {**rows[0], "terminal": False}

    def plan(self, plan_id, owner):
        rows = self.sql("SELECT body FROM fixture_plans WHERE id=:id AND owner_id=:owner", id=plan_id, owner=owner)
        if not rows:
            raise HTTPException(404, "Scoped plan not found")
        return json.loads(rows[0]["body"])

    def add_task(self, owner="alice"):
        task_id, plan_id = str(uuid4()), str(uuid4())
        plan = {"id": plan_id, "ownerId": owner, "status": "ready", "tools": ["checksum"], "syntheticFixture": True}
        self.sql("INSERT INTO fixture_plans VALUES(:id,:owner,:body)", id=plan_id, owner=owner, body=canonical(plan))
        self.sql("INSERT INTO fixture_tasks VALUES(:id,:owner,:plan,'{}')", id=task_id, owner=owner, plan=plan_id)
        return task_id

    def audit(self, actor, action, target, body):
        self.sql("INSERT INTO fixture_audit VALUES(:actor,:action,:target,:body)", actor=actor, action=action, target=target, body=canonical(body))

    def artifact_write(self, task_id, name, content, media_type, metadata):
        self.task(task_id)
        raw = content.encode()
        body = {"id": str(uuid4()), "jobId": task_id, "name": name, "sha256": hashlib.sha256(raw).hexdigest(),
                "mediaType": media_type, "size": len(raw), "provenance": metadata}
        self.sql("INSERT INTO fixture_artifacts VALUES(:id,:task,:body,:content)", id=body["id"], task=task_id, body=canonical(body), content=raw)
        return body


class NativePeerFixture:
    """Selected native route shapes; effects and acknowledgements are synthetic."""
    def __init__(self):
        self.epoch = "fixture-boot-1"
        self.version = "3.1.0"
        self.submissions = 0
        self.cancellations = 0
        self.disconnected = False
        self.lose_submit_ack = False
        self.lose_cancel_ack = False
        self.runs = {}
        self.envelopes = {}

    def handle(self, request):
        if self.disconnected:
            raise httpx.ConnectError("synthetic transport disconnected", request=request)
        path = request.url.path
        if path == "/info":
            return httpx.Response(200, json={"agno_version": self.version, "os_id": "fixture-os", "boot_epoch": self.epoch,
                                              "agent_count": 1, "auth_mode": "jwt", "user_isolation": True})
        if path == "/config":
            return httpx.Response(200, json={"agents": [{"id": "factory-executor"}]})
        if request.method == "POST" and path.endswith("/runs"):
            self.submissions += 1
            form = parse_qs(request.content.decode())
            session = form["session_id"][0]
            envelope = json.loads(form["session_state"][0])["factory_envelope"]
            self.envelopes[session] = envelope
            run = {"run_id": f"fixture-run-{self.submissions}", "session_id": session, "user_id": envelope["user_id"],
                   "agent_id": "factory-executor", "status": "PENDING", "content": "synthetic result, not research evidence"}
            self.runs[run["run_id"]] = run
            if self.lose_submit_ack:
                raise httpx.ReadTimeout("effect accepted but synthetic reply lost", request=request)
            return httpx.Response(202, json=run)
        if path.startswith("/sessions/"):
            session = path.split("/")[2]
            if path.endswith("/runs"):
                return httpx.Response(200, json=[r for r in self.runs.values() if r["session_id"] == session])
            return httpx.Response(200, json={"session_state": {"factory_envelope": self.envelopes.get(session, {})}})
        if path.endswith("/cancel"):
            self.cancellations += 1
            if self.lose_cancel_ack:
                raise httpx.ReadTimeout("synthetic cancellation reply lost", request=request)
            return httpx.Response(200, json={"status": "cancellation_requested"})
        run = self.runs.get(path.split("/")[-1])
        return httpx.Response(200, json=run) if run else httpx.Response(404, json={"detail": "not found"})


class ComputeProviderFixture:
    """No process/container/VM is allocated. State-only provider fixture."""
    def __init__(self):
        self.records = {}
        self.allocations = 0
        self.releases = 0
        self.cancellations = 0
        self.lose_ack = False
        self.release_confirmed = False
        self.cancel_confirmed = False

    async def allocate(self, lease_id, owner, fingerprint, limits):
        self.allocations += 1
        self.records[lease_id] = {"leaseId": lease_id, "ownerId": owner, "fingerprint": fingerprint,
                                  "state": "RUNNING", "providerJobId": "synthetic-compute", "limits": limits}
        if self.lose_ack:
            raise TimeoutError("synthetic allocation reply lost")
        return self.records[lease_id]

    async def inspect(self, lease_id, owner):
        record = self.records[lease_id]
        if self.release_confirmed:
            return {**record, "state": "RECLAIMED", "released": True}
        if self.cancel_confirmed:
            return {**record, "state": "CANCEL_CONFIRMED"}
        return record

    async def cancel(self, lease_id, owner):
        self.cancellations += 1
        return {"accepted": True}

    async def reclaim(self, lease_id, owner):
        self.releases += 1
        return {"accepted": True}


class ResourceContractTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "resources.sqlite"
        self.store = DiskStoreFixture(self.path)
        self.auth = AuthFixture()
        self.peer = NativePeerFixture()
        self.provider = ComputeProviderFixture()
        self.targets = {
            "runtime-ref": RemoteTarget("Synthetic native peer", "runtime", frozenset({"alice", "bob"}),
                base_url="http://127.0.0.1:1", transport=httpx.MockTransport(self.peer.handle),
                headers=lambda owner: {"Authorization": "Bearer synthetic-server-token"}, synthetic_fixture=True),
            "compute-ref": RemoteTarget("Synthetic provider", "compute", frozenset({"alice"}), provider=self.provider, synthetic_fixture=True),
            "a2a-ref": RemoteTarget("Optional interface", "a2a", frozenset({"alice"}), synthetic_fixture=True),
        }
        self.service = PersistentResourceService(self.store, self.auth, self.targets)
        self.task = self.store.add_task()

    async def asyncTearDown(self):
        self.store.engine.dispose()
        self.temp.cleanup()

    async def test_actual_installed_agno_metadata_attachment_no_run(self):
        db = SqliteDb(db_file=str(Path(self.temp.name) / "native.sqlite"))
        agent = Agent(id="factory-executor", model=DemoModel(), db=db, telemetry=False)
        os = AgentOS(id="actual-local-os", agents=[agent], db=db)
        target = RemoteTarget("Actual local metadata fixture", "runtime", frozenset({"alice"}),
                              base_url="http://local.native.fixture", transport=httpx.ASGITransport(app=os.get_app()), synthetic_fixture=True)
        service = PersistentResourceService(self.store, self.auth, {"actual-native": target})
        metadata = await service.attach("alice", "actual-native")
        self.assertTrue(metadata["serverVersion"].startswith("3.1."))
        self.assertEqual(metadata["capabilities"]["registeredExecutor"], "factory-executor")
        self.assertIsNone(metadata["bootEpoch"])
        self.assertFalse(metadata["bootEpochVerified"])
        self.assertFalse(metadata["allocationSupported"])
        self.assertEqual(metadata["capabilities"]["eventReplay"], "not_verified")
        self.assertEqual(self.store.sql("SELECT * FROM af_leases"), [])
        db.db_engine.dispose()

    async def test_registry_scoped_reference_only_and_three_axes(self):
        alice = self.service.discover("alice")
        self.assertEqual({r["axis"] for r in alice}, {"runtime", "compute", "a2a"})
        self.assertEqual(len(self.service.discover("bob")), 1)
        persisted = canonical(self.store.sql("SELECT body FROM af_resources"))
        self.assertNotIn("127.0.0.1", persisted)
        self.assertNotIn("synthetic-server-token", persisted)
        for ref in ["http://evil.example", "compute-ref"]:
            with self.assertRaises(HTTPException):
                await self.service.attach("bob", ref)
        optional = await self.service.attach("alice", "a2a-ref")
        self.assertFalse(optional["dispatchSupported"])
        with self.assertRaises(HTTPException):
            await self.service.allocate("alice", "runtime-ref", self.task, "allocate", {"cpu": 1})

    async def test_lost_ack_restart_reconcile_without_replay_or_release(self):
        self.peer.lose_submit_ack = True
        lease = await self.service.attach("alice", "runtime-ref", self.task, "request-1")
        self.assertEqual(lease["state"], "UNKNOWN")
        self.assertTrue(lease["capacityHeld"])
        self.store.engine.dispose()
        self.store = DiskStoreFixture(self.path)
        restarted = PersistentResourceService(self.store, self.auth, self.targets)
        again = await restarted.attach("alice", "runtime-ref", self.task, "request-1")
        self.assertEqual(again["id"], lease["id"])
        self.assertEqual(self.peer.submissions, 1)
        with self.assertRaises(HTTPException):
            await restarted.reclaim("alice", lease["id"])
        observed = await restarted.reconcile("alice", lease["id"])
        self.assertEqual(observed["state"], "ACCEPTED")
        self.assertEqual(observed["remoteRunId"], "fixture-run-1")
        self.assertEqual(observed["remoteSessionId"], self.task)
        self.assertTrue(observed["capacityHeld"])
        other_task = self.store.add_task()
        with self.assertRaises(HTTPException) as conflict:
            await restarted.attach("alice", "runtime-ref", other_task, "request-1")
        self.assertEqual(conflict.exception.status_code, 409)
        with self.assertRaises(HTTPException):
            await restarted.attach("alice", "runtime-ref", self.task, "different-request")
        self.assertEqual(self.peer.submissions, 1)

    async def test_foreign_fingerprint_and_epoch_are_not_adopted(self):
        self.peer.lose_submit_ack = True
        lease = await self.service.attach("alice", "runtime-ref", self.task, "request-epoch")
        self.peer.envelopes[self.task]["resource_fingerprint"] = "wrong"
        result = await self.service.reconcile("alice", lease["id"])
        self.assertEqual(result["state"], "UNKNOWN")
        self.assertIsNone(result["remoteRunId"])
        self.peer.epoch = "fixture-boot-2"
        result = await self.service.reconcile("alice", lease["id"])
        self.assertTrue(result["epochMismatch"])
        self.assertTrue(result["capacityHeld"])

    async def test_disconnect_cancel_ack_terminal_artifact_and_runtime_reclaim(self):
        lease = await self.service.attach("alice", "runtime-ref", self.task, "request-cancel")
        disconnected = self.service.disconnect("alice", lease["id"])
        self.assertFalse(disconnected["connected"])
        self.assertEqual(self.peer.cancellations, 0)
        self.assertFalse(disconnected["cancelRequested"])
        accepted = await self.service.cancel("alice", lease["id"])
        self.assertEqual(accepted["state"], "CANCEL_REQUESTED")
        self.assertTrue(accepted["capacityHeld"])
        await self.service.cancel("alice", lease["id"])
        self.assertEqual(self.peer.cancellations, 1)
        pending = await self.service.reconcile("alice", lease["id"])
        self.assertEqual(pending["state"], "CANCEL_REQUESTED")
        self.peer.runs[lease["remoteRunId"]]["status"] = "CANCELLED"
        confirmed = await self.service.reconcile("alice", lease["id"])
        self.assertEqual(confirmed["state"], "CANCEL_CONFIRMED")
        self.assertTrue(confirmed["capacityHeld"])
        artifact = confirmed["artifacts"][0]
        row = self.store.sql("SELECT * FROM fixture_artifacts WHERE id=:id", id=artifact["id"])[0]
        self.assertEqual(hashlib.sha256(row["content"]).hexdigest(), artifact["sha256"])
        self.assertEqual(artifact["provenance"]["connectionRef"], "runtime-ref")
        self.assertTrue(artifact["provenance"]["syntheticFixture"])
        self.assertFalse(artifact["provenance"]["researchValidated"])
        result = await self.service.reclaim("alice", lease["id"])
        self.assertFalse(result["capacityHeld"])
        self.assertEqual(result["releaseScope"], "runtime_attachment_only")

    async def test_lost_cancel_reply_is_not_replayed(self):
        lease = await self.service.attach("alice", "runtime-ref", self.task, "request-cancel-lost")
        self.peer.lose_cancel_ack = True
        uncertain = await self.service.cancel("alice", lease["id"])
        self.assertEqual(uncertain["state"], "UNKNOWN")
        await self.service.cancel("alice", lease["id"])
        self.assertEqual(self.peer.cancellations, 1)
        self.assertTrue(self.service.inspect("alice", lease["id"])["capacityHeld"])

    async def test_capacity_scope_heartbeat_and_revocation(self):
        self.peer.lose_submit_ack = True
        first = await self.service.attach("alice", "runtime-ref", self.task, "cap-1")
        second_task = self.store.add_task("bob")
        await self.service.attach("bob", "runtime-ref", second_task, "cap-2")
        with self.assertRaises(HTTPException) as exhausted:
            await self.service.attach("alice", "runtime-ref", self.store.add_task(), "cap-3")
        self.assertEqual(exhausted.exception.status_code, 429)
        with self.assertRaises(HTTPException):
            self.service.heartbeat("bob", first["id"])
        renewed = self.service.heartbeat("alice", first["id"])
        self.assertEqual(renewed["deadlineAt"], first["deadlineAt"])
        self.auth.revoked.add("alice")
        with self.assertRaises(HTTPException):
            await self.service.cancel("alice", first["id"])
        self.assertEqual(self.peer.cancellations, 0)

    async def test_compute_provider_separate_allocation_release_confirmation(self):
        limits = {"cpu": 1, "memoryMb": 512, "diskMb": 128, "seconds": 20}
        self.provider.lose_ack = True
        lease = await self.service.allocate("alice", "compute-ref", self.task, "compute-1", limits)
        self.assertEqual(lease["state"], "UNKNOWN")
        await self.service.allocate("alice", "compute-ref", self.task, "compute-1", limits)
        self.assertEqual(self.provider.allocations, 1)
        observed = await self.service.reconcile("alice", lease["id"])
        self.assertEqual(observed["state"], "RUNNING")
        accepted = await self.service.cancel("alice", lease["id"])
        self.assertEqual(accepted["state"], "CANCEL_REQUESTED")
        self.provider.cancel_confirmed = True
        await self.service.reconcile("alice", lease["id"])
        releasing = await self.service.reclaim("alice", lease["id"])
        self.assertTrue(releasing["capacityHeld"])
        self.assertEqual(releasing["state"], "RECLAIMING")
        with self.assertRaises(HTTPException):
            await self.service.reclaim("alice", lease["id"])
        self.assertEqual(self.provider.releases, 1)
        self.provider.release_confirmed = True
        released = await self.service.reconcile("alice", lease["id"])
        self.assertEqual(released["state"], "RECLAIMED")
        self.assertFalse(released["capacityHeld"])
        with self.assertRaises(HTTPException):
            await self.service.allocate("alice", "compute-ref", self.task, "too-large", {**limits, "cpu": 100})

    async def test_version_url_and_production_identity_fail_closed(self):
        self.peer.version = "3.1.99"
        with self.assertRaises(HTTPException) as unsupported:
            await self.service.attach("alice", "runtime-ref")
        self.assertEqual(unsupported.exception.status_code, 409)
        self.assertEqual(self.peer.submissions, 0)
        for url in ["file:///tmp/anything", "https://user:secret@example.com", "https://example.com?token=secret", "https://example.com#fragment"]:
            with self.assertRaises(ValueError):
                RemoteTarget("Invalid operator URL", "runtime", frozenset({"alice"}), base_url=url, synthetic_fixture=True)
        with self.assertRaises(ValueError):
            RemoteTarget("Missing trusted credentials", "runtime", frozenset({"alice"}), base_url="https://example.com")

    async def test_expired_lease_retains_capacity_and_heartbeat_cannot_extend_it(self):
        lease = await self.service.attach("alice", "runtime-ref", self.task, "expiry-1")
        body = {**lease, "deadlineAt": "2000-01-01T00:00:00+00:00"}
        self.store.sql("UPDATE af_leases SET body=:body WHERE id=:id", body=canonical(body), id=lease["id"])
        expired = self.service.inspect("alice", lease["id"])
        self.assertTrue(expired["expired"])
        self.assertTrue(expired["capacityHeld"])
        with self.assertRaises(HTTPException):
            self.service.heartbeat("alice", lease["id"])
        with self.assertRaises(HTTPException):
            await self.service.reclaim("alice", lease["id"])
        self.assertEqual(self.peer.cancellations, 0)

    async def test_provider_foreign_snapshot_is_not_adopted(self):
        limits = {"cpu": 1, "memoryMb": 512, "diskMb": 128, "seconds": 20}
        lease = await self.service.allocate("alice", "compute-ref", self.task, "foreign-provider", limits)
        self.provider.records[lease["id"]]["fingerprint"] = "foreign-work"
        snapshot = await self.service.reconcile("alice", lease["id"])
        self.assertEqual(snapshot["state"], "UNKNOWN")
        self.assertTrue(snapshot["capacityHeld"])
        self.assertFalse(snapshot["connected"])

    async def test_operator_reference_rebinding_cannot_redirect_existing_effect(self):
        lease = await self.service.attach("alice", "runtime-ref", self.task, "rebind-1")
        self.service.targets["runtime-ref"] = RemoteTarget("Rebound target", "runtime", frozenset({"alice"}),
            base_url="http://127.0.0.1:2", transport=httpx.MockTransport(self.peer.handle), synthetic_fixture=True)
        with self.assertRaises(HTTPException) as rebound:
            await self.service.cancel("alice", lease["id"])
        self.assertEqual(rebound.exception.status_code, 409)
        self.assertEqual(self.peer.cancellations, 0)
        row = self.store.sql("SELECT body FROM af_leases WHERE id=:id", id=lease["id"])[0]
        self.assertTrue(json.loads(row["body"])["capacityHeld"])


if __name__ == "__main__":
    unittest.main()
