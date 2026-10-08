"""Neutral contract and frozen v1 migration evidence over synthetic fixtures."""
import asyncio
import copy
import unittest
from uuid import uuid4
from agent_factory.store import digest
from fastapi import HTTPException
from agent_factory.application_schema import ApplicationDefinitionV2, definition_model, time_budget
from agent_factory.applications import demo_definitions
from agent_factory.remote_handoff import _manifest, plan_manifest
import test_applications_composition as fixtures


class ApplicationContractV2Tests(fixtures.ApplicationCompositionFixture):
    def plan(self):
        return self.composition.create_plan('alice', 'Checksum neutral controlled evidence', 'execute', 'checksum-neutral')

    def test_neutral_configuration_composes_and_rechecks_without_research_fields(self):
        plan = self.plan()
        self.assertEqual(plan['contractVersion'], 2)
        self.assertEqual(set(plan['budget']), {'toolCalls', 'maxDepth', 'maxChildren', 'operationSeconds', 'outputBytes', 'depth'})
        self.assertEqual(set(plan['config']), {'sample', 'toolOrder', 'applicationConfig'})
        self.assertEqual(plan['config']['applicationConfig'], {})
        self.assertEqual(plan['mode'], 'execute')
        self.assertEqual(self.applications.require_plan_current(plan)['id'], 'checksum-neutral')
        for edit in ({'applicationConfig': {'permissions': ['admin']}}, {'experimentDurationSeconds': 60}):
            changed = copy.deepcopy(plan)
            changed['config'].update(edit)
            with self.assertRaises(HTTPException):
                self.applications.require_plan_current(changed)
        with self.assertRaises(HTTPException) as denied:
            _manifest(plan_manifest(plan), self.store, 'alice')
        self.assertIn('REMOTE_CONTRACT_UNSUPPORTED', str(denied.exception.detail))

    def test_neutral_composed_plan_runs_actual_native_model_tool_loop(self):
        # Native model/tool execution is real; persistence/authority here is an
        # owned fixture, not evidence for PostgreSQL queue durability.
        from test_execution_bindings import MultiPlanStore
        from agent_factory.execution_bindings import default_bindings
        from agent_factory.runtime import build_runtime
        plan = self.plan()
        runtime_store = MultiPlanStore()
        runtime_store.plans[plan['id']] = copy.deepcopy(plan)
        runtime_store.execution_bindings = default_bindings(self.settings, runtime_store)
        agent, _ = build_runtime(self.settings, runtime_store, self.db)
        async def run():
            return await agent.arun('Run the exact approved checksum', user_id='alice',
                session_id='neutral-contract-native-session', session_state={'factory_envelope': {
                    'plan_ref': plan['id'], 'user_id': 'alice', 'task_id': 'neutral-contract-native-session',
                    'request_id': 'fixture-neutral-contract-native-session'}})
        result = asyncio.run(run())
        self.assertIn('synthetic-complete', str(result.content))
        self.assertTrue(runtime_store.artifacts)
        self.assertTrue(any(event['type'] == 'checksum_completed' for event in runtime_store.events))

    def test_v1_seed_bodies_and_existing_plan_are_unchanged_after_restart(self):
        # Captured from clean base f869ab5, not recomputed from migrated schema.
        hashes = {'research': '8031528d7f3907573fffd7bfa84b993fa19c0b6ca5aa06b7b1069037120f5b0b',
                  'checksum': 'f32c6e0a187966fd67632cf0b031a2527bcc60906ae6ccdfc93a1e85e3bf85a6'}
        seeds = {item['id']: item for item in self.store.materials()}
        for expected in demo_definitions(seeds):
            actual = next(app for app in self.applications.list_active('alice') if app['id'] == expected['id'])
            self.assertEqual({key: value for key, value in actual.items() if key not in {'version', 'createdAt', 'schema', 'origin', 'sha256'}}, expected)
            self.assertNotIn('contractVersion', actual)
            self.assertEqual(actual['sha256'], hashes[actual['id']])
        original = self.composition.create_plan('alice', 'Checksum historical compatibility', 'literature', 'checksum')
        self.applications.seed_demo()
        self.assertEqual(self.store.plan(original['id'], 'alice'), original)
        self.assertNotIn('contractVersion', original)
        self.assertIn('experimentSeconds', original['budget'])
        self.applications.require_plan_current(original)

    def test_application_owned_schema_is_strict_and_cannot_be_authority(self):
        app = self.applications.require_current(self.plan()['applicationRef'])
        body = {key: value for key, value in app.items() if key in ApplicationDefinitionV2.model_fields}
        body['modes']['execute']['configSchema'] = {'type': 'object', 'properties': {'format': {'type': 'string', 'maxLength': 12, 'enum': ['hex']}}, 'required': ['format'], 'additionalProperties': False}
        body['modes']['execute']['config'] = {'format': 'hex'}
        self.applications.validate_definition(body)
        body['modes']['execute']['config']['format'] = 'unknown'
        with self.assertRaises(HTTPException): self.applications.validate_definition(body)
        body['modes']['execute']['configSchema']['properties']['capabilities'] = {'type': 'string', 'maxLength': 12}
        body['modes']['execute']['config'] = {'format': 'hex'}
        with self.assertRaises(HTTPException): self.applications.validate_definition(body)
        body.pop('defaultMode')
        with self.assertRaises(HTTPException): self.applications.validate_definition(body)
        for version in (1, True, '2', 3):
            with self.assertRaises(ValueError): definition_model({'contractVersion': version})

    def test_governed_v1_rejects_injected_v2_marker_and_mixed_budget(self):
        original = self.composition.create_plan('alice', 'Checksum strict historical budget', 'literature', 'checksum')
        for marker in (2, 1, True, '2', 3, None):
            changed = copy.deepcopy(original)
            changed['contractVersion'] = marker
            changed['budget']['operationSeconds'] = 600
            with self.subTest(marker=marker), self.assertRaises(HTTPException):
                self.applications.require_plan_current(changed)
        # Even an internally saved/rehashed plan must not choose its own
        # budget interpretation against a still-valid governed application.
        persisted = copy.deepcopy(original)
        persisted.update(id=str(uuid4()), contractVersion=2)
        persisted['budget']['operationSeconds'] = 600
        persisted['fingerprint'] = digest({key: value for key, value in persisted.items()
                                         if key not in {'id', 'createdAt', 'fingerprint'}})
        self.store.save_plan(persisted)
        with self.assertRaises(HTTPException):
            self.applications.require_plan_current(self.store.plan(persisted['id'], 'alice'))
        changed = copy.deepcopy(original)
        changed['budget']['operationSeconds'] = 600
        with self.assertRaises(HTTPException): self.applications.require_plan_current(changed)
        with self.assertRaises(ValueError): time_budget(changed, 600)
        for marker in (1, True, '2', 3, None):
            with self.subTest(marker=marker), self.assertRaises(ValueError):
                time_budget({'contractVersion': marker, 'budget': {'experimentSeconds': 8}}, 600)
        changed['contractVersion'] = 2
        with self.assertRaises(ValueError): time_budget(changed, 600)
        self.assertEqual(self.store.plan(original['id'], 'alice'), original)
        self.assertEqual(time_budget(original, 600), original['budget']['experimentSeconds'])

    def test_v2_time_budget_never_falls_back_to_legacy_limit(self):
        self.assertEqual(time_budget({'contractVersion': 2, 'budget': {'operationSeconds': 2}}, 30), 2)
        with self.assertRaises(ValueError): time_budget({'contractVersion': 2, 'budget': {'experimentSeconds': 30}}, 60)
        changed = self.plan()
        changed['budget']['experimentSeconds'] = 600
        with self.assertRaises(HTTPException): self.applications.require_plan_current(changed)


