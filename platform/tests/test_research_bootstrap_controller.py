"""Offline controller ordering/fault tests; no native execution or GPU claim."""
import asyncio
from copy import deepcopy
from typing import Callable
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

from agent_factory.research_bootstrap_controller import ResearchBootstrapController, ResearchBootstrapError


class Harness:
    def __init__(self):
        self.now = 0.0
        self.calls = []
        self.approved = False
        self.task = {'id': 'original-task', 'owner_id': 'alice', 'plan_id': 'original-plan',
                     'run_id': 'original-run', 'cancel_requested': False, 'terminal': False}
        self.lease = {'id': 'original-lease', 'ownerId': 'alice', 'localTaskId': 'original-task',
                      'planId': 'original-plan', 'nativeRunId': 'original-run', 'providerJobId': 'original-process',
                      'state': 'RECLAIMED', 'executionStatus': 'COMPLETED', 'exitCode': 0, 'capacityHeld': False,
                      'stopEvidence': {'allStopped': True}, 'gpuEvidence': {'state': 'RELEASED'},
                      'syntheticFixture': True}
        self.store = SimpleNamespace(task=Mock(side_effect=lambda *args: deepcopy(self.task)),
                                     plan=Mock(return_value={'id': 'original-plan'}), request_cancel=Mock())
        self.runtime = SimpleNamespace(submit=AsyncMock(return_value=deepcopy(self.lease)),
            inspect_task=AsyncMock(return_value=deepcopy(self.lease)),
            _config=Mock(return_value=('target', {'manifest': 'controlled'}, 'variant')),
            _paused=Mock(return_value={'id': 'original-requirement', 'version': 'original-version'}))
        self.store.research_runtime = self.runtime
        self.state = {'store': self.store, 'research_runtime': self.runtime}
        self.imported = Mock(return_value={'artifactId': 'original-checkpoint'})
        self.progress = []
        self.fault: Callable | None = None

    def request(self, method, path, body, *, owner):
        self.calls.append((method, path, deepcopy(body), owner))
        if self.fault:
            self.fault(method, path, body)
        if path.endswith('/compositions/proposals'):
            return {'id': 'original-proposal'}
        if path.endswith('/accept'):
            return {'id': 'original-plan'}
        if path.endswith('/plan-reviews'):
            return {'id': 'original-review'}
        if path.endswith('/decision'):
            return {'approved': True}
        if path.endswith('/instances'):
            return {'id': 'original-task'}
        if '/requests/' in path:
            return {'requestId': 'operator-attempt:instance', 'taskId': 'original-task', 'planId': 'original-plan'}
        if path.endswith('/approve'):
            self.approved = True
            return {'accepted': True}
        if path.endswith('/cancel'):
            return {'accepted': True}
        if path.endswith('/jobs/original-task'):
            return {'job': {'id': 'original-task', 'ownerId': 'alice', 'planId': 'original-plan',
                'status': 'completed' if self.approved else 'waiting_approval',
                'approvalDetail': {'id': 'original-requirement', 'version': 'original-version'}}}
        raise AssertionError('Unexpected route')

    def sleep(self, duration):
        self.now += duration

    def run(self, **kwargs):
        controller = ResearchBootstrapController(self.state, self.request,
            lambda method: asyncio.run(method()), clock=lambda: self.now, sleep=self.sleep)
        return controller.run(owner='alice', reviewer='task-dev-reviewer',
            application_ref={'id': 'approved-app', 'version': 1, 'sha256': 'a' * 64},
            goal='Original governed training', request_id='operator-attempt', after_reclaimed=self.imported,
            on_progress=self.progress.append, timeout_seconds=kwargs.get('timeout_seconds', 1))


