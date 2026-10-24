"""Bounded owner drains preserve original cleanup tasks and service identity."""
import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from agent_factory_research.assembly import research_lifespan
from agent_factory_research.autoresearch import AutoResearchService
from agent_factory_research.autoresearch_session_control import AutoResearchSessionControl
from agent_factory_research.remote_scientific_receiver import RemoteScientificReceiver
from agent_factory_research.services import services_for, release_services


class ResearchShutdownOwnerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tasks = []
        self.store = SimpleNamespace()

    async def asyncTearDown(self):
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        release_services(self.store)

    def pending(self):
        task = asyncio.create_task(asyncio.Event().wait())
        self.tasks.append(task)
        return task

    async def test_controller_close_covers_original_research_cleanup(self):
        original = self.pending()
        graph = services_for(self.store)
        graph.autoresearch = SimpleNamespace(cleanups={'original': original})
        control = AutoResearchSessionControl(self.store, None)
        done = await control.close(deadline=asyncio.get_running_loop().time() + .01)
        self.assertFalse(done)
        self.assertFalse(original.done())
        self.assertIs(graph, services_for(self.store))
        self.assertIs(graph.autoresearch.cleanups['original'], original)

    async def test_receiver_timeout_does_not_recancel_or_forget_original_drive(self):
        entered = asyncio.Event()
        release = asyncio.Event()
        async def drive():
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                await release.wait()
        task = asyncio.create_task(drive())
        self.tasks.append(task)
        await entered.wait()
        receiver = RemoteScientificReceiver.__new__(RemoteScientificReceiver)
        receiver._closing = False
        receiver._drives = {'original-receipt': task}
        receiver._read = Mock(side_effect=AssertionError('pending drive must retain durable intent'))
        self.assertFalse(await receiver.close(deadline=asyncio.get_running_loop().time() + .01))
        self.assertIs(receiver._drives['original-receipt'], task)
        self.assertFalse(task.done())
        receiver._read.assert_not_called()
        release.set()
        await task

    async def test_service_close_includes_cleanup_created_by_original_execution(self):
        service = AutoResearchService.__new__(AutoResearchService)
        service.closed = False
        service.executions = {}
        service.cleanups = {}
        entered = asyncio.Event()
        async def execute():
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                service.cleanups['original'] = self.pending()
            finally:
                service.executions.pop('original', None)
        task = asyncio.create_task(execute())
        self.tasks.append(task)
        service.executions['original'] = task
        await entered.wait()
        self.assertFalse(await service.close(deadline=asyncio.get_running_loop().time() + .01))
        self.assertTrue(service.closed)
        self.assertFalse(service.cleanups['original'].done())
        with self.assertRaisesRegex(ValueError, 'RESEARCH_SERVICE_CLOSED'):
            await service.execute(None)

    async def test_completed_owners_close_cleanly_at_expired_deadline(self):
        service = AutoResearchService.__new__(AutoResearchService)
        service.closed = False
        service.executions = {}
        service.cleanups = {}
        self.assertTrue(await service.close(deadline=0))
        control = AutoResearchSessionControl(self.store, None)
        self.assertTrue(await control.close(deadline=0))
        receiver = RemoteScientificReceiver.__new__(RemoteScientificReceiver)
        receiver._drives = {}
        self.assertTrue(await receiver.close(deadline=0))

    async def test_research_startup_requires_fatal_process_policy(self):
        app = SimpleNamespace(state=SimpleNamespace(factory={'store': self.store}))
        with self.assertRaisesRegex(RuntimeError, 'RESEARCH_SHUTDOWN_PROCESS_POLICY_REQUIRED'):
            async with research_lifespan(app):
                self.fail('Research started without its process shutdown policy')
