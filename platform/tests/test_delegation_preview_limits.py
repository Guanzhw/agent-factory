"""Impossible child previews deny locally; viable previews still recheck authority."""
import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from agno.exceptions import RunCancelledException
from fastapi import HTTPException

from agent_factory.delegation import DelegationService, application_group_status
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
        service._descendants = Mock(return_value=[{'child_id': str(index)} for index in range(children)])
        remote_authority = Mock(return_value=('root', [plan]))
        service._mandate = Mock(side_effect=remote_authority)
        return service, remote_authority

    def test_pending_child_admission_does_not_block_known_running_parent(self):
        group = {'unknown': True, 'parent': {'nativeStatus': 'running', 'unknown': False}}
        self.assertEqual(application_group_status('running', group), 'running')
        self.assertEqual(application_group_status('completed', group), 'unknown')
        group['parent']['unknown'] = True
        self.assertEqual(application_group_status('running', group), 'unknown')

    def test_historical_depth_count_and_tool_limits_do_not_block_preview(self):
        for state in ({'depth': 20}, {'children': 50}, {'used': 1000}):
            with self.subTest(state=state):
                service, authority = self.fixture(**state)
                result = service.delegation_scope('alice', 'root')
                self.assertTrue(result['allowed'])
                self.assertIsNone(result['sharedBudget']['toolCallsLimit'])
                authority.assert_called_once()

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

    def test_declared_depth_and_children_above_old_limits_are_honored(self):
        service, authority = self.fixture(depth=3, children=4)
        plan = service.store.plan.return_value
        plan['budget'].update(maxDepth=3, maxChildren=5)
        result = service.delegation_scope('alice', 'root')
        self.assertTrue(result['allowed'], result)
        self.assertIsNone(result['sharedBudget']['maxDepth'])
        self.assertIsNone(result['sharedBudget']['childrenLimit'])
        authority.assert_called_once()
    def test_deep_persisted_ancestry_remains_cycle_checked(self):
        service, _ = self.fixture()
        tasks = {str(index): {'id': str(index), 'owner_id': 'alice'} for index in range(20)}
        service.store.task.side_effect = lambda key, owner: tasks[key]
        service._link = Mock(side_effect=lambda key: {'parent_id': str(int(key) - 1)} if int(key) else None)
        root, ancestors = DelegationService._ancestry(service, tasks['19'])
        self.assertEqual(root, '0')
        self.assertEqual(len(ancestors), 19)
        service._link.side_effect = lambda key: {'parent_id': '19'}
        with self.assertRaises(HTTPException):
            DelegationService._ancestry(service, tasks['19'])

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

    def test_local_modes_match_admission_scope_while_remote_materials_stay_pinned(self):
        for remote in (False, True):
            with self.subTest(remote=remote):
                service, _ = self.fixture()
                plan = service.store.plan.return_value
                plan.update(applicationRef={'id': 'approved-app'}, mode='parent', materialRefs=[],
                            remoteHandoff={'id': 'handoff'} if remote else None)
                material = {'id': 'child-model', 'version': 1, 'sha256': 'a' * 64,
                            'kind': 'model', 'content': 'model', 'permissions': []}
                apps = Mock()
                apps.require_plan_current.return_value = {'defaultMode': 'child', 'modes': {
                    'child': {'materialChoices': {}, 'toolOrder': ['inspect']}}}
                apps.closure.return_value = [material]
                service.store.applications = apps
                result = service.delegation_scope('alice', 'root')
                self.assertEqual(result['allowed'], not remote)
                self.assertEqual(result['modes'], [] if remote else ['child'])

    def test_read_projection_preserves_request_cancellation(self):
        service, authority = self.fixture()
        authority.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            service.delegation_scope('alice', 'root')



if __name__ == '__main__':
    unittest.main()
