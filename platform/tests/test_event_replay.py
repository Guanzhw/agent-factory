"""Factory cursor protocol tests: owned portable SQL + opt-in native PostgreSQL.

SQLite/native-auth cases prove cursor validation, scope and byte bounds only.
Generated PostgreSQL databases additionally prove actual Factory HTTP/native jobs,
snapshot/commit ordering, large history, concurrent CAS and API restart.
"""
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
import hashlib
import json
import os
from pathlib import Path
import secrets
from tempfile import TemporaryDirectory
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import Column, Integer, JSON, MetaData, String, Table, create_engine, select, text

from agent_factory.auth import AuthService
from agent_factory.config import Settings
from agent_factory.demo_model import DemoModel
from agent_factory.event_replay import EventReplay, event_replay_router
from agent_factory.main import create_app
from agent_factory.store import canonical, digest
from pg_fixture import IsolatedPostgres


class PortableEvents:
    """Owned metadata only: this fixture does not prove native queue durability."""
    def __init__(self, db):
        self.engine = db.db_engine
        self._connection = ContextVar("event_fixture_connection", default=None)
        metadata = MetaData()
        self.tasks = Table("af_tasks", metadata, Column("id", String, primary_key=True), Column("owner_id", String))
        self.events = Table("af_events", metadata, Column("id", Integer, primary_key=True, autoincrement=True),
            Column("task_id", String), Column("type", String), Column("message", String), Column("data", JSON), Column("created_at", String))
        metadata.create_all(self.engine)

    def add_task(self, owner, identifier=None):
        identifier = identifier or str(uuid4())
        with self.engine.begin() as conn:
            conn.execute(self.tasks.insert().values(id=identifier, owner_id=owner))
        return identifier

    def task(self, identifier, owner=None):
        borrowed = self._connection.get()
        if borrowed is not None:
            row = borrowed.execute(select(self.tasks).where(self.tasks.c.id == identifier)).mappings().first()
        else:
            with self.engine.connect() as conn:
                row = conn.execute(select(self.tasks).where(self.tasks.c.id == identifier)).mappings().first()
        if not row or owner is not None and row["owner_id"] != owner:
            raise HTTPException(404, "Task not found")
        return dict(row)

    def append(self, task, *, identifier=None, data=None):
        event = {"task_id": task, "type": "controlled_fixture", "message": "Original synthetic replay evidence",
                 "data": data or {}, "created_at": "2026-10-01T12:00:00+00:00"}
        if identifier is not None:
            event["id"] = identifier
        with self.engine.begin() as conn:
            return conn.execute(self.events.insert().values(**event)).inserted_primary_key[0]

    def many(self, first, other, count):
        values = []
        for index in range(count):
            values.extend([{ "task_id": first, "type": "controlled_fixture", "message": "Synthetic replay row",
                            "data": {"fixtureIndex": index}, "created_at": "2026-10-01T12:00:00+00:00"},
                           {"task_id": other, "type": "other_fixture", "message": "Other owner's synthetic row",
                            "data": {}, "created_at": "2026-10-01T12:00:00+00:00"}])
        with self.engine.begin() as conn:
            conn.execute(self.events.insert(), values)


class EventReplayTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.db = SqliteDb(db_file=str(Path(self.directory.name) / "owned-events.sqlite"))
        self.auth = AuthService(SimpleNamespace(demo=True, jwt_key=secrets.token_urlsafe(48)), self.db)
        self.auth.initialize_demo()
        self.store = PortableEvents(self.db)
        self.alice, self.bob = self.store.add_task("alice"), self.store.add_task("bob")
        self.service = EventReplay(self.store, self.auth, signing_key=self.auth._key)

    def tearDown(self):
        self.db.db_engine.dispose()
        self.directory.cleanup()

    def collect(self, *, service=None, task=None, cursor=None, limit=1000):
        service, task = service or self.service, task or self.alice
        events, pages = [], []
        for _ in range(100):
            page = service.page("alice", task, cursor=cursor, limit=limit)
            pages.append(page)
            events.extend(page["events"])
            cursor = page["nextCursor"]
            if not page["hasMore"]:
                return events, pages
        self.fail("Pagination did not converge")

    def test_empty_stream_restart_and_late_appends_use_stable_identity(self):
        first = self.service.page("alice", self.alice)
        self.assertEqual(first["events"], [])
        self.assertIsNone(first["startSequence"])
        self.assertEqual(first["highWatermark"], 0)
        self.assertFalse(first["hasMore"])
        self.assertFalse(first["nativeCursor"])
        restarted = EventReplay(self.store, self.auth, signing_key=self.auth._key)
        self.assertEqual(restarted.page("alice", self.alice, cursor=first["nextCursor"]), first)
        self.store.append(self.bob)
        identifier = self.store.append(self.alice)
        later = restarted.page("alice", self.alice, cursor=first["nextCursor"])
        self.assertEqual(later["streamId"], first["streamId"])
        self.assertEqual(later["events"][0]["id"], identifier)
        self.assertEqual(later["startSequence"], 1)
        self.assertEqual(later["highWatermarkSequence"], 1)

    def test_large_history_and_other_job_global_gaps_page_without_loss(self):
        self.store.many(self.alice, self.bob, 2157)
        first = self.service.page("alice", self.alice, limit=1000)
        self.assertEqual(len(first["events"]), 1000)
        second = self.service.page("alice", self.alice, cursor=first["nextCursor"], limit=1000)
        self.assertEqual(second, self.service.page("alice", self.alice, cursor=first["nextCursor"], limit=1000))
        events, pages = self.collect()
        self.assertEqual(len(events), 2157)
        self.assertEqual([event["sequence"] for event in events], list(range(1, 2158)))
        self.assertEqual(len(set(event["id"] for event in events)), 2157)
        self.assertTrue(all(events[index + 1]["id"] - events[index]["id"] == 2 for index in range(len(events) - 1)))
        self.assertEqual(pages[-1]["endSequence"], 2157)
        self.assertFalse(pages[-1]["hasMore"])
        for event in events:
            self.assertEqual(event["payloadSha256"], digest({key: value for key, value in event.items() if key not in {"payloadSha256", "sequence"}}))
        for page in pages:
            self.assertEqual(page["payloadSha256"], digest(page["events"]))

    def test_cursor_tampering_foreign_task_owner_key_and_schema_fail_closed(self):
        self.store.append(self.alice)
        first = self.service.page("alice", self.alice)
        token = first["nextCursor"]
        for invalid in ("invalid", token[:-1], "er2" + token[3:], token + "=", "x" * 4097):
            with self.assertRaises(HTTPException) as denied:
                self.service.page("alice", self.alice, cursor=invalid)
            self.assertEqual(denied.exception.status_code, 400)
        other_alice = self.store.add_task("alice")
        with self.assertRaises(HTTPException) as task:
            self.service.page("alice", other_alice, cursor=token)
        self.assertEqual(task.exception.status_code, 404)
        bob_token = self.service.page("bob", self.bob)["nextCursor"]
        with self.assertRaises(HTTPException) as owner:
            self.service.page("alice", self.alice, cursor=bob_token)
        self.assertEqual(owner.exception.status_code, 404)
        for actor in ("bob", "manager"):
            with self.assertRaises(HTTPException) as hidden:
                self.service.page(actor, self.alice, cursor=token)
            self.assertEqual(hidden.exception.status_code, 404)
        rotated = EventReplay(self.store, self.auth, signing_key=secrets.token_urlsafe(48))
        with self.assertRaises(HTTPException) as key:
            rotated.page("alice", self.alice, cursor=token)
        self.assertEqual(key.exception.status_code, 400)

    def test_cursor_from_different_database_cannot_bind_same_task_id(self):
        original = self.service.page("alice", self.alice)
        other_db = SqliteDb(db_file=str(Path(self.directory.name) / "second-owned-events.sqlite"))
        try:
            other = PortableEvents(other_db)
            other.add_task("alice", self.alice)
            receiver = EventReplay(other, self.auth, signing_key=self.auth._key)
            with self.assertRaises(HTTPException) as denied:
                receiver.page("alice", self.alice, cursor=original["nextCursor"])
            self.assertEqual(denied.exception.status_code, 404)
            self.assertNotEqual(receiver.page("alice", self.alice)["streamId"], original["streamId"])
        finally:
            other_db.db_engine.dispose()

    def test_small_page_byte_budget_paginates_and_oversize_event_is_explicit(self):
        service = EventReplay(self.store, self.auth, signing_key=self.auth._key, max_page_bytes=16384, max_event_bytes=8192)
        for _ in range(9):
            self.store.append(self.alice, data={"syntheticPayload": "界" * 1000})
        events, pages = self.collect(service=service)
        self.assertEqual(len(events), 9)
        self.assertGreater(len(pages), 1)
        for page in pages:
            self.assertLessEqual(len(canonical(page).encode()), 16384)
            self.assertEqual(page["payloadBytes"], len(canonical(page["events"]).encode()))
        self.store.append(self.alice, data={"syntheticPayload": "x" * 20000})
        with self.assertRaises(HTTPException) as oversized:
            service.page("alice", self.alice, cursor=pages[-1]["nextCursor"])
        self.assertEqual(oversized.exception.status_code, 413)
        self.assertIn("EVENT_INLINE_LIMIT", oversized.exception.detail)

    def test_current_native_read_is_checked_before_and_after_snapshot(self):
        self.store.append(self.alice)
        first = self.service.page("alice", self.alice)
        original = self.service._snapshot

        def revoke(*args):
            result = original(*args)
            self.auth.authorization.unassign("alice", "factory-user")
            return result

        with patch.object(self.service, "_snapshot", side_effect=revoke), self.assertRaises(HTTPException) as revoked:
            self.service.page("alice", self.alice, cursor=first["nextCursor"])
        self.assertEqual(revoked.exception.status_code, 403)
        with self.assertRaises(HTTPException):
            self.service.page("alice", self.alice)

    def test_late_lower_id_requires_replay_and_new_high_id_remains_normal(self):
        self.store.append(self.alice, identifier=10)
        first = self.service.page("alice", self.alice)
        self.store.append(self.bob, identifier=20)
        self.store.append(self.alice, identifier=30)
        normal = self.service.page("alice", self.alice, cursor=first["nextCursor"])
        self.assertEqual(normal["startSequence"], 2)
        self.assertEqual(normal["events"][0]["id"], 30)
        self.store.append(self.alice, identifier=5)
        with self.assertRaises(HTTPException) as changed:
            self.service.page("alice", self.alice, cursor=normal["nextCursor"])
        self.assertEqual(changed.exception.status_code, 409)
        self.assertIn("EVENT_PREFIX_CHANGED", changed.exception.detail)
        replay = self.service.page("alice", self.alice)
        self.assertEqual([event["id"] for event in replay["events"]], [5, 10, 30])
        self.assertEqual([event["sequence"] for event in replay["events"]], [1, 2, 3])
        self.assertEqual(replay["events"][1]["payloadSha256"], first["events"][0]["payloadSha256"])
        self.assertEqual(replay["events"][2]["payloadSha256"], normal["events"][0]["payloadSha256"])

    def test_exact_snapshot_excludes_append_after_sql_returns(self):
        identifier = self.store.append(self.alice)
        original = self.service._snapshot

        def append_later(*args):
            result = original(*args)
            self.store.append(self.alice)
            return result

        with patch.object(self.service, "_snapshot", side_effect=append_later):
            before = self.service.page("alice", self.alice)
        self.assertEqual(before["highWatermark"], identifier)
        self.assertEqual(before["highWatermarkSequence"], 1)
        self.assertFalse(before["hasMore"])
        later = self.service.page("alice", self.alice, cursor=before["nextCursor"])
        self.assertEqual(later["startSequence"], 2)
        self.assertGreater(later["highWatermark"], identifier)

    def test_limits_config_and_borrowed_connection_do_not_bypass_scope(self):
        for limit in (0, 1001, True, "100", 1.5):
            with self.assertRaises(HTTPException):
                self.service.page("alice", self.alice, limit=limit)
        for options in ({"signing_key": "short"}, {"signing_key": self.auth._key, "max_page_bytes": True},
                        {"signing_key": self.auth._key, "max_event_bytes": 1048576}):
            with self.assertRaises(ValueError):
                EventReplay(self.store, self.auth, **options)
        self.store.append(self.alice)
        with self.store.engine.begin() as conn:
            token = self.store._connection.set(conn)
            try:
                self.assertEqual(len(self.service.page("alice", self.alice)["events"]), 1)
                with self.assertRaises(HTTPException):
                    self.service.page("bob", self.alice)
            finally:
                self.store._connection.reset(token)

    def test_router_uses_actual_native_identity_and_current_read(self):
        self.store.append(self.alice)
        native = AgentOS(id="event-router-fixture", agents=[Agent(id="factory-executor", db=self.db, model=DemoModel(), telemetry=False)],
                         db=self.db, **self.auth.agentos_kwargs(), mcp=False, scheduler=False, telemetry=False).get_app()
        native.include_router(event_replay_router(self.auth, self.service))
        with TestClient(native) as client:
            alice = {"Authorization": "Bearer " + self.auth.issue_demo_token("alice")}
            bob = {"Authorization": "Bearer " + self.auth.issue_demo_token("bob")}
            path = "/api/factory/jobs/" + self.alice + "/events"
            self.assertEqual(client.get(path).status_code, 401)
            self.assertEqual(client.get(path, headers=bob).status_code, 404)
            self.assertEqual(client.get(path + "?limit=1001", headers=alice).status_code, 422)
            result = client.get(path, headers=alice)
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(result.json()["events"][0]["jobId"], self.alice)
            self.auth.directory.set_disabled("alice", True)
            self.assertEqual(client.get(path, headers=alice).status_code, 403)


