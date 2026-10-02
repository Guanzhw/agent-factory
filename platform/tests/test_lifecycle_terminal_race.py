"""Terminal observation must reconcile late failure provenance and fresh stop proof."""
from contextlib import nullcontext
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from fastapi import HTTPException

from agent_factory.lifecycle_observer import FactoryLifecycleObserver
from agent_factory.plan_policy import NativeMandateCompleted


class LifecycleTerminalRaceTests(unittest.TestCase):
    def fixture(self):
        task = {'id': 'synthetic-root', 'owner_id': 'alice', 'plan_id': 'synthetic-plan',
            'run_id': 'synthetic-run', 'request_id': 'synthetic-request',
            'admission': 'accepted', 'cancel_requested': False}
        failure = {'present': False}
        actions = []
        store = Mock()
        store.task.side_effect = lambda *_: task.copy()
        store.plan.return_value = {'id': task['plan_id']}
        store.effects.return_value = []
        store.has_failures.side_effect = lambda _: failure['present']
        store.transaction.side_effect = nullcontext
        store.delegation = SimpleNamespace(_root_lock=lambda _: nullcontext())

        def sql(statement, **params):
            if 'UPDATE af_tasks SET cancel_requested=TRUE' in statement:
                if task['cancel_requested']:
                    return []
                task['cancel_requested'] = True
                actions.append('cancel-flag')
                return [{'id': task['id']}]
            if 'SET reclaimed=TRUE' in statement:
                actions.append('release-root')
            return []

        def event(identifier, kind, message, data):
            actions.append(kind)
            if kind == 'protected_denied' or (kind == 'lifecycle_cleanup_requested'
                    and data['reason'] in {'protected-failure', 'current-authority-ended', 'native-failure'}):
                failure['present'] = True

        store.sql.side_effect = sql
        store.event.side_effect = event
        store.observed.side_effect = lambda current, status, terminal: actions.append(('terminal', status, current['cancel_requested']))
        observer = FactoryLifecycleObserver(store, Mock(), Mock(), lambda: None)
        observer._group = Mock(side_effect=lambda _: ([task.copy()], []))
        observer._binding = Mock(return_value={'status': 'completed'})
        return observer, store, task, failure, actions

    def test_failure_after_positive_stop_records_cleanup_before_terminal_release(self):
        observer, store, task, failure, actions = self.fixture()
        requested, errors = observer._request_cleanup(task)
        self.assertEqual((requested, errors), ({}, []))
        original_facts = observer._facts
        observed_once = False

        def facts(current):
            nonlocal observed_once
            value = original_facts(current)
            if not observed_once:
                self.assertTrue(value['stopped'])
                self.assertFalse(value['failed'])
                failure['present'] = True  # Concurrent tool/protected failure.
                observed_once = True
            return value

        observer._facts = facts
        result = observer._observe_stopped(task)
        self.assertTrue(result[task['id']]['groupFailed'])
        self.assertEqual(actions, ['cancel-flag', 'lifecycle_cleanup_requested', ('terminal', 'failed', True), 'release-root'])
        store.event.assert_called_once()
        self.assertEqual(store.event.call_args.args[3]['reason'], 'protected-failure')

    def test_current_binding_error_prevents_terminal_and_release(self):
        observer, store, task, _, actions = self.fixture()
        observer._binding.side_effect = [{'status': 'completed'}, PermissionError('Synthetic native binding changed')]
        with self.assertRaises(PermissionError):
            observer._observe_stopped(task)
        store.observed.assert_not_called()
        self.assertNotIn('release-root', actions)
        self.assertFalse(task['cancel_requested'])

    def test_refreshed_unknown_or_queued_facts_keep_capacity_held(self):
        for latest in (PermissionError('Synthetic receipt unavailable'), {'status': 'queued'}):
            with self.subTest(latest=type(latest).__name__):
                observer, store, task, _, actions = self.fixture()
                observer._binding.side_effect = [{'status': 'completed'}, {'status': 'completed'}, latest]
                result = observer._observe_stopped(task)
                self.assertFalse(result[task['id']]['groupStopped'])
                self.assertFalse(result[task['id']]['stopped'])
                if isinstance(latest, Exception):
                    self.assertTrue(result[task['id']]['unknown'])
                store.observed.assert_not_called()
                self.assertNotIn('release-root', actions)

    def test_fresh_authority_denial_records_failed_not_user_cancelled(self):
        observer, store, task, _, actions = self.fixture()
        # The native row changes between observations, so the final boundary
        # must check current authority and then obtain a new positive stop fact.
        observer._binding.side_effect = [{'status': 'completed'}, {'status': 'running'}, {'status': 'completed'}]
        store.require_plan_execution.side_effect = PermissionError('Synthetic current authority revoked')
        result = observer._observe_stopped(task)
        self.assertTrue(result[task['id']]['groupFailed'])
        self.assertEqual(actions, ['cancel-flag', 'protected_denied', 'lifecycle_cleanup_requested',
            ('terminal', 'failed', True), 'release-root'])
        store.require_plan_execution.assert_called_once()
        self.assertEqual(store.event.call_args.args[3]['reason'], 'current-authority-ended')

    def test_exact_completion_during_each_phase_is_observed_without_cancellation(self):
        for phase in ('request', 'observe'):
            with self.subTest(phase=phase):
                observer, store, task, _, actions = self.fixture()
                sequence = [{'status': 'running'}, {'status': 'completed'}]
                if phase == 'observe':
                    sequence = [{'status': 'completed'}, *sequence, {'status': 'completed'}]
                observer._binding.side_effect = sequence
                store.require_plan_execution.side_effect = NativeMandateCompleted(task['id'], task['run_id'])
                if phase == 'request':
                    self.assertEqual(observer._request_cleanup(task), ({}, []))
                    self.assertEqual(actions, [])
                else:
                    result = observer._observe_stopped(task)
                    self.assertTrue(result[task['id']]['groupStopped'])
                    self.assertFalse(result[task['id']]['groupFailed'])
                    self.assertEqual(actions, [('terminal', 'completed', False), 'release-root'])
                store.event.assert_not_called()
                self.assertFalse(task['cancel_requested'])

    def test_typed_completion_rechecks_fresh_failure_cancel_and_unresolved_effect(self):
        for fault, reason in (('failure', 'protected-failure'), ('cancel', 'cancel-requested'),
                              ('unresolved', 'native-ended-unresolved-experiment')):
            with self.subTest(fault=fault):
                observer, store, task, failure, _ = self.fixture()
                observer._binding.side_effect = [{'status': 'running'}, {'status': 'completed'}]
                def deny(*args, **kwargs):
                    if fault == 'failure': failure['present'] = True
                    elif fault == 'cancel': task['cancel_requested'] = True
                    else:
                        store.effects.return_value = [{'effect_key': task['run_id'] + ':orx-experiment-launch-v1',
                                                       'status': 'UNKNOWN'}]
                    raise NativeMandateCompleted(task['id'], task['run_id'])
                store.require_plan_execution.side_effect = deny
                requested, errors = observer._request_cleanup(task)
                self.assertEqual(errors, [])
                self.assertIn(task['id'], requested)
                self.assertTrue(task['cancel_requested'])
                if fault != 'cancel':
                    self.assertEqual(store.event.call_args.args[3]['reason'], reason)

    def test_completion_without_exact_fresh_terminal_binding_never_releases(self):
        cases = ('missing', 'nonterminal', 'binding-error', 'error-task', 'error-run',
                 'fresh-id', 'fresh-owner_id', 'fresh-plan_id', 'fresh-run_id', 'fresh-request_id')
        for phase in ('request', 'observe'):
            for fault in cases:
                with self.subTest(phase=phase, fault=fault):
                    observer, store, task, _, actions = self.fixture()
                    sequence = [{'status': 'running'},
                        None if fault == 'missing' else {'status': 'queued'} if fault == 'nonterminal'
                        else ValueError('Synthetic mismatch') if fault == 'binding-error' else {'status': 'completed'}]
                    if phase == 'observe': sequence.insert(0, {'status': 'completed'})
                    observer._binding.side_effect = sequence
                    def deny(*args, **kwargs):
                        original = task.copy()
                        if fault.startswith('fresh-'):
                            task[fault.removeprefix('fresh-')] = 'changed'
                        raise NativeMandateCompleted('foreign' if fault == 'error-task' else original['id'],
                            'foreign' if fault == 'error-run' else original['run_id'])
                    store.require_plan_execution.side_effect = deny
                    if phase == 'request':
                        requested, errors = observer._request_cleanup(task)
                        self.assertEqual(requested, {})
                        self.assertEqual(len(errors), 1)
                    else:
                        with self.assertRaises(ValueError): observer._observe_stopped(task)
                    store.observed.assert_not_called()
                    self.assertNotIn('release-root', actions)
                    self.assertFalse(task['cancel_requested'])

    def test_generic_denials_cannot_be_reclassified_as_normal_completion(self):
        for error in (HTTPException(403, 'Synthetic revoked'), HTTPException(409, 'Current native delegation mandate is completed'),
                      PermissionError('Synthetic permission denied')):
            with self.subTest(error=type(error).__name__, status=getattr(error, 'status_code', None)):
                observer, store, task, _, actions = self.fixture()
                observer._binding.side_effect = [{'status': 'completed'}, {'status': 'running'}, {'status': 'completed'}]
                store.require_plan_execution.side_effect = error
                result = observer._observe_stopped(task)
                self.assertTrue(result[task['id']]['groupFailed'])
                self.assertIn(('terminal', 'failed', True), actions)
                self.assertIn('protected_denied', actions)

    def test_normal_completed_work_is_not_cancelled(self):
        observer, store, task, _, actions = self.fixture()
        self.assertEqual(observer._request_cleanup(task), ({}, []))
        result = observer._observe_stopped(task)
        self.assertTrue(result[task['id']]['groupStopped'])
        self.assertFalse(result[task['id']]['groupFailed'])
        self.assertEqual(actions, [('terminal', 'completed', False), 'release-root'])
        store.event.assert_not_called()
        self.assertFalse(task['cancel_requested'])


if __name__ == '__main__':
    unittest.main()
