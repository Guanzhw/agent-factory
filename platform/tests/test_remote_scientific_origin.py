"""In-memory contract tests, not PostgreSQL locking or remote execution proof."""
from contextlib import contextmanager
from copy import deepcopy
import json
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException

from agent_factory.autoresearch_profile import APPLICATION_ID
from agent_factory.factory_api import status_of
from agent_factory.remote_scientific_origin import RemoteScientificOrigin, validate_source
from agent_factory.store import digest
from agent_factory.research_manifest import manifest_fingerprint
from test_research_manifest import example_manifest


class Fixture:
    def __init__(self):
        self.origins, self.calls, self.shared, self.receivers = {}, {}, {}, {}
        self.drives = {}
        self.root_locked = False
        self.grants = True
        self.parent = {'id': str(uuid4()), 'owner_id': 'alice', 'plan_id': str(uuid4()), 'run_id': str(uuid4()),
                       'cancel_requested': False, 'terminal': False}
        self.child = {'id': str(uuid4()), 'owner_id': 'alice', 'plan_id': str(uuid4()), 'run_id': None,
                      'cancel_requested': False, 'terminal': False}
        self.app = {'id': APPLICATION_ID, 'version': 1, 'sha256': 'a' * 64}
        self.parent_plan = {'id': self.parent['plan_id'], 'ownerId': 'alice', 'applicationRef': self.app,
                            'tools': ['research_preparation_verify'], 'capabilities': ['research:read'],
                            'budget': {'toolCalls': 2}}
        self.plan = {'id': self.child['plan_id'], 'ownerId': 'alice', 'application': APPLICATION_ID,
            'applicationRef': self.app, 'mode': 'remote-scientific-preparation',
            'tools': ['research_preparation_verify'], 'capabilities': ['research:read'], 'budget': {'toolCalls': 1},
            'delegation': {'parentTaskId': self.parent['id'], 'rootTaskId': self.parent['id'], 'depth': 1}}
        self.candidate = {'trainPy': '# controlled fixture only\n'}
        self.manifest = example_manifest()
        self.scope_binding = {'originParentTaskId': self.parent['id'], 'originParentRunId': self.parent['run_id'],
            'originParentPlanSha256': digest(self.parent_plan), 'candidateSha256': digest(self.candidate),
            'comparisonManifestSha256': manifest_fingerprint(self.manifest), 'receiverSciencePinSha256': 'c' * 64}
        self.placement = {'targetRef': 'receiver-target', 'projectId': 'fixture-project', 'projectPin': 'c' * 64,
            'phase': 'preparation', 'candidate': self.candidate, 'prior': {}, 'scopeBinding': self.scope_binding}
        binding = {'parentRunId': self.parent['run_id'], 'candidateSha256': digest(self.candidate)}
        request = 'ar-remote:' + digest({'binding': binding, 'phase': 'preparation'})
        self.experiment = {'fingerprint': digest(binding), 'owner_id': 'alice', 'parent_task_id': self.parent['id'],
            'body': {'binding': binding, 'candidate': self.candidate, 'phases': {'preparation': {
                'placement': self.placement, 'placementSha256': digest(self.placement), 'requestId': request}}}}
        self.link = {'owner_id': 'alice', 'parent_id': self.parent['id'], 'root_id': self.parent['id'],
            'depth': 1, 'plan_id': self.plan['id'], 'request_id': request, 'child_id': self.child['id']}
        self.session = {'deadline': time.time() + 100, 'candidates': {'one': self.candidate}}
        self.ticket = {'status': 'paused', 'persistedRunStatus': 'paused'}
        self.target = SimpleNamespace(origin_ref='origin', configuration_revision='1', fingerprint='d' * 64,
                                      identity_map={'alice': 'receiver'})
        self.remote_task, self.remote_run = str(uuid4()), str(uuid4())
        self.handoff_row = {'target_ref': 'receiver-target', 'body': {'receipt': {
            'remoteTaskId': self.remote_task, 'remoteRunId': None}}}
        self.handoff = SimpleNamespace(_row=lambda *_: self.handoff_row, _target=lambda *_: self.target,
            targets={'receiver-target': self.target}, receipt=self.receipt, cancel_scientific_original=self.cancel,
            scientific_cleanup_receipt=self.cleanup_receipt)
        self.auth = SimpleNamespace(require=self.require)
        self.delegation = SimpleNamespace(_link=lambda _: self.link, _mandate=lambda *_: None,
            _root_lock=self.root_lock, _descendants=lambda task: [self.link] if task == self.parent['id'] else [])
        self.store = SimpleNamespace(sql=self.sql, task=self.task, plan=self.get_plan, require_current_policy=lambda: None,
            has_failures=lambda _: False, require_plan_execution=lambda *_, **kw: None, delegation=self.delegation,
            lifecycle_observer=SimpleNamespace(_binding=lambda _: self.ticket),
            process_runtime=SimpleNamespace(_context=lambda task: SimpleNamespace(run_id=task['run_id'])),
            autoresearch=SimpleNamespace(current=lambda _: SimpleNamespace(manifest=self.manifest), row=lambda *_: {'body': self.session}),
            transaction=self.transaction)
        self.variant = 'e' * 64
        self.service = RemoteScientificOrigin(self.store, self.auth, handoff_client=self.handoff,
                                             project_validator=lambda *_: self.variant)
        self.envelope = self.service.prepare_placement('alice', self.parent, self.child, self.plan, self.placement)
        self.cancelled = []

    def require(self, *_):
        if not self.grants:
            raise HTTPException(403, 'fixture-revoked')

    def task(self, identifier, owner):
        for task in (self.parent, self.child):
            if task['id'] == identifier and owner == task['owner_id']:
                return deepcopy(task)
        raise HTTPException(404, 'fixture-not-found')

    def get_plan(self, identifier, owner):
        for plan in (self.plan, self.parent_plan):
            if plan['id'] == identifier and owner == plan['ownerId']:
                return deepcopy(plan)
        raise HTTPException(404, 'fixture-not-found')

    @contextmanager
    def root_lock(self, root):
        assert root == self.parent['id'] and not self.root_locked
        self.root_locked = True
        try: yield None
        finally: self.root_locked = False

    @contextmanager
    def transaction(self):
        before = deepcopy((self.calls, self.shared, self.receivers))
        try: yield SimpleNamespace(execute=lambda query, params: self.sql(str(query), **params))
        except BaseException:
            self.calls, self.shared, self.receivers = before
            raise

    def sql(self, query, **p):
        if query.startswith('CREATE'): return []
        if query.startswith('SELECT * FROM af_remote_placements'):
            assert 'FOR UPDATE' in query and self.root_locked
            return [deepcopy(self.handoff_row)]
        if 'af_autoresearch_remote_experiments' in query: return [deepcopy(self.experiment)]
        if query.startswith('SELECT * FROM af_remote_scientific_drive_intents'):
            row = self.drives.get(p['child'])
            return [{'scope_sha256': row['scope'], 'receiver_id': row['receiver']}] if row else []
        if query.startswith('INSERT INTO af_remote_scientific_drive_intents'):
            if p['child'] in self.drives: return []
            self.drives[p['child']] = deepcopy(p)
            return [{'child_id': p['child']}]
        if query.startswith('INSERT INTO af_remote_scientific_origins'):
            self.origins.setdefault(p['child'], {'child_id': p['child'], 'owner_id': p['owner'],
                'parent_id': p['parent'], 'fingerprint': p['fp'], 'body': json.loads(p['body']), 'receipt': None})
            return []
        if query.startswith('SELECT * FROM af_remote_scientific_origins'):
            row = self.origins.get(p['child'])
            return [deepcopy(row)] if row and row['owner_id'] == p['owner'] else []
        if query.startswith('INSERT INTO af_remote_scientific_receiver_runs'):
            self.receivers.setdefault(p['child'], {'receiver_task_id': p['receiver'], 'native_run_id': p['native']})
            return []
        if query.startswith('SELECT * FROM af_remote_scientific_receiver_runs'):
            row = self.receivers.get(p['child']); return [deepcopy(row)] if row else []
        if query.startswith('SELECT * FROM af_remote_scientific_calls'):
            row = self.calls.get((p['child'], p['call'])); return [deepcopy(row)] if row else []
        if query.startswith('SELECT * FROM af_delegation_tool_calls'):
            row = self.shared.get((p['id'], p['call'])); return [deepcopy(row)] if row else []
        if query.startswith('SELECT COUNT(*)'):
            return [{'n': sum(key[0] in p['ids'] for key in self.shared)}]
        if query.startswith('INSERT INTO af_delegation_tool_calls'):
            self.shared[p['task'], p['call']] = deepcopy(p); return []
        if query.startswith('INSERT INTO af_remote_scientific_calls'):
            self.calls[p['child'], p['call']] = {'body': json.loads(p['body']), 'fingerprint': p['fp']}; return []
        if query.startswith('UPDATE af_remote_scientific_origins'):
            row = self.origins[p['child']]
            if row['receipt'] != (json.loads(p['previous']) if p['previous'] else None): return []
            row['receipt'] = json.loads(p['receipt']); return [{'child_id': p['child']}]
        raise AssertionError('Unexpected fixture query')

    def debit_body(self):
        return {'schema': 1, 'originRef': 'origin', 'targetRef': 'receiver-target', 'originOwner': 'alice',
            'originTaskId': self.child['id'], 'manifestSha256': digest(self.plan), 'tool': 'research_preparation_verify',
            'receiverIdentity': 'receiver', 'targetRevision': '1', 'targetFingerprint': 'd' * 64,
            'callId': 'original-call', 'receiverTaskId': self.remote_task, 'nativeRunId': self.remote_run,
            'phaseScopeSha256': digest(self.envelope['scope'])}

    async def receipt(self, *_):
        scope = self.envelope['scope']
        receipt = {'id': self.handoff_row['body']['receipt'].get('id') or str(uuid4()), 'originTaskId': self.child['id'], 'manifestHash': digest(self.plan),
            'remoteOwnerId': 'receiver', 'remoteTaskId': self.remote_task, 'remotePlanId': str(uuid4()),
            'remoteRunId': self.remote_run, 'native': {'queue': {'status': 'completed'}}, 'applicationStatus': 'completed', 'allStopped': True,
            'scientificEvidence': {'schema': 1, 'scope': scope, 'lease': None, 'launchProof': None,
                'checkpoint': None, 'evaluation': None, 'preparation': None}}
        self.handoff_row['body']['receipt'] = deepcopy(receipt)
        self.handoff_row['state'] = 'ACCEPTED'
        return receipt

    async def cancel(self, owner, child, *, expected_scope):
        self.child['cancel_requested'] = True
        self.cancelled.append((owner, child, expected_scope)); return {'cleanupRequested': True}

    async def cleanup_receipt(self, owner, child, *, expected_scope):
        assert self.child['cancel_requested'] is True and expected_scope == self.envelope['scope']
        return await self.receipt(owner, child)


class RemoteScientificOriginTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self): self.f = Fixture()

    def test_immutable_envelope_does_not_create_native_ticket(self):
        f = self.f
        self.assertEqual(f.service.prepare_placement('alice', f.parent, f.child, f.plan, f.placement), f.envelope)
        self.assertEqual(f.service.validate_source(f.plan, f.envelope), f.envelope)
        self.assertIsNone(f.child['run_id'])
        self.assertEqual(len(f.origins), 1)
        f.variant = 'f' * 64
        with self.assertRaises(HTTPException): f.service.assert_authority('alice', f.child['id'])

    def test_scope_mode_candidate_source_plan_and_parent_changes_deny(self):
        f = self.f
        for plan, envelope in (({**f.plan, 'mode': 'scientific-preparation'}, f.envelope),
                               (f.plan, {**f.envelope, 'candidate': {'trainPy': 'changed'}}),
                               ({**f.plan, 'ownerId': 'changed'}, f.envelope)):
            with self.assertRaises(HTTPException): validate_source(plan, envelope)
        for mutation in ('deadline', 'candidate', 'paused', 'parentrun', 'revoke', 'childrun', 'link'):
            f = Fixture()
            if mutation == 'deadline': f.session['deadline'] = time.time() - 1
            elif mutation == 'candidate': f.session['candidates'] = {}
            elif mutation == 'paused': f.ticket['persistedRunStatus'] = 'running'
            elif mutation == 'parentrun': f.parent['run_id'] = str(uuid4())
            elif mutation == 'revoke': f.grants = False
            elif mutation == 'childrun': f.child['run_id'] = str(uuid4())
            elif mutation == 'link': f.link['request_id'] = 'changed'
            with self.assertRaises(HTTPException): f.service.assert_authority('alice', f.child['id'])

    def test_debit_pins_receiver_native_and_charges_shared_root_exactly_once(self):
        f = self.f; body = f.debit_body()
        proof = f.service.consume_remote_tool(body)
        self.assertEqual(proof, {'callProofSha256': digest(body)})
        self.assertEqual(f.service.consume_remote_tool(body), proof)
        self.assertEqual(len(f.shared), 1)
        self.assertEqual(len(f.calls), 1)
        self.assertEqual(f.receivers[f.child['id']]['native_run_id'], f.remote_run)
        with self.assertRaises(HTTPException):
            f.service.consume_remote_tool({**body, 'nativeRunId': str(uuid4())})
        self.assertEqual(len(f.shared), 1)

    def test_budget_and_receiver_scope_conflicts_do_not_charge(self):
        for field, value in (('phaseScopeSha256', 'f' * 64), ('receiverTaskId', str(uuid4())),
                             ('targetRevision', '2'), ('receiverIdentity', 'other')):
            f = Fixture()
            with self.assertRaises(HTTPException): f.service.consume_remote_tool({**f.debit_body(), field: value})
            self.assertEqual(f.shared, {})
        f = self.f
        f.shared[f.parent['id'], 'one'] = {}; f.shared[f.parent['id'], 'two'] = {}
        with self.assertRaises(HTTPException) as error: f.service.consume_remote_tool(f.debit_body())
        self.assertEqual(error.exception.status_code, 429)
        self.assertEqual(f.calls, {})
        self.assertEqual(f.receivers, {})

    def test_repeat_call_after_revoke_is_denied_not_new_authority(self):
        f = self.f; body = f.debit_body(); f.service.consume_remote_tool(body)
        f.grants = False
        with self.assertRaises(HTTPException): f.service.consume_remote_tool(body)
        self.assertEqual(len(f.shared), 1)

    async def test_phase_custody_is_not_execution_and_cleanup_uses_original_only(self):
        f = self.f
        observation = await f.service.origin_phase('alice', f.child['id'])
        self.assertEqual(observation['scope'], f.envelope['scope'])
        self.assertTrue(observation['allStopped'])
        f.grants = False
        with self.assertRaises(HTTPException): await f.service.origin_phase('alice', f.child['id'])
        await f.service.cancel_original('alice', f.child['id'])
        self.assertEqual(f.cancelled, [('alice', f.child['id'], f.envelope['scope'])])
        with self.assertRaises(HTTPException): await f.service.cancel_original('bob', f.child['id'])

    async def test_preparation_cannot_claim_stopped_with_nonterminal_native(self):
        f = self.f
        receipt = await f.receipt()
        receipt['native'] = {'queue': {'status': 'running'}}
        async def stale(*_):
            f.handoff_row['body']['receipt'] = deepcopy(receipt)
            return receipt
        f.handoff.receipt = stale
        self.assertFalse((await f.service.origin_phase('alice', f.child['id']))['allStopped'])

    def test_mutable_task_projection_changes_do_not_break_immutable_authority(self):
        f = self.f
        parent, child = deepcopy(f.parent), deepcopy(f.child)
        f.parent['body'] = {'lastObservation': 'new'}
        f.child['body'] = {'lastObservation': 'new'}
        self.assertEqual(f.service._binding('alice', parent, child, f.plan, f.placement, current=True), f.envelope)
        f.child['cancel_requested'] = True
        with self.assertRaises(HTTPException):
            f.service._binding('alice', parent, child, f.plan, f.placement, current=True)
        f.child['cancel_requested'] = False
        f.child['fingerprint'] = 'changed'
        with self.assertRaises(HTTPException):
            f.service._binding('alice', parent, child, f.plan, f.placement, current=True)

    async def test_operator_review_wait_then_original_dispatch_once(self):
        f = self.f
        f.handoff_row['state'] = 'PREPARING'
        receipt = f.handoff_row['body']['receipt']
        receipt.update(id=str(uuid4()), state='PREPARING', receiverReviewRequired=True)
        approved = False
        calls = []
        async def prepare(*_):
            calls.append('prepare')
            if approved:
                f.handoff_row['state'] = 'PREPARED'
                receipt.update(state='PREPARED', receiverReviewRequired=False)
            return deepcopy(receipt)
        async def dispatch(*_):
            calls.append('dispatch')
            f.handoff_row['body']['dispatchAttempted'] = True
            f.handoff_row['state'] = 'ACCEPTED'
            receipt.update(state='ACCEPTED', remoteRunId=f.remote_run)
            return deepcopy(receipt)
        async def request(*_):
            calls.append('drive'); return deepcopy(receipt)
        f.handoff.prepare, f.handoff.dispatch, f.handoff._request = prepare, dispatch, request
        f.handoff._save_receipt = lambda row, target, result: result
        await f.service.start_phase('alice', f.child['id'])
        self.assertEqual(calls, ['prepare'])
        self.assertEqual(f.drives, {})
        self.assertTrue(receipt['receiverReviewRequired'])
        approved = True  # synthetic separate operator action, never the service
        await f.service.start_phase('alice', f.child['id'])
        await f.service.start_phase('alice', f.child['id'])
        self.assertEqual(calls, ['prepare', 'prepare', 'dispatch', 'drive'])

    async def test_unknown_dispatch_is_read_only_and_known_review_is_pending(self):
        f = self.f
        original = await f.receipt()
        original.update(remoteRunId=None, state='PREPARING', originDispatchState='PREPARING',
                        applicationStatus='unknown', allStopped=False, native=None)
        reads = []
        async def read(*_):
            reads.append(True)
            f.handoff_row['body']['receipt'] = deepcopy(original)
            f.handoff_row['state'] = original['originDispatchState']
            return deepcopy(original)
        f.handoff.receipt = read
        observation = await f.service.origin_phase('alice', f.child['id'])
        self.assertEqual(observation['status'], 'pending')
        f.handoff_row.update(state='DISPATCH_UNKNOWN')
        f.handoff_row['body']['dispatchAttempted'] = True
        original['originDispatchState'] = 'DISPATCH_UNKNOWN'
        await f.service.start_phase('alice', f.child['id'])
        self.assertEqual(f.drives, {})
        observation = await f.service.origin_phase('alice', f.child['id'])
        self.assertEqual(observation['status'], 'unknown')
        self.assertEqual(len(reads), 3)

    async def test_real_ui_status_projection_remains_nonterminal(self):
        for native, cancelled, expected in (
            ({'status': 'paused'}, False, 'waiting_approval'),
            ({'status': 'paused', 'requirements': [{'tool_execution': {'requires_user_input': True}}]}, False, 'waiting_input'),
            ({'status': 'running'}, True, 'canceling'),
        ):
            f = Fixture()
            task = {**f.child, 'admission': 'accepted', 'run_id': f.remote_run, 'cancel_requested': cancelled}
            actual = status_of(task, native, [], [])
            self.assertEqual(actual, expected)
            receipt = await f.receipt()
            receipt.update(native=native, applicationStatus=actual, allStopped=True)
            async def read(*_):
                f.handoff_row['body']['receipt'] = deepcopy(receipt)
                return receipt
            f.handoff.receipt = read
            observed = await f.service.origin_phase('alice', f.child['id'])
            self.assertEqual(observed['status'], 'running' if cancelled else 'paused')
            self.assertFalse(observed['allStopped'])
        receipt['applicationStatus'] = 'unrecognized-state'
        with self.assertRaises(HTTPException):
            await f.service.origin_phase('alice', f.child['id'])

    async def test_overlapping_observation_uses_latest_persisted_receipt(self):
        f = self.f
        stale = await f.receipt()
        stale.update(applicationStatus='running', allStopped=False)
        latest = deepcopy(stale)
        latest.update(applicationStatus='completed', allStopped=True)
        async def overlapping(*_):
            # Another observer advanced both journals while our HTTP was away.
            f.handoff_row['body']['receipt'] = deepcopy(latest)
            f.origins[f.child['id']]['receipt'] = deepcopy(latest)
            return stale
        f.handoff.receipt = overlapping
        first = await f.service.origin_phase('alice', f.child['id'])
        second = await f.service.origin_phase('alice', f.child['id'])
        self.assertEqual(first, second)
        self.assertEqual(first['status'], 'completed')
        self.assertTrue(first['allStopped'])
        self.assertEqual(f.origins[f.child['id']]['receipt']['applicationStatus'], 'completed')

    async def test_drive_once_and_lost_ack_never_replays(self):
        for lose_ack in (False, True):
            f = Fixture()
            f.handoff_row['body']['receipt'].update(id=str(uuid4()), remoteRunId=f.remote_run)
            calls, saved = [], []
            async def request(owner, target, method, path):
                calls.append((method, path))
                if lose_ack: raise HTTPException(503, 'fixture-unknown')
                return await f.receipt()
            f.handoff._request = request
            f.handoff._save_receipt = lambda row, target, receipt: saved.append(receipt) or receipt
            self.assertIsNone(f.service.drive_outcome('alice', f.child['id']))
            original = deepcopy(f.origins[f.child['id']]['body'])
            if lose_ack:
                with self.assertRaises(HTTPException): await f.service.start_phase('alice', f.child['id'])
            else:
                await f.service.start_phase('alice', f.child['id'])
            self.assertIsNone(await f.service.start_phase('alice', f.child['id']))
            self.assertEqual(len(calls), 1)
            self.assertEqual(f.service.drive_outcome('alice', f.child['id'])['nativeRunId'], f.remote_run)
            self.assertEqual(len(saved), 0 if lose_ack else 1)
            self.assertEqual(f.origins[f.child['id']]['body'], original)
            f.grants = False
            with self.assertRaises(HTTPException): await f.service.start_phase('alice', f.child['id'])
            self.assertEqual(len(calls), 1)

    def test_completed_custody_checks_current_parent_without_execution_grant(self):
        f = self.f
        envelope = deepcopy(f.envelope); envelope['scope']['phase'] = 'training'
        f.origins[f.child['id']]['body']['envelope'] = envelope
        f.origins[f.child['id']]['fingerprint'] = digest(f.origins[f.child['id']]['body'])
        f.child['terminal'] = True
        f.handoff._target = lambda *_, **kw: f.target
        f.store.plan_policy = SimpleNamespace(require_scientific_custody=lambda *_, **kw: None)
        lease_id = str(uuid4())
        receipt = {'remoteTaskId': f.remote_task, 'remoteRunId': f.remote_run,
                   'applicationStatus': 'completed', 'allStopped': True}
        f.handoff_row['body']['receipt'] = receipt
        body = {key: value for key, value in f.debit_body().items() if key != 'callId'}
        body.update(tool=None, leaseId=lease_id, phaseScopeSha256=digest(envelope['scope']))
        evidence = {'lease': {'id': lease_id, 'state': 'RECLAIMED', 'executionStatus': 'COMPLETED', 'exitCode': 0},
                    'checkpoint': {'artifactId': 'synthetic-original'}}
        # Receipt shape/stop validation has its own pure suite; isolate mandate
        # and binding decisions here, without pretending to execute science.
        with patch.object(f.service, '_binding', return_value=envelope), \
             patch('agent_factory.remote_scientific_origin.validate_scientific_evidence', return_value=evidence), \
             patch('agent_factory.remote_scientific_origin.scientific_stopped', return_value=True):
            self.assertEqual(set(f.service.authorize_completed_custody(body)), {'custodyProofSha256'})
            self.assertEqual(f.shared, {})
            for field, value in (('nativeRunId', str(uuid4())), ('leaseId', str(uuid4())), ('phaseScopeSha256', 'f' * 64)):
                with self.assertRaises(HTTPException): f.service.authorize_completed_custody({**body, field: value})
            f.child['terminal'] = False
            with self.assertRaises(HTTPException): f.service.authorize_completed_custody(body)
            f.child['terminal'] = True
            f.ticket['status'] = 'running'
            with self.assertRaises(HTTPException): f.service.authorize_completed_custody(body)
            f.ticket['status'] = 'paused'
            f.child['cancel_requested'] = True
            with self.assertRaises(HTTPException): f.service.authorize_completed_custody(body)
            f.child['cancel_requested'] = False
            wrong_phase = deepcopy(envelope); wrong_phase['scope']['phase'] = 'evaluation'
            with patch.object(f.service, '_binding', return_value=wrong_phase), self.assertRaises(HTTPException):
                f.service.authorize_completed_custody(body)
            f.grants = False
            with self.assertRaises(HTTPException): f.service.authorize_completed_custody(body)

    def test_received_native_is_checked_before_handoff_release(self):
        f = self.f
        f.service.consume_remote_tool(f.debit_body())
        valid = {'remoteTaskId': f.remote_task, 'remoteRunId': f.remote_run}
        f.service.validate_received_native('alice', f.child['id'], valid)
        for key in valid:
            with self.assertRaises(HTTPException):
                f.service.validate_received_native('alice', f.child['id'], {**valid, key: str(uuid4())})

    async def test_baseline_uses_pinned_project_and_observation_identity(self):
        f = self.f
        f.service.project_bindings = {'fixture-project': {'targetRef': 'receiver-target', 'projectPin': 'c' * 64,
            'manifest': f.manifest, 'ownerId': 'alice'}}
        calls = []
        observation = {'schema': 1, 'status': 'completed', 'comparisonIdentitySha256': manifest_fingerprint(f.manifest),
            'variantSha256': f.manifest['baselineSourceManifestSha256'], 'valBpb': 1.2}
        async def request(owner, target, method, path, **kwargs):
            calls.append((owner, method, path, kwargs))
            return {'schema': 1, 'projectId': 'fixture-project', 'projectPin': 'c' * 64, 'observation': observation}
        f.handoff._request = request
        self.assertEqual(await f.service.project_baseline('alice', 'receiver-target', 'fixture-project', 'c' * 64), observation)
        self.assertEqual(calls[0][1:3], ('GET', '/api/factory/remote-handoffs/scientific-projects/fixture-project/baseline'))
        with self.assertRaises(HTTPException):
            await f.service.project_baseline('bob', 'receiver-target', 'fixture-project', 'c' * 64)
        observation['variantSha256'] = 'f' * 64
        with self.assertRaises(HTTPException):
            await f.service.project_baseline('alice', 'receiver-target', 'fixture-project', 'c' * 64)

    async def test_phase_receipt_cannot_change_first_attested_native_run(self):
        f = self.f
        f.service.consume_remote_tool(f.debit_body())
        f.remote_run = str(uuid4())
        with self.assertRaises(HTTPException): await f.service.origin_phase('alice', f.child['id'])
        self.assertIsNone(f.origins[f.child['id']]['receipt'])

    async def test_internal_cleanup_read_requires_original_cancel_and_not_public_grant(self):
        f = self.f
        with self.assertRaises(HTTPException): await f.service.cleanup_phase('alice', f.child['id'])
        f.grants = False
        await f.service.cancel_original('alice', f.child['id'])
        self.assertTrue((await f.service.cleanup_phase('alice', f.child['id']))['allStopped'])
        with self.assertRaises(HTTPException): await f.service.origin_phase('alice', f.child['id'])
        with self.assertRaises(HTTPException): await f.service.cleanup_phase('bob', f.child['id'])


if __name__ == '__main__': unittest.main()
