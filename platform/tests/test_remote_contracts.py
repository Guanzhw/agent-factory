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


class _Applications:
    def require_plan_current(self, plan):
        return None


class _Policy:
    def __init__(self, contract: str):
        self.contract = contract

    def current(self):
        return {"tool_contract": self.contract}


class _Connections:
    def __init__(self):
        self.preflights = []

    def preflight(self, owner, reference, **kwargs):
        self.preflights.append((owner, reference, kwargs))
        return {"ref": reference, "configured": True}


class _Store:
    def __init__(self, contract: str, materials: list[dict]):
        self.settings = SimpleNamespace(
            demo=False,
            runtime_tool_contract=contract,
            max_tool_calls=8,
            experiment_timeout_seconds=8,
            experiment_output_bytes=65536,
        )
        self.plan_policy = _Policy(contract)
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
        "ref": "orx-demo",
        "version": 1,
        "fingerprint": "a" * 64,
        "kind": "orx",
        "revision": "operator-r1",
        "capabilities": ["research:read"],
        "taskId": None,
    }
    model_binding = {"adapterId": "fixture-model-v1", "revision": "1", "config": {}}
    environment_binding = {"adapterId": "fixture-environment-v1", "revision": "1", "config": {}}
    tool_binding = {
        "adapterId": "openresearch-discover-v1",
        "revision": "1",
        "config": {"connectionName": "literatureProvider"},
    }
    materials = [
        _material("fixture-model", "model", "fixture-model-v1", model_binding),
        _material("fixture-environment", "environment", "fixture-environment-v1", environment_binding),
        _material("fixture-orx-discover", "tool", "orx_discover", tool_binding, ["research:read"]),
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
            "toolName": "orx_discover",
        }],
        "knowledge": [],
    }
    execution_bindings = {**binding_body, "sha256": digest(binding_body)}
    binding_anchor = {
        "schema": 1,
        "executionBindingsSha256": execution_bindings["sha256"],
        "connections": {"literatureProvider": connection},
        "materialRefs": refs,
    }
    binding_anchor["sha256"] = digest(binding_anchor)
    plan = {
        "id": str(uuid4()),
        "ownerId": "alice",
        "normalizedGoal": "Find public research metadata.",
        "mode": "research",
        "application": "research",
        "instructions": ["Return a short public metadata summary."],
        "tools": ["orx_discover"],
        "config": {
            "askScope": False,
            "sample": "public metadata",
            "experimentDurationSeconds": 1,
            "toolOrder": ["orx_discover"],
        },
        "materialRefs": refs,
        "materials": materials,
        "capabilities": ["research:read"],
        "missing": [],
        "status": "ready",
        "createdAt": "2026-10-02T00:00:00+00:00",
        "policy": "read-only-auto",
        "budget": {
            "toolCalls": 2,
            "maxDepth": 1,
            "maxChildren": 1,
            "experimentSeconds": 1,
            "outputBytes": 4096,
            "depth": 0,
        },
        "syntheticFixture": False,
        "applicationRef": {"id": "research", "version": 1, "sha256": "b" * 64},
        "executionBindings": execution_bindings,
        "bindingManifest": binding_anchor,
        "compositionProposalId": str(uuid4()),
    }
    plan["fingerprint"] = digest({key: value for key, value in plan.items()
                                  if key not in {"id", "createdAt", "fingerprint"}})
    manifest = {"plan": plan, "sha256": digest(plan)}
    return materials, plan, manifest


class RemoteContractsTests(unittest.TestCase):
    def test_legacy_tool_contract_and_origin_fingerprint_are_stable(self):
        self.assertEqual(
            tools_for_contract("legacy-v1"),
            {
                "literature_search": "research:read",
                "ask_scope": "question:ask",
                "checksum": "checksum:read",
                "run_experiment": "experiment:synthetic",
            },
        )
        origin = TrustedOrigin("fixture-origin", {"alice": "bob"}, lambda *_: None)
        self.assertEqual(origin.fingerprint, "54041d86f7edace9b101ea7104a5b0127d0f083d610199d300e39f8ac4ad809b")
        self.assertEqual(origin.tool_contract, "legacy-v1")

    def test_registered_remote_contract_requires_a_distinct_operator_revision(self):
        with self.assertRaisesRegex(ValueError, "distinct operator revision"):
            TrustedOrigin(
                "fixture-origin",
                {"alice": "bob"},
                lambda *_: None,
                capabilities=frozenset({"research:read"}),
                tools=frozenset({"orx_discover"}),
                tool_contract="registered-runtime-v1",
            )

        origin = TrustedOrigin(
            "fixture-origin",
            {"alice": "bob"},
            lambda *_: None,
            capabilities=frozenset({"research:read"}),
            tools=frozenset({"orx_discover"}),
            configuration_revision="orx-contract-r2",
            tool_contract="registered-runtime-v1",
        )
        self.assertEqual(origin.tool_contract, "registered-runtime-v1")
        self.assertNotEqual(origin.fingerprint, "54041d86f7edace9b101ea7104a5b0127d0f083d610199d300e39f8ac4ad809b")

    def test_orx_manifest_is_rejected_by_legacy_admission(self):
        materials, _, manifest = _fixture()
        store = _Store("legacy-v1", materials)
        registry = ExecutionBindings(store.settings, store, _Connections())
        service = RemoteBindingService.__new__(RemoteBindingService)
        service.store, service.bindings = store, registry
        store.execution_bindings = registry
        store.remote_bindings = service

        with self.assertRaises(HTTPException) as denied:
            _manifest(manifest, store, "alice", receiver=True)

        self.assertEqual(denied.exception.status_code, 422)
        self.assertIn("unregistered remote tool", str(denied.exception.detail))
        self.assertEqual(tools_for_contract("legacy-v1").get("orx_discover"), None)

    def test_registered_orx_scope_requires_exact_registered_adapter_and_preflight(self):
        materials, plan, manifest = _fixture()
        store = _Store("registered-runtime-v1", materials)
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
            "openresearch-discover-v1",
            "1",
            lambda _context: None,
            tool_name="orx_discover",
            connection_kind="orx",
            required_capabilities=("research:read",),
            permissions=("research:read",),
        )
        service._effective_check("tool", source, source, tool_material, "bob")

        self.assertEqual(len(connections.preflights), 1)
        owner, reference, options = connections.preflights[0]
        self.assertEqual((owner, reference), ("bob", "orx-demo"))
        self.assertEqual(options["expected_kind"], "orx")
        self.assertEqual(options["expected_revision"], "operator-r1")
        self.assertEqual(options["expected_fingerprint"], "a" * 64)
        self.assertEqual(options["expected_version"], 1)
        self.assertEqual(options["required_capabilities"], ("research:read",))
        self.assertEqual(options["expected_adapter_ref"], "openresearch-discover-v1")

        widened = deepcopy(source)
        widened["connection"]["capabilities"].append("experiment:run")
        with self.assertRaises(HTTPException) as denied:
            service._effective_check("tool", source, widened, tool_material, "bob")
        self.assertEqual(denied.exception.status_code, 409)
        self.assertIn("connection", str(denied.exception.detail).lower())


if __name__ == "__main__":
    unittest.main()
