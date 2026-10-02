"""Opt-in official PostgreSQL dump/restore of an owned synthetic Factory fixture.

The app, native queue, managed SQL roles, review/material policies and artifacts
are real. One UNKNOWN reservation is deliberately created without a ticket.
This proves clean-stop schema/data recovery, not production RPO/RTO, PITR,
concurrent backup consistency, external workspace/credential backup or load.
Only generated loopback databases and a private temporary dump are used.
"""
import hashlib
import os
from pathlib import Path
import re
import secrets
import subprocess
import tempfile
import time
import unittest
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from agent_factory.auth import EXECUTOR_ID
from agent_factory.config import Settings
from agent_factory.main import create_app
from agent_factory.store import digest
from pg_fixture import IsolatedPostgres


def pg_tools():
    configured = os.getenv("FACTORY_PG_BIN")
    if not configured:
        return None
    suffix = ".exe" if os.name == "nt" else ""
    tools = tuple(Path(configured) / (name + suffix) for name in ("pg_dump", "pg_restore"))
    return tools if all(tool.is_file() for tool in tools) else None


@unittest.skipUnless(os.getenv("FACTORY_TEST_DATABASE_URL") and pg_tools(),
                     "Requires disposable loopback PostgreSQL and opt-in FACTORY_PG_BIN")
class PostgreSQLRestoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.source = IsolatedPostgres(os.environ["FACTORY_TEST_DATABASE_URL"]).__enter__()
        self.addCleanup(self.source.__exit__, None, None, None)
        self.target = IsolatedPostgres(os.environ["FACTORY_TEST_DATABASE_URL"]).__enter__()
        self.addCleanup(self.target.__exit__, None, None, None)
        self.fixture_key = secrets.token_urlsafe(48)
        self.policy_revision = "restore-policy-" + uuid4().hex
        self.material_revision = "restore-material-policy-" + uuid4().hex
        self.handles = []
        self.addCleanup(self.close_apps)

    def app(self, database, workspace_name):
        settings = Settings(db_url=database.url, jwt_key=self.fixture_key,
            workspace=Path(self.directory.name) / workspace_name, max_workers=1,
            max_user_tasks=1, temporary_policy="admin-review", policy_revision=self.policy_revision,
            material_policy_revision=self.material_revision)
        app = create_app(settings)
        client = TestClient(app).__enter__()
        state = app.app.state.factory
        handle = (client, state["store"], state)
        self.handles.append(handle)
        return handle

    def close_app(self, handle):
        if handle not in self.handles:
            return
        client, store, _state = handle
        try:
            # Actual composed native queue and SchedulePoller lifespan stops.
            client.__exit__(None, None, None)
        finally:
            store.engine.dispose()
            store.native_db.db_engine.dispose()
            self.handles.remove(handle)

    def close_apps(self):
        for handle in list(reversed(self.handles)):
            self.close_app(handle)

    def login(self, client, persona="alice"):
        client.cookies.clear()
        response = client.post("/api/factory/demo/login", json={"persona": persona})
        self.assertEqual(response.status_code, 200)

    def approved_plan(self, client, policy, application):
        self.login(client)
        result = client.post("/api/factory/plans", json={
            "topic": "Original synthetic restore " + application + " fixture", "mode": "literature",
            "application": application, "requestId": uuid4().hex})
        self.assertEqual(result.status_code, 201)
        plan = result.json()
        review = policy.request_review("alice", plan["id"], uuid4().hex)
        decision = policy.decide("manager", review["id"], True, uuid4().hex)
        self.assertTrue(decision["approvalEffective"])
        return plan["id"], review["id"]

    def wait_completed(self, client, task_id):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            response = client.get("/api/factory/jobs/" + task_id)
            self.assertEqual(response.status_code, 200)
            body = response.json()
            if body["job"]["status"] in {"completed", "failed"}:
                self.assertEqual(body["job"]["status"], "completed")
                return body
            time.sleep(.05)
        self.fail("Real native checksum ticket did not complete")

    def database_snapshot(self, url):
        """Compare every owned table's schema/data digest without exposing rows."""
        engine = create_engine(url)
        try:
            inspector = inspect(engine)
            quote = engine.dialect.identifier_preparer.quote
            snapshot = {}
            with engine.connect() as connection:
                for schema in sorted(set(inspector.get_schema_names()) - {"information_schema", "pg_catalog"}):
                    for table in sorted(inspector.get_table_names(schema=schema)):
                        columns = inspector.get_columns(table, schema=schema)
                        statement = f"SELECT row_to_json(t) AS row FROM {quote(schema)}.{quote(table)} t ORDER BY row_to_json(t)::text"
                        rows = connection.execute(text(statement)).scalars().all()
                        snapshot[schema + "." + table] = {
                            "columns": [(column["name"], str(column["type"]), column["nullable"], column["default"]) for column in columns],
                            "primaryKey": inspector.get_pk_constraint(table, schema=schema)["constrained_columns"],
                            "count": len(rows), "dataDigest": digest(list(rows))}
            return snapshot
        finally:
            engine.dispose()

    def postgres_command(self, binary, database, arguments):
        url = make_url(database.url)
        if url.host not in {"127.0.0.1", "localhost", "::1"} or not re.fullmatch(r"af_test_[a-f0-9]{32}", url.database or ""):
            raise ValueError("Restore acceptance refuses nonfixture/nonloopback targets")
        home = Path(self.directory.name) / "isolated-pg-home"
        home.mkdir(exist_ok=True)
        pgpass = home / "empty-pgpass"
        pgpass.write_text("", encoding="utf-8")
        environment = {name: os.environ[name] for name in ("SystemRoot", "WINDIR", "TEMP", "TMP", "PATH", "LANG", "LC_ALL") if name in os.environ}
        # Subprocess-only homes prevent libpq reading a personal pgpass,
        # service/config or SSL certificate. No provider environment is copied.
        environment.update(HOME=str(home), USERPROFILE=str(home), APPDATA=str(home),
                           PGPASSFILE=str(pgpass), PGSYSCONFDIR=str(home), PGCONNECT_TIMEOUT="5", PGCLIENTENCODING="UTF8")
        if url.password is not None:
            environment["PGPASSWORD"] = url.password
        command = [str(binary), "--host", url.host, "--port", str(url.port or 5432),
                   "--username", url.username, "--dbname", url.database, "--no-password", *arguments]
        result = subprocess.run(command, env=environment, capture_output=True, timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        # Neither command args containing a password nor full database output
        # is included in failure reports. Dump/restore writes only fixture data.
        self.assertEqual(result.returncode, 0, Path(binary).name + " failed; captured private diagnostic output is not printed")

    def test_official_clean_dump_restore_preserves_evidence_authority_and_unknown_capacity(self):
        source_handle = self.app(self.source, "source-workspace")
        client, store, state = source_handle
        auth, policy, governance = state["auth"], state["plan_policy"], state["material_governance"]
        plan_id, review_id = self.approved_plan(client, policy, "checksum")
        admitted_key = uuid4().hex
        admitted = client.post("/api/factory/instances", json={"planId": plan_id, "requestId": admitted_key})
        self.assertEqual(admitted.status_code, 202)
        task_id = admitted.json()["id"]
        detail = self.wait_completed(client, task_id)
        artifact = detail["artifacts"][0]
        artifact_path = f"/api/factory/jobs/{task_id}/artifacts/{artifact['id']}"
        content = client.get(artifact_path)
        self.assertEqual(content.status_code, 200)
        artifact_bytes = content.content
        self.assertEqual(hashlib.sha256(artifact_bytes).hexdigest(), artifact["sha256"])
        run_id = store.task(task_id, "alice")["run_id"]
        self.assertEqual(store.native_db.get_job(run_id)["status"], "completed")

        unknown_plan_id, unknown_review_id = self.approved_plan(client, policy, "research")
        unknown_key = uuid4().hex
        unknown, fresh = store.reserve_task(store.plan(unknown_plan_id, "alice"), unknown_key)
        self.assertTrue(fresh)
        store.admission_unknown(unknown["id"])
        self.assertFalse(store.task(unknown["id"], "alice")["terminal"])
        self.assertIsNone(store.task(unknown["id"], "alice")["run_id"])

        # Current managed SQL grants override the old role in any JWT. Alice
        # retains owner evidence reads while the run grant is revoked.
        reader_role = "restore-fixture-reader"
        reader_scopes = [f"agents:{EXECUTOR_ID}:read", "sessions:read", "components:read", "filesystem:read"]
        auth.authorization.define_role(reader_role, reader_scopes)
        auth.authorization.unassign("alice", "factory-user")
        auth.authorization.assign("alice", reader_role)
        with self.assertRaises(HTTPException) as denied:
            auth.require("alice", "run")
        self.assertEqual(denied.exception.status_code, 403)
        auth.require("alice", "read")
        governance.withdraw("manager", "checksum-tool", 1, uuid4().hex, "Synthetic current policy withdrawal after completed evidence")
        governance.archive("manager", "research-prompt", 1, uuid4().hex, "Synthetic archival after UNKNOWN reservation")
        old_plan, old_unknown_plan = store.plan(plan_id, "alice"), store.plan(unknown_plan_id, "alice")
        old_task, old_unknown = store.task(task_id, "alice"), store.task(unknown["id"], "alice")
        old_policy, old_governance = policy.current(), governance.current()
        source_materials = {mid: governance.inspect_version("manager", mid, 1) for mid in ("checksum-tool", "research-prompt")}
        source_review = policy.inspect("manager", review_id)
        source_unknown_review = policy.inspect("manager", unknown_review_id)
        source_cookie = dict(client.cookies)
        self.close_app(source_handle)

        expected = self.database_snapshot(self.source.url)
        self.assertIn("ai.agno_jobs", expected)
        self.assertEqual(expected["ai.agno_jobs"]["count"], 1)
        self.assertEqual(expected["public.af_tasks"]["count"], 2)
        self.assertEqual(self.database_snapshot(self.target.url), {})
        dump = Path(self.directory.name) / "owned-fixture.dump"
        binaries = pg_tools()
        self.postgres_command(binaries[0], self.source,
            ["--format=custom", "--no-owner", "--no-acl", "--file", str(dump)])
        self.assertTrue(dump.is_file())
        self.assertGreater(dump.stat().st_size, 0)
        self.postgres_command(binaries[1], self.target,
            ["--no-owner", "--no-acl", "--exit-on-error", str(dump)])
        self.assertEqual(self.database_snapshot(self.target.url), expected)

        restored_handle = self.app(self.target, "new-empty-target-workspace")
        restored_client, restored_store, restored_state = restored_handle
        restored_auth = restored_state["auth"]
        self.assertEqual(restored_state["plan_policy"].current(), old_policy)
        self.assertEqual(restored_state["material_governance"].current(), old_governance)
        self.assertEqual(restored_store.plan(plan_id, "alice"), old_plan)
        self.assertEqual(restored_store.plan(unknown_plan_id, "alice"), old_unknown_plan)
        self.assertEqual(restored_store.sql("SELECT hash FROM af_plans WHERE id=:id", id=plan_id)[0]["hash"], digest(old_plan))
        self.assertEqual(restored_store.task(task_id, "alice"), old_task)
        restored_unknown = restored_store.task_for_request(unknown_key, "alice")
        # Schema/data digests were exact before startup. The trusted background
        # observer may now add cancel intent because current run rights/material
        # authority are revoked; immutable receipt and UNKNOWN hold stay intact.
        for key in ("id", "owner_id", "plan_id", "request_id", "fingerprint", "admission", "run_id", "terminal"):
            self.assertEqual(restored_unknown[key], old_unknown[key], key)
        self.assertEqual(restored_unknown["body"]["createdAt"], old_unknown["body"]["createdAt"])
        self.assertFalse(restored_unknown["terminal"])
        self.assertIsNone(restored_unknown["run_id"])
        self.assertEqual(restored_store.native_db.get_job(run_id)["status"], "completed")
        self.assertEqual(restored_state["plan_policy"].inspect("manager", review_id), source_review)
        self.assertEqual(restored_state["plan_policy"].inspect("manager", unknown_review_id), source_unknown_review)
        self.assertEqual(set(restored_auth.authorization.roles_of("alice")), {reader_role})
        restored_auth.require("alice", "read")
        with self.assertRaises(HTTPException) as revoked:
            restored_auth.require("alice", "run")
        self.assertEqual(revoked.exception.status_code, 403)
        restored_auth.require("manager", "agent_os:admin")

        # Preserve the source synthetic cookie to verify trusted same-key
        # restart without provisioning/reassigning the revoked principal.
        restored_client.cookies.update(source_cookie)
        evidence = restored_client.get(artifact_path)
        self.assertEqual(evidence.status_code, 200)
        self.assertEqual(evidence.content, artifact_bytes)
        self.assertEqual(hashlib.sha256(evidence.content).hexdigest(), artifact["sha256"])
        job = restored_client.get("/api/factory/jobs/" + task_id)
        self.assertEqual(job.status_code, 200)
        self.assertEqual(job.json()["job"]["status"], "completed")
        self.assertEqual(job.json()["artifacts"], detail["artifacts"])
        receipt = restored_client.get("/api/factory/requests/" + unknown_key)
        self.assertEqual(receipt.status_code, 200)
        self.assertEqual(receipt.json()["taskId"], unknown["id"])
        self.assertEqual(receipt.json()["admission"], "unknown")
        self.assertIsNone(receipt.json()["runId"])
        self.assertEqual(restored_client.post("/api/factory/instances", json={"planId": unknown_plan_id, "requestId": unknown_key}).status_code, 403)
        with self.assertRaises(HTTPException) as held:
            restored_store.reserve_task(old_unknown_plan, uuid4().hex)
        self.assertEqual(held.exception.status_code, 429, "Restored UNKNOWN reservation must continue holding the owner's capacity")
        self.assertEqual(restored_store.sql("SELECT COUNT(*) AS n FROM ai.agno_jobs")[0]["n"], 1)
        self.assertEqual(restored_store.sql("SELECT COUNT(*) AS n FROM af_tasks")[0]["n"], 2)
        for mid, material in source_materials.items():
            self.assertEqual(restored_state["material_governance"].inspect_version("manager", mid, 1), material)
        with self.assertRaises(HTTPException) as withdrawn:
            restored_state["material_governance"].require_materials_current(old_plan)
        self.assertEqual(withdrawn.exception.status_code, 409)
        self.assertEqual(restored_client.post(f"/agents/{EXECUTOR_ID}/runs", data={"message": "blocked raw entry"}).status_code, 403)
        self.close_app(restored_handle)


if __name__ == "__main__":
    unittest.main()
