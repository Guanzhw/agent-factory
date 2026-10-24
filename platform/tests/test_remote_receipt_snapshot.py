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

from agent_factory.remote_handoff import PreparedHandoffService


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
        self.service._placement_stopped = Mock(return_value=True)
        self.service._refresh_placement_evidence = AsyncMock()
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
        async def refresh(row, task, result, *, reconcile=False):
            self.assertTrue(reconcile)
            if result['native']['queue']['status'] == 'running':
                captured.set()
                await release.wait()
        self.service._refresh_placement_evidence.side_effect = refresh
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
