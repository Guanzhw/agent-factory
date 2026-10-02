"""Exact inert application distribution, with independent local publication.

Portable cases use synthetic SQLite metadata and actual native managed Auth;
they do not claim queue or concurrency coverage. Opt-in PostgreSQL cases use
two independent generated databases and the wired native Factory executor.
No source approvals, credentials, runtime code or production grants are imported.
"""
from concurrent.futures import ThreadPoolExecutor
import copy
import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from typing import Any
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.engine import make_url

from agent_factory.config import Settings
from agent_factory.main import create_app
from agent_factory.store import digest
from pg_fixture import IsolatedPostgres
from test_applications_composition import ApplicationCompositionFixture, app_definition, pin


def rehash(value):
    value["sha256"] = digest({key: item for key, item in value.items() if key != "sha256"})
    return value


class ApplicationSnapshotPortableTests(ApplicationCompositionFixture):
    def snapshot(self, identifier="owned-distributed-application", version=1):
        # Original inert structured fixture. Real source creation/distribution
        # is independently exercised below between two PostgreSQL Factories.
        definition = self.applications.validate_definition(app_definition(self.store, identifier), check_materials=False)
        return rehash({**definition, "version": version, "schema": 1,
                       "createdAt": "2026-10-01T09:07:06.123456+09:00", "origin": "manager-authored"})

    def count(self, table):
        with self.applications.db.read() as conn:
            return conn.execute(select(func.count()).select_from(table)).scalar_one()

    def publish_import(self, snapshot, key="import"):
        self.applications.import_snapshot("manager", snapshot, key)
        review = self.applications.request_publication("manager", snapshot["id"], snapshot["version"], key + "-review")
        self.applications.decide_publication("bob", review["id"], True, key + "-approve")
        return review

    def test_exact_body_digest_timestamp_local_draft_and_separate_publication(self):
        snapshot = self.snapshot()
        expected = copy.deepcopy(snapshot)
        with patch("subprocess.Popen") as process:
            imported = self.applications.import_snapshot("manager", snapshot, "snapshot-one")
        self.assertEqual(imported, expected)
        self.assertEqual(process.call_count, 0)
        snapshot["description"] = "Caller mutation does not alter the immutable ledger."
        inspected = self.applications.inspect("manager", expected["id"], expected["version"])
        self.assertEqual(inspected["application"], expected)
        self.assertEqual(inspected["governance"]["author_id"], "manager")
        self.assertEqual(inspected["governance"]["state"], "draft")
        self.assertFalse(inspected["governance"]["bootstrap"])
        self.assertIsNone(inspected["governance"]["review_id"])
        self.assertEqual(self.count(self.applications.reviews), 0)
        with self.assertRaises(HTTPException) as unpublished:
            self.applications.require_current(pin(expected))
        self.assertEqual(unpublished.exception.status_code, 409)
        review = self.applications.request_publication("manager", expected["id"], 1, "local-review")
        with self.assertRaises(HTTPException) as self_review:
            self.applications.decide_publication("manager", review["id"], True, "self-denied")
        self.assertEqual(self_review.exception.status_code, 403)
        self.applications.decide_publication("bob", review["id"], True, "separate-local-reviewer")
        self.assertEqual(self.applications.require_current(pin(expected)), expected)
        self.assertEqual(self.applications.inspect("manager", expected["id"], 1)["application"], expected)

    def test_current_native_admin_required_even_for_idempotent_receipt(self):
        snapshot = self.snapshot()
        self.auth.directory.upsert("owned-editor", name="Original isolated synthetic editor")
        self.auth.authorization.define_role("owned-editor-role", ["components:read", "components:write"])
        self.auth.authorization.assign("owned-editor", "owned-editor-role")
        for actor in ("alice", "owned-editor"):
            with self.subTest(actor=actor), self.assertRaises(HTTPException) as denied:
                self.applications.import_snapshot(actor, snapshot, "denied-" + actor)
            self.assertEqual(denied.exception.status_code, 403)
        imported = self.applications.import_snapshot("manager", snapshot, "current-admin")
        self.auth.authorization.unassign("manager", "factory-manager")
        with self.assertRaises(HTTPException) as revoked:
            self.applications.import_snapshot("manager", snapshot, "current-admin")
        self.assertEqual(revoked.exception.status_code, 403)
        self.assertEqual(imported, snapshot)

    def test_complete_canonical_safe_schema_hash_and_timezone_are_enforced(self):
        snapshot = self.snapshot()
        invalid = []
        def case(label, mutate, *, hash_again=True):
            value = copy.deepcopy(snapshot)
            mutate(value)
            invalid.append((label, rehash(value) if hash_again else value))
        case("source-approval", lambda value: value.update(reviewId="not-inherited", approved=True))
        case("body-identity", lambda value: value.update(authorId="another-user"))
        case("missing-description", lambda value: value.pop("description"))
        case("missing-defaults", lambda value: value["modes"]["literature"].pop("budget"))
        case("naive-time", lambda value: value.update(createdAt="2026-10-01T09:07:06"))
        case("invalid-calendar", lambda value: value.update(createdAt="2026-02-30T09:07:06+00:00"))
        case("boolean-schema", lambda value: value.update(schema=True))
        case("boolean-version", lambda value: value.update(version=True))
        case("overflow-version", lambda value: value.update(version=2147483648))
        case("bootstrap-origin", lambda value: value.update(origin="demo-bootstrap"))
        case("missing-id", lambda value: value.update(id=None))
        case("raw-credential", lambda value: value.update(api_key="original-synthetic-forbidden-placeholder"))
        case("digest", lambda value: value.update(sha256="0" * 64), hash_again=False)
        case("missing-hash", lambda value: value.pop("sha256"), hash_again=False)
        case("unbounded-input", lambda value: value.update(description="x" * 140000))
        case("noncanonical-budget", lambda value: value["modes"]["literature"]["budget"].update(toolCalls="8"))
        before = self.count(self.applications.versions)
        for label, value in invalid:
            with self.subTest(label=label), self.assertRaises(HTTPException) as rejected:
                self.applications.import_snapshot("manager", value, "invalid-" + label)
            self.assertEqual(rejected.exception.status_code, 422)
        self.assertEqual(self.count(self.applications.versions), before)
        self.assertEqual(self.count(self.applications.commands), 0)

    def test_semantic_key_and_immutable_version_conflicts_never_overwrite(self):
        snapshot = self.snapshot()
        result = self.applications.import_snapshot("manager", snapshot, "exact-intent")
        self.assertEqual(self.applications.import_snapshot("manager", copy.deepcopy(snapshot), "exact-intent"), result)
        changed = rehash({**snapshot, "description": "A different fully valid synthetic intent."})
        for key in ("exact-intent", "different-key"):
            with self.subTest(key=key), self.assertRaises(HTTPException) as conflict:
                self.applications.import_snapshot("manager", changed, key)
            self.assertEqual(conflict.exception.status_code, 409)
        self.assertEqual(self.applications.inspect("manager", snapshot["id"], 1)["application"], snapshot)
        self.assertEqual(self.count(self.applications.commands), 1)

    def test_new_versions_require_monotonic_lineage_but_preserve_source_number(self):
        first = self.snapshot(version=5)
        self.assertEqual(self.applications.import_snapshot("manager", first, "source-version-five"), first)
        historical = rehash({**first, "version": 4})
        with self.assertRaises(HTTPException) as older:
            self.applications.import_snapshot("manager", historical, "source-version-four")
        self.assertEqual(older.exception.status_code, 409)
        latest = rehash({**first, "version": 8, "description": "Original later version."})
        self.assertEqual(self.applications.import_snapshot("manager", latest, "source-version-eight"), latest)
        self.assertEqual(self.applications.inspect("manager", first["id"], 5)["application"], first)
        with self.assertRaises(HTTPException) as no_gap_fill:
            self.applications.import_snapshot("manager", rehash({**first, "version": 6}), "no-gap-fill")
        self.assertEqual(no_gap_fill.exception.status_code, 409)

    def test_observing_published_archived_or_withdrawn_body_never_resets_local_review(self):
        for action in (None, "archive", "withdraw"):
            with self.subTest(action=action):
                snapshot = self.snapshot("owned-" + (action or "published"))
                self.publish_import(snapshot, "original-" + (action or "published"))
                if action:
                    getattr(self.applications, action)("bob", snapshot["id"], 1, "retire-" + action, "Owned synthetic retirement")
                before = self.applications.inspect("manager", snapshot["id"], 1)
                self.assertEqual(self.applications.import_snapshot("bob", snapshot, "observe-" + (action or "published")), snapshot)
                after = self.applications.inspect("manager", snapshot["id"], 1)
                self.assertEqual(after, before)
                self.assertEqual(after["governance"]["author_id"], "manager")
                if action:
                    with self.assertRaises(HTTPException):
                        self.applications.require_current(pin(snapshot))
                else:
                    self.assertEqual(self.applications.require_current(pin(snapshot)), snapshot)

    def test_local_material_approval_is_rechecked_without_erasing_receipts(self):
        snapshot = self.snapshot()
        accepted = self.applications.import_snapshot("manager", snapshot, "before-material-withdrawal")
        assert self.store.material_governance is not None
        self.store.material_governance.withdraw("bob", "synthetic-knowledge", 1, "withdraw-local-material", "Original isolated test")
        # Exact retry recovers the original immutable import receipt; it does
        # not restore material publication or approve the local application.
        self.assertEqual(self.applications.import_snapshot("manager", snapshot, "before-material-withdrawal"), accepted)
        for body, key in ((snapshot, "new-observation"), (rehash({**snapshot, "id": "new-local-import"}), "new-import")):
            with self.subTest(key=key), self.assertRaises(HTTPException) as denied:
                self.applications.import_snapshot("manager", body, key)
            self.assertEqual(denied.exception.status_code, 409)
        with self.assertRaises(HTTPException):
            self.applications.request_publication("manager", snapshot["id"], 1, "no-current-review")
        self.assertEqual(self.applications.inspect("manager", snapshot["id"], 1)["application"], snapshot)


