"""Portable v2 wire tests over owned SQLite metadata; no native processes."""
import copy
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

from fastapi import HTTPException

from agent_factory.application_schema import ApplicationDefinitionV2
from agent_factory.remote_handoff import (
    HandoffAuthority, HandoffTarget, PrepareBody, PreparedHandoffService, TrustedHandoffClient, TrustedOrigin,
    _manifest, plan_manifest,
)
from agent_factory.store import digest
from test_applications_composition import ApplicationCompositionFixture


def rehash(plan):
    plan['fingerprint'] = digest({k: v for k, v in plan.items() if k not in {'id', 'createdAt', 'fingerprint'}})
    return plan


class V2ManifestFixture(ApplicationCompositionFixture):
    def make_plan(self):
        seed = self.composition.create_plan('alice', 'Checksum exact neutral evidence', 'execute', 'fixture-checksum-v2')
        original = self.applications.require_current(seed['applicationRef'])
        definition = {key: copy.deepcopy(original[key]) for key in ApplicationDefinitionV2.model_fields}
        definition['id'] = 'wire-neutral'
        schema = {'type': 'object', 'properties': {'format': {'type': 'string', 'maxLength': 12, 'enum': ['hex']}},
                  'required': ['format'], 'additionalProperties': False}
        mode = definition['modes']['execute']
        mode.update(configSchema=schema, config={'format': 'hex'}, inputSchema=copy.deepcopy(schema))
        self.publish(definition)
        return self.composition.create_plan('alice', 'Checksum exact neutral evidence', 'execute', 'wire-neutral', input_values={'format': 'hex'})

    def envelope(self, plan):
        return plan_manifest(plan, application_definition=self.applications.require_current(plan['applicationRef']))

    def read(self, envelope, **kwargs):
        return _manifest(envelope, self.store, 'alice', supported_application_contracts=(1, 2), **kwargs)


class RemoteV2ManifestTests(V2ManifestFixture):
    def test_complete_nonempty_definition_and_input_config_survive(self):
        plan = self.make_plan()
        envelope = self.envelope(plan)
        self.assertEqual(self.read(envelope), plan)
        self.assertEqual(envelope['sha256'], digest(plan))
        self.assertNotEqual(envelope['sha256'], digest(envelope))
        self.assertEqual(plan['config']['applicationConfig'], {'format': 'hex'})
        self.assertEqual(plan['inputValues'], {'format': 'hex'})
        self.assertIn('operationSeconds', plan['budget'])
        envelope['applicationDefinition']['name'] = 'tampered'
        with self.assertRaises(HTTPException): self.read(envelope)

    def test_rehashed_definition_cannot_replace_plan_pin(self):
        envelope = self.envelope(self.make_plan())
        definition = envelope['applicationDefinition']
        definition['modes']['execute']['config']['format'] = 'other'
        definition['sha256'] = digest({k: v for k, v in definition.items() if k != 'sha256'})
        with self.assertRaises(HTTPException): self.read(envelope)

    def test_rehashed_plan_cannot_change_governed_values(self):
        original = self.make_plan()
        edits = [lambda p: p['config']['applicationConfig'].update(format='other'),
                 lambda p: p['inputValues'].update(format='other'),
                 lambda p: p.update(mode='other'),
                 lambda p: p['inputSchema']['properties']['format'].update(enum=['other']),
                 lambda p: p['budget'].update(operationSeconds=600),
                 lambda p: p['budget'].update(experimentSeconds=1),
                 lambda p: p['budget'].pop('operationSeconds'),
                 lambda p: p['executionBindings']['model'].update(revision='other')]
        for edit in edits:
            plan = copy.deepcopy(original)
            edit(plan)
            with self.subTest(edit=edit), self.assertRaises(HTTPException):
                self.read(self.envelope(rehash(plan)))

    def test_version_extra_fields_default_optout_and_root_only(self):
        original = self.make_plan()
        envelope = self.envelope(original)
        with self.assertRaisesRegex(HTTPException, 'REMOTE_CONTRACT_UNSUPPORTED'):
            _manifest(envelope, self.store, 'alice')
        for marker in (True, '2', 1, 3, None):
            changed = copy.deepcopy(envelope)
            changed['wireVersion'] = marker
            with self.subTest(marker=marker), self.assertRaises(HTTPException): self.read(changed)
            changed = copy.deepcopy(envelope)
            changed['plan']['contractVersion'] = marker
            changed['sha256'] = digest(changed['plan'])
            with self.assertRaises(HTTPException): self.read(changed)
        changed = {**envelope, 'extra': False}
        with self.assertRaises(HTTPException): self.read(changed)
        for field in ('delegation', 'remoteHandoff', 'nativeComponent', 'scientificEnvelope', 'sourceSnapshotRef'):
            plan = rehash({**copy.deepcopy(original), field: {}})
            with self.subTest(field=field), self.assertRaises(HTTPException): self.read(self.envelope(plan))
        plan = copy.deepcopy(original)
        plan['budget']['depth'] = 1
        with self.assertRaises(HTTPException): self.read(self.envelope(rehash(plan)))

    def test_actual_reserve_and_prepare_ingress_require_explicit_optin(self):
        plan = self.make_plan()
        target = HandoffTarget('receiver', 'origin', 'http://localhost:1', {'alice': 'alice'}, lambda _: {})
        client = object.__new__(TrustedHandoffClient)
        client.store, client.auth, client.targets = self.store, self.auth, {'receiver': target}
        client.admission_guard = Mock()
        self.store.reserve_task = Mock(return_value=({'id': str(uuid4()), 'run_id': None}, True))
        self.store.sql = Mock()
        with self.assertRaisesRegex(HTTPException, 'REMOTE_CONTRACT_UNSUPPORTED'):
            client.reserve('alice', plan['id'], 'receiver', 'v2-request-test')
        self.store.reserve_task.assert_not_called()
        self.store.sql.assert_not_called()
        target = replace(target, supported_application_contracts=(1, 2))
        client.targets['receiver'] = target
        row = {'target_ref': 'receiver', 'manifest_hash': digest(plan), 'configuration_hash': target.fingerprint, 'body': {}}
        client._row = Mock(return_value=row)
        self.store.sql.return_value = []
        self.assertEqual(client.reserve('alice', plan['id'], 'receiver', 'v2-request-test'), row)
        import json
        saved = json.loads(self.store.sql.call_args.kwargs['body'])
        self.assertEqual(saved['manifest'], self.envelope(plan))
        receiver = object.__new__(PreparedHandoffService)
        receiver.store, receiver.auth = self.store, self.auth
        receiver.origins = {'origin': TrustedOrigin('origin', {'alice': 'alice'}, Mock())}
        body = PrepareBody(originRef='origin', originOwnerId='alice', originTaskId=uuid4(),
                           requestId='v2-request-test', manifest=saved['manifest'])
        with self.assertRaisesRegex(HTTPException, 'REMOTE_CONTRACT_UNSUPPORTED'):
            receiver.prepare('alice', body)
        receiver.origins['origin'].authorize.assert_not_called()

    def test_v1_wire_and_hash_remain_exact(self):
        plan = self.composition.create_plan('alice', 'Frozen checksum fixture', 'literature', 'fixture-checksum')
        envelope = plan_manifest(plan)
        self.assertEqual(envelope, {'plan': plan, 'sha256': digest(plan)})
        self.assertEqual(_manifest(envelope, self.store, 'alice'), plan)
        self.assertNotIn('contractVersion', envelope['plan'])
        # Explicit member-authored fixture with fixed creation time and declared runtime bindings.
        self.assertEqual(self.applications.require_current(plan['applicationRef'])['sha256'],
                         '1ae47b187fa677e869316ab5a6801f1e35b738cc9ac91753c0d1f8d91eb1e949')


