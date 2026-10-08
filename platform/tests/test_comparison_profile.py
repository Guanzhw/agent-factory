"""Governed finite profile wiring with mocks; no process/DB/provider execution."""
from copy import deepcopy
from types import SimpleNamespace
import unittest
from typing import Any
from unittest.mock import AsyncMock, Mock

from agno.run import RunContext
from agent_factory.comparison_fixture import input_manifest
from agent_factory.comparison_profile import (APPLICATION_ID, CHOICES, ENVIRONMENT_ID, KNOWLEDGE_ID, MODEL_ID,
    TOOL_ID, TOOL_NAME, ComparisonFixtureModel, application_definition, material_drafts,
    pricing_registration, publish_comparison_application, registrations)
from agent_factory.execution_bindings import KnowledgeContext
from agent_factory.store import digest


def context(choice='linear-v1', adapter=MODEL_ID) -> Any:
    run = RunContext(user_id='alice', session_id='task', run_id='native')
    config = {'targetRef': 'fixed-target'}
    return SimpleNamespace(settings=SimpleNamespace(demo=True, temporary_policy='admin-review'),
        run_context=run, spec={'config': config if adapter == TOOL_ID else {**config, 'choice': choice}},
        plan={'ownerId': 'alice', 'application': APPLICATION_ID, 'applicationRef': {'id': APPLICATION_ID},
              'mode': choice, 'tools': [TOOL_NAME], 'capabilities': ['compute:local'],
              'executionBindings': {'tools': [{'adapterId': TOOL_ID, 'revision': '1', 'config': config}]}},
        store=SimpleNamespace(authorize_tool=Mock(), process_runtime=SimpleNamespace(run=AsyncMock(return_value={'original': True})),
                              comparisons=SimpleNamespace(persist=AsyncMock(return_value={'verified': True}))))


class ComparisonProfileTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.entries = {item.adapter_id: item for item in registrations()}

    def test_finite_choices_manifest_six_kinds_and_exact_configs(self):
        for choice in CHOICES:
            rows = material_drafts(choice, 'fixed-target')
            self.assertEqual({row['kind'] for row in rows}, {'skill', 'prompt', 'knowledge', 'model', 'tool', 'environment'})
            knowledge = next(row for row in rows if row['kind'] == 'knowledge')
            import json
            self.assertEqual(json.loads(knowledge['content']), input_manifest(choice))
            for row in rows:
                if 'runtimeBinding' in row:
                    expected = {'targetRef': 'fixed-target'}
                    if row['kind'] != 'tool': expected['choice'] = choice
                    self.assertEqual(row['runtimeBinding']['config'], expected)
        for choice, target in [('arbitrary', 'valid'), ('linear-v1', '../shell')]:
            with self.assertRaises(ValueError): material_drafts(choice, target)

    def test_controlled_model_pricing_and_knowledge_context_preserve_pins(self):
        model = self.entries[MODEL_ID].factory(context())
        self.assertIsInstance(model, ComparisonFixtureModel)
        self.assertEqual(model.id, MODEL_ID)
        knowledge = self.entries[KNOWLEDGE_ID].factory(context(adapter=KNOWLEDGE_ID))
        self.assertIsInstance(knowledge, KnowledgeContext)
        self.assertEqual(knowledge.provenance['inputManifestSha256'], digest(input_manifest('linear-v1')))
        self.assertFalse(knowledge.provenance['scientificValidation'])
        limits = self.entries[ENVIRONMENT_ID].factory(context(adapter=ENVIRONMENT_ID))
        self.assertEqual((limits.timeout_seconds, limits.memory_bytes, limits.output_bytes), (5, 128 * 1024 * 1024, 65536))
        self.assertIs(pricing_registration().local_model_type, ComparisonFixtureModel)

    def test_scope_rejects_production_policy_foreignowner_mode_remote_and_delegation(self):
        changes = [('settings', 'demo', False), ('settings', 'temporary_policy', 'bounded-synthetic'),
                   ('plan', 'ownerId', 'bob'), ('plan', 'mode', 'constant-v1'),
                   ('plan', 'application', 'other'), ('plan', 'delegation', {'parent': 'x'}),
                   ('plan', 'remoteHandoff', {'origin': 'x'})]
        for area, key, value in changes:
            ctx = context()
            if area == 'plan': ctx.plan[key] = value
            else: setattr(ctx.settings, key, value)
            with self.subTest(key=key), self.assertRaises(ValueError): self.entries[MODEL_ID].factory(ctx)
        ctx = context(); ctx.plan['executionBindings']['tools'][0]['config']['targetRef'] = 'another'
        with self.assertRaises(ValueError): self.entries[MODEL_ID].factory(ctx)

    async def test_tool_reuses_single_runtime_then_derived_persistence_with_fresh_checks(self):
        ctx = context(adapter=TOOL_ID)
        function = self.entries[TOOL_ID].factory(ctx)
        result = await function.entrypoint(run_context=ctx.run_context)
        self.assertIn('verified', result)
        ctx.store.process_runtime.run.assert_awaited_once_with(ctx.run_context, {'targetRef': 'fixed-target'})
        ctx.store.comparisons.persist.assert_awaited_once_with(ctx.run_context, {'original': True})
        self.assertEqual(ctx.store.authorize_tool.call_count, 3)

    async def test_no_persist_after_revoke_or_failed_process_and_no_foreign_context(self):
        ctx = context(adapter=TOOL_ID)
        function = self.entries[TOOL_ID].factory(ctx)
        ctx.store.authorize_tool.side_effect = [None, PermissionError('revoked')]
        with self.assertRaises(PermissionError): await function.entrypoint(run_context=ctx.run_context)
        ctx.store.comparisons.persist.assert_not_awaited()
        ctx = context(adapter=TOOL_ID); ctx.store.process_runtime.run.side_effect = ValueError('UNKNOWN')
        function = self.entries[TOOL_ID].factory(ctx)
        with self.assertRaises(ValueError): await function.entrypoint(run_context=ctx.run_context)
        ctx.store.comparisons.persist.assert_not_awaited()
        ctx = context(adapter=TOOL_ID); function = self.entries[TOOL_ID].factory(ctx)
        with self.assertRaises(ValueError):
            await function.entrypoint(run_context=RunContext(user_id='bob', session_id='task', run_id='native'))
        ctx.store.process_runtime.run.assert_not_awaited()

    def test_application_modes_pin_exact_immutable_materials_without_mutation(self):
        rows = [{**row, 'version': 1, 'sha256': digest(row)} for row in material_drafts('linear-v1', 'fixed-target')]
        original = deepcopy(rows)
        app = application_definition({'linear-v1': rows})
        self.assertEqual(app['id'], APPLICATION_ID)
        self.assertEqual(app['modes']['linear-v1']['materialRefs'], [{key: row[key] for key in ('id', 'version', 'sha256')} for row in rows])
        self.assertEqual(app['modes']['linear-v1']['capabilities'], ['compute:local'])
        self.assertEqual(rows, original)

    def test_publication_calls_distinct_reviewer_for_every_material_and_application(self):
        def manager():
            return SimpleNamespace(create_draft=Mock(side_effect=lambda author, definition, key:
                {**deepcopy(definition), 'version': 1, 'sha256': digest(definition)}),
                request_publication=Mock(return_value={'id': 'review'}), decide_publication=Mock())
        state = {'auth': SimpleNamespace(require=Mock()), 'material_governance': manager(), 'applications': manager()}
        with self.assertRaises(ValueError):
            publish_comparison_application(state, {'linear-v1': 'fixed-target'}, author='manager', reviewer='manager')
        state['material_governance'].create_draft.assert_not_called()
        app = publish_comparison_application(state, {'linear-v1': 'fixed-target'}, author='manager', reviewer='manager2')
        self.assertEqual(app['id'], APPLICATION_ID)
        self.assertEqual(state['material_governance'].decide_publication.call_count, 6)
        for call in state['material_governance'].decide_publication.call_args_list:
            self.assertEqual(call.args[:3], ('manager2', 'review', True))
        state['applications'].decide_publication.assert_called_once()


if __name__ == '__main__':
    unittest.main()
