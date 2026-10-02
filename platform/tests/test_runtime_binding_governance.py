"""Inert registration contracts with real native auth/persisted metadata.

Portable SQLite tests do not claim PostgreSQL concurrency or live providers.
The optional PG test uses a disposable DB and the actual governance HTTP routes.
"""
from dataclasses import asdict
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select

from agent_factory.config import Settings
from agent_factory.main import create_app
from agent_factory.material_governance import (
    GovernanceConfig, LICENSES, MaterialGovernance, RuntimeBinding, normalize_runtime_binding,
)
from agent_factory.plan_policy import (
    LEGACY_TOOLS, PlanPolicyConfig,
)
from agent_factory.store import digest
from pg_fixture import IsolatedPostgres
import test_material_governance as governance_fixture
import test_plan_policy as policy_fixture


def binding(adapter="native-checksum-v1", **config):
    return {"adapterId": adapter, "revision": "1", "config": config}


class RuntimeBindingGovernanceTests(unittest.TestCase):
    def setUp(self):
        self.fixture = governance_fixture.MaterialGovernanceTests("runTest")
        self.fixture.setUp()
        self.service, self.store = self.fixture.service, self.fixture.store

    def tearDown(self):
        self.fixture.tearDown()

    def test_legacy_fingerprints_and_old_persisted_config_body_remain_exact(self):
        legacy = GovernanceConfig()
        expected = digest({"review_mode": "separate-admin", "revision": "material-governance-v1",
            "licenses": LICENSES, "toolBindings": LEGACY_TOOLS, "schemaVersion": "structured-material/v1"})
        self.assertEqual(legacy.fingerprint, expected)
        old_body = {key: value for key, value in asdict(legacy).items() if key != "tool_contract"}
        with self.store.engine.begin() as connection:
            connection.execute(self.service.configs.update().values(body=old_body))
        restarted = MaterialGovernance(self.store, self.fixture.auth)
        self.assertEqual(restarted.current()["fingerprint"], expected)
        self.store.seed()
        before = [self.store.raw({"id": seed[0], "version": 1})["body"] for seed in governance_fixture.SEEDS]
        restarted.adopt_demo_bootstrap()
        after = [self.store.raw({"id": seed[0], "version": 1})["body"] for seed in governance_fixture.SEEDS]
        self.assertEqual(before, after)
        self.assertTrue(all("runtimeBinding" not in item for item in after))

    def test_binding_normalizes_only_strict_inert_data_without_starting_anything(self):
        examples = [governance_fixture.definition(kind="tool", content="checksum", permissions=["checksum:read"], runtimeBinding=binding()),
                    governance_fixture.definition(kind="model", runtimeBinding=binding("local-synthetic-model-v1", temperature=0.2, maxOutputTokens=100, mode="concise")),
                    governance_fixture.definition(kind="environment", runtimeBinding=binding("local-bounded-environment-v1", profile="bounded", labels=["fixture", "local"])),
                    governance_fixture.definition(kind="knowledge", runtimeBinding=binding("local-synthetic-knowledge-v1"))]
        with patch("subprocess.Popen") as no_process, patch("importlib.import_module") as no_import:
            imported = self.service.import_definitions("manager", examples, "inert-bindings")
        self.assertEqual(no_process.call_count, 0)
        self.assertEqual(no_import.call_count, 0)
        self.assertEqual([item["runtimeBinding"] for item in imported["materials"]], [item["runtimeBinding"] for item in examples])
        self.assertFalse(imported["executesCode"])
        self.assertFalse(any(item["published"] for item in imported["materials"]))
        self.assertEqual(normalize_runtime_binding(binding(connectionName="literatureProvider")), binding(connectionName="literatureProvider"))
        self.assertEqual(RuntimeBinding.model_validate(binding()).model_dump(), binding())

    def test_absent_binding_stays_absent_and_is_not_a_hash_migration(self):
        original = governance_fixture.definition()
        normalized = self.service.validate_definition(original)
        self.assertNotIn("runtimeBinding", normalized)
        self.assertEqual(normalized, self.service.validate_definition({**original, "runtimeBinding": None}))
        self.assertNotIn("runtimeBinding", self.service.create_draft("manager", original, "no-binding"))

    def test_runtime_config_code_credentials_paths_urls_and_bounds_fail_closed(self):
        invalid = [binding(factory="subprocess.Popen"), binding(modelFactory="subprocess.Popen"), binding(command="python"), binding(shell=True),
            binding(module="os"), binding(path="relative.py"), binding(connectionRef="owner-secret-ref"),
            binding(connectionName="https://fixtures.invalid"), binding(connectionName=True), binding(endpoint="loopback"),
            binding(apiKey="synthetic-forbidden"), binding(token="synthetic-forbidden"),
            binding(value="https://fixtures.invalid"), binding(value="C:\\owned\\file"),
            binding(value="../owned"), binding(value="print('synthetic')"), binding(value="module:factory"),
            binding(value=float("inf")), binding(value=10**1000), binding(value=list(range(33))),
            {**binding(), "adapterId": 1}, {**binding(), "revision": 1}, {**binding(), "extra": "x"},
            {**binding(), "adapterId": "sk-proj-" + "X" * 30},
            {"adapterId": "native-checksum-v1", "revision": "1"}]
        nested = {}
        for _ in range(8):
            nested = {"next": nested}
        invalid += [binding(nested=nested), binding(**{f"item{i}": i for i in range(33)})]
        for index, value in enumerate(invalid):
            with self.subTest(index=index), self.assertRaises(HTTPException) as denied:
                self.service.import_definitions("manager", [governance_fixture.definition(kind="model", runtimeBinding=value)], f"invalid-{index}")
            self.assertEqual(denied.exception.status_code, 422)
        with self.store.engine.connect() as connection:
            self.assertEqual(list(connection.execute(select(self.store.materials))), [])

    def test_only_runtime_kinds_bind_and_managers_cannot_register_new_callables(self):
        for kind in ("prompt", "skill"):
            with self.assertRaises(HTTPException):
                self.service.create_draft("manager", governance_fixture.definition(kind=kind, runtimeBinding=binding()), str(uuid4()))
        for tool, caps in (("module:function", ["checksum:read"]), ("custom_tool", ["research:read"]),
                           ("checksum", ["agent_os:admin"]), ("checksum", ["research:read"])):
            with self.assertRaises(HTTPException):
                self.service.create_draft("manager", governance_fixture.definition(kind="tool", content=tool, permissions=caps, runtimeBinding=binding()), str(uuid4()))

    def test_unknown_inert_adapter_is_metadata_only_and_binding_changes_conflict(self):
        # Installed-descriptor resolution belongs to ExecutionBindings, not import.
        definition = governance_fixture.definition(kind="model", runtimeBinding=binding("uninstalled-fixture"))
        first = self.service.create_draft("manager", definition, "binding-key")
        replay = self.service.create_draft("manager", definition, "binding-key")
        self.assertEqual(first, replay)
        with self.assertRaises(HTTPException) as conflict:
            self.service.create_draft("manager", {**definition, "runtimeBinding": binding("different-fixture")}, "binding-key")
        self.assertEqual(conflict.exception.status_code, 409)

    def test_orx_registration_is_explicit_fixed_read_capability_and_new_revision(self):
        definition = governance_fixture.definition(kind="tool", content="orx_discover", permissions=["research:read"],
            runtimeBinding=binding("orx-discover-v1", connectionName="literatureProvider"))
        with self.assertRaises(HTTPException):
            self.service.create_draft("manager", definition, "legacy-orx")
        with self.assertRaises(ValueError):
            GovernanceConfig(tool_contract="registered-runtime-v1")
        new = GovernanceConfig(revision="material-runtime-v2", tool_contract="registered-runtime-v1")
        self.service.replace_configuration(new, expected_revision="material-governance-v1")
        created = self.service.create_draft("manager", definition, "registered-orx")
        self.assertEqual(created["permissions"], ["research:read"])
        self.assertNotEqual(new.fingerprint, GovernanceConfig().fingerprint)
        for tool in ("orx_run", "orx_spawn", "orx_login", "orx_up", "orx_serve"):
            with self.assertRaises(HTTPException):
                self.service.create_draft("manager", {**definition, "content": tool}, str(uuid4()))
        self.fixture.publish(created)
        plan = {"materialRefs": [governance_fixture.ref(created)]}
        self.assertTrue(self.service.require_materials_current(plan)["allowed"])
        self.service.replace_configuration(GovernanceConfig(revision="legacy-contract-again"), expected_revision=new.revision)
        with self.assertRaises(HTTPException):
            self.service.require_materials_current(plan)


