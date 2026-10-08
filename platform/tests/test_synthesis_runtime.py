"""Plan-bound synthesis adapters: synthetic sources, no PG or provider I/O."""
from copy import deepcopy
from types import SimpleNamespace
from typing import Any
import unittest
from unittest.mock import Mock, patch

from agno.models.message import Message

from agent_factory.literature_synthesis import build_source_context
from agent_factory.literature_synthesis_profile import ControlledScientificFixture, ScientificFixtureModel
from agent_factory.synthesis_runtime import (SCOPE, APPLICATION_ID, TOOL_NAME, PERMISSION,
    application_definition, material_drafts, pricing_registration, registrations, resolve_context, validate_plan_source,
    KNOWLEDGE_ID, ENVIRONMENT_ID, TOOL_ID)
from test_literature_synthesis import projection  # pyright: ignore[reportMissingImports]
import json
import hashlib
from agent_factory.literature_synthesis import validate_synthesis_report, FIXTURE_PROVIDER, SCIENTIFIC_CAPABILITY
from agent_factory.synthesis_runtime import inspect_synthesis_evidence, MODEL_ID
from test_literature_synthesis import report  # pyright: ignore[reportMissingImports]


class SynthesisRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.projection = projection()
        self.context = build_source_context('Question?', self.projection)
        self.snapshot = {'question': 'Question?', 'projection': self.projection,
                         'fingerprint': 'a' * 64, 'contextFingerprint': self.context.provenance['snapshotSha256']}
        self.service = SimpleNamespace(revalidate=Mock(side_effect=lambda *args, **kwargs: deepcopy(self.snapshot)))
        self.ctx: Any = SimpleNamespace(settings=SimpleNamespace(demo=True, source_synthesis_enabled=True),
            store=SimpleNamespace(synthesis_sources=self.service),
            spec={'config': {'scope': SCOPE}}, connection=ControlledScientificFixture(),
            run_context=SimpleNamespace(user_id='alice', session_id='task', run_id='run'),
            plan={'ownerId': 'alice', 'application': APPLICATION_ID, 'applicationRef': {'id': APPLICATION_ID},
                  'mode': 'controlled-fixture', 'tools': [TOOL_NAME], 'capabilities': [PERMISSION],
                  'sourceSnapshotRef': {'id': 'snapshot', 'fingerprint': 'a' * 64}})
        self.entries = {row.kind: row for row in registrations()}

    def test_snapshot_fresh_resolution_and_native_knowledge_model_injection(self):
        knowledge = self.entries['knowledge'].factory(self.ctx)
        model = self.entries['model'].factory(self.ctx)
        self.assertIs(type(model), ScientificFixtureModel)
        self.assertEqual(knowledge, self.context)
        self.service.revalidate.assert_called_with('alice', 'snapshot', expected_fingerprint='a' * 64)
        with self.assertRaisesRegex(ValueError, 'NOT_INJECTED'):
            model.invoke([Message(role='user', content='Question?')])
        output = model.invoke([Message(role='system', content='FACTORY_KNOWLEDGE_CONTEXT=' + json.dumps({'content': knowledge.content}))])
        self.assertEqual(output.tool_calls[0]['function']['name'], TOOL_NAME)
        self.assertEqual(self.service.revalidate.call_count, 2)

    def test_current_owner_demo_flag_and_exact_scope_fail_closed(self):
        changes = [lambda c: setattr(c.settings, 'demo', False),
                   lambda c: setattr(c.settings, 'source_synthesis_enabled', False),
                   lambda c: setattr(c.run_context, 'user_id', 'bob'),
                   lambda c: c.plan.update(delegation={'parentTaskId': 'other'}),
                   lambda c: c.plan.update(tools=[TOOL_NAME, 'arbitrary_tool']),
                   lambda c: c.plan.update(capabilities=[PERMISSION, 'experiment:execute']),
                   lambda c: c.plan.update(mode='live'),
                   lambda c: c.spec.update(config={'scope': 'other'}),
                   lambda c: c.plan.pop('sourceSnapshotRef'),
                   lambda c: c.plan['sourceSnapshotRef'].update(extra='not-allowed')]
        for change in changes:
            with self.subTest(change=change):
                ctx = deepcopy(self.ctx)
                change(ctx)
                with self.assertRaises(ValueError):
                    resolve_context(ctx)
                ctx.store.synthesis_sources.revalidate.assert_not_called()

    def test_approved_clone_scope_has_no_hardcoded_application_id(self):
        self.ctx.plan.update(application='reviewed-clone', applicationRef={'id': 'reviewed-clone'})
        self.assertEqual(resolve_context(self.ctx), self.context)
        self.ctx.plan['applicationRef']['id'] = 'different'
        with self.assertRaises(ValueError):
            resolve_context(self.ctx)

    def test_source_fingerprint_context_drift_and_service_revocation_propagate(self):
        for key in ('fingerprint', 'contextFingerprint'):
            saved = self.snapshot[key]
            self.snapshot[key] = 'b' * 64
            with self.subTest(key=key), self.assertRaises(ValueError):
                resolve_context(self.ctx)
            self.snapshot[key] = saved
        self.service.revalidate.side_effect = PermissionError('synthetic revoked')
        with self.assertRaises(PermissionError):
            resolve_context(self.ctx)

    def test_model_requires_exact_credential_free_fixture_handle(self):
        for handle in (None, object(), ControlledScientificFixture('other')):
            self.ctx.connection = handle
            with self.assertRaises(ValueError):
                self.entries['model'].factory(self.ctx)

    def test_shared_saver_revalidates_original_context_at_each_callback(self):
        with patch('agent_factory.literature_synthesis_profile.make_synthesis_saver', create=True) as make:
            sentinel = object()
            make.return_value = sentinel
            self.assertIs(self.entries['tool'].factory(self.ctx), sentinel)
            args, kwargs = make.call_args
            self.assertIs(args[0], self.ctx)
            self.assertEqual(args[1], self.context)
            callback = kwargs['revalidate']
            callback()
            self.snapshot['question'] = 'Changed?'
            self.snapshot['contextFingerprint'] = build_source_context('Changed?', self.projection).provenance['snapshotSha256']
            with self.assertRaises(ValueError):
                callback()
            self.assertEqual(self.service.revalidate.call_count, 3)

    def test_static_six_kind_drafts_contain_no_snapshot_and_do_not_publish(self):
        drafts = material_drafts()
        self.assertEqual({row['kind'] for row in drafts}, {'skill', 'prompt', 'knowledge', 'model', 'tool', 'environment'})
        self.assertEqual(next(row['content'] for row in drafts if row['kind'] == 'tool'), TOOL_NAME)
        self.assertNotIn('sourceSnapshotRef', json.dumps(drafts))
        self.assertTrue(all('published' not in row for row in drafts))
        materials = [{**row, 'version': 1, 'sha256': str(index) * 64} for index, row in enumerate(drafts)]
        definition = application_definition(materials)
        mode = definition['modes']['controlled-fixture']
        self.assertEqual(len(mode['materialRefs']), 6)
        self.assertEqual(mode['tools'] if 'tools' in mode else mode['toolOrder'], [TOOL_NAME])
        with self.assertRaises(ValueError):
            application_definition(materials[:-1])
        with self.assertRaises(ValueError):
            application_definition([{**row, 'version': True} for row in materials])
        for entry in self.entries.values():
            self.assertTrue(entry.demo_only)
            assert entry.validator is not None
            entry.validator({'scope': SCOPE})
            with self.assertRaises(ValueError):
                entry.validator({'scope': SCOPE, 'sourceSnapshotRef': {'id': 'unsafe'}})
        self.assertIs(pricing_registration().local_model_type, ScientificFixtureModel)

    def test_guard_revalidates_exact_plan_binding_goal_and_review_policy(self):
        settings = SimpleNamespace(demo=True, source_synthesis_enabled=True, temporary_policy='admin-review')
        self.ctx.store.settings = settings
        ref = self.ctx.plan['sourceSnapshotRef']
        self.ctx.plan.update(normalizedGoal='Question?', bindingManifest={'sourceSnapshotRef': deepcopy(ref)},
            executionBindings={'model': {'adapterId': MODEL_ID, 'revision': '1', 'config': {'scope': SCOPE}},
                'environment': {'adapterId': ENVIRONMENT_ID, 'revision': '1', 'config': {'scope': SCOPE}},
                'knowledge': [{'adapterId': KNOWLEDGE_ID, 'revision': '1', 'config': {'scope': SCOPE}}],
                'tools': [{'adapterId': TOOL_ID, 'revision': '1', 'config': {'scope': SCOPE}, 'toolName': TOOL_NAME}]})
        validate_plan_source(self.ctx.store, self.ctx.plan)
        for mutation in (lambda p: p.update(normalizedGoal='Changed'),
                         lambda p: p['bindingManifest']['sourceSnapshotRef'].update(fingerprint='c' * 64),
                         lambda p: p['executionBindings']['model'].update(adapterId='other'),
                         lambda p: p.update(remoteHandoff={'enabled': True})):
            plan = deepcopy(self.ctx.plan)
            mutation(plan)
            with self.assertRaises(ValueError):
                validate_plan_source(self.ctx.store, plan)
        settings.temporary_policy = 'read-only-auto'
        with self.assertRaises(ValueError):
            validate_plan_source(self.ctx.store, self.ctx.plan)
        validate_plan_source(SimpleNamespace(), {'executionBindings': {}})

    def inspector_store(self):
        context = self.context
        ref = self.ctx.plan['sourceSnapshotRef']
        plan = {**self.ctx.plan, 'id': 'plan', 'fingerprint': 'b' * 64,
                'executionBindings': {'model': {'adapterId': MODEL_ID, 'revision': '1'}}}
        checked = validate_synthesis_report(report(), context, provider_id=FIXTURE_PROVIDER,
            capabilities=(SCIENTIFIC_CAPABILITY,), execution_mode='controlled-fixture')
        document = {**checked, 'evidenceKind': 'controlled_model_synthesis',
                    'citationIntegrityVerified': True, 'modelExecution': 'controlled-fixture'}
        encoded = json.dumps(document, sort_keys=True, ensure_ascii=False).encode()
        markdown = '# Controlled literature synthesis fixture\n\n' + '\n'.join(
            '    ' + line for line in json.dumps(report(), ensure_ascii=False, indent=2).splitlines())
        markdown += '\n\nCitation structure checked; semantic review required. Snapshot: ' + context.provenance['snapshotSha256']
        metadata = {'ownerId': 'alice', 'taskId': 'task', 'planId': 'plan', 'planFingerprint': 'b' * 64,
                    'sourceSnapshotRef': ref, 'evidenceKind': 'controlled_model_synthesis',
                    'snapshotSha256': context.provenance['snapshotSha256'], 'citationIntegrityVerified': True,
                    'semanticReview': 'required', 'modelAdapterId': MODEL_ID, 'modelExecution': 'controlled-fixture',
                    'sourceEvidenceKind': context.provenance['sourceEvidenceKind']}
        rows = []
        raw = {}
        for identifier, name, media, content in [('json-id', 'literature-synthesis.json', 'application/json', encoded),
                ('md-id', 'literature-synthesis.md', 'text/markdown', markdown.encode())]:
            rows.append({'id': identifier, 'jobId': 'task', 'name': name, 'mediaType': media, 'size': len(content),
                         'sha256': hashlib.sha256(content).hexdigest(), 'provenance': deepcopy(metadata)})
            raw[identifier] = content
        result = {'artifactId': 'json-id', 'markdownArtifactId': 'md-id',
                  'originalReportSha256': hashlib.sha256(encoded).hexdigest(),
                  'snapshotSha256': context.provenance['snapshotSha256'], 'citationIntegrityVerified': True,
                  'semanticReview': 'required'}
        store = SimpleNamespace(task=Mock(return_value={'id': 'task', 'plan_id': 'plan', 'run_id': 'run'}),
            plan=Mock(return_value=plan), artifacts=Mock(return_value=rows),
            artifact=Mock(side_effect=lambda task, identifier: (next(row for row in rows if row['id'] == identifier), raw[identifier])),
            effects=Mock(return_value=[{'effect_key': 'run:literature-synthesis-report-v1', 'status': 'DONE', 'result': result}]),
            synthesis_sources=SimpleNamespace(read=Mock(return_value=deepcopy(self.snapshot)),
                revalidate=Mock(return_value=deepcopy(self.snapshot))))
        return store, rows, raw

    def test_inspector_verifies_artifacts_and_retains_history_on_source_drift(self):
        store, _, _ = self.inspector_store()
        evidence = inspect_synthesis_evidence(store, 'alice', 'task')
        self.assertEqual(evidence['status'], 'ready')
        self.assertEqual(evidence['report'], report())
        self.assertTrue(evidence['sourceCurrent'])
        self.assertFalse(evidence['scientificConclusionVerified'])
        store.synthesis_sources.revalidate.side_effect = ValueError('synthetic drift')
        evidence = inspect_synthesis_evidence(store, 'alice', 'task')
        self.assertEqual(evidence['status'], 'ready')
        self.assertFalse(evidence['sourceCurrent'])

    def test_inspector_rejects_tampering_and_does_not_leak_invalid_body(self):
        mutations = [lambda store, rows, raw: raw.update({'json-id': b'private corrupted bytes'}),
                     lambda store, rows, raw: rows[0]['provenance'].update(citationIntegrityVerified=1),
                     lambda store, rows, raw: rows[1]['provenance'].update(ownerId='bob'),
                     lambda store, rows, raw: store.effects.return_value[0].update(status='UNKNOWN'),
                     lambda store, rows, raw: rows.append(deepcopy(rows[0]))]
        for mutate in mutations:
            store, rows, raw = self.inspector_store()
            mutate(store, rows, raw)
            evidence = inspect_synthesis_evidence(store, 'alice', 'task')
            self.assertEqual(evidence['status'], 'invalid')
            self.assertIsNone(evidence['report'])
            self.assertIsNone(evidence['artifactIds'])
            self.assertNotIn('private', json.dumps(evidence))
        store, _, _ = self.inspector_store()
        store.artifacts.return_value = []
        self.assertEqual(inspect_synthesis_evidence(store, 'alice', 'task')['status'], 'pending')

    def test_inspector_checks_owner_before_plan_or_artifact_access(self):
        store, _, _ = self.inspector_store()
        store.task.side_effect = PermissionError('synthetic owner denial')
        with self.assertRaises(PermissionError):
            inspect_synthesis_evidence(store, 'bob', 'task')
        store.plan.assert_not_called()
        store.artifacts.assert_not_called()
        store.synthesis_sources.read.assert_not_called()


if __name__ == '__main__':
    unittest.main()