class RemoteV2ConfigurationTests(unittest.TestCase):
    def test_v1_fingerprints_unchanged_and_v2_explicit(self):
        target = HandoffTarget('receiver', 'origin', 'http://localhost:1', {'a': 'b'}, lambda _: {})
        self.assertEqual(target.fingerprint, digest({'reference': 'receiver', 'origin': 'origin',
            'url': 'http://localhost:1', 'mapping': {'a': 'b'}, 'revision': '1'}))
        self.assertNotEqual(replace(target, supported_application_contracts=(1, 2)).fingerprint, target.fingerprint)
        origin = TrustedOrigin('origin', {'a': 'b'}, lambda *args: None)
        self.assertEqual(origin.fingerprint, digest({'reference': 'origin', 'identityMap': {'a': 'b'},
            'capabilities': sorted(origin.capabilities), 'tools': sorted(origin.tools), 'budget': dict(origin.budget), 'revision': '1'}))
        with self.assertRaises(ValueError): replace(origin, supported_application_contracts=(1, 2))
        for contracts in ((True,), (2, 1), (1, 1), (), (3,)):
            with self.subTest(contracts=contracts), self.assertRaises(ValueError): replace(target, supported_application_contracts=contracts)

    def test_authority_uses_original_version_and_explicit_receiver_ceiling(self):
        budget = {'toolCalls': 8, 'maxDepth': 2, 'maxChildren': 4, 'operationSeconds': 3, 'outputBytes': 65536}
        authority = HandoffAuthority(frozenset({'checksum:read'}), frozenset({'checksum'}), budget, contract_version=2)
        callback = Mock(return_value=authority)
        origin = TrustedOrigin('origin', {'a': 'b'}, callback, supported_application_contracts=(1, 2), v2_budget=budget)
        service = object.__new__(PreparedHandoffService)
        service.store = SimpleNamespace(settings=SimpleNamespace(max_tool_calls=8, experiment_timeout_seconds=8, experiment_output_bytes=65536))
        plan = {'contractVersion': 2, 'tools': ['checksum'], 'capabilities': ['checksum:read'], 'budget': {**budget, 'depth': 0}}
        self.assertEqual(service._authority(origin, 'a', 'task', 'sha', plan), authority)
        callback.assert_called_once_with('a', 'task', 'sha', None)
        callback.return_value = replace(authority, contract_version=1)
        with self.assertRaises(HTTPException): service._authority(origin, 'a', 'task', 'sha', plan)
        callback.return_value = authority
        plan['budget']['operationSeconds'] = 4
        with self.assertRaises(HTTPException): service._authority(origin, 'a', 'task', 'sha', plan)
        callback.side_effect = PermissionError('revoked')
        with self.assertRaises(HTTPException): service._authority(origin, 'a', 'task', 'sha', plan)
