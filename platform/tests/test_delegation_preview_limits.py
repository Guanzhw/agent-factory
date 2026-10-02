"""Impossible child previews deny locally; viable previews still recheck authority."""
import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from agno.exceptions import RunCancelledException
from fastapi import HTTPException

from agent_factory.delegation import DelegationService
from agent_factory.remote_handoff import HandoffCancellationRequested


class DelegationPreviewLimitsTests(unittest.TestCase):
    def fixture(self, *, depth=1, children=0, used=0):
        task = {'id': 'root', 'owner_id': 'alice', 'plan_id': 'plan'}
        plan = {'id': 'plan', 'capabilities': ['research:read'], 'tools': ['inspect'],
                'budget': {'toolCalls': 8, 'maxDepth': 1, 'maxChildren': 1}}
        store = Mock()
        store.task.return_value = task
        store.plan.return_value = plan
        store.applications = None
        store.sql.side_effect = lambda query, **_: ([{'n': used}] if 'af_delegation_tool_calls' in query
            else [{'n': children}] if 'af_delegation_links' in query else [{'total': 1, 'owned': 1}])
        settings = SimpleNamespace(max_total_tasks=20, max_user_tasks=4)
        service = DelegationService(settings, store, Mock(), Mock())
        service._ancestry = Mock(return_value=('root', [task] * (depth - 1)))
        remote_authority = Mock(return_value=('root', [plan]))
        service._mandate = Mock(side_effect=remote_authority)
        return service, remote_authority

    def test_exhausted_depth_count_and_tool_limits_deny_without_remote_authority(self):
        for state in ({'depth': 2}, {'children': 1}, {'used': 8}):
            with self.subTest(state=state):
                service, authority = self.fixture(**state)
                result = service.delegation_scope('alice', 'root')
                self.assertFalse(result['allowed'])
                self.assertEqual(result['reason'], 'Shared delegation budget exhausted')
                self.assertEqual(result['modes'], [])
                service._mandate.assert_not_called()
                authority.assert_not_called()

    def test_viable_preview_rechecks_authority_on_every_read(self):
        service, authority = self.fixture()
        self.assertTrue(service.delegation_scope('alice', 'root')['allowed'])
        authority.side_effect = HTTPException(403, 'Synthetic current source revocation')
        second = service.delegation_scope('alice', 'root')
        self.assertFalse(second['allowed'])
        self.assertEqual(second['reason'], 'Synthetic current source revocation')
        self.assertEqual(authority.call_count, 2)
        self.assertEqual(service._mandate.call_count, 2)
        self.assertTrue(all(call.kwargs == {'creating': True} for call in service._mandate.call_args_list))

    def test_local_ceiling_denial_does_not_bypass_owner_lookup(self):
        service, authority = self.fixture(children=1)
        service.store.task.side_effect = HTTPException(404, 'Task not found')
        with self.assertRaises(HTTPException) as raised:
            service.delegation_scope('bob', 'root')
        self.assertEqual(raised.exception.status_code, 404)
        service.store.task.assert_called_once_with('root', 'bob')
        authority.assert_not_called()

    def test_cancellation_during_fresh_preview_denies_without_hiding_readable_facts(self):
        for error in (RunCancelledException('late native cancellation'),
                      HandoffCancellationRequested('alice', 'root', 'synthetic-manifest')):
            with self.subTest(error=type(error).__name__):
                service, authority = self.fixture()
                self.assertTrue(service.delegation_scope('alice', 'root')['allowed'])
                authority.side_effect = error
                result = service.delegation_scope('alice', 'root')
                self.assertFalse(result['allowed'])
                self.assertEqual(result['reason'], 'Factory cancellation requested')
                self.assertEqual(result['modes'], [])
                self.assertIsNone(result['defaultMode'])
                self.assertEqual(result['parentTaskId'], 'root')
                self.assertEqual(result['sharedBudget']['childrenUsed'], 0)
                self.assertEqual(authority.call_count, 2)
                service.store.event.assert_not_called()

    def test_read_projection_preserves_request_cancellation(self):
        service, authority = self.fixture()
        authority.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            service.delegation_scope('alice', 'root')


if __name__ == '__main__':
    unittest.main()
