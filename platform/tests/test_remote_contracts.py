"""Portable remote manifest/registry contract checks (no service or provider calls)."""
from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
import unittest
from uuid import uuid4

from fastapi import HTTPException

from agent_factory.execution_bindings import ExecutionBindings
from agent_factory.plan_policy import tools_for_contract
from agent_factory.remote_bindings import RemoteBindingService
from agent_factory.remote_handoff import TrustedOrigin, _manifest
from agent_factory.store import digest


def _no_authority(*_):
    raise AssertionError("Metadata contract checks must not request runtime authority")


class _Applications:
    def require_plan_current(self, plan):
        return None


class _Connections:
    def __init__(self):
        self.preflights = []

    def preflight(self, owner, reference, **kwargs):
        self.preflights.append((owner, reference, kwargs))
        return {"ref": reference, "configured": True}


class _Store:
    execution_bindings: ExecutionBindings
    remote_bindings: RemoteBindingService

    def __init__(self, contract: str, materials: list[dict]):
        self.settings = SimpleNamespace(
            demo=False,
            runtime_tool_contract=contract,
            max_tool_calls=8,
            experiment_timeout_seconds=8,
            experiment_output_bytes=65536,
        )
        self._materials = deepcopy(materials)
        self.applications = _Applications()

    def materials(self, published_only=False):
        return deepcopy(self._materials)


def _material(identifier: str, kind: str, content: str, runtime_binding: dict,
              permissions: list[str] | None = None) -> dict:
    value = {
        "id": identifier,
        "version": 1,
        "name": identifier,
        "kind": kind,
        "description": "Synthetic fixture for a contract test.",
        "content": content,
        "permissions": permissions or [],
        "dependencies": [],
        "compatibility": ["agno:3.1.0"],
        "license": "MIT",
        "provenance": {"kind": "original", "notice": "Synthetic test fixture."},
        "runtimeBinding": deepcopy(runtime_binding),
        "published": True,
    }
    value["sha256"] = digest({key: item for key, item in value.items()
                              if key not in {"sha256", "published", "createdAt"}})
    return value


def _reference(material: dict) -> dict:
    return {key: material[key] for key in ("id", "version", "sha256")}


def _fixture():
    connection = {
        "ref": "fixture-metadata-connection",
        "version": 1,
        "fingerprint": "a" * 64,
        "kind": "model",
        "revision": "operator-r1",
        "capabilities": ["metadata:read"],
        "taskId": None,
    }
    model_binding = {"adapterId": "fixture-model-v1", "revision": "1", "config": {}}
    environment_binding = {"adapterId": "fixture-environment-v1", "revision": "1", "config": {}}
    tool_binding = {
        "adapterId": "fixture-metadata-v1",
        "revision": "1",
        "config": {"connectionName": "metadataProvider"},
    }
    materials = [
        _material("fixture-model", "model", "fixture-model-v1", model_binding),
        _material("fixture-environment", "environment", "fixture-environment-v1", environment_binding),
        _material("fixture-metadata-tool", "tool", "fixture_metadata", tool_binding, ["metadata:read"]),
    ]
    refs = [_reference(item) for item in materials]
    model_ref, environment_ref, tool_ref = refs
    binding_body = {
        "schema": 1,
        "model": {**model_binding, "materialRef": model_ref},
        "environment": {**environment_binding, "materialRef": environment_ref},
        "tools": [{
            **tool_binding,
            "materialRef": tool_ref,
            "connection": connection,
            "toolName": "fixture_metadata",
        }],
        "knowledge": [],
    }
    execution_bindings = {**binding_body, "sha256": digest(binding_body)}
    binding_anchor = {
        "schema": 1,
        "executionBindingsSha256": execution_bindings["sha256"],
        "connections": {"metadataProvider": connection},
        "materialRefs": refs,
    }
    binding_anchor["sha256"] = digest(binding_anchor)
    plan = {
        "id": str(uuid4()),
        "ownerId": "alice",
        "normalizedGoal": "Read controlled fixture metadata.",
        "mode": "fixture-metadata",
        "application": "fixture-metadata",
        "instructions": ["Return a short public metadata summary."],
        "tools": ["fixture_metadata"],
        "config": {
            "askScope": False,
            "sample": "public metadata",
            "experimentDurationSeconds": 1,
            "toolOrder": ["fixture_metadata"],
        },
        "materialRefs": refs,
        "materials": materials,
        "capabilities": ["metadata:read"],
        "missing": [],
        "status": "ready",
        "createdAt": "2026-10-02T00:00:00+00:00",
        "policy": "member-self-service",
        "budget": {
            "toolCalls": 2,
            "maxDepth": 1,
            "maxChildren": 1,
            "experimentSeconds": 1,
            "outputBytes": 4096,
            "depth": 0,
        },
        "syntheticFixture": False,
        "applicationRef": {"id": "fixture-metadata", "version": 1, "sha256": "b" * 64},
        "executionBindings": execution_bindings,
        "bindingManifest": binding_anchor,
        "compositionProposalId": str(uuid4()),
    }
    plan["fingerprint"] = digest({key: value for key, value in plan.items()
                                  if key not in {"id", "createdAt", "fingerprint"}})
    manifest = {"plan": plan, "sha256": digest(plan)}
    return materials, plan, manifest


