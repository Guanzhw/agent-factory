"""Offline-only development profile contracts. No environment or live billing evidence."""
import asyncio
import copy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, call, patch

import httpx
from fastapi import HTTPException

from agent_factory.applications import ApplicationDefinition
from agent_factory.execution_bindings import BindingContext, ExecutionBindings
from fixture_go_development import (APPLICATION_ID, CAPABILITY, CONNECTION_NAME, MODEL_ADAPTER_IDS,
    GoDevelopmentHandle, application_definition, material_drafts, model_registrations, preflight,
    _scope, preflight_plan, publish_go_development_models, stable_session, trusted_model_binding)
from agent_factory.material_governance import MaterialDefinition


class GoDevelopmentProfileTests(unittest.TestCase):
    def fixture(self, model="deepseek-v4-flash"):
        transport = httpx.MockTransport(lambda request: httpx.Response(500))
        handle = GoDevelopmentHandle(mode="fixture", async_transport=transport)
        settings = SimpleNamespace(development_profile="opencode-go")
        plan = {"ownerId": "alice", "application": APPLICATION_ID, "applicationRef": {"id": APPLICATION_ID},
                "mode": model, "tools": ["checksum"], "capabilities": ["checksum:read"]}
        context = SimpleNamespace(user_id="alice", session_id="synthetic-session-123", run_id="synthetic-run-123")
        spec = next(d["runtimeBinding"] for d in material_drafts() if d["runtimeBinding"]["adapterId"] == MODEL_ADAPTER_IDS[model])
        return BindingContext(settings, None, plan, context, spec, handle)

    def test_unknown_model_fails_before_callbacks_or_transport(self):
        credential, billing = Mock(), Mock(return_value=True)
        handle = GoDevelopmentHandle(credential=credential, billing_verified=billing)
        with self.assertRaises(HTTPException) as caught:
            preflight(handle, session_id='synthetic-session', model_id='unregistered-model', settings=SimpleNamespace())
        self.assertTrue(caught.exception.detail.startswith('GO_DEVELOPMENT_BINDING'))
        credential.assert_not_called()
        billing.assert_not_called()

    def test_live_profile_remains_blocked_even_if_verifier_claims_true(self):
        for verifier in (None, Mock(return_value=False), Mock(return_value=True)):
            credential = Mock()
            handle = GoDevelopmentHandle(credential=credential, billing_verified=verifier)
            with self.assertRaises(HTTPException) as caught:
                preflight(handle, session_id="synthetic-session", model_id="gpt-6-luna", settings=self.fixture().settings)
            self.assertTrue(caught.exception.detail.startswith("GO_LIVE_VALIDATION_PENDING"))
            credential.assert_not_called()
            if verifier is not None: verifier.assert_not_called()

    def test_fixture_has_explicit_transport_and_no_real_credential_or_billing_input(self):
        transport = self.fixture().connection.async_transport
        for kwargs in ({}, {"async_transport": transport, "credential": Mock()},
                       {"async_transport": transport, "billing_verified": Mock()}):
            with self.assertRaises(ValueError): GoDevelopmentHandle(mode="fixture", **kwargs)
        handle = GoDevelopmentHandle(mode="fixture", async_transport=transport)
        result = preflight(handle, session_id="synthetic-session", model_id="gpt-6-luna", settings=self.fixture().settings)
        self.assertEqual(result["evidenceMode"], "fixture")
        self.assertEqual(result["protocol"], "responses")
        self.assertNotIn("credential", repr(handle))
        self.assertNotIn("transport", repr(handle))
        with self.assertRaises(ValueError): GoDevelopmentHandle(credential=Mock(), native_retries=1)

    def test_fixture_transport_allowlist_rejects_network_and_subclass_escape(self):
        from go_http_fixture import GoLoopbackTransport
        class DisguisedMock(httpx.MockTransport):
            pass
        network = httpx.AsyncHTTPTransport()
        self.addCleanup(lambda: asyncio.run(network.aclose()))
        for transport in (network, DisguisedMock(lambda request: httpx.Response(200))):
            with self.subTest(transport=type(transport).__name__), self.assertRaises(ValueError):
                GoDevelopmentHandle(mode="fixture", async_transport=transport)
        for base_url in ("http://127.0.0.1:19876", "http://[::1]:19876"):
            transport = GoLoopbackTransport(base_url)
            self.addCleanup(lambda transport=transport: asyncio.run(transport.aclose()))
            handle = GoDevelopmentHandle(mode="fixture", async_transport=transport)
            self.assertIs(handle.async_transport, transport)
            self.assertEqual(preflight(handle, session_id="synthetic-session", model_id="gpt-6-luna",
                settings=self.fixture().settings)["evidenceMode"], "fixture")

    def test_registration_factory_has_exact_model_session_and_scope(self):
        entries = model_registrations()
        self.assertEqual({entry.adapter_id for entry in entries}, set(MODEL_ADAPTER_IDS.values()))
        for model, entry in zip(MODEL_ADAPTER_IDS, entries):
            context = self.fixture(model)
            with patch("fixture_go_development.GoDevelopmentModel") as constructor:
                entry.factory(context)
            kwargs = constructor.call_args.kwargs
            self.assertEqual(kwargs["model_id"], model)
            self.assertEqual(kwargs["session_id"], context.run_context.session_id)
            self.assertEqual(kwargs["native_retries"], 0)
            self.assertTrue(kwargs["wire_stream"])
            self.assertIs(kwargs["async_transport"], context.connection.async_transport)
            self.assertFalse(hasattr(entry, "demo_only"))
            self.assertEqual(entry.required_capabilities, (CAPABILITY,))
            self.assertEqual(stable_session(context.run_context), stable_session(context.run_context))

    def test_real_factory_constructs_native_models_without_transport_dispatch(self):
        from agent_factory.opencode_go import GoDevelopmentModel, USER_AGENT
        calls = []
        transport = httpx.MockTransport(lambda request: calls.append(request) or httpx.Response(500))
        for model, registration in zip(MODEL_ADAPTER_IDS, model_registrations()):
            context = self.fixture(model)
            context = BindingContext(context.settings, None, context.plan, context.run_context, context.spec,
                                     GoDevelopmentHandle(mode="fixture", async_transport=transport))
            native = registration.factory(context)
            self.assertIsInstance(native, GoDevelopmentModel)
            self.assertEqual(native.id, model)
            self.assertEqual(native._headers()["x-opencode-session"], context.run_context.session_id)
            self.assertEqual(native._headers()["User-Agent"], USER_AGENT)
            self.assertEqual(native.retries, 0)
        self.assertEqual(calls, [])

    def test_foreign_application_tool_model_alias_delegation_and_material_override_rejected(self):
        for changes in ({"application": "auto-research"}, {"applicationRef": {"id": "foreign"}},
                        {"tools": ["run_experiment"]}, {"capabilities": ["compute:local"]},
                        {"mode": "deepseek-flash"}, {"delegation": {"rootTaskId": "parent"}}):
            context = self.fixture()
            with self.subTest(changes=changes), self.assertRaises(HTTPException):
                _scope({**context.plan, **changes}, model_id="deepseek-v4-flash")
        entry = model_registrations()[0]
        for config in ({}, {"scope": "research"}, {"scope": "coding-development", "base_url": "https://foreign.invalid"},
                       {"scope": "coding-development", "model": "gpt-6-luna"}):
            with self.assertRaises(ValueError): entry.validator(config)
        with self.assertRaises(HTTPException):
            preflight(self.fixture().connection, session_id="synthetic-session", model_id="deepseek-unregistered", settings=self.fixture().settings)

    def test_plan_preflight_uses_exact_current_connection_without_factory_or_credentials(self):
        context = self.fixture()
        pin = {"ref": "synthetic-pin", "version": 1, "fingerprint": "a" * 64, "kind": "model",
               "revision": "1", "capabilities": [CAPABILITY], "taskId": None}
        plan = {**context.plan, "executionBindings": {"model": {**context.spec, "connection": pin}}}
        connections = Mock()
        connections.resolve.return_value = context.connection
        with patch("fixture_go_development.GoDevelopmentModel") as factory:
            result = preflight_plan(context.settings, plan, connections)
            self.assertEqual(result["evidenceMode"], "fixture")
            self.assertEqual(connections.resolve.call_args.kwargs["expected_fingerprint"], pin["fingerprint"])
            self.assertIsNone(connections.resolve.call_args.kwargs["task_id"])
            preflight_plan(context.settings, plan, connections, context.run_context)
            self.assertEqual(connections.resolve.call_args.kwargs["task_id"], context.run_context.session_id)
            connections.resolve.side_effect = HTTPException(409, "Current connection revoked")
            with self.assertRaises(HTTPException): preflight_plan(context.settings, plan, connections, context.run_context)
            factory.assert_not_called()
        connections.reset_mock()
        self.assertIsNone(preflight_plan(context.settings, {"application": "auto-research"}, connections))
        connections.resolve.assert_not_called()

    def test_materials_and_application_use_real_schema_and_are_not_discoverable_defaults(self):
        materials = []
        for draft in material_drafts():
            MaterialDefinition.model_validate(draft)
            materials.append({**draft, "version": 1, "sha256": "a" * 64})
        other = {"id": "checksum-tool", "version": 1, "sha256": "b" * 64}
        environment = {"id": "local-environment", "version": 1, "sha256": "c" * 64}
        definition = application_definition(materials, other, environment)
        validated = ApplicationDefinition.model_validate(definition)
        self.assertFalse(validated.defaultForDiscovery)
        self.assertEqual(validated.discoveryKeywords, [])
        for mode in validated.modes.values():
            self.assertEqual(mode.toolOrder, ["checksum"])
            self.assertEqual(mode.connectionRequirements[0].name, CONNECTION_NAME)
            self.assertEqual(mode.connectionRequirements[0].requiredCapabilities, [])
            self.assertEqual(mode.capabilities, ["checksum:read"])
        self.assertNotIn("api_key", json.dumps(definition))
    def test_member_publishes_exact_model_versions_without_review_or_dispatch(self):
        for revision in ("1", "2"):
            with self.subTest(revision=revision):
                materials = [{**draft, "version": 3, "sha256": "a" * 64, "published": True}
                    for draft in material_drafts(luna_output_revision=revision)]
                governance = Mock()
                governance.create_draft.side_effect = materials
                store = Mock()
                store.materials.return_value = materials
                state = {"auth": Mock(), "material_governance": governance, "store": store}
                with patch("fixture_go_development.GoDevelopmentModel") as model:
                    result = publish_go_development_models(state, author="alice", luna_output_revision=revision)
                self.assertEqual(result, materials)
                state["auth"].require_member.assert_called_once_with("alice")
                key = "go-development-v1" + (":output-2" if revision == "2" else "")
                self.assertEqual(governance.publish.call_args_list, [
                    call("alice", material["id"], 3, key + ":publish:" + material["id"]) for material in materials])
                self.assertEqual([row.args[:2] for row in governance.create_draft.call_args_list],
                    [("alice", draft) for draft in material_drafts(luna_output_revision=revision)])
                governance.request_publication.assert_not_called()
                governance.decide_publication.assert_not_called()
                model.assert_not_called()

    def test_revoked_member_cannot_create_or_publish_model_materials(self):
        governance = Mock()
        state = {"auth": Mock(), "material_governance": governance}
        state["auth"].require_member.side_effect = HTTPException(403, "Permission revoked")
        with self.assertRaises(HTTPException) as denied:
            publish_go_development_models(state, author="alice")
        self.assertEqual(denied.exception.status_code, 403)
        governance.create_draft.assert_not_called()
        governance.publish.assert_not_called()
        governance.request_publication.assert_not_called()

    def test_real_binding_registry_rejects_override_and_production_selection(self):
        context = self.fixture()
        registry = ExecutionBindings(context.settings, None)
        for entry in model_registrations():
            registry.register(entry.kind, entry.adapter_id, entry.revision, entry.factory,
                connection_kind=entry.connection_kind, required_capabilities=entry.required_capabilities,
                validator=entry.validator, connection_adapter_ref=entry.connection_adapter_ref)
        self.assertEqual(registry._entry("model", context.spec).adapter_id, context.spec["adapterId"])
        altered = copy.deepcopy(context.spec)
        altered["config"]["scope"] = "research"
        material = next(row for row in material_drafts() if row["runtimeBinding"]["adapterId"] == context.spec["adapterId"])
        with self.assertRaises(HTTPException) as invalid:
            registry._spec({**material, "version": 1, "sha256": "a" * 64, "runtimeBinding": altered}, {})
        self.assertIn("BINDING_CONFIG_INVALID", invalid.exception.detail)
        binding = trusted_model_binding("alice", context.connection)
        self.assertEqual(binding.kind, "model")
        self.assertEqual(binding.capabilities, frozenset({CAPABILITY}))
        self.assertNotIn("credential", json.dumps(binding.metadata()))


if __name__ == "__main__":
    unittest.main()
