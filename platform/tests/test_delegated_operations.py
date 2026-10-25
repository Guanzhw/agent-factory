"""Portable adapter protocol checks; no native lifecycle or real-model claim."""
from contextlib import nullcontext
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

from fastapi import HTTPException

from agent_factory.delegated_operations import DelegatedOperations
from agent_factory.delegation import DelegationService
from agent_factory.store import digest
from agent_factory.workflow_contracts import WorkflowAcknowledgementUnknown, WorkflowContext

PIN = {'adapterId': 'native-delegated-operations-v1', 'revision': '1', 'configFingerprint': digest({})}


class DelegatedOperationsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.context = WorkflowContext('parent', 'native-run', 'alice', 'experiment', 'a' * 64)
        self.inputs = {'goal': 'compute checksum', 'mode': 'checksum'}
        self.body = {'id': 'operation-1', 'ownerId': 'alice', 'taskId': 'parent', 'adapterPin': PIN,
            'inputsSha256': digest(self.inputs), 'cancelRequested': False, 'closed': False, 'handle': None}
        self.child = {'id': 'child', 'plan_id': 'child-plan', 'run_id': 'child-run'}
        self.link = {'child_id': 'child', 'plan_id': 'child-plan'}
        custody = SimpleNamespace(_load=Mock(return_value=self.body), _identity=Mock(),
            _context=Mock(return_value=self.context))
        self.store = SimpleNamespace(workflow=custody, sql=Mock(return_value=[self.link]),
            task=Mock(return_value=self.child), artifacts=Mock(return_value=[]))
        self.delegation = SimpleNamespace(store=self.store, create=AsyncMock(), _ancestry=Mock(return_value=('parent', [])),
            _root_lock=Mock(side_effect=lambda _: nullcontext()))
        self.facts = {'nativeStatus': 'completed', 'failed': False, 'content': 'actual checksum result'}
        self.group = {'parent': self.facts, 'children': [], 'allStopped': True, 'unknown': False}
        self.observer = SimpleNamespace(inspect_subtree=AsyncMock(return_value=self.group), cancel_subtree=AsyncMock(return_value={'errors': []}))
        self.adapter = DelegatedOperations(self.delegation, self.observer, PIN)

    async def test_start_uses_only_original_parent_request_and_observes_child_subtree(self):
        result = await self.adapter.start(self.context, self.body['id'], self.inputs)
        self.delegation.create.assert_awaited_once_with('alice', 'parent', 'compute checksum', 'checksum', 'operation:operation-1', original_operation_id='operation-1')
        self.observer.inspect_subtree.assert_called_once_with('alice', 'child')
        self.assertEqual(result['output']['result'], 'actual checksum result')
        self.assertEqual(result['state'], 'COMPLETED')
        self.assertTrue(result['allStopped'])

    async def test_lookup_never_creates_when_ack_or_child_missing(self):
        for rows in ([], [{'child_id': None}], [self.link]):
            with self.subTest(rows=rows):
                self.store.sql.return_value = rows
                self.store.task.side_effect = HTTPException(404, 'missing child')
                result = await self.adapter.lookup(self.context, self.body['id'])
                self.assertEqual(result['state'], 'UNKNOWN')
                self.assertFalse(result['allStopped'])
        self.delegation.create.assert_not_awaited()
        self.observer.inspect_subtree.assert_not_called()

    async def test_lost_ack_is_not_retried_and_lookup_uses_original_link(self):
        self.delegation.create.side_effect = TimeoutError()
        with self.assertRaises(WorkflowAcknowledgementUnknown):
            await self.adapter.start(self.context, self.body['id'], self.inputs)
        result = await self.adapter.lookup(self.context, self.body['id'])
        self.assertEqual(result['state'], 'COMPLETED')
        self.assertEqual(self.delegation.create.await_count, 1)

    async def test_input_conflict_and_extra_authority_are_rejected_before_create(self):
        for inputs in ({**self.inputs, 'goal': 'different'}, {**self.inputs, 'placement': {}},
                       {**self.inputs, 'owner': 'bob'}, {'mode': 'checksum'}):
            with self.subTest(inputs=inputs), self.assertRaises(HTTPException):
                await self.adapter.start(self.context, self.body['id'], inputs)
        self.delegation.create.assert_not_awaited()

    async def test_context_pin_and_persisted_handle_are_required_for_cleanup(self):
        handle = {'adapterId': PIN['adapterId'], 'revision': '1', 'id': self.body['id']}
        self.body['handle'] = handle
        bad_context = WorkflowContext('other-parent', 'native-run', 'alice', 'experiment', 'a' * 64)
        with self.assertRaises(HTTPException):
            await self.adapter.cancel(bad_context, handle)
        self.body['handle'] = {**handle, 'id': 'other-operation'}
        with self.assertRaises(HTTPException):
            await self.adapter.cancel(self.context, handle)
        self.body['handle'] = handle
        self.body['adapterPin'] = {**PIN, 'revision': '2'}
        with self.assertRaises(HTTPException):
            await self.adapter.cancel(self.context, handle)
        self.observer.cancel_subtree.assert_not_awaited()

    async def test_cleanup_uses_only_original_child_and_requires_positive_stop(self):
        handle = {'adapterId': PIN['adapterId'], 'revision': '1', 'id': self.body['id']}
        self.body['handle'] = handle
        self.group.update(allStopped=False, unknown=True)
        result = await self.adapter.cancel(self.context, handle)
        self.observer.cancel_subtree.assert_awaited_once_with('alice', 'child')
        self.assertEqual(result['state'], 'UNKNOWN')
        self.assertFalse(result['allStopped'])
        self.delegation.create.assert_not_awaited()

    async def test_failed_and_cancelled_are_not_completed_science(self):
        for facts, state in (({'failed': True}, 'FAILED'), ({'nativeStatus': 'cancelled'}, 'CANCELLED')):
            with self.subTest(state=state):
                self.group['parent'] = {**deepcopy(self.facts), **facts}
                result = await self.adapter.lookup(self.context, self.body['id'])
                self.assertEqual(result['state'], state)
                self.assertIsNone(result['output'])

    async def test_cleanup_error_is_not_hidden_as_running(self):
        handle = {'adapterId': PIN['adapterId'], 'revision': '1', 'id': self.body['id']}
        self.body['handle'] = handle
        self.observer.cancel_subtree.return_value = {'errors': [{'taskId': 'child', 'errorType': 'ConnectionError'}]}
        with self.assertRaises(HTTPException) as caught:
            await self.adapter.cancel(self.context, handle)
        self.assertEqual(caught.exception.status_code, 503)
        self.assertEqual(caught.exception.detail, 'DELEGATED_CHILD_CANCELLATION_UNKNOWN')
        self.observer.inspect_subtree.assert_not_called()

    async def test_public_create_cannot_claim_reserved_operation_namespace(self):
        auth, store, bridge = Mock(), Mock(), Mock()
        service = DelegationService(None, store, auth, bridge)
        with self.assertRaises(HTTPException) as caught:
            await service.create('alice', 'parent', 'compute checksum', 'checksum', 'operation:operation-1')
        self.assertEqual(caught.exception.detail, 'DELEGATED_OPERATION_REQUEST_RESERVED')
        store.task.assert_not_called()
        bridge.submit.assert_not_called()
