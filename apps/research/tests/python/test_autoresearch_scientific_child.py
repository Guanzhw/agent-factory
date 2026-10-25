"""Ancestor-bound adapters with inert durable-pin service, no process execution."""
from agent_factory_research.services import ResearchServices, bind_registrations
from copy import deepcopy
from types import SimpleNamespace
from typing import cast
import unittest
from unittest.mock import AsyncMock, Mock

from agno.models.message import Message
from agno.run import RunContext
from agent_factory_research import autoresearch_scientific_child as profile
from agent_factory.execution_bindings import BindingContext
from agent_factory.material_governance import MaterialDefinition
from agent_factory_research.research_manifest import manifest_fingerprint
from test_research_manifest import example_manifest  # pyright: ignore[reportMissingImports]


def context(phase):
    manifest = example_manifest()
    pin = {'targetRef': 'original-' + phase, 'comparisonManifest': manifest,
        'comparisonManifestSha256': manifest_fingerprint(manifest), 'variantSha256': 'b'*64}
    store = SimpleNamespace(authorize_tool=Mock(), process_runtime=SimpleNamespace(run=AsyncMock(return_value={'originalLeaseId': 'lease'})))
    research = ResearchServices(factory_store=store, installed=True, autoresearch_children=SimpleNamespace(require_child=Mock(return_value=pin), verify_preparation=AsyncMock(return_value={'execution': {'taskId': 'original-producer'}, 'artifact': {'id': 'retained'}})))
    ctx = BindingContext(SimpleNamespace(demo=True, temporary_policy='member-self-service'),
        store,
        {'ownerId': 'alice', 'application': profile.APPLICATION_ID, 'applicationRef': {'id': profile.APPLICATION_ID},
         'mode': profile.MODE_NAMES[phase], 'tools': [profile.TOOLS[phase]], 'capabilities': [profile.CAPABILITIES[phase]],
         'delegation': {'parentTaskId': 'parent', 'rootTaskId': 'parent', 'depth': 1}},
        RunContext(user_id='alice', session_id='original-child', run_id='original-child-run'),
        {'config': {'presetId': 'project', 'phase': phase}})
    return ctx, research


class ScientificChildProfileTests(unittest.IsolatedAsyncioTestCase):
    async def test_preparation_reads_original_artifact_without_launch_and_rechecks_parent(self):
        ctx, research = context('preparation')
        entry = next(e for e in profile.registrations('project') if e.kind == 'tool' and e.tool_name == 'research_preparation_verify')
        tool = bind_registrations([entry], research)[0].factory(ctx)
        await tool.entrypoint(run_context=ctx.run_context)
        research.autoresearch_children.verify_preparation.assert_awaited_once_with(ctx)
        ctx.store.process_runtime.run.assert_not_awaited()
        self.assertEqual(research.autoresearch_children.require_child.call_count, 3)
        research.autoresearch_children.require_child.side_effect = PermissionError('parent revoked')
        with self.assertRaises(PermissionError): await tool.entrypoint(run_context=ctx.run_context)
        ctx.store.process_runtime.run.assert_not_awaited()
        research.autoresearch_children.verify_preparation.assert_awaited_once()

    def test_training_evaluation_preserve_external_requirement_and_exact_manifest(self):
        for phase in ('training', 'evaluation'):
            ctx, research = context(phase)
            entries = {e.kind: e for e in profile.registrations('project') if e.adapter_id.startswith('autoresearch-child-'+phase+'-')}
            tool = bind_registrations([entries['tool']], research)[0].factory(ctx)
            self.assertTrue(tool.external_execution)
            with self.assertRaises(ValueError): tool.entrypoint(run_context=ctx.run_context)
            ctx.store.process_runtime.run.assert_not_awaited()
            knowledge = bind_registrations([entries['knowledge']], research)[0].factory(ctx)
            self.assertEqual(knowledge.provenance['evidenceKind'], 'offline_research_experiment_manifest')
            model = bind_registrations([entries['model']], research)[0].factory(ctx)
            result = model.invoke([])
            self.assertEqual(result.tool_calls[0]['function']['name'], 'research_process_run')
            message = Message(role='tool', tool_name='research_process_run', content='original-receipt')
            final = model.invoke([message])
            self.assertFalse(final.tool_calls); self.assertIn('scientificConclusionVerified', final.content)
            self.assertEqual(model.retries, 0)

    def test_standalone_forged_ancestry_and_changed_pin_fail_closed(self):
        for change in ({'delegation': None}, {'delegation': {'parentTaskId': 'parent', 'rootTaskId': 'other', 'depth': 1}},
                       {'mode': 'controlled-fixture'}, {'ownerId': 'bob'}, {'remoteHandoff': {'id': 'remote'}}):
            ctx, research = context('training'); cast(dict, ctx.plan).update(change)
            with self.subTest(change=change), self.assertRaises(ValueError): profile.child_pin(ctx, 'training', research=research)
            research.autoresearch_children.require_child.assert_not_called()
        ctx, research = context('training')
        pin = deepcopy(research.autoresearch_children.require_child.return_value)
        pin['comparisonManifestSha256'] = 'f'*64
        research.autoresearch_children.require_child.return_value = pin
        with self.assertRaises(ValueError): profile.child_pin(ctx, 'training', research=research)
        research.autoresearch_children.require_child.side_effect = PermissionError('unknown original binding')
        with self.assertRaises(PermissionError): profile.child_pin(ctx, 'training', research=research)

    def test_materials_and_zero_local_pricing_are_phase_distinct(self):
        ids = set()
        for phase in profile.PHASES:
            rows = profile.material_drafts('project', phase)
            for row in rows:
                MaterialDefinition.model_validate(row)
                self.assertNotIn(row['id'], ids); ids.add(row['id'])
            tool = next(row for row in rows if row['kind'] == 'tool')
            self.assertEqual(tool['content'], profile.TOOLS[phase]); self.assertEqual(tool['permissions'], [profile.CAPABILITIES[phase]])
        prices = profile.pricing_registrations()
        self.assertEqual(len(prices), 3)
        self.assertTrue(all(p.local_model_type is profile.ScientificChildControlModel for p in prices))
        self.assertTrue(all(e.demo_only for e in profile.registrations('project')))