class OwnedFactory:
    """Generated native database and workspace, owned only by this test."""
    def __init__(self, test):
        base = make_url(os.environ["FACTORY_TEST_DATABASE_URL"])
        base = base.set(query={**base.query, "connect_timeout": "5"})
        self.database = IsolatedPostgres(base.render_as_string(hide_password=False)).__enter__()
        test.addCleanup(self.database.__exit__, None, None, None)
        self.directory = TemporaryDirectory()
        test.addCleanup(self.directory.cleanup)
        self.settings = Settings(db_url=self.database.url, workspace=Path(self.directory.name), max_workers=1)
        self.client: Any = None
        test.addCleanup(self.stop)
        self.start()
        # Explicit separate native administrator inside this generated DB.
        self.auth.authorization.unassign("bob", "factory-user")
        self.auth.authorization.assign("bob", "factory-manager")

    def start(self):
        self.app: Any = create_app(self.settings)
        state = self.app.app.state.factory
        self.store, self.auth = state["store"], state["auth"]
        self.applications, self.composition = state["applications"], state["composition"]
        self.client = TestClient(self.app).__enter__()

    def stop(self):
        if self.client is not None:
            self.client.__exit__(None, None, None)
            self.client = None
            self.store.engine.dispose()
            self.store.native_db.db_engine.dispose()

    def source_snapshot(self):
        application = self.applications.create_draft("manager", app_definition(self.store, "independently-distributed-config"), "source-draft")
        review = self.applications.request_publication("manager", application["id"], 1, "source-review")
        self.applications.decide_publication("bob", review["id"], True, "source-approve")
        return application


