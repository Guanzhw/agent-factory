"""Contention preserves original custody without inventing stop evidence."""
import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

from agent_factory.local_compute import LocalComputeBusy
from agent_factory.process_runtime import ProcessRuntimeService


class ObservationContention(unittest.IsolatedAsyncioTestCase):
    def fixture(self, error):
        target = object()
        original = {'id': 'original', 'state': 'UNKNOWN', 'capacityHeld': True}
        latest = {**original, 'providerJobId': 'original-job'}
        runtime = SimpleNamespace(
            _custody=Mock(side_effect=[(original, target, {}, {}), (latest, target, {}, {})]),
            _reason=Mock(return_value='TASK_CANCEL_REQUESTED'),
            _read=AsyncMock(side_effect=error), resources=Mock())
        return runtime, latest

    async def test_busy_read_retains_latest_original_and_does_not_repeat_effect(self):
        runtime, latest = self.fixture(LocalComputeBusy('LOCAL_COMPUTE_UNCONFIRMED'))
        result = await ProcessRuntimeService.observe_lease(runtime, 'original')
        self.assertIs(result, latest)
        runtime._read.assert_awaited_once_with('original')
        self.assertEqual(runtime.resources.mock_calls, [])
        self.assertNotIn('snapshotAt', result)
        self.assertNotIn('stopEvidence', result)

    async def test_corruption_and_cancellation_are_not_contention(self):
        for error in (ValueError('LOCAL_COMPUTE_UNCONFIRMED'), asyncio.CancelledError()):
            runtime, _ = self.fixture(error)
            with self.assertRaises(type(error)):
                await ProcessRuntimeService.observe_lease(runtime, 'original')
            self.assertEqual(runtime._custody.call_count, 1)
            self.assertEqual(runtime.resources.mock_calls, [])

    async def test_changed_target_during_busy_read_fails_closed(self):
        from fastapi import HTTPException
        runtime, latest = self.fixture(LocalComputeBusy())
        runtime._custody.side_effect = [({'state': 'UNKNOWN'}, object(), {}, {}),
                                       (latest, object(), {}, {})]
        with self.assertRaises(HTTPException):
            await ProcessRuntimeService.observe_lease(runtime, 'original')
        self.assertEqual(runtime.resources.mock_calls, [])