class NeutralChecksumNativeTests(fixtures.ApplicationCompositionPostgresTests):
    # Reuse the actual native queue fixture but not its inherited v1 test methods.
    def test_neutral_checksum_native_artifact(self):
        self.login('alice')
        response = self.client.post('/api/factory/compositions/proposals', json={'goal': 'Checksum neutral original fixture', 'application': 'checksum-neutral', 'requestId': 'neutral-propose'})
        self.assertEqual(response.status_code, 201, response.text)
        accepted = self.client.post('/api/factory/compositions/proposals/' + response.json()['id'] + '/accept', json={'requestId': 'neutral-accept'})
        self.assertEqual(accepted.status_code, 201, accepted.text)
        plan = accepted.json()
        self.assertEqual(plan['contractVersion'], 2)
        admission = self.client.post('/api/factory/instances', json={'planId': plan['id'], 'requestId': 'neutral-run'})
        self.assertEqual(admission.status_code, 202, admission.text)
        detail = self.wait_job(admission.json()['id'])
        self.assertEqual(detail['job']['status'], 'completed', detail)
        self.assertTrue(detail['artifacts'])
        self.assertTrue(any(event['type'] == 'checksum_completed' for event in self.store.events(detail['job']['id'])))


# Do not run inherited acceptance cases twice in this focused module.
for _name in dir(fixtures.ApplicationCompositionPostgresTests):
    if _name.startswith('test_'):
        setattr(NeutralChecksumNativeTests, _name, None)

if __name__ == '__main__': unittest.main()
