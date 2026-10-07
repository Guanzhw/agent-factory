"""Completed scientific custody never renews execution or ignores other denials."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from fastapi import HTTPException

from agent_factory.autoresearch_custody import require_original_custody
from agent_factory.autoresearch_profile import APPLICATION_ID
from agent_factory.autoresearch_scientific_child import adapter_id
from agent_factory.plan_policy import NativeMandateCompleted


class ScientificCustodyTests(unittest.TestCase):
    def fixture(self):
        context = SimpleNamespace(session_id='child', run_id='run', user_id='alice')
        plan = {'application': APPLICATION_ID, 'mode': 'scientific-training', 'delegation': {'parentTaskId': 'parent'}}
        store = Mock()
        store.require_plan_execution.side_effect = NativeMandateCompleted('child', 'run')
        store.execution_bindings.recheck.return_value = {'tools': [{'adapterId': adapter_id('training', 'tool')}]}
        store.execution_guards = {'current-source': Mock()}
        return store, plan, context

    def test_original_completed_read_checks_custody_materials_and_remaining_guards(self):
        store, plan, context = self.fixture()
        with patch('agent_factory.autoresearch_custody.child_pin') as pin:
            require_original_custody(store, 'alice', plan, context, stopped=True)
        self.assertEqual(pin.call_args.kwargs, {'custody': True})
        store.material_governance.require_materials_current.assert_called_once_with(plan)
        store.execution_guards['current-source'].assert_called_once_with('alice', plan, context, None)

    def test_completed_never_renews_launch_or_foreign_original(self):
        for change in ('launch', 'foreign', 'standalone', 'remote'):
            with self.subTest(change=change):
                store, plan, context = self.fixture()
                if change == 'foreign': store.require_plan_execution.side_effect = NativeMandateCompleted('another-child', 'run')
                if change == 'standalone': plan.pop('delegation')
                if change == 'remote': plan['remoteHandoff'] = {'id': 'remote'}
                with patch('agent_factory.autoresearch_custody.child_pin') as pin:
                    with self.assertRaises(NativeMandateCompleted):
                        require_original_custody(store, 'alice', plan, context, stopped=change != 'launch')
                    pin.assert_not_called()

    def test_current_revocation_and_failed_custody_remain_denials(self):
        store, plan, context = self.fixture()
        store.require_plan_execution.side_effect = HTTPException(403, 'revoked')
        with self.assertRaises(HTTPException):
            require_original_custody(store, 'alice', plan, context, stopped=True)
        store.require_plan_execution.side_effect = NativeMandateCompleted('child', 'run')
        with patch('agent_factory.autoresearch_custody.child_pin', side_effect=PermissionError('parent revoked')):
            with self.assertRaises(PermissionError):
                require_original_custody(store, 'alice', plan, context, stopped=True)