class ControllerTests(unittest.TestCase):
    def test_original_lifecycle_review_import_and_continuation_order(self):
        h = Harness()
        result = h.run()
        h.runtime.submit.assert_awaited_once_with('alice', 'original-task')
        h.imported.assert_called_once()
        self.assertEqual(result['progress']['phase'], 'COMPLETED')
        self.assertEqual(result['progress']['nativeRunId'], 'original-run')
        self.assertEqual(result['lease']['providerJobId'], 'original-process')
        self.assertFalse(result['progress']['scientificConclusionVerified'])
        self.assertTrue(result['lease']['syntheticFixture'])
        decision = next(c for c in h.calls if c[1].endswith('/decision'))
        self.assertEqual(decision[3], 'task-dev-reviewer')
        approval = next(c for c in h.calls if c[1].endswith('/approve'))
        self.assertEqual(approval[2], {'requirementId': 'original-requirement', 'version': 'original-version', 'approved': True})
        h.store.request_cancel.assert_not_called()
        self.assertEqual([p['phase'] for p in h.progress], ['STARTED', 'PLAN_APPROVED', 'TASK_ACCEPTED',
            'NATIVE_PAUSED', 'PROCESS_SUBMITTED', 'PROCESS_RECLAIMED', 'EVIDENCE_IMPORTED', 'COMPLETED'])

    def test_lost_instance_ack_only_reads_original_request_then_cancels(self):
        h = Harness()
        def fault(method, path, body):
            if path.endswith('/instances'):
                raise ConnectionError('private transport detail')
        h.fault = fault
        with self.assertRaises(ResearchBootstrapError) as caught:
            h.run()
        self.assertEqual(str(caught.exception), 'RESEARCH_BOOTSTRAP_STOPPED')
        self.assertEqual(caught.exception.progress['taskId'], 'original-task')
        self.assertEqual(sum(c[1].endswith('/instances') for c in h.calls), 1)
        self.assertTrue(any('/requests/' in c[1] for c in h.calls))
        h.store.request_cancel.assert_called_once_with('original-task')
        h.runtime.submit.assert_not_awaited()

    def test_unknown_remains_same_lease_until_deadline_no_replay_or_import(self):
        h = Harness()
        unknown = {**h.lease, 'state': 'UNKNOWN', 'capacityHeld': True}
        h.runtime.submit.return_value = unknown
        h.runtime.inspect_task.return_value = unknown
        with self.assertRaises(ResearchBootstrapError) as caught:
            h.run(timeout_seconds=.25)
        self.assertTrue(caught.exception.progress['cancelRequested'])
        self.assertFalse(caught.exception.progress['cleanupConfirmed'])
        h.runtime.submit.assert_awaited_once()
        h.imported.assert_not_called()
        self.assertFalse(h.approved)

    def test_changed_original_identity_denies_import_and_continuation(self):
        for field in ('nativeRunId', 'providerJobId', 'id'):
            with self.subTest(field=field):
                h = Harness()
                h.runtime.submit.return_value = {**h.lease, 'state': 'UNKNOWN'}
                h.runtime.inspect_task.return_value = {**h.lease, field: 'replacement'}
                with self.assertRaises(ResearchBootstrapError):
                    h.run()
                h.runtime.submit.assert_awaited_once()
                h.imported.assert_not_called()
                self.assertFalse(h.approved)

    def test_nonpositive_cleanup_and_failed_execution_cannot_import(self):
        for change in ({'capacityHeld': True}, {'executionStatus': 'FAILED'}, {'exitCode': True},
                       {'gpuEvidence': {'state': 'UNKNOWN'}}, {'stopEvidence': {'allStopped': False}}):
            with self.subTest(change=change):
                h = Harness(); h.runtime.submit.return_value.update(change)
                with self.assertRaises(ResearchBootstrapError):
                    h.run()
                h.imported.assert_not_called()
                self.assertFalse(h.approved)

    def test_import_failure_stops_original_without_approval(self):
        h = Harness(); h.imported.side_effect = ValueError('checkpoint mismatch')
        with self.assertRaises(ResearchBootstrapError):
            h.run()
        h.store.request_cancel.assert_called_once_with('original-task')
        self.assertFalse(h.approved)

    def test_revocation_during_inspection_keeps_original_cancel_marker(self):
        h = Harness(); h.runtime.submit.return_value = {**h.lease, 'state': 'RUNNING'}
        h.runtime.inspect_task.side_effect = PermissionError('current authority denied')
        def fault(method, path, body):
            if path.endswith('/cancel'):
                raise PermissionError('HTTP permission also revoked')
        h.fault = fault
        with self.assertRaises(ResearchBootstrapError) as caught:
            h.run()
        self.assertTrue(caught.exception.progress['cancelRequested'])
        h.store.request_cancel.assert_called_once_with('original-task')
        h.imported.assert_not_called()

    def test_changed_requirement_denies_import_and_approval(self):
        h = Harness()
        h.runtime._paused.return_value = {'id': 'original-requirement', 'version': 'old-version'}
        with self.assertRaises(ResearchBootstrapError):
            h.run()
        h.imported.assert_not_called()
        self.assertFalse(h.approved)

    def test_submit_lost_ack_cancels_task_without_second_allocation(self):
        h = Harness()
        h.runtime.submit.side_effect = ConnectionError('may already have launched')
        with self.assertRaises(ResearchBootstrapError) as caught:
            h.run()
        h.runtime.submit.assert_awaited_once()
        h.store.request_cancel.assert_called_once_with('original-task')
        self.assertIsNone(caught.exception.progress['leaseId'])
        self.assertFalse(caught.exception.progress['cleanupConfirmed'])
        h.imported.assert_not_called()


    def test_lost_admission_ack_before_native_id_still_cancels_original_reservation(self):
        h = Harness(); h.task['run_id'] = None
        def fault(method, path, body):
            if path.endswith('/instances'):
                raise ConnectionError('native submission acknowledgement unknown')
        h.fault = fault
        with self.assertRaises(ResearchBootstrapError) as caught:
            h.run()
        self.assertIsNone(caught.exception.progress['nativeRunId'])
        self.assertTrue(caught.exception.progress['cancelRequested'])
        h.store.request_cancel.assert_called_once_with('original-task')
        h.runtime.submit.assert_not_awaited()


    def test_changed_owned_task_plan_cannot_cancel_or_observe_other_execution(self):
        h = Harness()
        h.task['plan_id'] = 'other-owned-plan'
        h.runtime.observe_lease = AsyncMock()
        with self.assertRaises(ResearchBootstrapError) as caught:
            h.run()
        self.assertFalse(caught.exception.progress['cancelRequested'])
        self.assertFalse(any(path.endswith('/cancel') for _, path, _, _ in h.calls))
        h.store.request_cancel.assert_not_called()
        h.runtime.observe_lease.assert_not_awaited()
        h.runtime.submit.assert_not_awaited()