class RuntimeToolPolicyTests(unittest.TestCase):
    def setUp(self):
        self.fixture = policy_fixture.PlanPolicyTests("runTest")
        self.fixture.setUp()

    def tearDown(self):
        self.fixture.tearDown()

    def test_old_policy_hash_and_old_persisted_body_are_preserved(self):
        old = PlanPolicyConfig()
        expected = digest({"name": "admin-review", "revision": "plan-policy-v1", "review_ttl_seconds": 3600,
            "knownTools": LEGACY_TOOLS, "readOnlyTools": ["ask_scope", "checksum", "literature_search"],
            "readOnlyCapabilities": ["checksum:read", "question:ask", "research:read"]})
        self.assertEqual(old.fingerprint, expected)
        with self.fixture.store.engine.begin() as connection:
            connection.execute(self.fixture.service.configs.update().values(body={key: value for key, value in asdict(old).items() if key != "tool_contract"}))
        self.assertEqual(self.fixture.service.current()["fingerprint"], expected)

    def test_orx_read_only_requires_operator_contract_and_stays_tool_scoped(self):
        fixture = self.fixture
        plan = fixture.store.add(tools=["orx_discover"], capabilities=["research:read"], syntheticFixture=False, policy="read-only-auto")
        fixture.service.replace_configuration(PlanPolicyConfig(name="read-only-auto", revision="legacy-read-only"), expected_revision="plan-policy-v1")
        with self.assertRaises(HTTPException):
            fixture.service.require_execution("alice", plan["id"])
        with self.assertRaises(ValueError):
            PlanPolicyConfig(tool_contract="registered-runtime-v1")
        configuration = PlanPolicyConfig(name="read-only-auto", revision="registered-read-only", tool_contract="registered-runtime-v1")
        fixture.service.replace_configuration(configuration, expected_revision="legacy-read-only")
        approved = fixture.service.require_tool("alice", plan["id"], "orx_discover")
        self.assertEqual(approved["source"], "read-only-auto")
        self.assertFalse(fixture.service.status("alice", plan["id"])["nativeToolConfirmationRequired"])
        with self.assertRaises(HTTPException):
            fixture.service.require_tool("alice", plan["id"], "run_experiment")


