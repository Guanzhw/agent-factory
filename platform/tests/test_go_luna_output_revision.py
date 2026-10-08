"""Offline immutable Luna output revision; no credential or network access."""
import copy
from dataclasses import replace
import unittest
from typing import Any, cast
from unittest.mock import Mock

from agno.models.message import Message
from fastapi import HTTPException

from agent_factory.execution_bindings import BindingContext, ExecutionBindings
from agent_factory.go_development import CAPABILITY, MODEL_ADAPTER_IDS, material_drafts, model_registrations, preflight_plan
from agent_factory.go_usage import luna_512_pricing, pricing_registrations, request_guard
from agent_factory.material_governance import MaterialDefinition
import test_go_development_profile as helpers  # type: ignore[reportMissingImports]


class LunaOutputRevisionTests(unittest.TestCase):
    def context(self, model="gpt-6-luna", revision="2"):
        base = helpers.GoDevelopmentProfileTests().fixture(model)
        spec = next(d["runtimeBinding"] for d in material_drafts(luna_output_revision=revision)
                    if d["runtimeBinding"]["adapterId"] == MODEL_ADAPTER_IDS[model])
        return BindingContext(base.settings, base.store, base.plan, base.run_context, spec, base.connection)

    def test_revision_one_defaults_unchanged_and_revision_two_is_luna_only(self):
        defaults = model_registrations()
        self.assertTrue(all(r.revision == "1" for r in defaults))
        for model, entry in zip(MODEL_ADAPTER_IDS, defaults, strict=True):
            instance = entry.factory(self.context(model, "1"))
            self.assertEqual(instance._cap, 256)
            self.assertEqual(instance.retries, 0)
        revised = model_registrations(revision="2")
        self.assertEqual([(r.adapter_id, r.revision) for r in revised], [(MODEL_ADAPTER_IDS["gpt-6-luna"], "2")])
        instance = revised[0].factory(self.context())
        self.assertEqual(instance.id, "gpt-6-luna")
        self.assertEqual(instance._cap, 512)
        self.assertEqual(instance.retries, 0)

    def test_exact_config_and_unknown_revisions_fail_closed(self):
        entry = model_registrations(revision="2")[0]
        assert entry.validator is not None
        config = {k: v for k, v in self.context().spec["config"].items() if k != "connectionName"}
        entry.validator(config)
        for cap in (256, 513, True, False, 512.0, "512", None):
            with self.subTest(cap=cap), self.assertRaises(ValueError):
                entry.validator({**config, "maxOutputTokens": cap})
        for revision in ("0", "3", 2, True, None):
            with self.assertRaises(ValueError):
                model_registrations(revision=cast(Any, revision))
            with self.assertRaises(ValueError):
                material_drafts(luna_output_revision=cast(Any, revision))
        with self.assertRaises(ValueError):
            entry.validator({"scope": config["scope"]})
        legacy_validator = model_registrations()[0].validator
        assert legacy_validator is not None
        with self.assertRaises(ValueError):
            legacy_validator(config)

    def test_material_revision_and_cap_are_part_of_bound_definition(self):
        legacy = {d["id"]: d for d in material_drafts()}
        revised = material_drafts(luna_output_revision="2")
        for draft in revised:
            MaterialDefinition.model_validate(draft)
            binding = draft["runtimeBinding"]
            if binding["adapterId"] == MODEL_ADAPTER_IDS["gpt-6-luna"]:
                self.assertEqual(binding["revision"], "2")
                self.assertEqual(binding["config"]["maxOutputTokens"], 512)
                self.assertNotEqual(draft, legacy[draft["id"]])
                self.assertEqual(legacy[draft["id"]]["runtimeBinding"]["revision"], "1")
                self.assertNotIn("maxOutputTokens", legacy[draft["id"]]["runtimeBinding"]["config"])
            else:
                self.assertEqual(draft, legacy[draft["id"]])

    def test_revision_two_preflight_rechecks_owner_pin_and_denies_other_models(self):
        context = self.context()
        pin = {"ref": "synthetic-pin", "version": 1, "fingerprint": "a"*64, "kind": "model",
               "revision": "1", "capabilities": [CAPABILITY], "taskId": None}
        plan = {**context.plan, "executionBindings": {"model": {**context.spec, "connection": pin}}}
        connections = Mock()
        connections.resolve.return_value = context.connection
        result = preflight_plan(context.settings, plan, connections, context.run_context)
        assert result is not None
        self.assertEqual(result["evidenceMode"], "fixture")
        self.assertEqual(connections.resolve.call_args.args, ("alice", pin["ref"]))
        self.assertEqual(connections.resolve.call_args.kwargs["expected_fingerprint"], pin["fingerprint"])
        self.assertEqual(connections.resolve.call_args.kwargs["expected_revision"], pin["revision"])
        self.assertEqual(connections.resolve.call_args.kwargs["task_id"], context.run_context.session_id)
        wrong_owner = copy.deepcopy(context.run_context)
        wrong_owner.user_id = "mallory"
        with self.assertRaises(HTTPException):
            preflight_plan(context.settings, plan, connections, wrong_owner)
        for model in ("deepseek-flash", "deepseek-v4-flash"):
            other = self.context(model, "1")
            other_spec = {**other.spec, "revision": "2", "connection": pin}
            other_plan = {**other.plan, "executionBindings": {"model": other_spec}}
            connections.reset_mock()
            with self.assertRaises(HTTPException):
                preflight_plan(other.settings, other_plan, connections, other.run_context)
            connections.resolve.assert_not_called()

    def test_binding_registry_requires_exact_installed_revision(self):
        context = self.context()
        registry = ExecutionBindings(context.settings, None)
        for entry in [*model_registrations(), *model_registrations(revision="2")]:
            registry.register(entry.kind, entry.adapter_id, entry.revision, entry.factory,
                connection_kind=entry.connection_kind, required_capabilities=entry.required_capabilities,
                validator=entry.validator, demo_only=entry.demo_only, connection_adapter_ref=entry.connection_adapter_ref)
        self.assertEqual(registry._entry("model", context.spec).revision, "2")
        for changed in ({**context.spec, "revision": "3"},
                        {**context.spec, "adapterId": MODEL_ADAPTER_IDS["deepseek-flash"]}):
            with self.assertRaises(HTTPException):
                registry._entry("model", changed)

    def test_pricing_new_identity_same_reservation_and_guard_blocks_overflow_retry(self):
        legacy = next(p for p in pricing_registrations(MODEL_ADAPTER_IDS) if p.model == "gpt-6-luna")
        revised = luna_512_pricing()
        self.assertEqual(revised.adapter_revision, "2")
        self.assertNotEqual(revised.revision, legacy.revision)
        self.assertNotEqual(revised.sha256, legacy.sha256)
        self.assertEqual(revised.per_attempt_output_tokens, 512)
        self.assertEqual(revised.accounting_basis, "operator-nominal-not-invoice")
        self.assertEqual(replace(revised, adapter_revision=legacy.adapter_revision, revision=legacy.revision).body, legacy.body)
        model = model_registrations(revision="2")[0].factory(self.context())
        commitment = {"perAttemptInputTokens": 32768, "perAttemptOutputTokens": 512}
        arguments = ([Message(role="user", content="Synthetic coding revision test")],)
        request_guard(model, arguments, {}, commitment)
        for field, value in (("_cap", 513), ("retries", 1)):
            previous = getattr(model, field)
            setattr(model, field, value)
            with self.assertRaises(HTTPException):
                request_guard(model, arguments, {}, commitment)
            setattr(model, field, previous)
