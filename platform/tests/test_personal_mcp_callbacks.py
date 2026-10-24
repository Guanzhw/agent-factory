"""Deterministic callback custody at queued, dequeued and running boundaries.

Gates/Futures order operations; bounded waits only escape fixture failures.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
import threading
import unittest

from agent_factory.personal_mcp import _InvocationState
from agent_factory.personal_tool_contract import ToolInvocation


def publish(loop, signal, value=None):
    def deliver():
        if not signal.done():
            signal.set_result(value)
    loop.call_soon_threadsafe(deliver)


async def complete(future):
    """Observe concurrent completion without cancelling that Future on timeout."""
    loop = asyncio.get_running_loop()
    signal = loop.create_future()
    future.add_done_callback(lambda finished: publish(loop, signal, finished))
    return await asyncio.wait_for(signal, 5)


async def arrived(signal):
    return await asyncio.wait_for(signal, 5)


def wait_gate(gate):
    if not gate.wait(5):
        raise TimeoutError('SYNTHETIC_CALLBACK_GATE_NOT_RELEASED')


class ObservedExecutor(ThreadPoolExecutor):
    """Expose submission acknowledgement without assuming a scheduler delay."""
    def __init__(self):
        super().__init__(max_workers=1, thread_name_prefix='mcp-callback-regression')
        self.submissions = asyncio.Queue()

    def submit(self, function, /, *args, **kwargs):
        future = super().submit(function, *args, **kwargs)
        # The tests and loop.run_in_executor submit from the event-loop thread.
        self.submissions.put_nowait(future)
        return future


class BeforeWrapperExecutor(ObservedExecutor):
    """Future is RUNNING, but the production to_thread wrapper has not entered."""
    def __init__(self, loop, entered, release):
        super().__init__()
        self.loop, self.entered, self.release = loop, entered, release

    def submit(self, function, /, *args, **kwargs):
        def before_wrapper():
            publish(self.loop, self.entered)
            wait_gate(self.release)
            return function(*args, **kwargs)
        return super().submit(before_wrapper)


class RejectedExecutor(ThreadPoolExecutor):
    def __init__(self, failure):
        super().__init__(max_workers=1)
        self.failure = failure
        self.attempts = 0

    def submit(self, function, /, *args, **kwargs):
        self.attempts += 1
        raise self.failure


class CallbackCustodyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.executors = []
        self.releases = []
        self.pending = []

    async def asyncTearDown(self):
        # Always release threads first, even after a failed assertion. No
        # worker can remain indefinitely blocked while its executor is joined.
        for release in self.releases:
            release.set()
        for pending in self.pending:
            if not pending.done():
                pending.cancel()
        try:
            if self.pending:
                await asyncio.wait_for(asyncio.gather(*self.pending, return_exceptions=True), 5)
        finally:
            for executor in self.executors:
                executor.shutdown(wait=True, cancel_futures=True)

    def executor(self, value=None):
        value = value if value is not None else ObservedExecutor()
        self.executors.append(value)
        asyncio.get_running_loop().set_default_executor(value)
        return value

    def gate(self):
        value = threading.Event()
        self.releases.append(value)
        return value

    def state(self, callback):
        return _InvocationState(ToolInvocation(
            owner_id='synthetic-alice', connection_ref='synthetic-connection',
            connection_revision='1', call_id='synthetic-call', arguments={},
            run_context=None, check_authorized=callback, resolve_credential=lambda: None,
        ))

    def start(self, state, callback):
        pending = asyncio.create_task(state.checked_callback(callback))
        self.pending.append(pending)
        return pending

    async def cancel(self, pending):
        pending.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await pending

    async def test_queued_future_cancel_acknowledges_never_started_callback(self):
        loop = asyncio.get_running_loop()
        executor = self.executor()
        occupied = loop.create_future()
        release = self.gate()
        calls = []

        def occupy():
            publish(loop, occupied)
            wait_gate(release)

        def callback():
            calls.append('called')

        blocker = executor.submit(occupy)
        self.assertIs(await arrived(executor.submissions.get()), blocker)
        await arrived(occupied)
        state = self.state(callback)
        pending = self.start(state, callback)
        queued = await arrived(executor.submissions.get())
        self.assertFalse(queued.running())
        await self.cancel(pending)
        await complete(queued)
        stopped_after_cancel = state.stopped_before_dispatch()
        self.assertTrue(queued.cancelled(), 'The executor must acknowledge this queued cancellation')
        release.set()
        await complete(blocker)
        # Drain the cancelled work item's queue position before checking calls.
        barrier = executor.submit(lambda: None)
        await complete(barrier)
        self.assertEqual(calls, [])
        self.assertTrue(stopped_after_cancel)
        self.assertTrue(state.stopped_before_dispatch())
        self.assertEqual(len(state.callbacks_finished), 1)
        self.assertTrue(state.callbacks_finished[0].is_set())

    async def test_dequeued_worker_cannot_start_callback_after_stop_acknowledgement(self):
        loop = asyncio.get_running_loop()
        entered = loop.create_future()
        release = self.gate()
        executor = self.executor(BeforeWrapperExecutor(loop, entered, release))
        calls = []

        def callback():
            calls.append('called')

        state = self.state(callback)
        pending = self.start(state, callback)
        dequeued = await arrived(executor.submissions.get())
        await arrived(entered)
        self.assertTrue(dequeued.running())
        self.assertEqual(calls, [])
        await self.cancel(pending)
        stopped_before_release = state.stopped_before_dispatch()
        self.assertFalse(dequeued.cancelled(), 'A running executor Future cannot be cancelled')
        release.set()
        await complete(dequeued)
        # This catches a false fix that merely sets finished on cancellation:
        # such a fix would still run callback after the wrapper gate opens.
        self.assertEqual(calls, [])
        self.assertTrue(stopped_before_release)
        self.assertTrue(state.stopped_before_dispatch())

    async def test_running_callback_retains_custody_until_its_real_finally(self):
        loop = asyncio.get_running_loop()
        executor = self.executor()
        entered = loop.create_future()
        release = self.gate()
        finished = threading.Event()

        def callback():
            publish(loop, entered)
            try:
                wait_gate(release)
            finally:
                finished.set()

        state = self.state(callback)
        pending = self.start(state, callback)
        running = await arrived(executor.submissions.get())
        await arrived(entered)
        self.assertTrue(running.running())
        await self.cancel(pending)
        self.assertFalse(finished.is_set())
        self.assertFalse(state.callbacks_finished[0].is_set())
        self.assertFalse(state.stopped_before_dispatch())
        release.set()
        await complete(running)
        self.assertTrue(finished.is_set())
        self.assertTrue(state.callbacks_finished[0].is_set())
        self.assertTrue(state.stopped_before_dispatch())

    async def test_submission_failure_propagates_and_cannot_leave_phantom_callback(self):
        failure = RuntimeError('SYNTHETIC_EXECUTOR_REJECTED')
        executor = self.executor(RejectedExecutor(failure))
        calls = []

        def callback():
            calls.append('called')

        state = self.state(callback)
        with self.assertRaises(RuntimeError) as raised:
            await state.checked_callback(callback)
        self.assertIs(raised.exception, failure)
        self.assertEqual(executor.attempts, 1)
        self.assertEqual(calls, [])
        self.assertEqual(len(state.callbacks_finished), 1)
        self.assertTrue(state.callbacks_finished[0].is_set())
        self.assertTrue(state.stopped_before_dispatch())

    async def test_return_exception_and_context_propagation_remain_unchanged(self):
        self.executor()
        scope = ContextVar('synthetic-callback-scope', default=None)
        marker = object()
        token = scope.set(marker)
        try:
            def success():
                return scope.get()

            state = self.state(success)
            self.assertIs(await state.checked_callback(success), marker)
            self.assertTrue(state.callbacks_finished[0].is_set())
            self.assertTrue(state.stopped_before_dispatch())

            failure = ValueError('SYNTHETIC_CALLBACK_REJECTED')

            def reject():
                raise failure

            state = self.state(reject)
            with self.assertRaises(ValueError) as raised:
                await state.checked_callback(reject)
            self.assertIs(raised.exception, failure)
            self.assertTrue(state.callbacks_finished[0].is_set())
            self.assertTrue(state.stopped_before_dispatch())
        finally:
            scope.reset(token)


if __name__ == '__main__':
    unittest.main()