@unittest.skipUnless(os.getenv("FACTORY_TEST_DATABASE_URL"), "Requires isolated PostgreSQL/native Factory acceptance")
class ApplicationSnapshotPostgresTests(unittest.TestCase):
    def setUp(self):
        self.origin = OwnedFactory(self)
        self.receiver = OwnedFactory(self)
        self.snapshot = self.origin.source_snapshot()
        self.assertNotEqual(self.origin.database.url, self.receiver.database.url)

    def test_exact_independent_distribution_requires_receiver_review_then_executes_native_checksum(self):
        source, receiver, snapshot = self.origin, self.receiver, self.snapshot
        self.assertEqual(receiver.applications.import_snapshot("manager", snapshot, "receiver-import"), snapshot)
        with self.assertRaises(HTTPException) as unpublished:
            receiver.composition.create_plan("alice", "Checksum the original synthetic receiver fixture", "literature", application_ref=pin(snapshot))
        self.assertEqual(unpublished.exception.status_code, 409)
        review = receiver.applications.request_publication("manager", snapshot["id"], 1, "receiver-review")
        with self.assertRaises(HTTPException) as self_review:
            receiver.applications.decide_publication("manager", review["id"], True, "receiver-self-denied")
        self.assertEqual(self_review.exception.status_code, 403)
        receiver.applications.decide_publication("bob", review["id"], True, "receiver-separate-reviewer")
        self.assertEqual(receiver.applications.require_current(pin(snapshot)), source.applications.require_current(pin(snapshot)))
        plan = receiver.composition.create_plan("alice", "Checksum original independent receiver evidence", "literature", application_ref=pin(snapshot))
        self.assertEqual(plan["applicationRef"], pin(snapshot))
        headers = {"Authorization": "Bearer " + receiver.auth.issue_demo_token("alice")}
        admitted = receiver.client.post("/api/factory/instances", headers=headers,
            json={"planId": plan["id"], "requestId": "receiver-native-instance"})
        self.assertEqual(admitted.status_code, 202, admitted.text)
        identifier = admitted.json()["id"]
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            response = receiver.client.get("/api/factory/jobs/" + identifier, headers=headers)
            self.assertEqual(response.status_code, 200, response.text)
            detail = response.json()
            if detail["job"]["status"] in {"completed", "failed", "cancelled"}:
                break
            time.sleep(.03)
        else:
            self.fail("Owned native receiver job did not become terminal")
        self.assertEqual(detail["job"]["status"], "completed", detail)
        self.assertTrue(detail["artifacts"])
        artifact = detail["artifacts"][0]
        raw = receiver.client.get(f'/api/factory/jobs/{identifier}/artifacts/{artifact["id"]}', headers=headers).content
        self.assertEqual(hashlib.sha256(raw).hexdigest(), artifact["sha256"])
        self.assertEqual(json.loads(raw)["algorithm"], "sha256")
        self.assertEqual(source.store.sql("SELECT COUNT(*) AS count FROM af_tasks")[0]["count"], 0)
        self.assertEqual(receiver.store.sql("SELECT COUNT(*) AS count FROM af_tasks")[0]["count"], 1)
        receiver.applications.withdraw("bob", snapshot["id"], 1, "local-withdrawal", "Owned receiver-only withdrawal")
        self.assertEqual(source.applications.require_current(pin(snapshot)), snapshot)
        self.assertEqual(receiver.client.get("/api/factory/jobs/" + identifier, headers=headers).json()["artifacts"], detail["artifacts"])

    def test_concurrent_import_receipts_and_local_approval_survive_actual_factory_restart(self):
        receiver, snapshot = self.receiver, self.snapshot
        with ThreadPoolExecutor(max_workers=4) as workers:
            results = list(workers.map(lambda _: receiver.applications.import_snapshot("manager", snapshot, "concurrent-import"), range(4)))
        self.assertEqual(results, [snapshot] * 4)
        with receiver.applications.db.read() as conn:
            versions = conn.execute(select(func.count()).select_from(receiver.applications.versions).where(receiver.applications.versions.c.id == snapshot["id"])).scalar_one()
            commands = conn.execute(select(func.count()).select_from(receiver.applications.commands).where(receiver.applications.commands.c.request_id == "concurrent-import")).scalar_one()
        self.assertEqual(versions, 1)
        self.assertEqual(commands, 1)
        review = receiver.applications.request_publication("manager", snapshot["id"], 1, "concurrent-local-review")
        receiver.applications.decide_publication("bob", review["id"], True, "concurrent-local-approval")
        before = receiver.applications.inspect("manager", snapshot["id"], 1)
        receiver.stop()
        receiver.start()
        self.assertEqual(receiver.applications.import_snapshot("manager", snapshot, "concurrent-import"), snapshot)
        self.assertEqual(receiver.applications.import_snapshot("bob", snapshot, "restart-observation"), snapshot)
        self.assertEqual(receiver.applications.inspect("manager", snapshot["id"], 1), before)
        self.assertEqual(receiver.applications.require_current(pin(snapshot)), snapshot)
        receiver.auth.authorization.unassign("manager", "factory-manager")
        with self.assertRaises(HTTPException) as revoked:
            receiver.applications.import_snapshot("manager", snapshot, "concurrent-import")
        self.assertEqual(revoked.exception.status_code, 403)
        self.assertEqual(self.origin.applications.require_current(pin(snapshot)), snapshot)


if __name__ == "__main__":
    unittest.main()
