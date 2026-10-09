"""Receiver proof persistence/current mapping checks on disposable PostgreSQL.

Plans and opaque handles here are controlled service-contract fixtures. Native
SQL identities and owner connection references are real; this suite does not
claim publication reviews, inter-host transport, model calls or provider use.
The separate process acceptance suite owns those integrated synthetic checks.
"""
import copy
from dataclasses import replace
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient

from agent_factory.catalog import create_plan
from agent_factory.config import Settings
from agent_factory.connections import TrustedConnectionBinding
from agent_factory.demo_model import DemoModel
from agent_factory.execution_bindings import default_bindings
from agent_factory.usage_ledger import PricingRevision, UsageLedger
from agent_factory.main import create_app
from agent_factory.remote_bindings import RemoteBindingService, TrustedRemoteBindingMapping
from agent_factory.remote_handoff import TrustedOrigin, plan_manifest
from agent_factory.store import digest, now
from pg_fixture import IsolatedPostgres


@unittest.skipUnless(os.getenv("FACTORY_TEST_DATABASE_URL"), "Requires disposable loopback PostgreSQL")
class RemoteBindingPostgresTests(unittest.TestCase):
    def setUp(self):
        database = IsolatedPostgres(os.environ["FACTORY_TEST_DATABASE_URL"]).__enter__()
        self.addCleanup(database.__exit__, None, None, None)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.source_handle, self.local_handle = object(), object()
        self.source_tool_handle, self.local_tool_handle, self.local_wide_tool_handle = object(), object(), object()
        # These existing proof/accounting compatibility fixtures use only local
        # synthetic models. Platform-paid execution remains disabled.
        settings = Settings(db_url=database.url, workspace=Path(directory.name), fee_management_enabled=True, trusted_connections={
            "origin-fixture": TrustedConnectionBinding("alice", "model", "origin-fixture-model", frozenset({"checksum:read"}),
                "origin-connection-v1", available=True, opaque_handle=self.source_handle, handle_ref="origin-handle-v1"),
            "receiver-fixture": TrustedConnectionBinding("bob", "model", "receiver-fixture-model", frozenset({"checksum:read"}),
                "receiver-connection-v1", available=True, opaque_handle=self.local_handle, handle_ref="receiver-handle-v1"),
            "origin-tool-fixture": TrustedConnectionBinding("alice", "model", "origin-fixture-tool", frozenset({"checksum:read", "experiment:synthetic"}),
                "origin-tool-connection-v1", available=True, opaque_handle=self.source_tool_handle, handle_ref="origin-tool-handle-v1"),
            "receiver-tool-narrow": TrustedConnectionBinding("bob", "model", "receiver-fixture-tool", frozenset({"checksum:read"}),
                "receiver-tool-connection-v1", available=True, opaque_handle=self.local_tool_handle, handle_ref="receiver-tool-handle-v1"),
            "receiver-tool-wide": TrustedConnectionBinding("bob", "model", "receiver-fixture-tool", frozenset({"checksum:read", "experiment:synthetic"}),
                "receiver-tool-wide-connection-v1", available=True, opaque_handle=self.local_wide_tool_handle, handle_ref="receiver-tool-wide-handle-v1")})
        app = create_app(settings)
        self.state = app.app.state.factory
        self.store, self.auth = self.state["store"], self.state["auth"]
        self.addCleanup(self.store.engine.dispose)
        self.addCleanup(self.store.native_db.db_engine.dispose)
        client = TestClient(app).__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        self.connections, self.bindings = self.state["connections"], self.state["execution_bindings"]
        self.source_pin = self.pin(self.connections.bind("alice", "origin-fixture", str(uuid4())))
        self.local_pin = self.pin(self.connections.bind("bob", "receiver-fixture", str(uuid4())))
        self.source_tool_pin = self.pin(self.connections.bind("alice", "origin-tool-fixture", str(uuid4())))
        self.local_tool_pin = self.pin(self.connections.bind("bob", "receiver-tool-narrow", str(uuid4())))
        self.local_wide_tool_pin = self.pin(self.connections.bind("bob", "receiver-tool-wide", str(uuid4())))
        # Receiver has no registration for origin-fixture-model.
        self.creations = []
        def local_model(context):
            self.creations.append(context.connection)
            from agent_factory.demo_model import DemoModel
            return DemoModel(id="receiver-proof-fixture-model")
        self.bindings.register("model", "receiver-fixture-model", "receiver-adapter-v2", local_model,
            connection_kind="model", required_capabilities=("checksum:read",))
        self.bindings.register("tool", "receiver-fixture-tool", "receiver-tool-v1", lambda context: None,
            tool_name="checksum", connection_kind="model", required_capabilities=("checksum:read",),
            permissions=("checksum:read",))
        origin_bindings = default_bindings(settings, self.store, self.connections)
        origin_bindings.register("model", "origin-fixture-model", "origin-adapter-v1", lambda context: None,
            connection_kind="model", required_capabilities=("checksum:read",))
        self.source = create_plan(self.store, "alice", "controlled remote proof fixture", "literature", "checksum")
        self.source = copy.deepcopy(self.source)
        model = next(item for item in self.source["materials"] if item["kind"] == "model")
        model.update(id="owned-source-model-fixture", content="Inert source connection model metadata",
            runtimeBinding={"adapterId": "origin-fixture-model", "revision": "origin-adapter-v1", "config": {"connectionName": "provider"}})
        model["sha256"] = digest({key: value for key, value in model.items() if key not in {"sha256", "published", "createdAt"}})
        self.source["materialRefs"] = [{key: item[key] for key in ("id", "version", "sha256")} for item in self.source["materials"]]
        self.source["executionBindings"] = origin_bindings.build(self.source["materials"], "alice", {"provider": self.source_pin})
        self.source["bindingManifest"].update(materialRefs=self.source["materialRefs"], connections={"provider": self.source_pin},
            executionBindingsSha256=self.source["executionBindings"]["sha256"])
        self.source["bindingManifest"]["sha256"] = digest({key: value for key, value in self.source["bindingManifest"].items() if key != "sha256"})
        # These service-contract descriptors are explicit zero-cost local
        # fixture profiles; neither price registration constructs a provider.
        ledger = self.store.usage_ledger
        self.store.usage_ledger = UsageLedger(self.store, (*ledger.prices,
            PricingRevision("origin-fixture-model", "origin-adapter-v1", "local-synthetic",
                "origin-proof-fixture-model", "owned-proof-zero-v1", local_model_type=DemoModel),
            PricingRevision("receiver-fixture-model", "receiver-adapter-v2", "local-synthetic",
                "receiver-proof-fixture-model", "owned-proof-zero-v1", local_model_type=DemoModel)), ledger.policy)
        self.source["usageBudget"] = self.store.usage_ledger.commitment_for(self.source)
        self.source["fingerprint"] = digest({key: value for key, value in self.source.items() if key not in {"id", "createdAt", "fingerprint"}})
        self.source_spec = self.source["executionBindings"]["model"]
        self.effective_spec = {**copy.deepcopy(self.source_spec), "adapterId": "receiver-fixture-model",
                               "revision": "receiver-adapter-v2", "connection": self.local_pin}
        self.mapping = TrustedRemoteBindingMapping("owned-model-map", "mapping-v1", "origin-fixture", "alice", "bob", "model",
                                                   self.source_spec, self.effective_spec)
        self.mappings = {self.mapping.reference: self.mapping}
        self.service = RemoteBindingService(self.store, self.auth, self.bindings, self.connections, self.mappings)
        self.store.remote_bindings = self.service
        self.origin = TrustedOrigin("origin-fixture", {"alice": "bob"}, lambda *args: None,
                                    configuration_revision="receiver-origin-config-v1")
        self.receipt_id, self.plan_id, self.origin_task_id = str(uuid4()), str(uuid4()), str(uuid4())
        self.manifest = plan_manifest(self.source)
        self.source_configuration = {"revision": "source-target-config-v1", "sha256": "a" * 64}

    @staticmethod
    def pin(value):
        return {key: copy.deepcopy(value[key]) for key in ("ref", "version", "fingerprint", "kind", "revision", "capabilities", "taskId")}

    def prepare(self, **kwargs):
        values = dict(receiver_plan_id=self.plan_id, source_configuration=self.source_configuration)
        values.update(kwargs)
        return self.service.prepare(self.origin, "bob", self.origin_task_id, self.receipt_id, self.manifest, **values)

    def imported(self, proof):
        plan = {**copy.deepcopy(self.source), "id": self.plan_id, "ownerId": "bob",
            "remoteHandoff": {"receiptId": self.receipt_id, "originRef": self.origin.reference,
                "originTaskId": self.origin_task_id, "manifestHash": self.manifest["sha256"], "bindingProofSha256": proof["sha256"]}}
        plan["fingerprint"] = digest({key: value for key, value in plan.items() if key not in {"id", "createdAt", "fingerprint"}})
        return plan

    def test_01_exact_source_and_receiver_mapping_no_origin_adapter_or_pin_resolution(self):
        source_before = copy.deepcopy(self.source)
        self.assertNotIn(("model", "origin-fixture-model", "origin-adapter-v1"), self.bindings._adapters)
        self.assertEqual(self.service.validate_source(self.source), self.source["executionBindings"])
        proof = self.prepare()
        self.assertEqual(self.prepare(), proof)
        self.assertEqual(self.creations, [])
        self.assertEqual(proof["sourceConfiguration"], self.source_configuration)
        self.assertEqual(proof["receiverConfiguration"]["sha256"], self.origin.fingerprint)
        plan = self.imported(proof)
        self.store.save_plan(plan)
        effective = self.bindings.manifest(plan)
        self.assertEqual(effective["model"], self.effective_spec)
        self.assertEqual(plan["executionBindings"], self.source["executionBindings"])
        self.assertEqual(self.source, source_before)
        task = self.store.reserve_task(plan, str(uuid4()))[0]
        run_id = str(uuid4())
        self.store.accept(task["id"], run_id)
        context = SimpleNamespace(user_id="bob", session_id=task["id"], run_id=run_id, session_state={})
        model = self.bindings.model_for(plan, context)
        self.assertEqual(model.id, "receiver-proof-fixture-model")
        self.assertEqual(self.creations, [self.local_handle])
        public = json.dumps(self.service.inspect(self.receipt_id, "bob"))
        self.assertNotIn("handleRef", public)
        self.assertNotIn("opaque_handle", public)
        self.assertNotIn("endpoint", public)

    def test_02_missing_wrong_owner_and_unregistered_mapping_fail_closed(self):
        self.service.mappings = {}
        with self.assertRaises(HTTPException) as missing:
            self.prepare()
        self.assertIn("REMOTE_BINDING_REQUIRED", str(missing.exception.detail))
        self.service.mappings = {self.mapping.reference: replace(self.mapping, receiver_owner="alice")}
        with self.assertRaises(HTTPException):
            self.prepare()
        self.service.mappings = {self.mapping.reference: replace(self.mapping, revision="unregistered-v2")}
        with self.assertRaises(HTTPException) as unregistered:
            self.prepare()
        self.assertIn("REMOTE_BINDING_INTEGRITY", str(unregistered.exception.detail))
        self.assertEqual(self.store.sql("SELECT COUNT(*) AS n FROM af_remote_binding_proofs")[0]["n"], 0)

    def test_effective_nonlocal_receiver_mapping_obeys_default_off_before_factory(self):
        # The persisted source is local. A trusted mapping selects a registered
        # receiver model carrying a nonlocal tariff; only the actual adapter is
        # paid. No provider or model factory may run while the flag is disabled.
        price = PricingRevision('receiver-fixture-model', 'receiver-adapter-v2',
            'synthetic-paid-provider', 'receiver-proof-fixture-model', 'synthetic-paid-v1',
            input_micros_per_million=1, output_micros_per_million=1,
            request_guard=lambda *args: None)
        self.store.settings.usage_pricing = (price,)
        self.assertFalse(self.store.settings.platform_paid_models_enabled)
        proof = self.prepare()
        plan = self.imported(proof)
        self.store.save_plan(plan)
        self.assertEqual(plan['executionBindings']['model']['adapterId'], 'origin-fixture-model')
        self.assertEqual(self.bindings.manifest(plan)['model']['adapterId'], 'receiver-fixture-model')
        task = self.store.reserve_task(plan, str(uuid4()))[0]
        run_id = str(uuid4())
        self.store.accept(task['id'], run_id)
        context = SimpleNamespace(user_id='bob', session_id=task['id'], run_id=run_id, session_state={})
        for fee_enabled in (True, False):
            self.store.settings.fee_management_enabled = fee_enabled
            with self.subTest(fee_enabled=fee_enabled):
                with self.assertRaises(HTTPException) as denied:
                    self.bindings.model_for(plan, context)
                self.assertEqual(denied.exception.status_code, 409)
                self.assertIn('PLATFORM_PAID_MODEL_DISABLED', str(denied.exception.detail))
        self.assertEqual(self.creations, [])
        self.assertEqual(self.service.inspect(self.receipt_id, 'bob')['sha256'], proof['sha256'])

    def test_03_local_connection_owner_pin_adapter_and_scope_are_exact(self):
        for pin_change in ({"connection": self.source_pin}, {"connection": {**self.local_pin, "fingerprint": "b" * 64}},
                           {"adapterId": "local-synthetic-model-v1", "revision": "1"}):
            with self.subTest(fields=list(pin_change)):
                mapping = replace(self.mapping, reference="variant-" + uuid4().hex, effective_spec={**self.effective_spec, **pin_change})
                self.service = RemoteBindingService(self.store, self.auth, self.bindings, self.connections, {mapping.reference: mapping})
                with self.assertRaises(HTTPException):
                    self.prepare()
        with self.assertRaises(ValueError):
            replace(self.mapping, effective_spec={**self.effective_spec,
                "connection": {**self.local_pin, "capabilities": ["checksum:read", "experiment:synthetic"]}})

    def test_09_tool_connection_capabilities_are_bounded_by_exact_material_permissions(self):
        material = next(item for item in self.source["materials"] if item["id"] == "checksum-tool")
        material_ref = {key: material[key] for key in ("id", "version", "sha256")}
        source_spec = {"materialRef": material_ref, "adapterId": "origin-fixture-tool", "revision": "origin-tool-v1",
            "config": {"connectionName": "toolProvider"}, "connection": self.source_tool_pin, "toolName": "checksum"}
        effective_spec = {**copy.deepcopy(source_spec), "adapterId": "receiver-fixture-tool", "revision": "receiver-tool-v1",
            "connection": self.local_tool_pin}

        # A narrowed receiver pin is valid and is still preflighted against the
        # registered receiver adapter and current owner-scoped connection.
        self.service._effective_check("tool", source_spec, effective_spec, material, "bob")

        # This receiver pin is a valid local connection and remains within the
        # origin's broader ceiling, but it exceeds the selected tool material's
        # checksum:read permission and must not be admitted.
        widened = {**effective_spec, "connection": self.local_wide_tool_pin}
        with self.assertRaises(HTTPException) as denied:
            self.service._effective_check("tool", source_spec, widened, material, "bob")
        self.assertIn("material permissions", str(denied.exception.detail))

    def test_historic_receiver_spec_survives_revocation_without_authorizing_execution(self):
        proof = self.prepare()
        plan = self.imported(proof)
        self.store.save_plan(plan)
        source = plan["executionBindings"]["model"]
        self.connections.revoke("bob", self.local_pin["ref"], str(uuid4()))
        self.service.mappings = {}
        self.auth.authorization.unassign("bob", "factory-user")
        with self.assertRaises(HTTPException):
            self.service.effective(plan, plan["executionBindings"])
        self.assertEqual(self.service.historical_spec(plan, "model", source), self.effective_spec)
        historical = self.service.historical_manifest(plan)
        self.assertEqual(historical["model"], self.effective_spec)
        self.assertEqual(historical["sha256"], digest({key: value for key, value in historical.items() if key != "sha256"}))
        # Trusted evidence persistence must not resolve a revoked execution
        # handle. This controlled metadata fixture does not execute a provider.
        task = self.store.reserve_task(plan, str(uuid4()))[0]
        run_id = str(uuid4())
        self.store.accept(task["id"], run_id)
        artifact = self.store.artifact_write(run_id, "cleanup-evidence.json", "{}", "application/json")
        provenance = artifact["provenance"]["bindingProvenance"]
        self.assertEqual(provenance["receiverBindingProofSha256"], proof["sha256"])
        self.assertEqual(provenance["effectiveExecutionBindingsSha256"], historical["sha256"])
        self.assertNotEqual(self.effective_spec["connection"], source["connection"])
        with self.assertRaises(HTTPException):
            self.service.historical_spec(plan, "model", {**source, "revision": "forged"})
        tampered = {**plan, "remoteHandoff": {**plan["remoteHandoff"], "bindingProofSha256": "0" * 64}}
        with self.assertRaises(HTTPException):
            self.service.historical_spec(tampered, "model", source)
        self.assertEqual(self.creations, [])

    def test_04_current_mapping_rotation_or_removal_denies_execution_preserves_reads(self):
        proof = self.prepare()
        plan = self.imported(proof)
        self.store.save_plan(plan)
        for mappings in ({}, {self.mapping.reference: replace(self.mapping, revision="mapping-v2")}):
            self.service.mappings = mappings
            with self.assertRaises(HTTPException) as changed:
                self.bindings.inspect(plan)
            self.assertIn("REMOTE_BINDING_CHANGED", str(changed.exception.detail))
            self.assertEqual(self.service.inspect(self.receipt_id, "bob")["sha256"], proof["sha256"])
        self.assertEqual(self.creations, [])

    def test_05_revoked_receiver_connection_denies_current_execution_not_evidence(self):
        proof = self.prepare()
        plan = self.imported(proof)
        self.store.save_plan(plan)
        self.connections.revoke("bob", self.local_pin["ref"], str(uuid4()))
        with self.assertRaises(HTTPException) as revoked:
            self.bindings.inspect(plan)
        self.assertIn("CONNECTION_REVOKED", str(revoked.exception.detail))
        self.assertEqual(self.service.inspect(self.receipt_id, "bob")["sha256"], proof["sha256"])
        self.assertEqual(self.creations, [])

    def test_06_manifest_proof_tamper_reuse_and_changed_configuration_conflicts(self):
        proof = self.prepare()
        plan = self.imported(proof)
        for changes in ({"ownerId": "alice"}, {"id": str(uuid4())}, {"normalizedGoal": "changed immutable source"},
                        {"delegation": {"rootTaskId": str(uuid4()), "parentTaskId": str(uuid4()), "depth": 1}},
                        {"remoteHandoff": {**plan["remoteHandoff"], "originTaskId": str(uuid4())}}):
            with self.subTest(fields=list(changes)), self.assertRaises(HTTPException):
                self.service.effective({**plan, **changes}, plan["executionBindings"])
        with self.assertRaises(HTTPException) as conflict:
            self.prepare(source_configuration={"revision": "source-target-v2", "sha256": "b" * 64})
        self.assertIn("REMOTE_BINDING_CONFLICT", str(conflict.exception.detail))
        with self.assertRaises(HTTPException) as reused:
            self.service.prepare(self.origin, "bob", self.origin_task_id, str(uuid4()), self.manifest,
                receiver_plan_id=self.plan_id, source_configuration=self.source_configuration)
        self.assertIn("REMOTE_BINDING_CONFLICT", str(reused.exception.detail))
        with self.store.engine.begin() as connection:
            connection.execute(self.service.proofs.update().where(self.service.proofs.c.receipt_id == self.receipt_id)
                .values(body={**{key: value for key, value in proof.items() if key != "sha256"}, "receiverOwner": "alice"}))
        with self.assertRaises(HTTPException):
            self.service.inspect(self.receipt_id, "bob")
        with self.assertRaises(HTTPException):
            self.service.effective(plan, plan["executionBindings"])

    def test_07_source_binding_integrity_and_mapping_revision_cannot_be_rebound(self):
        changed = copy.deepcopy(self.source)
        changed["executionBindings"]["model"]["revision"] = "changed"
        manifest = changed["executionBindings"]
        manifest["sha256"] = digest({key: value for key, value in manifest.items() if key != "sha256"})
        with self.assertRaises(HTTPException):
            self.service.validate_source(changed)
        for pins in ({}, {"provider": self.local_pin}, {"provider": self.source_pin, "unused": self.source_pin}):
            with self.subTest(pins=list(pins)):
                changed = copy.deepcopy(self.source)
                changed["bindingManifest"]["connections"] = pins
                changed["bindingManifest"]["sha256"] = digest({key: value for key, value in changed["bindingManifest"].items() if key != "sha256"})
                with self.assertRaises(HTTPException):
                    self.service.validate_source(changed)
        changed_mapping = replace(self.mapping, effective_spec={**self.effective_spec, "config": {"connectionName": "provider", "label": "changed"}})
        with self.assertRaises(ValueError):
            RemoteBindingService(self.store, self.auth, self.bindings, self.connections, {self.mapping.reference: changed_mapping})
        with self.assertRaises(HTTPException):
            self.service.inspect(self.receipt_id, "alice")

    def test_08_child_inherits_exact_source_pins_only_on_persisted_receiver_path(self):
        proof = self.prepare()
        root = self.imported(proof)
        self.store.save_plan(root)
        root_task = self.store.reserve_task(root, str(uuid4()))[0]
        # This is a metadata/proof contract test: neither reservation is submitted
        # to native. The separate remote product acceptance owns native child work.
        materials = [copy.deepcopy(item) for item in root["materials"] if item["kind"] != "knowledge"]
        inherited = self.service.build_inherited(materials, "bob", root, {"provider": self.source_pin})
        self.assertEqual(inherited["model"]["connection"], self.source_pin)
        self.assertEqual(inherited["knowledge"], [])
        with self.assertRaises(HTTPException):
            self.service.build_inherited(materials, "bob", root, {"provider": self.local_pin})
        expanded = copy.deepcopy(materials)
        expanded.append(copy.deepcopy(next(item for item in self.store.materials() if item["kind"] == "skill")))
        with self.assertRaises(HTTPException):
            self.service.build_inherited(expanded, "bob", root)
        child = {**copy.deepcopy(root), "id": str(uuid4()), "materials": materials,
            "normalizedGoal": "narrowed receiver-local metadata child", "executionBindings": inherited,
            "delegation": {"rootTaskId": root_task["id"], "parentTaskId": root_task["id"], "depth": 1}}
        del child["remoteHandoff"]
        child["materialRefs"] = [{key: item[key] for key in ("id", "version", "sha256")} for item in materials]
        child["bindingManifest"].update(materialRefs=child["materialRefs"], executionBindingsSha256=inherited["sha256"])
        child["bindingManifest"]["sha256"] = digest({key: value for key, value in child["bindingManifest"].items() if key != "sha256"})
        child["fingerprint"] = digest({key: value for key, value in child.items() if key not in {"id", "createdAt", "fingerprint"}})
        self.store.save_plan(child)
        with self.assertRaises(HTTPException) as unlinked:
            self.bindings.manifest(child)
        self.assertIn("REMOTE_BINDING_ANCESTRY", str(unlinked.exception.detail))
        request = str(uuid4())
        self.store.sql("""INSERT INTO af_delegation_links VALUES(:owner,:parent,:request,:root,1,:fingerprint,:plan,NULL,:at)""",
            owner="bob", parent=root_task["id"], request=request, root=root_task["id"],
            fingerprint=digest(child), plan=child["id"], at=now())
        with self.assertRaises(HTTPException):
            self.bindings.manifest(child)
        child_task = self.store.reserve_task(child, "delegation:" + request)[0]
        self.store.sql("UPDATE af_delegation_links SET child_id=:child WHERE plan_id=:plan", child=child_task["id"], plan=child["id"])
        effective = self.bindings.inspect(child)
        self.assertEqual(effective["model"]["connection"], self.local_pin)
        self.assertEqual(effective["knowledge"], [])
        with self.assertRaises(HTTPException):
            self.service.effective(child, inherited, SimpleNamespace(user_id="bob", session_id=root_task["id"], run_id=None))
        changed = copy.deepcopy(child)
        changed["executionBindings"]["model"]["connection"] = self.local_pin
        changed["executionBindings"]["sha256"] = digest({key: value for key, value in changed["executionBindings"].items() if key != "sha256"})
        changed["bindingManifest"].update(connections={"provider": self.local_pin}, executionBindingsSha256=changed["executionBindings"]["sha256"])
        changed["bindingManifest"]["sha256"] = digest({key: value for key, value in changed["bindingManifest"].items() if key != "sha256"})
        with self.assertRaises(HTTPException) as repinned:
            self.bindings.manifest(changed)
        self.assertIn("REMOTE_BINDING_SCOPE", str(repinned.exception.detail))
        self.service.mappings = {}
        with self.assertRaises(HTTPException):
            self.bindings.inspect(child)
        self.assertEqual(self.service.inspect(self.receipt_id, "bob")["sha256"], proof["sha256"])
        self.assertEqual(self.creations, [])


if __name__ == "__main__":
    unittest.main()
