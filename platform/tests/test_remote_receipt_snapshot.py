"""Controlled receiver snapshot interleaving, without PG or native dispatch.

Runs the real receipt reconciliation flow. A scalar ledger double models only
remote_statement's monotonic CLOSED behavior; real accounting remains covered
by test_usage_ledger_postgres and test_remote_usage_process_postgres.
"""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException
from sqlalchemy import Column, JSON, MetaData, String, Table, create_engine

from agent_factory.remote_bindings import RemoteBindingService
from agent_factory.remote_handoff import PreparedHandoffService
from agent_factory.store import digest


class RemoteReceiptSnapshotTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.phase = 'running'
        self.held_child = False
        self.statement = {'sequence': 1, 'allStopped': False}
        self.ledger_state = 'IMPORTED'
        self.task = {'id': 'original-task', 'owner_id': 'bob', 'plan_id': 'original-plan',
                     'run_id': 'original-run', 'admission': 'accepted',
                     'cancel_requested': False, 'terminal': False, 'body': {}}
        self.row = {'id': 'original-receipt', 'state': 'ACCEPTED',
                    'body': {'remoteTaskId': self.task['id'], 'usageGrant': {'id': 'original-receipt'}}}
        self.service = object.__new__(PreparedHandoffService)
        self.service._row = Mock(side_effect=self.row_for)
        self.service._check_row = Mock()
        self.service._fence_cancelled_preparation = Mock()
        self.service._public = Mock(side_effect=lambda row, native=None: {
            'id': row['id'], 'remoteTaskId': self.task['id'], 'remotePlanId': self.task['plan_id'],
            'remoteRunId': self.task['run_id'], 'native': deepcopy(native)})
        self.service.dispatch = AsyncMock(side_effect=AssertionError('Reconcile cannot dispatch'))
        self.service.bridge = SimpleNamespace(
            find_run=AsyncMock(return_value={'run_id': 'original-run'}),
            detail=AsyncMock(side_effect=self.native),
            submit=AsyncMock(side_effect=AssertionError('No new native admission')))
        self.ledger = SimpleNamespace(remote_statement=Mock(side_effect=self.remote_statement))
        self.service.store = SimpleNamespace(
            task=Mock(side_effect=self.task_for), effects=Mock(return_value=[]),
            events=Mock(return_value=[]), artifacts=Mock(return_value=[]),
            sql=Mock(side_effect=self.sql), usage_ledger=self.ledger,
            accept=Mock(side_effect=AssertionError('Original run already bound')),
            delegation=SimpleNamespace(inspect_group=AsyncMock(side_effect=self.group)))
        # Presentation and unrelated runtime custody are isolated; real group
        # allStopped and native queue status drive the receipt's stop predicate.
        for target, value in (
            ('agent_factory.factory_api.status_of', lambda task, native, *args: native['queue']['status']),
            ('agent_factory.delegation.application_group_status', lambda status, group: status),
            ('agent_factory.remote_handoff.runtime_custody_held', lambda *args: False),
        ):
            active = patch(target, side_effect=value)
            active.start()
            self.addCleanup(active.stop)

    def row_for(self, identifier, owner):
        self.assertEqual((identifier, owner), ('original-receipt', 'bob'))
        return deepcopy(self.row)

    def task_for(self, identifier, owner):
        self.assertEqual((identifier, owner), ('original-task', 'bob'))
        return deepcopy(self.task)

    async def native(self, run, task, owner):
        self.assertEqual((run, task, owner), ('original-run', 'original-task', 'bob'))
        return {'run_id': run, 'queue': {'status': self.phase}}

    async def group(self, owner, task):
        self.assertEqual((owner, task), ('bob', 'original-task'))
        return {'allStopped': self.phase == 'completed' and not self.held_child}

    def sql(self, query, **params):
        if query.startswith('SELECT statement FROM af_usage_remote_grants'):
            self.assertEqual(params, {'id': 'original-receipt', 'owner': 'bob', 'task': 'original-task'})
            return [{'statement': deepcopy(self.statement)}]
        self.assertTrue(query.startswith("UPDATE af_remote_handoffs SET state='ACCEPTED'"))
        self.assertEqual(params, {'id': 'original-receipt'})
        return []

    def remote_statement(self, owner, task, receipt, *, all_stopped):
        self.assertEqual((owner, task, receipt), ('bob', 'original-task', 'original-receipt'))
        if all_stopped and self.ledger_state != 'CLOSED':
            self.ledger_state = 'CLOSED'
            self.statement = {'sequence': 2, 'allStopped': True}
        return deepcopy(self.statement)

    def assert_no_dispatch(self):
        self.service.dispatch.assert_not_awaited()
        self.service.bridge.submit.assert_not_awaited()
        self.service.store.accept.assert_not_called()

    async def test_overtaken_snapshot_refreshes_original_once_and_keeps_closed_statement(self):
        captured, release = asyncio.Event(), asyncio.Event()
        async def inspect_group(owner, task):
            snapshot = await self.group(owner, task)
            if not snapshot['allStopped']:
                captured.set()
                await release.wait()
            return snapshot
        self.service.store.delegation.inspect_group.side_effect = inspect_group
        older = asyncio.create_task(self.service.reconcile('bob', 'original-receipt'))
        try:
            await asyncio.wait_for(captured.wait(), 2)
            self.phase = 'completed'
            newer = await self.service.reconcile('bob', 'original-receipt')
            self.assertTrue(newer['allStopped'])
            closed = deepcopy(self.statement)
            release.set()
            recovered = await asyncio.wait_for(older, 2)
        finally:
            release.set()
            if not older.done():
                older.cancel()
            await asyncio.gather(older, return_exceptions=True)
        self.assertEqual(recovered, newer)
        self.assertEqual(recovered['remoteRunId'], 'original-run')
        self.assertEqual(recovered['usageStatement'], closed)
        self.assertEqual((self.ledger_state, self.statement), ('CLOSED', closed))
        self.assertEqual(self.service.bridge.detail.await_count, 3)  # B + A + one A refresh
        self.assertEqual([call.kwargs['all_stopped'] for call in self.ledger.remote_statement.call_args_list],
                         [True, False, True])
        self.assert_no_dispatch()

    async def test_closed_accounting_cannot_override_still_held_child(self):
        self.phase = 'completed'
        self.held_child = True
        self.ledger_state = 'CLOSED'
        self.statement = {'sequence': 2, 'allStopped': True}
        original = deepcopy(self.statement)
        with self.assertRaises(HTTPException) as caught:
            await self.service.reconcile('bob', 'original-receipt')
        self.assertEqual(caught.exception.status_code, 409)
        self.assertTrue(caught.exception.detail.startswith('USAGE_REMOTE_STATEMENT_STOP:'))
        self.assertEqual(self.service.bridge.detail.await_count, 2)
        self.assertEqual([call.kwargs['all_stopped'] for call in self.ledger.remote_statement.call_args_list], [False, False])
        self.assertEqual((self.ledger_state, self.statement), ('CLOSED', original))
        self.assert_no_dispatch()

    async def test_read_only_snapshot_omits_conflicting_statement_without_refresh_or_writes(self):
        self.ledger_state = 'CLOSED'
        self.statement = {'sequence': 2, 'allStopped': True}
        result = await self.service.receipt('bob', 'original-receipt')
        self.assertFalse(result['allStopped'])
        self.assertNotIn('usageStatement', result)
        self.assertEqual(self.service.bridge.detail.await_count, 1)
        self.ledger.remote_statement.assert_not_called()
        self.assertTrue(all(call.args[0].startswith('SELECT ') for call in self.service.store.sql.call_args_list))
        self.assert_no_dispatch()

    def original_cleanup(self):
        # Keep the real origin mapping/configuration checks while making all
        # execution-authorized reads fail as they do for a disabled receiver.
        self.row.update(remote_owner='bob', origin_ref='original-origin', origin_owner='alice',
                        origin_task='origin-task', request_id='original-request', manifest_hash='original-manifest',
                        configuration_hash='original-configuration')
        self.row['body']['manifest'] = {'plan': {}}
        self.row['body']['remotePlan'] = {'id': self.task['plan_id'], 'syntheticFixture': True}
        self.row['body']['usageGrant']['sha256'] = 'c' * 64
        self.service.origins = {'original-origin': SimpleNamespace(
            identity_map={'alice': 'bob'}, fingerprint='original-configuration')}
        self.service.auth = SimpleNamespace(require_member=Mock(side_effect=HTTPException(403, 'disabled')))
        self.service._check_row = PreparedHandoffService._check_row.__get__(self.service)
        self.service.bridge.find_run.side_effect = HTTPException(403, 'disabled')
        self.service.bridge.detail.side_effect = HTTPException(403, 'disabled')
        self.service.bridge.find_original_run = AsyncMock(return_value={'run_id': 'original-run'})
        self.child = {**self.task, 'id': 'original-child', 'plan_id': 'child-plan', 'run_id': 'child-run'}
        self.service.store.task.side_effect = lambda identifier, owner: deepcopy(
            {'original-task': self.task, 'original-child': self.child}[identifier]) if owner == 'bob' else None
        self.service.store.lifecycle_observer = SimpleNamespace(_binding=Mock(side_effect=lambda task: {
            'id': task['run_id'], 'status': self.phase, 'requirements': []}))
        self.service.store.has_failures = Mock(return_value=False)
        self.service.store.process_runtime = self.service.store.workflow = None
        # Exercise the actual receipt projection and persisted proof read; a
        # stubbed _public previously hid its repeated active-member check.
        engine = create_engine('sqlite://')
        self.addCleanup(engine.dispose)
        bindings = object.__new__(RemoteBindingService)
        bindings.store, bindings.auth = SimpleNamespace(engine=engine), self.service.auth
        metadata = MetaData()
        bindings.proofs = Table('proofs', metadata,
            Column('receipt_id', String, primary_key=True), Column('receiver_owner', String),
            Column('receiver_plan_id', String), Column('sha', String), Column('body', JSON))
        metadata.create_all(engine)
        proof = {'schema': 1, 'originRef': self.row['origin_ref'], 'receiptId': self.row['id'],
            'originTaskId': self.row['origin_task'], 'originOwner': 'alice', 'receiverOwner': 'bob',
            'receiverPlanId': self.task['plan_id'], 'manifestHash': self.row['manifest_hash'],
            'sourceConfiguration': {'revision': '1', 'sha256': 'a' * 64},
            'receiverConfiguration': {'revision': '1', 'sha256': 'b' * 64}, 'entries': []}
        with engine.begin() as conn:
            conn.execute(bindings.proofs.insert().values(receipt_id=self.row['id'], receiver_owner='bob',
                receiver_plan_id=self.task['plan_id'], sha=digest(proof), body=proof))
        self.service.store.remote_bindings = bindings
        self.service._public = PreparedHandoffService._public.__get__(self.service)
        from agent_factory.delegation import DelegationService
        delegation = object.__new__(DelegationService)
        delegation.store, delegation.auth = self.service.store, self.service.auth
        delegation.bridge = self.service.bridge
        delegation._descendants = Mock(return_value=[{'child_id': self.child['id'], 'owner_id': 'bob'}])
        self.service.store.delegation = delegation

    async def test_disabled_receiver_internal_settlement_uses_original_facts_without_member_http(self):
        self.original_cleanup()
        self.phase = 'completed'
        recovered = await self.service._receipt('bob', 'original-receipt', reconcile=True, trusted_cleanup=True)
        self.assertTrue(recovered['allStopped'])
        self.assertEqual(recovered['usageStatement'], {'sequence': 2, 'allStopped': True})
        self.assertEqual(self.ledger_state, 'CLOSED')
        self.assertEqual(recovered['receiverBindingProof']['receiverOwner'], 'bob')
        self.service.bridge.find_original_run.assert_awaited_once_with('original-task', 'bob')
        self.assertEqual([call.args[0]['id'] for call in self.service.store.lifecycle_observer._binding.call_args_list],
                         ['original-task', 'original-child', 'original-task'])
        self.service.auth.require_member.assert_not_called()
        self.service.bridge.find_run.assert_not_awaited()
        self.service.bridge.detail.assert_not_awaited()
        with self.assertRaises(HTTPException) as caught:
            await self.service.receipt('bob', 'original-receipt')
        self.assertEqual(caught.exception.status_code, 403)
        with self.assertRaises(HTTPException) as caught:
            await self.service.store.delegation.inspect_group('bob', 'original-task')
        self.assertEqual(caught.exception.status_code, 403)
        with self.assertRaises(HTTPException) as caught:
            self.service.store.remote_bindings.inspect('original-receipt', 'bob')
        self.assertEqual(caught.exception.status_code, 403)
        with self.assertRaises(HTTPException) as caught:
            self.service.store.remote_bindings._inspect('original-receipt', 'alice')
        self.assertEqual(caught.exception.status_code, 404)
        self.assert_no_dispatch()

    async def test_original_proof_integrity_failure_cannot_close_receiver_grant(self):
        self.original_cleanup()
        self.phase = 'completed'
        bindings = self.service.store.remote_bindings
        with bindings.store.engine.begin() as conn:
            conn.execute(bindings.proofs.update().values(sha='different-proof'))
        with self.assertRaises(HTTPException) as caught:
            await self.service._receipt('bob', 'original-receipt', reconcile=True, trusted_cleanup=True)
        self.assertEqual(caught.exception.status_code, 409)
        self.assertIn('REMOTE_BINDING_INTEGRITY', caught.exception.detail)
        self.assertEqual(self.ledger_state, 'IMPORTED')
        self.ledger.remote_statement.assert_not_called()
        self.assert_no_dispatch()

    async def test_missing_or_invalid_child_binding_holds_original_grant(self):
        for missing in (True, False):
            with self.subTest(missing=missing):
                self.original_cleanup()
                self.phase = 'completed'
                def binding(task):
                    if task['id'] == 'original-child':
                        if missing:
                            return None
                        raise ValueError('Different child envelope')
                    return {'id': task['run_id'], 'status': self.phase, 'requirements': []}
                self.service.store.lifecycle_observer._binding.side_effect = binding
                result = await self.service._receipt('bob', 'original-receipt', reconcile=True, trusted_cleanup=True)
                self.assertFalse(result['allStopped'])
                self.assertTrue(result['group']['unknown'])
                self.assertEqual(self.ledger_state, 'IMPORTED')
                self.service.bridge.detail.assert_not_awaited()
                self.assert_no_dispatch()

    async def test_original_stop_proof_failure_cannot_close_receiver_grant(self):
        self.original_cleanup()
        self.phase = 'completed'
        self.service.store.lifecycle_observer._binding.side_effect = ValueError('Wrong native envelope')
        with self.assertRaises(ValueError):
            await self.service._receipt('bob', 'original-receipt', reconcile=True, trusted_cleanup=True)
        self.assertEqual(self.ledger_state, 'IMPORTED')
        self.ledger.remote_statement.assert_not_called()
        self.assert_no_dispatch()

    async def test_missing_original_stop_binding_cannot_close_receiver_grant(self):
        self.original_cleanup()
        self.phase = 'completed'
        self.service.store.lifecycle_observer._binding.side_effect = None
        self.service.store.lifecycle_observer._binding.return_value = None
        with self.assertRaises(HTTPException) as caught:
            await self.service._receipt('bob', 'original-receipt', reconcile=True, trusted_cleanup=True)
        self.assertEqual(caught.exception.status_code, 503)
        self.assertEqual(self.ledger_state, 'IMPORTED')
        self.ledger.remote_statement.assert_not_called()
        self.assert_no_dispatch()

    async def test_lost_admission_ack_is_bound_before_original_stop_read(self):
        self.original_cleanup()
        self.phase = 'completed'
        self.row['state'] = 'UNKNOWN'
        self.task['run_id'] = None
        def accept(task, run):
            self.assertEqual((task, run), ('original-task', 'original-run'))
            self.task['run_id'] = run
        self.service.store.accept.side_effect = accept
        recovered = await self.service._receipt('bob', 'original-receipt', reconcile=True, trusted_cleanup=True)
        self.assertTrue(recovered['allStopped'])
        self.service.store.accept.assert_called_once_with('original-task', 'original-run')
        self.assertEqual(self.service.store.lifecycle_observer._binding.call_args.args[0]['run_id'], 'original-run')
        self.service.bridge.submit.assert_not_awaited()
        self.service.dispatch.assert_not_awaited()


