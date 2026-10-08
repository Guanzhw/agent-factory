"""Readonly terminal custody versus execution; real SQLite approval, mocked peers."""
from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from fastapi import HTTPException
from agent_factory.autoresearch_custody import require_original_custody
from agent_factory.autoresearch_profile import APPLICATION_ID
import test_remote_scientific_policy as policy_fixture


class OriginCustodyPolicyTests(unittest.TestCase):
    def setUp(self):
        self.f = policy_fixture.RemoteScientificPolicyTests()
        self.f.setUp()
        self.addCleanup(self.f.tearDown)
        f = self.f
        f.child_plan = f.store.add(mode='remote-scientific-training',
            delegation={'parentTaskId': 'parent', 'rootTaskId': 'parent', 'depth': 1})
        f.child.update(plan_id=f.child_plan['id'], terminal=True)
        f.link['plan_id'] = f.child_plan['id']
        f.store.execution_bindings = SimpleNamespace(recheck=Mock())
        f.store.material_governance = SimpleNamespace(require_materials_current=Mock())
        f.approve()

    def read(self):
        return self.f.policy.require_scientific_custody('alice', self.f.child_plan, scientific_child_id='child')

    def test_terminal_read_is_not_execution_approval_and_current_review_remains_required(self):
        result = self.read()
        self.assertIs(result['custodyReadable'], True)
        self.assertNotIn('allowed', result)
        with self.assertRaises(HTTPException): self.f.execute()
        self.f.policy.clock = lambda: datetime(2026, 10, 9, tzinfo=timezone.utc)
        with self.assertRaises(HTTPException): self.read()

    def test_all_installed_guards_bindings_and_material_currency_still_deny(self):
        f = self.f
        guard = Mock(side_effect=PermissionError('current guard denied'))
        f.store.execution_guards['all-guards'] = guard
        with self.assertRaises(PermissionError): self.read()
        guard.assert_called_once_with('alice', f.child_plan, None, None)
        f.store.execution_bindings.recheck.assert_called_with(f.child_plan)
        f.store.material_governance.require_materials_current.assert_called_with(f.child_plan)
        for check in (f.store.execution_bindings.recheck, f.store.material_governance.require_materials_current):
            guard.side_effect = None
            check.side_effect = PermissionError('current material or binding denied')
            with self.assertRaises(PermissionError): self.read()
            check.side_effect = None

    def test_active_cancelled_or_failed_source_cannot_receive_terminal_custody(self):
        f = self.f
        f.child['terminal'] = False
        with self.assertRaises(HTTPException): self.read()
        self.assertTrue(f.execute()['allowed'])
        f.child['terminal'] = True
        f.child['cancel_requested'] = True
        with self.assertRaises(HTTPException): self.read()
        f.child['cancel_requested'] = False
        f.store.has_failures.return_value = True
        with self.assertRaises(HTTPException): self.read()

    def test_completed_evaluation_does_not_get_training_custody_exception(self):
        f = self.f
        f.child_plan = f.store.add(mode='remote-scientific-evaluation',
            delegation={'parentTaskId': 'parent', 'rootTaskId': 'parent', 'depth': 1})
        f.child['plan_id'] = f.child_plan['id']
        f.link['plan_id'] = f.child_plan['id']
        with self.assertRaises(HTTPException): self.read()


class ReceiverCustodyFallbackTests(unittest.TestCase):
    def fixture(self):
        context = SimpleNamespace(user_id='alice', session_id='receiver-task', run_id='receiver-run')
        plan = {'application': APPLICATION_ID, 'mode': 'remote-scientific-training', 'remoteHandoff': {'receiptId': 'receipt'}}
        store = Mock()
        store.require_plan_execution.side_effect = HTTPException(403, 'execution ended')
        store.execution_guards = {'remote_receiver': Mock(side_effect=AssertionError('must use typed custody proof')),
                                  'other': Mock()}
        return store, plan, context

    def test_active_normal_path_does_not_request_custody_or_repeat_guards(self):
        store, plan, context = self.fixture()
        store.require_plan_execution.side_effect = None
        require_original_custody(store, 'alice', plan, context, stopped=False)
        store.remote_scientific_receiver.require_completed_custody.assert_not_called()
        store.plan_policy.require_execution.assert_not_called()

    def test_only_stopped_training_with_installed_receiver_can_fallback(self):
        for failure in ('unstopped', 'phase', 'receiver', 'status'):
            with self.subTest(failure=failure):
                store, plan, context = self.fixture()
                receiver = store.remote_scientific_receiver
                if failure == 'phase': plan['mode'] = 'remote-scientific-evaluation'
                if failure == 'receiver': store.remote_scientific_receiver = None
                if failure == 'status': store.require_plan_execution.side_effect = HTTPException(503, 'unavailable')
                with self.assertRaises((HTTPException, PermissionError)):
                    require_original_custody(store, 'alice', plan, context, stopped=failure != 'unstopped')
                receiver.require_completed_custody.assert_not_called()

    def test_typed_custody_does_not_bypass_other_current_guards(self):
        store, plan, context = self.fixture()
        require_original_custody(store, 'alice', plan, context, stopped=True)
        store.remote_scientific_receiver.require_completed_custody.assert_called_once_with('alice', plan, context)
        store.plan_policy.require_execution.assert_called_once_with('alice', plan, run_context=context)
        store.execution_bindings.recheck.assert_called_once_with(plan, context)
        store.material_governance.require_materials_current.assert_called_once_with(plan)
        store.execution_guards['other'].assert_called_once_with('alice', plan, context, None)
        for check in (store.plan_policy.require_execution, store.execution_bindings.recheck,
                      store.material_governance.require_materials_current, store.execution_guards['other']):
            check.side_effect = PermissionError('fresh denial')
            with self.assertRaises(PermissionError):
                require_original_custody(store, 'alice', plan, context, stopped=True)
            check.side_effect = None
