"""Persisted inference waits project history status without reconciling work."""
import unittest
from unittest.mock import Mock

from agent_factory.store import digest
from agent_factory_research.inference_wait import CONTROL_NAME
from agent_factory_research.lifecycle_compatibility import ResearchLifecycleObserver


class HistoryResearchSummaryTests(unittest.TestCase):
    def setUp(self):
        self.task = {'id': 'task', 'owner_id': 'alice', 'run_id': 'run', 'plan_id': 'plan',
                     'cancel_requested': False}
        body = {'taskId': 'task', 'ownerId': 'alice', 'nativeRunId': 'run', 'planId': 'plan'}
        self.row = {'body': body, 'hash': digest(body), 'state': 'WAITING'}
        self.store = Mock()
        self.store.task.return_value = self.task
        self.store.has_failures.return_value = False
        def read_only_sql(statement, **params):
            self.assertTrue(statement.lstrip().upper().startswith('SELECT '), statement)
            return [self.row]
        self.store.sql.side_effect = read_only_sql
        self.observer = ResearchLifecycleObserver(self.store, Mock(), Mock(), lambda: None)
        self.ticket = {'status': 'paused', 'requirements': [{'tool_execution': {
            'tool_name': CONTROL_NAME, 'external_execution_required': True}}]}
        self.observer._binding = Mock(return_value=self.ticket)

    def assert_no_writes(self):
        self.store.observed.assert_not_called()
        self.store.observe_summary.assert_not_called()
        self.store.event.assert_not_called()
        self.store.request_cancel.assert_not_called()

    def test_verified_waiting_external_control_projects_approval_without_writes(self):
        # Exercise inference_wait.read's real owner/run/plan/hash validation.
        self.assertEqual(self.observer._summary_status(self.task, 'unknown'), 'waiting_approval')
        self.observer._binding.assert_called_once_with(self.task)
        self.assert_no_writes()

    def test_nonmatching_or_ended_wait_keeps_existing_status(self):
        cases = (
            ('wait-state', lambda: self.row.update(state='RESUMING')),
            ('cancel', lambda: self.task.update(cancel_requested=True)),
            ('failure', lambda: setattr(self.store.has_failures, 'return_value', True)),
            ('native-running', lambda: self.ticket.update(status='running')),
            ('other-control', lambda: self.ticket['requirements'][0]['tool_execution'].update(tool_name='other')),
            ('not-external', lambda: self.ticket['requirements'][0]['tool_execution'].update(external_execution_required=False)),
        )
        for name, change in cases:
            with self.subTest(name=name):
                self.row['state'] = 'WAITING'
                self.task['cancel_requested'] = False
                self.store.has_failures.return_value = False
                self.ticket.update(status='paused', requirements=[{'tool_execution': {
                    'tool_name': CONTROL_NAME, 'external_execution_required': True}}])
                change()
                self.assertEqual(self.observer._summary_status(self.task, 'unknown'), 'unknown')
                self.assert_no_writes()

    def test_mismatched_persisted_wait_is_not_trusted_or_reconciled(self):
        for key in ('ownerId', 'nativeRunId', 'planId'):
            with self.subTest(key=key):
                original = self.row['body'][key]
                self.row['body'][key] = 'different'
                self.row['hash'] = digest(self.row['body'])
                with self.assertRaises(PermissionError):
                    self.observer._summary_status(self.task, 'unknown')
                self.row['body'][key] = original
                self.row['hash'] = digest(self.row['body'])
                self.assert_no_writes()
