"""Real persisted delegation guard distinguishes completion from revoked authority."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from fastapi import HTTPException

from agent_factory.plan_policy import NativeMandateCompleted, persisted_ancestor_guard


class NativeMandateCompletedTests(unittest.TestCase):
    def fixture(self):
        parent = {'id': 'parent', 'owner_id': 'alice', 'plan_id': 'parent-plan',
                  'run_id': 'parent-run', 'cancel_requested': False, 'admission': 'accepted'}
        child = {**parent, 'id': 'child', 'plan_id': 'child-plan', 'run_id': 'child-run'}
        parent_plan = {'id': 'parent-plan', 'tools': ['checksum'], 'capabilities': ['checksum:read']}
        plan = {**parent_plan, 'id': 'child-plan', 'delegation':
                {'parentTaskId': 'parent', 'rootTaskId': 'parent', 'depth': 1}}
        tickets = {t['run_id']: {'session_id': t['id'], 'user_id': 'alice',
                   'component_id': 'factory-executor', 'status': 'completed'} for t in (child, parent)}
        store = Mock()
        store.task.return_value = child
        store.plan.return_value = parent_plan
        store.sql.return_value = [{'owner_id': 'alice', 'reclaimed': False}]
        store.has_failures.return_value = False
        store.native_db.get_job.side_effect = lambda run: tickets.get(run)
        store.delegation = SimpleNamespace(_ancestry=lambda _: ('parent', [parent]),
            _link=lambda _: {'owner_id': 'alice', 'plan_id': 'child-plan'})
        context = SimpleNamespace(session_id='child', run_id='child-run', user_id='alice')
        return store, child, parent, plan, parent_plan, tickets, context

    def test_own_completed_remains_execution_409_after_ancestor_validation(self):
        store, _, _, plan, _, _, context = self.fixture()
        with self.assertRaises(NativeMandateCompleted) as caught:
            persisted_ancestor_guard(store)('alice', plan, context)
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual((caught.exception.task_id, caught.exception.run_id), ('child', 'child-run'))
        store.plan.assert_called_once_with('parent-plan', 'alice')
        self.assertEqual([c.args[0] for c in store.native_db.get_job.call_args_list], ['child-run', 'parent-run'])

    def test_completed_child_cannot_mask_revoked_failed_missing_or_wider_ancestor(self):
        for fault in ('cancel', 'rejected', 'failure', 'missing', 'foreign', 'failed', 'unacknowledged', 'narrowing'):
            with self.subTest(fault=fault):
                store, _, parent, plan, parent_plan, tickets, context = self.fixture()
                if fault == 'cancel': parent['cancel_requested'] = True
                elif fault == 'rejected': parent['admission'] = 'rejected'
                elif fault == 'failure': store.has_failures.side_effect = lambda task: task == 'parent'
                elif fault == 'missing': del tickets['parent-run']
                elif fault == 'foreign': tickets['parent-run']['user_id'] = 'foreign'
                elif fault == 'failed': tickets['parent-run']['status'] = 'failed'
                elif fault == 'unacknowledged': parent['admission'] = 'reserved'
                elif fault == 'narrowing': parent_plan['tools'] = []
                with self.assertRaises(HTTPException) as caught:
                    persisted_ancestor_guard(store)('alice', plan, context)
                self.assertNotIsInstance(caught.exception, NativeMandateCompleted)
                self.assertIn(caught.exception.status_code, {403, 409})

    def test_active_child_under_completed_parent_still_validates_current_mandate(self):
        store, _, _, plan, parent_plan, tickets, context = self.fixture()
        tickets['child-run']['status'] = 'running'
        guard = persisted_ancestor_guard(store)
        self.assertEqual(guard('alice', plan, context), [parent_plan])
        parent_plan['capabilities'] = []
        with self.assertRaises(HTTPException) as caught:
            guard('alice', plan, context)
        self.assertEqual(caught.exception.status_code, 403)
        self.assertNotIsInstance(caught.exception, NativeMandateCompleted)


if __name__ == '__main__':
    unittest.main()