@unittest.skipUnless(os.getenv("FACTORY_TEST_DATABASE_URL"), "Requires isolated PostgreSQL acceptance")
class EventReplayPostgresTests(unittest.TestCase):
    def setUp(self):
        self.database = IsolatedPostgres(os.environ["FACTORY_TEST_DATABASE_URL"]).__enter__()
        self.addCleanup(self.database.__exit__, None, None, None)
        self.directory = TemporaryDirectory()
        self.settings = Settings(db_url=self.database.url, workspace=Path(self.directory.name), max_workers=1)
        self.start()

    def start(self):
        self.app = create_app(self.settings)
        self.state = self.app.app.state.factory
        self.store, self.auth = self.state["store"], self.state["auth"]
        self.service = self.state["event_replay"]
        self.assertIs(self.store.event_replay, self.service)
        self.client = TestClient(self.app).__enter__()
        self.login()

    def stop(self):
        self.client.__exit__(None, None, None)
        self.store.engine.dispose()
        self.store.native_db.db_engine.dispose()

    def tearDown(self):
        self.stop()
        self.directory.cleanup()

    def login(self, owner="alice"):
        self.client.cookies.clear()
        response = self.client.post("/api/factory/demo/login", json={"persona": owner})
        self.assertEqual(response.status_code, 200, response.text)

    def job(self, owner="alice"):
        self.login(owner)
        proposal = self.client.post("/api/factory/plans", json={"topic": "Controlled replay checksum fixture", "mode": "literature", "application": "checksum", "requestId": str(uuid4())})
        self.assertEqual(proposal.status_code, 201, proposal.text)
        admitted = self.client.post("/api/factory/instances", json={"planId": proposal.json()["id"], "requestId": str(uuid4())})
        self.assertEqual(admitted.status_code, 202, admitted.text)
        job = admitted.json()
        end = time.monotonic() + 15
        while time.monotonic() < end:
            response = self.client.get("/api/factory/jobs/" + job["id"])
            self.assertEqual(response.status_code, 200, response.text)
            if response.json()["job"]["status"] in {"completed", "failed"}:
                self.assertEqual(response.json()["job"]["status"], "completed", response.text)
                return response.json()
            time.sleep(.03)
        self.fail("Native checksum did not complete")

    def http_page(self, task, cursor=None, limit=1000):
        response = self.client.get(f'/api/factory/jobs/{task}/events', params={"limit": limit, **({"cursor": cursor} if cursor else {})})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_actual_native_http_events_artifact_provenance_and_api_restart(self):
        detail = self.job()
        task = detail["job"]["id"]
        first = self.http_page(task, limit=2)
        next_page = self.http_page(task, first["nextCursor"], limit=2)
        self.assertEqual(next_page, self.http_page(task, first["nextCursor"], limit=2))
        artifact = detail["artifacts"][0]
        raw = self.client.get(f'/api/factory/jobs/{task}/artifacts/{artifact["id"]}').content
        self.assertEqual(hashlib.sha256(raw).hexdigest(), artifact["sha256"])
        self.stop()
        self.start()
        after_restart = self.http_page(task, first["nextCursor"], limit=2)
        self.assertEqual(after_restart, next_page)
        self.assertEqual(after_restart["streamId"], first["streamId"])
        self.login("bob")
        self.assertEqual(self.client.get(f'/api/factory/jobs/{task}/events').status_code, 404)
        self.login("alice")
        self.auth.authorization.unassign("alice", "factory-user")
        self.assertEqual(self.client.get(f'/api/factory/jobs/{task}/events').status_code, 403)

    def test_postgres_large_history_other_job_gaps_and_late_events(self):
        first_job, other_job = self.job(), self.job("bob")
        task, other = first_job["job"]["id"], other_job["job"]["id"]
        values = []
        for index in range(2157):
            values.extend([{"task": task, "data": json.dumps({"syntheticIndex": index})}, {"task": other, "data": "{}"}])
        with self.store.engine.begin() as conn:
            conn.execute(text("INSERT INTO af_events(task_id,type,message,data,created_at) VALUES(:task,'controlled_replay','Synthetic fixture',CAST(:data AS JSONB),'2026-10-01T12:00:00+00:00')"), values)
        count = self.store.sql("SELECT COUNT(*) AS n,MAX(id) AS maximum FROM af_events WHERE task_id=:task", task=task)[0]
        self.login("alice")
        cursor, events = None, []
        for _ in range(10):
            page = self.http_page(task, cursor)
            events.extend(page["events"])
            cursor = page["nextCursor"]
            self.assertEqual(page["highWatermark"], count["maximum"])
            if not page["hasMore"]:
                break
        self.assertEqual(len(events), count["n"])
        self.assertEqual([event["sequence"] for event in events], list(range(1, count["n"] + 1)))
        self.assertEqual(len(set(event["id"] for event in events)), count["n"])
        self.store.event(other, "other_late", "Other job global gap", {})
        self.store.event(task, "late_fixture", "Late original synthetic evidence", {})
        later = self.http_page(task, cursor)
        self.assertEqual(len(later["events"]), 1)
        self.assertEqual(later["startSequence"], count["n"] + 1)
        self.assertGreater(later["highWatermark"], count["maximum"])

    def test_postgres_lower_sequence_commit_is_detected_without_event_rewrite(self):
        detail = self.job()
        task = detail["job"]["id"]
        self.http_page(task)
        delayed = self.store.engine.connect()
        transaction = delayed.begin()
        try:
            low = delayed.execute(text("INSERT INTO af_events(task_id,type,message,data,created_at) VALUES(:task,'delayed_commit','Synthetic delayed fixture','{}'::jsonb,'2026-10-01T12:00:00+00:00') RETURNING id"), {"task": task}).scalar_one()
            self.store.event(task, "earlier_commit", "Higher ID committed first", {})
            visible = self.http_page(task)
            self.assertGreater(visible["highWatermark"], low)
            self.assertFalse(any(event["id"] == low for event in visible["events"]))
            transaction.commit()
            response = self.client.get(f'/api/factory/jobs/{task}/events', params={"cursor": visible["nextCursor"]})
            self.assertEqual(response.status_code, 409, response.text)
            self.assertIn("EVENT_PREFIX_CHANGED", response.text)
            replay = self.http_page(task)
            self.assertTrue(any(event["id"] == low for event in replay["events"]))
            self.assertEqual([event["sequence"] for event in replay["events"]], list(range(1, len(replay["events"]) + 1)))
        finally:
            if transaction.is_active:
                transaction.rollback()
            delayed.close()

    def test_native_protected_failure_persists_beyond_latest_thousand_display(self):
        detail = self.job()
        task = detail["job"]["id"]
        artifact = detail["artifacts"][0]
        artifact_path = f'/api/factory/jobs/{task}/artifacts/{artifact["id"]}'
        original_artifact = self.client.get(artifact_path).content
        self.store.event(task, "protected_denied", "Controlled synthetic protected-failure marker", {"syntheticFixture": True})
        values = [{"task": task, "data": json.dumps({"syntheticIndex": index})} for index in range(1107)]
        with self.store.engine.begin() as conn:
            conn.execute(text("INSERT INTO af_events(task_id,type,message,data,created_at) VALUES(:task,'controlled_replay','Synthetic later fixture',CAST(:data AS JSONB),'2026-10-01T12:00:00+00:00')"), values)
        display = self.store.events(task)
        self.assertEqual(len(display), 1000)
        self.assertEqual([event["id"] for event in display], sorted(event["id"] for event in display))
        self.assertFalse(any(event["type"] == "protected_denied" for event in display))
        self.assertTrue(self.store.has_failures(task))
        response = self.client.get("/api/factory/jobs/" + task)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["job"]["status"], "failed")
        self.assertEqual(self.client.get(artifact_path).content, original_artifact)
        first = self.http_page(task)
        self.assertTrue(any(event["type"] == "protected_denied" for event in first["events"]))
        self.assertTrue(first["hasMore"])
        last = self.http_page(task, first["nextCursor"])
        self.assertFalse(last["hasMore"])
        self.assertEqual(first["highWatermark"], last["highWatermark"])

    def test_postgres_concurrent_lazy_stream_cas_and_borrowed_pool_one(self):
        detail = self.job()
        task = detail["job"]["id"]
        services = [EventReplay(self.store, self.auth, signing_key=self.auth._key) for _ in range(2)]
        with ThreadPoolExecutor(max_workers=2) as pool:
            pages = list(pool.map(lambda service: service.page("alice", task), services))
        self.assertEqual(pages[0], pages[1])
        self.assertEqual(self.store.sql("SELECT COUNT(*) AS n FROM af_event_streams WHERE task_id=:task", task=task)[0]["n"], 1)
        original = self.store.engine
        bounded = create_engine(self.database.url, pool_size=1, max_overflow=0, pool_timeout=2)
        self.store.engine = bounded
        try:
            service = EventReplay(self.store, self.auth, signing_key=self.auth._key)
            with bounded.begin() as conn:
                token = self.store._connection.set(conn)
                try:
                    borrowed = service.page("alice", task)
                finally:
                    self.store._connection.reset(token)
            self.assertEqual(borrowed, pages[0])
            self.assertEqual(service.page("alice", task), borrowed)
        finally:
            self.store.engine = original
            bounded.dispose()


if __name__ == "__main__":
    unittest.main()
