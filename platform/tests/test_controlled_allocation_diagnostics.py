"""Pure observations for the controlled fixture; no database or process launch."""
import asyncio
from datetime import datetime, timedelta, timezone
import json
import unittest
from unittest.mock import Mock, patch

from fastapi import HTTPException

from controlled_remote_process_worker import (
    AllocationDiagnostics, process_identity_observation, provider_observations, safe_allocation_error,
)


def lease():
    return {'id': 'synthetic-lease', 'localTaskId': 'synthetic-task', 'nativeRunId': 'synthetic-run',
            'deadlineAt': (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()}


class AllocationDiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    async def test_return_and_each_callback_invocation_are_transparent(self):
        diagnostics, original_lease, token = AllocationDiagnostics(), lease(), object()
        callback = Mock(return_value=token)

        async def original(actual, *, before_effect):
            self.assertIs(actual, original_lease)
            self.assertIs(before_effect(), token)
            self.assertIs(before_effect(), token)
            return token

        self.assertIs(await diagnostics.allocate(original, original_lease, callback), token)
        self.assertEqual(callback.call_count, 2)  # Once per actual provider callback, not once per allocation.
        records = diagnostics.snapshot()['records']
        self.assertEqual([row['phase'] for row in records], [
            'ALLOCATE_ENTRY', 'BEFORE_EFFECT_ENTRY', 'BEFORE_EFFECT_RETURNED',
            'BEFORE_EFFECT_ENTRY', 'BEFORE_EFFECT_RETURNED', 'ALLOCATE_RETURNED'])
        self.assertTrue(all(row['leaseId'] == original_lease['id'] for row in records))
        self.assertTrue(all(row['deadlineElapsed'] is True for row in records))

    async def test_callback_denial_is_same_exception_and_original_is_called_once(self):
        diagnostics = AllocationDiagnostics()
        error = HTTPException(409, 'Canceled, terminal or expired work cannot allocate new effects')
        callback, calls = Mock(side_effect=error), []

        async def original(actual, *, before_effect):
            calls.append(actual)
            before_effect()
            self.fail('Denied effect continued')

        original_lease = lease()
        with self.assertRaises(HTTPException) as caught:
            await diagnostics.allocate(original, original_lease, callback)
        self.assertIs(caught.exception, error)
        callback.assert_called_once_with()
        self.assertEqual(calls, [original_lease])
        records = diagnostics.snapshot()['records']
        self.assertEqual([row['phase'] for row in records], [
            'ALLOCATE_ENTRY', 'BEFORE_EFFECT_ENTRY', 'BEFORE_EFFECT_ERROR', 'ALLOCATE_ERROR'])
        for row in records[-2:]:
            self.assertEqual(row['errorCode'], 'ADMISSION_WORK_ENDED')
            self.assertEqual(row['httpStatus'], 409)
            self.assertEqual(row['errorCategory'], 'HTTP_REJECTION')
            self.assertTrue(row['deadlineElapsed'])

    async def test_provider_error_and_cancellation_identity_are_preserved(self):
        for error in (ValueError('synthetic private payload'), asyncio.CancelledError()):
            with self.subTest(kind=type(error).__name__):
                diagnostics, callback = AllocationDiagnostics(), Mock()

                async def original(actual, *, before_effect):
                    raise error

                with self.assertRaises(type(error)) as caught:
                    await diagnostics.allocate(original, lease(), callback)
                self.assertIs(caught.exception, error)
                callback.assert_not_called()
                self.assertEqual([row['phase'] for row in diagnostics.snapshot()['records']],
                                 ['ALLOCATE_ENTRY', 'ALLOCATE_ERROR'])
                self.assertNotIn('private payload', json.dumps(diagnostics.snapshot()))

    def test_records_are_bounded_and_snapshot_is_detached(self):
        diagnostics, original_lease = AllocationDiagnostics(), lease()
        for _ in range(130):
            diagnostics.record(original_lease, 'ALLOCATE_ENTRY')
        first = diagnostics.snapshot()
        self.assertEqual(len(first['records']), 128)
        self.assertEqual(first['dropped'], 2)
        first['records'][0]['leaseId'] = 'changed'
        self.assertEqual(diagnostics.snapshot()['records'][0]['leaseId'], original_lease['id'])

    def test_unknown_details_and_error_string_are_never_disclosed(self):
        class TrapError(ValueError):
            def __str__(self):
                raise AssertionError('Diagnostic must not stringify exceptions')

        for error in (HTTPException(409, '/private/token?body=synthetic-secret'),
                      HTTPException(503, {'detail': 'synthetic-secret'}), TrapError('synthetic-secret')):
            result = safe_allocation_error(error)
            self.assertIsNone(result['errorCode'])
            self.assertNotIn('synthetic-secret', json.dumps(result))
            self.assertNotIn('/private', json.dumps(result))
            self.assertIn(result['errorType'], {'HTTPException', 'ValueError'})

    def test_provider_absence_and_finite_record_fields_are_distinct(self):
        original_lease = lease()
        self.assertEqual(provider_observations([original_lease], []),
                         [{'leaseId': original_lease['id'], 'providerRowPresent': False}])
        row = {'id': original_lease['id'], 'body': {'state': 'FAILED', 'executionStatus': 'LIMIT_STOPPED',
            'exitCode': -9, 'allStopped': True, 'released': True,
            'stopKind': 'original-root-reaped-and-no-live-process-group-members',
            'processPin': {'private': 'not emitted'}, 'journalIdentity': [1, 2]}}
        result = provider_observations([original_lease], [row])[0]
        self.assertTrue(result['providerRowPresent'])
        self.assertEqual(result['executionStatus'], 'LIMIT_STOPPED')
        self.assertEqual(result['exitCode'], -9)
        self.assertTrue(result['allStopped'])
        self.assertTrue(result['released'])
        self.assertTrue(result['processPinPresent'])
        self.assertNotIn('not emitted', json.dumps(result))
        row['body'].update(state='private-state', executionStatus='private-status', exitCode=True,
                           stopKind='private-kind', allStopped=1, released=1)
        result = provider_observations([original_lease], [row])[0]
        self.assertEqual(result['state'], 'unrecognized')
        self.assertEqual(result['executionStatus'], 'unrecognized')
        self.assertIsNone(result['exitCode'])
        self.assertIsNone(result['stopKind'])
        self.assertFalse(result['allStopped'])
        self.assertFalse(result['released'])

    def test_unreadable_birth_is_unknown_never_positive_stop(self):
        self.assertEqual(process_identity_observation(None),
                         {'currentState': 'UNPINNED', 'matchesOriginal': None})
        with patch('controlled_remote_process_worker.birth', return_value=None):
            self.assertEqual(process_identity_observation({'pid': 123}),
                             {'currentState': 'UNKNOWN', 'matchesOriginal': None})
        pin = {'pid': 123, 'start': '456', 'group': 123, 'bootId': '00000000-0000-0000-0000-000000000001'}
        with patch('controlled_remote_process_worker.birth', return_value={**pin, 'state': 'Z'}):
            self.assertEqual(process_identity_observation(pin),
                             {'currentState': 'Z', 'matchesOriginal': True})