class OriginReceiptMonotonicityTests(unittest.TestCase):
    """Exercise real pre-persistence receipt checks against a read-only DB seam."""
    def setUp(self):
        from contextlib import contextmanager
        from uuid import uuid4
        from agent_factory.remote_handoff import TrustedHandoffClient
        from agent_factory.store import digest
        self.identifier, remote_plan, remote_task, remote_run = (str(uuid4()) for _ in range(4))
        self.target = SimpleNamespace(origin_ref='origin', identity_map={'alice':'bob'},
                                      configuration_revision='1', fingerprint='f'*64)
        plan = {'executionBindings': {'schema':1}}
        proof = {'schema':1, 'originRef':'origin', 'receiptId':self.identifier,
                 'originTaskId':'original-origin-task', 'originOwner':'alice',
                 'receiverOwner':'bob', 'receiverPlanId':remote_plan, 'manifestHash':'m'*64,
                 'sourceConfiguration':{'revision':'1','sha256':'f'*64},
                 'receiverConfiguration':{'revision':'1','sha256':'r'*64}, 'entries':[]}
        proof['sha256'] = digest({**proof,'sourcePlan':plan,'sourceBindings':plan['executionBindings']})
        self.receipt = {'id':self.identifier, 'originRef':'origin', 'originOwnerId':'alice',
                        'originTaskId':'original-origin-task', 'remoteOwnerId':'bob',
                        'requestId':'original-request', 'manifestHash':'m'*64,
                        'remotePlanId':remote_plan,'remoteTaskId':remote_task,'remoteRunId':remote_run,
                        'receiverBindingProof':proof,'state':'ACCEPTED','allStopped':True,
                        'usageGrant':{'id':self.identifier,'sha256':'g'*64},
                        'usageStatement':{'grantId':self.identifier,'sequence':2,'allStopped':True}}
        self.row = {'task_id':'original-origin-task','owner_id':'alice','request_id':'original-request',
                    'manifest_hash':'m'*64,'state':'ACCEPTED',
                    'body':{'manifest':{'plan':plan},'receipt':deepcopy(self.receipt),
                            'usageGrant':deepcopy(self.receipt['usageGrant'])}}
        self.task = {'id':'original-origin-task','terminal':True}
        self.ledger_state = {'state':'SETTLED','heldTokens':0,'heldAmountMicros':0,'sequence':2}
        def execute(statement, params):
            self.assertTrue(str(statement).startswith('SELECT * FROM af_remote_placements'),
                            'Stale observation must fail before UPDATE')
            self.assertEqual(params,{'id':'original-origin-task','owner':'alice'})
            return SimpleNamespace(mappings=lambda:SimpleNamespace(first=lambda:deepcopy(self.row)))
        connection = SimpleNamespace(execute=Mock(side_effect=execute))
        @contextmanager
        def transaction():
            yield connection
        forbidden = Mock(side_effect=AssertionError('Stale observation cannot mutate custody or accounting'))
        self.client = object.__new__(TrustedHandoffClient)
        self.client.store = SimpleNamespace(transaction=transaction, observed=forbidden,
            usage_ledger=SimpleNamespace(apply_remote_statement=forbidden,
                                         reclaim_remote_no_dispatch=forbidden))
        self.forbidden = forbidden

    def test_late_receipt_without_statement_cannot_replace_positive_receipt_even_on_read(self):
        original = deepcopy((self.row,self.task,self.ledger_state))
        late = deepcopy(self.receipt)
        late.pop('usageStatement')
        late['allStopped'] = False
        for persist in (True,False):
            with self.subTest(persist=persist), self.assertRaises(HTTPException) as caught:
                self.client._save_receipt(deepcopy(self.row),self.target,late,persist=persist)
            self.assertEqual(caught.exception.status_code,409)
            self.assertTrue(caught.exception.detail.startswith('REMOTE_OBSERVATION_STALE:'))
            self.assertEqual((self.row,self.task,self.ledger_state),original)
        self.forbidden.assert_not_called()

    def test_stale_statement_sequence_cannot_replace_settled_original(self):
        original = deepcopy((self.row,self.task,self.ledger_state))
        late = deepcopy(self.receipt)
        late['usageStatement']['sequence'] = 1
        with self.assertRaises(HTTPException) as caught:
            self.client._save_receipt(deepcopy(self.row),self.target,late)
        self.assertEqual(caught.exception.status_code,409)
        self.assertTrue(caught.exception.detail.startswith('USAGE_REMOTE_STATEMENT_STALE:'))
        self.assertEqual((self.row,self.task,self.ledger_state),original)
        self.forbidden.assert_not_called()

    def test_invalid_binding_proof_is_rejected_before_any_mutation(self):
        original = deepcopy((self.row,self.task,self.ledger_state))
        invalid = deepcopy(self.receipt)
        invalid['receiverBindingProof']['sourceConfiguration']['revision'] = 'replacement'
        with self.assertRaises(HTTPException) as caught:
            self.client._save_receipt(deepcopy(self.row),self.target,invalid)
        self.assertEqual(caught.exception.status_code,409)
        self.assertEqual((self.row,self.task,self.ledger_state),original)
        self.forbidden.assert_not_called()