class RemoteContractsTests(unittest.TestCase):
    def test_member_policy_manifest_is_supported_without_accepting_unknown_policy(self):
        materials, plan, _ = _fixture()
        store = _Store("bounded-process-v1", materials)
        registry = ExecutionBindings(store.settings, store, _Connections())
        service = RemoteBindingService.__new__(RemoteBindingService)
        service.store, service.bindings = store, registry
        store.execution_bindings = registry
        store.remote_bindings = service
        for policy in ('member-self-service', 'unknown-policy', 'unset', 'admin-review', 'read-only-auto', 'bounded-synthetic'):
            with self.subTest(policy=policy):
                candidate = {**plan, 'policy': policy}
                candidate['fingerprint'] = digest({key: value for key, value in candidate.items()
                    if key not in {'id', 'createdAt', 'fingerprint'}})
                manifest = {'plan': candidate, 'sha256': digest(candidate)}
                if policy == 'member-self-service':
                    self.assertEqual(_manifest(manifest, store, 'alice', receiver=True), candidate)
                else:
                    with self.assertRaises(HTTPException) as denied:
                        _manifest(manifest, store, 'alice', receiver=True)
                    self.assertEqual(denied.exception.status_code, 409)
                    self.assertIn('explicit supported policy', denied.exception.detail)

    def test_legacy_tool_contract_and_origin_fingerprint_are_stable(self):
        self.assertEqual(
            tools_for_contract("legacy-v1"),
            {
                "ask_scope": "question:ask",
                "checksum": "checksum:read",
            },
        )
        origin = TrustedOrigin("fixture-origin", {"alice": "bob"}, _no_authority)
        self.assertEqual(origin.fingerprint, '88425db87ae6f336876845d27b8e1fe3e559241d8eef589b8fefcbc6855b12a3')
        self.assertEqual(origin.tool_contract, "legacy-v1")

    def test_registered_remote_contract_requires_a_distinct_operator_revision(self):
        with self.assertRaisesRegex(ValueError, "distinct operator revision"):
            TrustedOrigin(
                "fixture-origin",
                {"alice": "bob"},
                _no_authority,
                capabilities=frozenset({"checksum:read"}),
                tools=frozenset({"checksum"}),
                tool_contract="bounded-process-v1",
            )

        origin = TrustedOrigin(
            "fixture-origin",
            {"alice": "bob"},
            _no_authority,
            capabilities=frozenset({"checksum:read"}),
            tools=frozenset({"checksum"}),
            configuration_revision="fixture-contract-r2",
            tool_contract="bounded-process-v1",
        )
        self.assertEqual(origin.tool_contract, "bounded-process-v1")
        self.assertNotEqual(origin.fingerprint, "88425db87ae6f336876845d27b8e1fe3e559241d8eef589b8fefcbc6855b12a3")

    def test_exact_source_bindings_are_independent_of_builtin_tool_contract(self):
        materials, _, manifest = _fixture()
        store = _Store("legacy-v1", materials)
        registry = ExecutionBindings(store.settings, store, _Connections())
        service = RemoteBindingService.__new__(RemoteBindingService)
        service.store, service.bindings = store, registry
        store.execution_bindings = registry
        store.remote_bindings = service

        self.assertEqual(_manifest(manifest, store, "alice", receiver=True), manifest["plan"])
        self.assertEqual(tools_for_contract("legacy-v1").get("fixture_metadata"), None)

    def test_manifest_tool_and_capability_scope_matches_selected_materials(self):
        materials, plan, _ = _fixture()
        store = _Store("legacy-v1", materials)
        registry = ExecutionBindings(store.settings, store, _Connections())
        service = RemoteBindingService.__new__(RemoteBindingService)
        service.store, service.bindings = store, registry
        store.execution_bindings = registry
        store.remote_bindings = service
        for changes, expected_status in (({"tools": ["fixture_metadata", "unselected_tool"]}, 409),
                                         ({"capabilities": ["metadata:read", "compute:local"]}, 422)):
            with self.subTest(changes=changes):
                candidate = deepcopy(plan)
                candidate.update(changes)
                candidate["config"]["toolOrder"] = candidate["tools"]
                candidate["fingerprint"] = digest({key: value for key, value in candidate.items()
                    if key not in {"id", "createdAt", "fingerprint"}})
                manifest = {"plan": candidate, "sha256": digest(candidate)}
                with self.assertRaises(HTTPException) as denied:
                    _manifest(manifest, store, "alice", receiver=True)
                self.assertEqual(denied.exception.status_code, expected_status)

    def test_registered_metadata_scope_requires_exact_registered_adapter_and_preflight(self):
        materials, plan, manifest = _fixture()
        store = _Store("bounded-process-v1", materials)
        connections = _Connections()
        registry = ExecutionBindings(store.settings, store, connections)
        service = RemoteBindingService.__new__(RemoteBindingService)
        service.store, service.bindings = store, registry
        store.execution_bindings = registry
        store.remote_bindings = service

        plan = _manifest(manifest, store, "alice", receiver=True)
        source = plan["executionBindings"]["tools"][0]
        tool_material = next(item for item in materials if item["kind"] == "tool")

        with self.assertRaises(HTTPException) as missing:
            service._effective_check("tool", source, source, tool_material, "bob")
        self.assertEqual(missing.exception.status_code, 409)
        self.assertIn("adapter revision is unavailable", str(missing.exception.detail))
        self.assertEqual(connections.preflights, [])

        registry.register(
            "tool",
            "fixture-metadata-v1",
            "1",
            lambda _context: None,
            tool_name="fixture_metadata",
            connection_kind="model",
            required_capabilities=("metadata:read",),
            permissions=("metadata:read",),
        )
        service._effective_check("tool", source, source, tool_material, "bob")

        self.assertEqual(len(connections.preflights), 1)
        owner, reference, options = connections.preflights[0]
        self.assertEqual((owner, reference), ("bob", "fixture-metadata-connection"))
        self.assertEqual(options["expected_kind"], "model")
        self.assertEqual(options["expected_revision"], "operator-r1")
        self.assertEqual(options["expected_fingerprint"], "a" * 64)
        self.assertEqual(options["expected_version"], 1)
        self.assertEqual(options["required_capabilities"], ("metadata:read",))
        self.assertEqual(options["expected_adapter_ref"], "fixture-metadata-v1")

        widened = deepcopy(source)
        widened["connection"]["capabilities"].append("experiment:run")
        with self.assertRaises(HTTPException) as denied:
            service._effective_check("tool", source, widened, tool_material, "bob")
        self.assertEqual(denied.exception.status_code, 409)
        self.assertIn("connection", str(denied.exception.detail).lower())


if __name__ == "__main__":
    unittest.main()