@unittest.skipUnless(os.getenv("FACTORY_TEST_DATABASE_URL"), "Requires disposable PostgreSQL")
class RuntimeBindingGovernancePostgresTests(unittest.TestCase):
    def test_http_binding_persists_exact_draft_and_conflict_with_no_execution(self):
        with IsolatedPostgres(os.environ["FACTORY_TEST_DATABASE_URL"]) as database, TemporaryDirectory() as workspace:
            app = create_app(Settings(db_url=database.url, workspace=Path(workspace)))
            state = app.app.state.factory
            try:
                with TestClient(app) as client:
                    self.assertEqual(client.post("/api/factory/demo/login", json={"persona": "manager"}).status_code, 200)
                    value = governance_fixture.definition(kind="model", id="registered-model-metadata", runtimeBinding=binding("local-synthetic-model-v1", temperature=0.2))
                    body = {"definition": value, "requestId": "actual-runtime-binding"}
                    first = client.post("/api/factory/material-governance/drafts", json=body)
                    repeat = client.post("/api/factory/material-governance/drafts", json=body)
                    self.assertEqual(first.status_code, 201, first.text)
                    self.assertEqual(first.json(), repeat.json())
                    material = first.json()
                    self.assertEqual(material["runtimeBinding"], value["runtimeBinding"])
                    self.assertFalse(material["published"])
                    changed = {**body, "definition": {**value, "runtimeBinding": binding("local-synthetic-model-v1", temperature=0.3)}}
                    self.assertEqual(client.post("/api/factory/material-governance/drafts", json=changed).status_code, 409)
                    count = state["store"].sql("SELECT COUNT(*) AS n FROM af_tasks")[0]["n"]
                    self.assertEqual(count, 0)
                    before = state["store"].materials()
                    self.assertEqual(client.post("/api/factory/material-governance/drafts", json={
                        "definition": {**value, "runtimeBinding": binding(command="python")}, "requestId": "forbidden-runtime-config"}).status_code, 422)
                    self.assertEqual(state["store"].materials(), before)
            finally:
                state["store"].engine.dispose()
                state["store"].native_db.db_engine.dispose()


if __name__ == "__main__":
    unittest.main()
