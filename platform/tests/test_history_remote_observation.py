"""Remote observation cannot monopolize local cleanup or outlive its owner."""
import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

from agent_factory.lifecycle_observer import FactoryLifecycleObserver


class BlockedRemote:
    def __init__(self):
        self.entered = asyncio.Event()
        self.cancelled = asyncio.Event()
        self.release_cleanup = asyncio.Event()
        self.finished = asyncio.Event()
        self.calls = 0

    async def observe_pending(self, *, limit):
        self.calls += 1
        self.entered.set()
        try:
            await asyncio.Future()
        finally:
            self.cancelled.set()
            await self.release_cleanup.wait()
            self.finished.set()


class RemoteObservationTests(unittest.IsolatedAsyncioTestCase):
    def make_observer(self, remote):
        task = {'id': 'local-root', 'owner_id': 'synthetic-owner'}
        store = SimpleNamespace(
            handoff_client=remote, delegation=object(),
            sql=Mock(return_value=[{'id': task['id']}]),
            task=Mock(return_value=task),
        )
        observer = FactoryLifecycleObserver(store, None, None, lambda: None)
        # Replace only the native/DB boundary facts; tick and observe_root run
        # unchanged, including the awaited original cancellation phase.
        observer._request_cleanup = Mock(return_value=({task['id']: task}, []))
        observer._cancel_bound = AsyncMock()
        observer._observe_stopped = Mock(return_value={task['id']: {'groupStopped': False}})
        observer._observe_summaries = Mock()

        async def cleanup():
            remote.release_cleanup.set()
            await asyncio.wait_for(observer.stop(), 2)

        self.addAsyncCleanup(cleanup)
        return observer

    async def test_blocked_remote_does_not_delay_local_cancel_or_spawn_duplicates(self):
        remote = BlockedRemote()
        observer = self.make_observer(remote)
        await asyncio.wait_for(observer.tick(), 2)
        await asyncio.wait_for(remote.entered.wait(), 2)
        for _ in range(3):
            result = await asyncio.wait_for(observer.tick(), 2)
            self.assertEqual(result['groups'][0]['requested'], ['local-root'])
            self.assertFalse(result['groups'][0]['allStopped'])
        self.assertEqual(observer._cancel_bound.await_count, 4)
        self.assertEqual(remote.calls, 1)
        self.assertFalse(remote.cancelled.is_set())

    async def test_stop_cancels_remote_and_joins_actual_cleanup(self):
        remote = BlockedRemote()
        observer = self.make_observer(remote)
        await asyncio.wait_for(observer.tick(), 2)
        await asyncio.wait_for(remote.entered.wait(), 2)
        stopping = asyncio.create_task(observer.stop())
        try:
            await asyncio.wait_for(remote.cancelled.wait(), 2)
            self.assertFalse(stopping.done())
            self.assertFalse(remote.finished.is_set())
            remote.release_cleanup.set()
            await asyncio.wait_for(stopping, 2)
            self.assertTrue(remote.finished.is_set())
            await asyncio.wait_for(observer.tick(), 2)
            self.assertEqual(remote.calls, 1, 'A stopped observer must not restart remote work')
        finally:
            remote.release_cleanup.set()
            await asyncio.gather(stopping, return_exceptions=True)

    async def test_remote_batch_deadline_cancels_pending_io_without_settling_local_work(self):
        remote = BlockedRemote()
        remote.release_cleanup.set()
        observer = self.make_observer(remote)
        await asyncio.wait_for(observer.tick(), 2)
        await asyncio.wait_for(remote.entered.wait(), 2)
        # Exercise the real five-second deadline, not a mocked timeout context.
        await asyncio.wait_for(remote.finished.wait(), 7)
        result = await asyncio.wait_for(observer.tick(), 2)
        self.assertEqual(result['remoteObservations']['handoff_client']['errors'],
                         [{'errorType': 'TimeoutError'}])
        self.assertFalse(result['groups'][0]['allStopped'])
        self.assertEqual(observer._cancel_bound.await_count, 2)


if __name__ == '__main__':
    unittest.main()
