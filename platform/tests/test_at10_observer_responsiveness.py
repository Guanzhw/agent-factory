"""AT10 regression: current authority must not starve native timers or launch work."""
import asyncio
from contextlib import contextmanager
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from agent_factory.lifecycle_observer import FactoryLifecycleObserver


class ObserverResponsivenessTests(unittest.IsolatedAsyncioTestCase):
    def fixture(self):
        task = {'id': 'synthetic-root', 'owner_id': 'alice', 'cancel_requested': False}
        lock_threads = []

        @contextmanager
        def root_lock(_root):
            entered = threading.get_ident()
            lock_threads.append(entered)
            try:
                yield
            finally:
                self.assertEqual(threading.get_ident(), entered, 'Root lock must release on its owning thread')

        store = Mock()
        store.task.side_effect = lambda *_: task.copy()
        store.delegation = SimpleNamespace(_root_lock=root_lock)
        store.bridge = SimpleNamespace(submit=AsyncMock(), continue_run=AsyncMock())
        observer = FactoryLifecycleObserver(store, Mock(), Mock(), lambda: None)
        observer._group = Mock(side_effect=lambda _: ([task.copy()], []))
        observer._binding = Mock(return_value={'status': 'running'})
        observer._facts = Mock(return_value={'taskId': task['id'], 'stopped': False, 'unknown': False})
        observer._cancel_bound = AsyncMock()
        observer._mark_cancel = Mock(side_effect=lambda *_: task.update(cancel_requested=True))
        return observer, store, task, lock_threads

    async def test_slow_fresh_authority_allows_heartbeat_and_rechecks_next_observation(self):
        observer, store, task, lock_threads = self.fixture()
        heartbeat = threading.Event()
        calls = []
        main_thread = threading.get_ident()

        def fresh_authority(task, ticket):
            calls.append(threading.get_ident())
            # A deterministic handshake, not a latency benchmark: the loop must
            # advance while a synchronous authority transport is awaiting I/O.
            self.assertTrue(heartbeat.wait(1), 'Current-authority check blocked the native event loop')
            return 'current-authority-ended' if len(calls) == 2 else None

        observer._reason = fresh_authority

        async def pulse():
            await asyncio.sleep(0)
            heartbeat.set()

        pulse_task = asyncio.create_task(pulse())
        with patch('agent_factory.inference_wait.read', return_value=None):
            first = await observer.observe_root(task['id'])
            second = await observer.observe_root(task['id'])
        await pulse_task
        self.assertEqual(first['errors'], [], 'Authority heartbeat or binding check failed')
        self.assertEqual(second['errors'], [])
        self.assertEqual(first['requested'], [])
        self.assertEqual(second['requested'], [task['id']])
        self.assertEqual(len(calls), 2, 'Every observation must recheck current authority')
        self.assertTrue(all(thread != main_thread for thread in calls))
        self.assertTrue(all(thread != main_thread for thread in lock_threads))
        self.assertEqual(observer._cancel_bound.await_count, 1)  # type: ignore[attr-defined]
        store.bridge.submit.assert_not_awaited()
        store.bridge.continue_run.assert_not_awaited()
        self.assertTrue(task['cancel_requested'])

    async def test_cancelled_observation_never_dispatches_native_work(self):
        observer, store, task, _ = self.fixture()
        entered = threading.Event()
        release = threading.Event()
        finished = threading.Event()

        def fresh_authority(task, ticket):
            entered.set()
            try:
                if not release.wait(1):
                    raise AssertionError('Synchronous authority prevented cancellation delivery')
                return 'current-authority-ended'
            finally:
                finished.set()

        observer._reason = fresh_authority
        with patch('agent_factory.inference_wait.read', return_value=None):
            pending = asyncio.create_task(observer.observe_root(task['id']))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 1))
                pending.cancel()
                release.set()
                with self.assertRaises(asyncio.CancelledError):
                    await pending
                self.assertTrue(await asyncio.to_thread(finished.wait, 1))
            finally:
                release.set()
                if not pending.done():
                    pending.cancel()
                    await asyncio.gather(pending, return_exceptions=True)
        store.bridge.submit.assert_not_awaited()
        store.bridge.continue_run.assert_not_awaited()
        store.observed.assert_not_called()


if __name__ == '__main__':
    unittest.main()
