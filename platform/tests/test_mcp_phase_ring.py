"""Deterministic phase-order calibration; no PostgreSQL, sockets or providers."""
import asyncio
from contextlib import asynccontextmanager
import gc
from concurrent.futures import ThreadPoolExecutor
import contextvars
from functools import partial
from types import SimpleNamespace
import threading
import unittest
from unittest.mock import patch

from agent_factory.personal_mcp import _InvocationState
from test_personal_mcp_capacity_postgres import MCPPhaseRing


class MCPPhaseRingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Own and join the calibration executor explicitly; do not replace the
        # runner's default executor or retain work across isolated test loops.
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.addCleanup(self.executor.shutdown, wait=True)
        async def to_thread(callback, *args, **kwargs):
            invoke = partial(contextvars.copy_context().run, callback, *args, **kwargs)
            return await asyncio.get_running_loop().run_in_executor(self.executor, invoke)
        self.submission = patch('asyncio.to_thread', new=to_thread)
        self.submission.start()
        self.addCleanup(self.submission.stop)

    def state(self, callback):
        return _InvocationState(SimpleNamespace(run_context=SimpleNamespace(run_id='native-fixture'),
            call_id='call-fixture', check_authorized=callback))

    async def scheduled(self, ring):
        async with asyncio.timeout(2):
            while not ring.snapshot()['events']:
                await asyncio.sleep(0)

    async def test_cancelled_before_executor_entry_has_no_thread_phase(self):
        executor = self.executor
        release, entered = threading.Event(), threading.Event()
        def occupy():
            entered.set()
            release.wait(2)
        occupied = executor.submit(occupy)
        self.assertTrue(entered.wait(2))
        ring = MCPPhaseRing()
        calls = []
        def callback():
            calls.append('unexpected')
        state = self.state(callback)
        pending = asyncio.create_task(ring.checked(_InvocationState.checked_callback, state, callback))
        try:
            await self.scheduled(ring)
            pending.cancel()
            with self.assertRaises(asyncio.CancelledError): await pending
            self.assertEqual([e['phase'] for e in ring.snapshot()['events']],
                             ['callback_schedule', 'callback_await_exit'])
            self.assertEqual(ring.snapshot()['events'][-1]['status'], 'cancelled')
            self.assertTrue(all(e.is_set() for e in state.callbacks_finished))
        finally:
            release.set()
            await asyncio.wrap_future(occupied)
        self.assertEqual(calls, [])

    async def test_running_callback_exit_can_follow_cancelled_await(self):
        loop = asyncio.get_running_loop()
        entered, finished = asyncio.Event(), asyncio.Event()
        release = threading.Event()
        def callback():
            loop.call_soon_threadsafe(entered.set)
            try:
                release.wait(2)
            finally:
                loop.call_soon_threadsafe(finished.set)
        ring, state = MCPPhaseRing(), self.state(callback)
        pending = asyncio.create_task(ring.checked(_InvocationState.checked_callback, state, callback))
        try:
            await asyncio.wait_for(entered.wait(), 2)
            pending.cancel()
            with self.assertRaises(asyncio.CancelledError): await pending
            self.assertEqual([e['phase'] for e in ring.snapshot()['events']],
                ['callback_schedule', 'callback_thread_enter', 'callback_await_exit'])
            self.assertFalse(all(e.is_set() for e in state.callbacks_finished))
        finally:
            release.set()
            await asyncio.wait_for(finished.wait(), 2)
        async with asyncio.timeout(2):
            while not all(e.is_set() for e in state.callbacks_finished): await asyncio.sleep(0)
        self.assertEqual(ring.snapshot()['events'][-1]['phase'], 'callback_thread_exit')

    async def test_finished_callback_and_delayed_await_return_are_distinct(self):
        # A continuation gate calibrates the reporting boundary without blocking
        # the event loop or claiming it reproduces any real scheduling slowdown.
        finished, resume = asyncio.Event(), asyncio.Event()
        async def delayed_original(state, callback):
            result = await _InvocationState.checked_callback(state, callback)
            finished.set()
            await resume.wait()
            return result
        def callback():
            return 'opaque-result-never-recorded'
        ring = MCPPhaseRing()
        pending = asyncio.create_task(ring.checked(delayed_original, self.state(callback), callback))
        try:
            await asyncio.wait_for(finished.wait(), 2)
            self.assertEqual([e['phase'] for e in ring.snapshot()['events']],
                ['callback_schedule', 'callback_thread_enter', 'callback_thread_exit'])
        finally:
            resume.set()
        self.assertEqual(await pending, 'opaque-result-never-recorded')
        self.assertEqual(ring.snapshot()['events'][-1]['status'], 'returned')
        self.assertNotIn('opaque-result', str(ring.snapshot()))

    async def test_ring_is_bounded_and_has_loss_count(self):
        ring = MCPPhaseRing(limit=2)
        for _ in range(5): ring.record('fixture_phase')
        snapshot = ring.snapshot()
        self.assertEqual((snapshot['eventsSeen'], snapshot['eventsRetained']), (5, 2))
        self.assertEqual([e['sequence'] for e in snapshot['events']], [4, 5])

    async def test_native_job_identity_uses_original_id_and_attempt(self):
        ring = MCPPhaseRing()
        identity = ring.native_identity({'id': 'original-run', 'status': 'running',
                                         'attempt': 2, 'worker_id': 'original-worker'})
        ring.record('native_observed', run_id=identity[0], status=identity[1],
                    attempt=identity[2], worker_id=identity[3])
        event = ring.snapshot()['events'][0]
        self.assertEqual((event['runId'], event['attempt'], event['workerId']),
                         ('original-run', 2, 'original-worker'))

    async def test_lifecycle_wrappers_preserve_calls_and_remove_gc_callback(self):
        from agno.os.job_queue import QueueWorker
        from agno.run import concurrency
        calls = []
        @asynccontextmanager
        async def original_slot(*args, **kwargs):
            calls.append(('slot', args, kwargs))
            yield
        async def original_execute(worker, job):
            calls.append(('execute', job['id']))
            async with concurrency.background_run_slot(run_id=job['id']):
                return 'not-logged'
        ring = MCPPhaseRing()
        before = tuple(gc.callbacks)
        with patch.object(QueueWorker, '_execute_claimed', new=original_execute), \
                patch.object(concurrency, 'background_run_slot', new=original_slot):
            with ring.lifecycle_trace():
                self.assertEqual(await QueueWorker._execute_claimed(
                    SimpleNamespace(worker_id='worker'), {'id': 'run', 'attempt': 1}), 'not-logged')
                # Invoke only the recorder: calibration never forces collection.
                added = [c for c in gc.callbacks if c not in before]
                self.assertEqual(len(added), 1)
                added[0]('start', {'generation': 2})
                added[0]('stop', {'generation': 2})
            self.assertIs(QueueWorker._execute_claimed, original_execute)
            self.assertIs(concurrency.background_run_slot, original_slot)
        self.assertEqual(tuple(gc.callbacks), before)
        phases = [e['phase'] for e in ring.snapshot()['events']]
        self.assertEqual(phases, ['claim_execute_enter', 'slot_wait', 'slot_enter',
                                'slot_scope_exit', 'claim_execute_exit', 'gc_start', 'gc_stop'])
        self.assertEqual(calls, [('execute', 'run'), ('slot', (), {'run_id': 'run'})])
        self.assertNotIn('not-logged', str(ring.snapshot()))
