# pyright: reportMissingImports=false
"""Light native function/profile checks, without queue, DB, processes or providers."""
import asyncio
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any
import unittest
from unittest.mock import Mock

from agno.models.message import Message
from agno.run import RunContext

from agent_factory import research_runtime_profile as profile
from agent_factory.store import digest
from agent_factory.material_governance import MaterialDefinition
from agent_factory.research_manifest import manifest_fingerprint
from test_research_manifest import example_manifest


class ResearchRuntimeProfileTests(unittest.TestCase):
    def setUp(self):
        self.manifest = example_manifest()
        self.entries = profile.registrations(target_ref='research-target', comparison_manifest=self.manifest)
        self.ctx: Any = SimpleNamespace(spec={'config': {'targetRef': 'research-target', 'comparisonManifestSha256': manifest_fingerprint(self.manifest), 'variantSha256': self.manifest['baselineSourceManifestSha256']}},
            settings=SimpleNamespace(demo=True, temporary_policy='admin-review'),
            run_context=RunContext(user_id='alice', session_id='task', run_id='native'), store=Mock(),
            plan={'ownerId': 'alice', 'application': profile.APPLICATION_ID, 'applicationRef': {'id': profile.APPLICATION_ID},
                'mode': 'controlled-fixture', 'tools': [profile.TOOL_NAME], 'capabilities': [profile.PERMISSION]})

    def entry(self, kind):
        return next(entry for entry in self.entries if entry.kind == kind)

    def test_external_tool_cannot_launch_and_has_no_model_parameters(self):
        entry = self.entry('tool')
        self.assertFalse(entry.demo_only)
        function = entry.factory(self.ctx)
        self.assertTrue(function.external_execution)
        function.process_entrypoint()
        self.assertEqual(function.parameters['properties'], {})
        with self.assertRaisesRegex(ValueError, '^RESEARCH_EXTERNAL_EXECUTION_REQUIRED$'):
            function.entrypoint(run_context=self.ctx.run_context)
        self.ctx.store.assert_not_called()
        self.assertEqual(self.ctx.store.mock_calls, [])

    def test_exact_detached_config_pins_refuse_manifest_and_target_changes(self):
        self.manifest['protocol']['seed'] = 7
        for entry in self.entries:
            assert entry.validator is not None
            entry.validator(self.ctx.spec['config'])
            for changed in ({'targetRef': 'other', 'comparisonManifestSha256': manifest_fingerprint(example_manifest())},
                            self.ctx.spec['config'] | {'argv': []}):
                with self.assertRaises(ValueError):
                    entry.validator(changed)
            changed = deepcopy(self.ctx.spec['config'])
            changed['comparisonManifestSha256'] = '0' * 64
            with self.assertRaises(ValueError):
                entry.validator(changed)

    def test_fixture_model_scope_and_external_operator_scope_are_separate(self):
        self.assertTrue(self.entry('model').demo_only)
        for field, value in (('ownerId', 'bob'), ('mode', 'other'), ('application', 'other'),
                             ('delegation', {'x': True}), ('remoteHandoff', {'x': True}),
                             ('tools', ['other']), ('capabilities', ['compute:remote'])):
            original = deepcopy(self.ctx.plan)
            self.ctx.plan[field] = value
            with self.assertRaises(ValueError):
                self.entry('model').factory(self.ctx)
            self.ctx.plan = original
        self.ctx.run_context.user_id = 'bob'
        with self.assertRaises(ValueError):
            self.entry('model').factory(self.ctx)
        self.ctx.run_context.user_id = 'alice'
        self.ctx.settings.demo = False
        with self.assertRaises(ValueError):
            self.entry('model').factory(self.ctx)
        self.assertTrue(self.entry('tool').factory(self.ctx).external_execution)
        env = self.entry('environment').factory(self.ctx)
        self.assertEqual(env.timeout_seconds, 30)
        self.assertEqual(env.memory_bytes, 128 * 1024 * 1024)
        self.assertEqual(env.output_bytes, 1024 * 1024)
        self.assertEqual(self.manifest['protocol']['trainingBudgetSeconds'], 300)

    def test_controlled_model_calls_once_then_finishes_without_parsing_output(self):
        model = self.entry('model').factory(self.ctx)
        first = model.invoke([Message(role='user', content='fixture')])
        self.assertEqual(len(first.tool_calls), 1)
        self.assertEqual(first.tool_calls[0]['function'], {'name': profile.TOOL_NAME, 'arguments': '{}'})
        result = Message(role='tool', tool_name=profile.TOOL_NAME, content='synthetic trusted receipt')
        self.assertFalse(model.invoke([result]).tool_calls)
        self.assertFalse(asyncio.run(model.ainvoke([result])).tool_calls)
        self.assertEqual(len(list(model.invoke_stream([]))), 1)
        result.tool_call_error = True
        with self.assertRaises(ValueError):
            model.invoke([result])
        self.assertEqual(model.retries, 0)

    def test_settings_and_materials_preserve_native_phase_and_experiment_identity(self):
        settings = profile.research_settings(db_url='postgresql+psycopg://fixture@localhost/fixture',
            workspace=Path('/synthetic/workspace'), target_ref='research-target', remote_targets={'research-target': object()},
            comparison_manifest=self.manifest)
        self.assertEqual(settings.runtime_tool_contract, profile.TOOL_CONTRACT)
        self.assertEqual(settings.temporary_policy, 'admin-review')
        self.assertEqual(settings.max_workers, 1)
        self.assertIs(settings.usage_pricing[0].local_model_type, profile.ResearchProcessFixtureModel)
        materials = profile.material_drafts(target_ref='research-target', comparison_manifest=self.manifest)
        tool = next(row for row in materials if row['kind'] == 'tool')
        self.assertEqual(tool['content'], profile.TOOL_NAME)
        for row in materials:
            if 'runtimeBinding' in row:
                self.assertEqual(row['runtimeBinding']['config']['comparisonManifestSha256'], manifest_fingerprint(self.manifest))
            MaterialDefinition.model_validate(row)
        self.assertEqual(tool['permissions'], [profile.PERMISSION])
        refs = [row | {'version': 1, 'sha256': digest(row)} for row in materials]
        app = profile.application_definition(refs)
        self.assertEqual(app['modes']['controlled-fixture']['budget']['experimentSeconds'], 30)

    def test_variant_is_distinct_from_comparison_identity_and_strictly_pinned(self):
        variant = '9' * 64
        entries = profile.registrations(target_ref='research-target', comparison_manifest=self.manifest, variant_sha256=variant)
        selected = dict(self.ctx.spec['config'], variantSha256=variant)
        for entry in entries:
            assert entry.validator is not None
            entry.validator(selected)
            with self.assertRaises(ValueError):
                entry.validator(self.ctx.spec['config'])
        drafts = profile.material_drafts(target_ref='research-target', comparison_manifest=self.manifest, variant_sha256=variant)
        for row in drafts:
            MaterialDefinition.model_validate(row)
            if 'runtimeBinding' in row:
                self.assertEqual(row['runtimeBinding']['config']['variantSha256'], variant)
        knowledge = next(row for row in drafts if row['kind'] == 'knowledge')
        self.assertEqual(json.loads(knowledge['content']), self.manifest)
        for bad in (True, 'bad', 'A' * 64):
            with self.assertRaises(ValueError):
                profile.registrations(target_ref='research-target', comparison_manifest=self.manifest, variant_sha256=bad)

    def test_knowledge_content_is_fixed_and_bounded(self):
        knowledge = self.entry('knowledge').factory(self.ctx)
        self.assertEqual(json.loads(knowledge.content), self.manifest)
        self.assertEqual(knowledge.provenance, {'evidenceKind': 'offline_research_experiment_manifest'})
        oversized = deepcopy(self.manifest)
        oversized['dataset']['shards'] = [{'id': f'shard-{i}', 'sha256': '0' * 64, 'sizeBytes': 1} for i in range(200)]
        oversized['dataset']['validationShardIds'] = ['shard-0']
        for operation in (profile.registrations, profile.material_drafts):
            with self.assertRaises(ValueError):
                operation(target_ref='research-target', comparison_manifest=oversized)

    def test_publication_is_explicit_and_requires_distinct_reviewers(self):
        governance = SimpleNamespace(create_draft=Mock(side_effect=lambda owner, definition, key: definition | {'version': 1, 'sha256': digest(definition)}),
            request_publication=Mock(return_value={'id': 'review'}), decide_publication=Mock())
        state = {'auth': Mock(), 'material_governance': governance, 'applications': governance}
        args = dict(target_ref='research-target', comparison_manifest=self.manifest, author='manager', reviewer='manager2')
        result = profile.publish_research_application(state, **args)
        self.assertEqual(result['id'], profile.APPLICATION_ID)
        self.assertEqual(governance.decide_publication.call_count, 6)
        self.assertTrue(all(call.args[0] == 'manager2' for call in governance.decide_publication.call_args_list))
        with self.assertRaises(ValueError):
            profile.publish_research_application(state, **(args | {'reviewer': 'manager'}))


if __name__ == '__main__':
    unittest.main()
