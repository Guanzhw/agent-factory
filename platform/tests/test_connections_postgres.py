"""Actual Factory/native SQL authorization and owner connection persistence.

Opaque handles are inert objects, never provider credentials or model calls.
Fixtures use generated loopback PostgreSQL databases and controlled synthetic
identities. Tests exercise main application wiring when installed and otherwise
mount only the owned connection router into the controlled Factory fixture.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from agent_factory.auth import EXECUTOR_ID
from agent_factory.catalog import create_plan
from agent_factory.config import Settings
from agent_factory.connections import ConnectionService, TrustedConnectionBinding, connection_router
from agent_factory.main import create_app
from agent_factory.store import Store
from pg_fixture import IsolatedPostgres


class OpaqueFixture:
    def __repr__(self):
        return "synthetic-internal-handle-never-public"


@unittest.skipUnless(os.getenv("FACTORY_TEST_DATABASE_URL"), "Requires disposable loopback PostgreSQL")
class ConnectionPostgresTests(unittest.TestCase):
    def setUp(self):
        self.database = IsolatedPostgres(os.environ["FACTORY_TEST_DATABASE_URL"]).__enter__()
        self.addCleanup(self.database.__exit__, None, None, None)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.at = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)
        self.handle, self.bob_handle = OpaqueFixture(), OpaqueFixture()
        self.registry = {
            "alice-model": TrustedConnectionBinding("alice", "model", "inert-model-adapter",
                frozenset({"model:synthetic", "model:stream"}), "fixture-v1", expires_at=self.at + timedelta(seconds=60),
                available=True, opaque_handle=self.handle, handle_ref="inert-alice-handle-v1"),
            "alice-orx-missing": TrustedConnectionBinding("alice", "orx", "unconfigured-orx-adapter",
                frozenset({"research:read"}), "fixture-unconfigured-v1"),
            "bob-model": TrustedConnectionBinding("bob", "model", "inert-model-adapter",
                frozenset({"model:synthetic"}), "fixture-v1", available=True,
                opaque_handle=self.bob_handle, handle_ref="inert-bob-handle-v1")}
        self.settings = Settings(db_url=self.database.url, workspace=Path(self.directory.name), max_workers=1, max_user_tasks=8)
        self.settings.trusted_connections = self.registry
        self.app = create_app(self.settings)
        self.state = self.app.app.state.factory
        self.store, self.auth = self.state["store"], self.state["auth"]
        self.addCleanup(self.store.engine.dispose)
        self.addCleanup(self.store.native_db.db_engine.dispose)
        if "connections" in self.state:
            self.service = self.state["connections"]
            self.service.clock = lambda: self.at
        else:
            self.service = ConnectionService(self.store, self.auth, self.registry, clock=lambda: self.at)
            self.app.app.include_router(connection_router(self.auth, self.service))
        self.client = TestClient(self.app).__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def login(self, persona="alice"):
        self.client.cookies.clear()
        response = self.client.post("/api/factory/demo/login", json={"persona": persona})
        self.assertEqual(response.status_code, 200)

    def bind(self, **kwargs):
        return self.service.bind("alice", "alice-model", uuid4().hex, **kwargs)

    def pins(self, bound):
        return {"expected_revision": bound["revision"], "expected_fingerprint": bound["fingerprint"],
                "expected_version": bound["version"], "required_capabilities": ["model:synthetic"]}

    def test_01_authenticated_two_user_lifecycle_and_public_redaction(self):
        path = "/api/factory/user-connections"
        self.assertEqual(self.client.get(path).status_code, 401)
        self.login()
        registrations = self.client.get(path + "/registrations")
        self.assertEqual(registrations.status_code, 200)
        self.assertEqual({row["registrationRef"] for row in registrations.json()}, {"alice-model", "alice-orx-missing"})
        request = {"registrationRef": "alice-model", "requestId": uuid4().hex, "capabilities": ["model:synthetic"]}
        result = self.client.post(path, json=request)
        self.assertEqual(result.status_code, 201)
        bound = result.json()
        self.assertEqual(bound["status"], "active")
        self.assertTrue(bound["available"])
        self.assertEqual(bound["allowedActions"], ["inspect", "revoke"])
        self.assertIs(self.service.resolve("alice", bound["ref"], "model", **self.pins(bound)), self.handle)
        self.assertEqual(self.client.post(path, json=request).json(), bound)
        public = json.dumps([registrations.json(), bound, self.service.list("alice")])
        for forbidden in ("opaque_handle", "adapterRef", "handleRef", "inert-alice-handle-v1", repr(self.handle)):
            self.assertNotIn(forbidden, public)
        stored = self.store.sql("SELECT body FROM af_user_connections")
        self.assertNotIn(repr(self.handle), json.dumps(stored))
        self.assertNotIn("adapterRef", json.dumps(stored))
        self.login("bob")
        self.assertEqual(self.client.get(path + "/" + bound["ref"]).status_code, 404)
        self.assertEqual(self.client.post(path + "/" + bound["ref"] + "/revoke", json={"requestId": uuid4().hex}).status_code, 404)
        self.assertEqual(self.client.post(path, json={**request, "requestId": uuid4().hex}).status_code, 404)
        own = self.client.post(path, json={"registrationRef": "bob-model", "requestId": request["requestId"]})
        self.assertEqual(own.status_code, 201)
        self.assertNotEqual(own.json()["ref"], bound["ref"])
        self.assertIs(self.service.resolve("bob", own.json()["ref"], "model"), self.bob_handle)
        self.login()
        decision = {"requestId": uuid4().hex}
        revoked = self.client.post(path + "/" + bound["ref"] + "/revoke", json=decision)
        self.assertEqual(revoked.status_code, 200)
        self.assertEqual(revoked.json()["status"], "revoked")
        self.assertFalse(revoked.json()["available"])
        self.assertEqual(revoked.json()["allowedActions"], ["inspect"])
        self.assertEqual(self.client.post(path + "/" + bound["ref"] + "/revoke", json=decision).json(), revoked.json())
        with self.assertRaises(HTTPException) as no_handle:
            self.service.resolve("alice", bound["ref"], "model", **self.pins(bound))
        self.assertEqual(no_handle.exception.status_code, 409)
        restarted = ConnectionService(self.store, self.auth, self.registry, clock=lambda: self.at)
        self.assertEqual(restarted.inspect("alice", bound["ref"]), revoked.json())
        with self.assertRaises(HTTPException) as still_revoked:
            restarted.resolve("alice", bound["ref"], "model", **self.pins(bound))
        self.assertEqual(still_revoked.exception.status_code, 409)

    def test_02_user_secret_url_and_owner_overrides_are_rejected(self):
        self.login()
        body = {"registrationRef": "alice-model", "requestId": uuid4().hex}
        for extra in ({"ownerId": "bob"}, {"token": "synthetic-rejected-token"}, {"url": "https://fixtures.invalid"},
                      {"adapterRef": "other"}, {"opaque_handle": "never-user-input"}, {"revision": "user-forged"}):
            with self.subTest(extra=list(extra)):
                self.assertEqual(self.client.post("/api/factory/user-connections", json={**body, **extra}).status_code, 422)
        for reference in ("https://fixtures.invalid", "sk-proj-" + "X" * 24, "../outside"):
            self.assertEqual(self.client.post("/api/factory/user-connections", json={**body, "registrationRef": reference}).status_code, 400)
        self.assertEqual(self.store.sql("SELECT COUNT(*) AS n FROM af_user_connections")[0]["n"], 0)

    def test_03_concurrent_idempotent_binding_and_changed_intent_conflict(self):
        key = uuid4().hex
        def same_bind(_index):
            return self.service.bind("alice", "alice-model", key, capabilities=["model:synthetic"])
        with ThreadPoolExecutor(max_workers=4) as workers:
            results = list(workers.map(same_bind, range(6)))
        self.assertEqual(len({row["ref"] for row in results}), 1)
        self.assertEqual(self.store.sql("SELECT COUNT(*) AS n FROM af_user_connections")[0]["n"], 1)
        self.assertEqual(self.store.sql("SELECT COUNT(*) AS n FROM af_connection_commands")[0]["n"], 1)
        self.assertEqual(self.store.sql("SELECT COUNT(*) AS n FROM af_audit WHERE action='connection.bind'")[0]["n"], 1)
        with self.assertRaises(HTTPException) as changed:
            self.service.bind("alice", "alice-model", key, capabilities=["model:stream"])
        self.assertEqual(changed.exception.status_code, 409)
        with self.assertRaises(HTTPException) as operation:
            self.service.revoke("alice", results[0]["ref"], key)
        self.assertEqual(operation.exception.status_code, 409)

    def test_04_unconfigured_removed_and_empty_registrations_fail_closed(self):
        unavailable = self.service.bind("alice", "alice-orx-missing", uuid4().hex)
        self.assertEqual(unavailable["status"], "unavailable")
        with self.assertRaises(HTTPException) as missing_adapter:
            self.service.resolve("alice", unavailable["ref"], "orx", required_capabilities=["research:read"])
        self.assertEqual(missing_adapter.exception.status_code, 409)
        with self.assertRaises(HTTPException) as missing_ref:
            self.service.bind("alice", "missing-registration", uuid4().hex)
        self.assertEqual(missing_ref.exception.status_code, 404)
        bound = self.bind()
        self.registry.pop("alice-model")
        self.assertEqual(self.service.inspect("alice", bound["ref"])["status"], "missing")
        with self.assertRaises(HTTPException) as removed:
            self.service.preflight("alice", bound["ref"], "model", **self.pins(bound))
        self.assertEqual(removed.exception.status_code, 409)
        empty = ConnectionService(self.store, self.auth)
        self.assertEqual(empty.registrations("bob"), [])
        self.assertEqual(empty.list("bob"), [])

    def test_05_expiry_recheck_and_restart_preserve_owner_reference(self):
        bound = self.bind()
        restarted = ConnectionService(self.store, self.auth, self.registry, clock=lambda: self.at)
        self.assertEqual(restarted.inspect("alice", bound["ref"]), bound)
        self.assertIs(restarted.resolve("alice", bound["ref"], "model", **self.pins(bound)), self.handle)
        self.at += timedelta(seconds=60)
        self.assertEqual(restarted.inspect("alice", bound["ref"])["status"], "expired")
        with self.assertRaises(HTTPException) as expired:
            restarted.resolve("alice", bound["ref"], "model", **self.pins(bound))
        self.assertIn("CONNECTION_EXPIRED", str(expired.exception.detail))

    def test_06_changed_revision_scope_and_handle_identity_cannot_rebind_old_reference(self):
        bound = self.bind()
        original = self.registry["alice-model"]
        self.registry["alice-model"] = replace(original, capabilities=frozenset({"model:stream"}))
        self.assertEqual(self.service.inspect("alice", bound["ref"])["status"], "changed")
        with self.assertRaises(HTTPException):
            self.service.resolve("alice", bound["ref"], "model")
        with self.assertRaises(ValueError):
            ConnectionService(self.store, self.auth, self.registry)
        self.registry["alice-model"] = replace(original, opaque_handle=OpaqueFixture())
        with self.assertRaises(HTTPException) as swapped:
            self.service.resolve("alice", bound["ref"], "model")
        self.assertIn("CONNECTION_CHANGED", str(swapped.exception.detail))
        replacement = replace(original, revision="fixture-v2", handle_ref="inert-alice-handle-v2", opaque_handle=OpaqueFixture())
        self.registry["alice-model"] = replacement
        changed = ConnectionService(self.store, self.auth, self.registry, clock=lambda: self.at)
        self.assertEqual(changed.inspect("alice", bound["ref"])["status"], "changed")
        with self.assertRaises(HTTPException):
            changed.resolve("alice", bound["ref"], "model", **self.pins(bound))
        new = changed.bind("alice", "alice-model", uuid4().hex)
        self.assertNotEqual(new["ref"], bound["ref"])
        self.assertEqual(new["revision"], "fixture-v2")
        self.assertIs(changed.resolve("alice", new["ref"], "model", **self.pins(new)), replacement.opaque_handle)

    def test_07_exact_pins_and_capability_intersection(self):
        bound = self.bind(capabilities=["model:synthetic"])
        for changed in ({"expected_revision": "changed"}, {"expected_version": 2}, {"expected_version": True},
                        {"expected_fingerprint": "0" * 64}, {"required_capabilities": ["model:stream"]},
                        {"expected_adapter_ref": "different-adapter"}):
            with self.subTest(changed=list(changed)):
                with self.assertRaises(HTTPException) as denied:
                    self.service.resolve("alice", bound["ref"], "model", **(self.pins(bound) | changed))
                self.assertEqual(denied.exception.status_code, 409)
        with self.assertRaises(HTTPException):
            self.service.resolve("alice", bound["ref"], "orx")
        with self.assertRaises(HTTPException):
            self.bind(capabilities=["arbitrary:grant"])

    def test_08_task_scope_cannot_cross_owner_task_cancel_or_terminal(self):
        plan = create_plan(self.store, "alice", "owned scope fixture", "literature", "checksum")
        first = self.store.reserve_task(plan, uuid4().hex)[0]
        second = self.store.reserve_task(plan, uuid4().hex)[0]
        bob_plan = create_plan(self.store, "bob", "other owned fixture", "literature", "checksum")
        bob = self.store.reserve_task(bob_plan, uuid4().hex)[0]
        bound = self.bind(task_id=first["id"])
        self.assertIs(self.service.resolve("alice", bound["ref"], "model", task_id=first["id"], **self.pins(bound)), self.handle)
        for other in (None, second["id"], bob["id"]):
            with self.subTest(other=other):
                with self.assertRaises(HTTPException):
                    self.service.resolve("alice", bound["ref"], "model", task_id=other, **self.pins(bound))
        with self.assertRaises(HTTPException) as other_owner:
            self.bind(task_id=bob["id"])
        self.assertEqual(other_owner.exception.status_code, 404)
        self.store.request_cancel(first["id"])
        self.assertEqual(self.service.inspect("alice", bound["ref"])["status"], "task_ended")
        with self.assertRaises(HTTPException):
            self.service.resolve("alice", bound["ref"], "model", task_id=first["id"])
        second_ref = self.bind(task_id=second["id"])
        self.store.observed(second, "completed", True)
        with self.assertRaises(HTTPException):
            self.service.preflight("alice", second_ref["ref"], "model", task_id=second["id"])

    def test_09_current_sql_authority_denies_resolution_but_allows_revoke(self):
        bound = self.bind()
        self.auth.authorization.define_role("inert-fixture-reader", [f"agents:{EXECUTOR_ID}:read", "components:read", "sessions:read"])
        # Native assign() is create-if-absent bootstrap; set_role() changes
        # CURRENT SQL grants for an already assigned controlled fixture owner.
        self.auth.authorization.set_role("alice", "inert-fixture-reader")
        self.assertEqual(self.service.inspect("alice", bound["ref"])["ref"], bound["ref"])
        for registration in self.service.registrations("alice"):
            self.assertEqual(registration["allowedActions"], ["inspect"])
        for operation in (lambda: self.service.resolve("alice", bound["ref"], "model"),
                          lambda: self.service.preflight("alice", bound["ref"], "model"), lambda: self.bind()):
            with self.assertRaises(HTTPException) as denied:
                operation()
            self.assertEqual(denied.exception.status_code, 403)
        self.assertEqual(self.service.revoke("alice", bound["ref"], uuid4().hex)["status"], "revoked")
        self.auth.directory.set_disabled("alice", True)
        with self.assertRaises(HTTPException) as disabled:
            self.service.inspect("alice", bound["ref"])
        self.assertEqual(disabled.exception.status_code, 403)

    def test_10_immutable_metadata_tamper_fails_before_handle(self):
        bound = self.bind()
        with self.store.engine.begin() as conn:
            row = dict(conn.execute(self.service.references.select().where(self.service.references.c.ref == bound["ref"])).mappings().one())
            body = dict(row["body"], capabilities=["forged:scope"])
            conn.execute(self.service.references.update().where(self.service.references.c.ref == bound["ref"]).values(body=body))
        with self.assertRaises(HTTPException) as corrupt:
            self.service.resolve("alice", bound["ref"], "model")
        self.assertIn("CONNECTION_INTEGRITY", str(corrupt.exception.detail))

    def test_11_borrowed_transaction_uses_one_pool_slot_and_current_state(self):
        bounded = Store(self.database.url, self.settings)
        bounded.engine.dispose()
        bounded.engine = create_engine(self.database.url, pool_size=1, max_overflow=0, pool_timeout=.25)
        self.addCleanup(bounded.engine.dispose)
        service = ConnectionService(bounded, self.auth, self.registry, clock=lambda: self.at)
        bound = service.bind("alice", "alice-model", uuid4().hex, capabilities=["model:synthetic"])
        pins = self.pins(bound) | {"expected_adapter_ref": "inert-model-adapter"}
        plan = create_plan(self.store, "alice", "single connection task fixture", "literature", "checksum")
        task = self.store.reserve_task(plan, uuid4().hex)[0]
        with bounded.engine.connect() as conn:
            transaction = conn.begin()
            token = bounded._connection.set(conn)
            try:
                self.assertEqual(bounded.engine.pool.checkedout(), 1)
                self.assertEqual(service.preflight("alice", bound["ref"], "model", **pins), bound)
                self.assertIs(service.resolve("alice", bound["ref"], "model", **pins), self.handle)
                self.assertIs(service.resolve("alice", bound["ref"], "model", task_id=task["id"], **pins), self.handle)
                self.assertEqual(service.inspect("alice", bound["ref"]), bound)
                self.assertEqual(service.list("alice"), [bound])
                self.assertEqual(len(service.registrations("alice")), 2)
                # An independent connection would miss this transaction's
                # uncommitted current revocation (and exceed the one-slot pool).
                conn.execute(service.references.update().where(service.references.c.ref == bound["ref"])
                             .values(state="REVOKED", revoked_at=self.at.isoformat()))
                for check in (service.preflight, service.resolve):
                    with self.assertRaises(HTTPException) as denied:
                        check("alice", bound["ref"], "model", **pins)
                    self.assertIn("CONNECTION_REVOKED", str(denied.exception.detail))
                self.assertEqual(bounded.engine.pool.checkedout(), 1)
            finally:
                bounded._connection.reset(token)
                transaction.rollback()
        self.assertIsNone(bounded._connection.get())
        self.assertIs(service.resolve("alice", bound["ref"], "model", **pins), self.handle)
        self.assertIs(service.resolve("alice", bound["ref"], "model", task_id=task["id"], **pins), self.handle)
        self.assertEqual(bounded.engine.pool.checkedout(), 0)
        # Owned mutation transactions must also share nested task/plan reads.
        scoped = service.bind("alice", "alice-model", uuid4().hex, task_id=task["id"])
        self.assertEqual(scoped["taskId"], task["id"])
        self.assertIs(service.resolve("alice", scoped["ref"], "model", task_id=task["id"], **self.pins(scoped)), self.handle)
        self.assertEqual(service.revoke("alice", scoped["ref"], uuid4().hex)["status"], "revoked")
        self.assertEqual(bounded.engine.pool.checkedout(), 0)
        self.assertIsNone(bounded._connection.get())


class TrustedBindingValidationTests(unittest.TestCase):
    def test_operator_only_handle_and_metadata_constraints(self):
        common = dict(owner="synthetic-owner", kind="model", adapter_ref="fixture", capabilities=frozenset(), revision="v1")
        for changes in ({"available": True}, {"available": False, "opaque_handle": OpaqueFixture()},
                        {"expires_at": datetime(2026, 10, 2)}, {"adapter_ref": "https://fixtures.invalid"},
                        {"revision": "sk-proj-" + "X" * 24}, {"capabilities": "invalid-collection"}):
            with self.subTest(changes=list(changes)):
                with self.assertRaises(ValueError):
                    TrustedConnectionBinding(**(common | changes))


if __name__ == "__main__":
    unittest.main()