class CleanupOriginalTests(unittest.TestCase):
    def test_actual_stop_only_runtime_route_before_close_never_submit(self):
        from agent_factory.research_bootstrap_controller import cleanup_original
        h = Harness()
        h.runtime._original = Mock(return_value={'task_id': 'original-task', 'owner_id': 'alice',
            'native_run_id': 'original-run', 'lease_id': 'original-lease'})
        h.runtime.observe_lease = AsyncMock(return_value=h.lease)
        result = cleanup_original(h.state, 'alice', 'original-task', runtime=h.runtime,
            call_async=lambda fn: asyncio.run(fn()), clock=lambda: h.now, sleep=h.sleep)
        self.assertTrue(result['cleanupConfirmed'])
        h.store.request_cancel.assert_called_once_with('original-task')
        h.runtime.observe_lease.assert_awaited_once_with('original-lease')
        h.runtime.submit.assert_not_awaited()

    def test_unknown_or_wrong_original_identity_never_claims_cleanup(self):
        from agent_factory.research_bootstrap_controller import cleanup_original
        for wrong_owner in (False, True):
            h = Harness()
            h.runtime._original = Mock(return_value={'task_id': 'original-task',
                'owner_id': 'bob' if wrong_owner else 'alice', 'native_run_id': 'original-run', 'lease_id': 'original-lease'})
            h.runtime.observe_lease = AsyncMock(return_value={**h.lease, 'state': 'UNKNOWN', 'capacityHeld': True})
            result = cleanup_original(h.state, 'alice', 'original-task', runtime=h.runtime,
                call_async=lambda fn: asyncio.run(fn()), timeout_seconds=.25, clock=lambda: h.now, sleep=h.sleep)
            self.assertFalse(result['cleanupConfirmed'])
            if wrong_owner:
                h.runtime.observe_lease.assert_not_awaited()
            else:
                self.assertGreater(h.runtime.observe_lease.await_count, 0)
            h.runtime.submit.assert_not_awaited()
