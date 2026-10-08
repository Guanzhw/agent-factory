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
        plans = {'parent-plan': parent_plan, 'child-plan': plan}
        store.plan.side_effect = lambda plan_id, owner: plans[plan_id] if owner == 'alice' else None
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
        self.assertTrue(store.plan.call_args_list)
        self.assertTrue(all(call.args[1] == 'alice' for call in store.plan.call_args_list))
        self.assertIn(('parent-plan', 'alice'), [call.args for call in store.plan.call_args_list])
        self.assertEqual([c.args[0] for c in store.native_db.get_job.call_args_list], ['child-run', 'parent-run'])

    def test_completed_child_cannot_mask_revoked_failed_missing_or_wider_ancestor(self):
        for fault in ('cancel', 'rejected', 'failure', 'missing', 'foreign', 'failed', 'unacknowledged', 'narrowing',
                      'child-component', 'parent-component', 'component-kind'):
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
                elif fault in {'child-component', 'parent-component'}:
                    selected = plan if fault == 'child-component' else parent_plan
                    selected['nativeComponent'] = {'kind': 'workflow', 'id': 'approved-workflow',
                                                   'revision': '1', 'sha256': 'a' * 64}
                elif fault == 'component-kind': tickets['parent-run']['component_type'] = 'workflow'
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
