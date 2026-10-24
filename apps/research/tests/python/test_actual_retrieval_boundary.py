"""Offline serialization and opt-in Linux containment; no public network request."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

from agent_factory_research.orx_pins import approved_pin
from agent_factory_research.orx_retrieval import TaskLinuxRetrievalProvider
from agent_factory_research.orx_linux import PYTHON_BINARY
from agent_factory_research.openresearch import BinaryPin, REVISION, VERSION


class RetrievalSerializationTests(unittest.IsolatedAsyncioTestCase):
    async def test_same_task_retrieval_waits_and_subsequent_call_runs(self):
        # Keep the real provider, public discover/preflight and execution path;
        # only the container and OS process are controlled offline fixtures.
        with tempfile.TemporaryDirectory(prefix='factory-retrieval-serial-') as directory:
            scope = Path(directory)
            binary = scope / 'fixture-orx'
            binary.write_bytes(b'controlled executable bytes; never launched')
            pin = BinaryPin(REVISION, VERSION, hashlib.sha256(binary.read_bytes()).hexdigest())
            entered, release, second_attempted = asyncio.Event(), asyncio.Event(), asyncio.Event()
            retrievals, feeders = [], []
            active, maximum = 0, 0

            async def spawn(adapter, argv):
                nonlocal active, maximum
                stdout, stderr = asyncio.StreamReader(), asyncio.StreamReader()
                stderr.feed_eof()
                retrieval = 'discover' in argv
                if retrieval:
                    query = argv[argv.index('discover') + 2]
                    retrievals.append(query)
                    active += 1
                    maximum = max(maximum, active)
                    if query == 'first':
                        entered.set()
                        async def finish_first():
                            await release.wait()
                            stdout.feed_data(b'[]')
                            stdout.feed_eof()
                        feeders.append(asyncio.create_task(finish_first()))
                    else:
                        stdout.feed_data(b'[]')
                        stdout.feed_eof()
                else:
                    stdout.feed_data(f'orx {VERSION}'.encode())
                    stdout.feed_eof()

                async def wait():
                    nonlocal active
                    if retrieval:
                        active -= 1
                    return 0
                return Mock(stdout=stdout, stderr=stderr, returncode=0, wait=AsyncMock(side_effect=wait))

            with patch('agent_factory_research.orx_retrieval.approved_pin', return_value=pin), \
                 patch('agent_factory_research.orx_retrieval.TaskLinuxContainer'), \
                 patch('agent_factory_research.orx_retrieval.LinuxRetrievalAdapter._spawn', spawn):
                provider = TaskLinuxRetrievalProvider(binary)
                kwargs = dict(owner_id='synthetic-owner', task_id=str(uuid4()), scope=scope,
                              authorize=lambda _: True, pin=pin, environment={})
                first = provider.create_retrieval_adapter(**kwargs)
                second = provider.create_retrieval_adapter(**kwargs)

                async def next_retrieval():
                    # The coroutine continues into discover until its first
                    # suspension, so this handshake observes a real attempt.
                    second_attempted.set()
                    return await second.discover('second')

                pending = [asyncio.create_task(first.discover('first'))]
                try:
                    await asyncio.wait_for(entered.wait(), 2)
                    pending.append(asyncio.create_task(next_retrieval()))
                    await asyncio.wait_for(second_attempted.wait(), 2)
                    self.assertEqual(retrievals, ['first'])
                    self.assertFalse(pending[1].done())
                    release.set()
                    self.assertEqual(await asyncio.wait_for(asyncio.gather(*pending), 2), [[], []])
                    self.assertEqual(await asyncio.wait_for(second.discover('after'), 2), [])
                    self.assertEqual(retrievals, ['first', 'second', 'after'])
                    self.assertEqual(maximum, 1)
                    self.assertEqual(active, 0)
                finally:
                    release.set()
                    await asyncio.gather(*pending, *feeders, return_exceptions=True)


@unittest.skipUnless(os.getenv('FACTORY_ORX_LINUX_CONTAINER') == '1' and os.getenv('FACTORY_ORX_BINARY'),
                     'Requires approved Linux binary and existing Docker runtime')
class ActualRetrievalBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_shared_namespace_and_independent_wall_guardian_stops_sleeping_descendant(self):
        with tempfile.TemporaryDirectory(prefix='factory-retrieval-wall-') as directory:
            task = str(uuid4())
            provider = TaskLinuxRetrievalProvider(Path(os.environ['FACTORY_ORX_BINARY']))
            bounds = {'timeoutSeconds': 3, 'outputBytes': 32768, 'memoryBytes': 134217728,
                      'cpuPercent': 25, 'cpuSeconds': 2, 'maxProcesses': 16}
            kwargs = dict(owner_id='owned-retrieval-boundary', task_id=task, scope=Path(directory),
                authorize=lambda _: True, pin=approved_pin(), max_output_bytes=32768,
                command_timeout=3, environment=bounds)
            first = provider.create_retrieval_adapter(**kwargs)
            second = provider.create_retrieval_adapter(**kwargs)
            cid = first.container.cid
            try:
                self.assertEqual(first.container.cid, second.container.cid)
                version = await first.preflight()
                self.assertEqual(version['binary_sha256'], approved_pin().sha256)
                first.container.exec_argv(('--version',), first.env)
                # Fixed harmless boundary probe, not an exposed arbitrary-command
                # tool. No Factory cleanup is called until the guardian exits.
                subprocess.run(['docker', 'exec', '-d', cid, PYTHON_BINARY, '-I', '-c', 'import time; time.sleep(120)'],
                               check=True, capture_output=True, timeout=5)
                started = time.monotonic()
                self.assertTrue(first.container.process_ids())
                while time.monotonic() - started < 8:
                    value = json.loads(subprocess.check_output(['docker', 'inspect', cid], text=True))[0]
                    if not value['State']['Running']: break
                    await asyncio.sleep(.1)
                self.assertFalse(value['State']['Running'])
                self.assertEqual(value['State']['Pid'], 0)
                self.assertEqual(value['State']['ExitCode'], 124)
                proof = second.containment_evidence()
                self.assertTrue(proof['allStopped'])
                self.assertIn('wall_time_guardian', proof['enforced'])
                self.assertEqual(proof['limits'], bounds)
                self.assertLess(time.monotonic() - started, 8)
            finally:
                first.container.terminate()
                saved = json.loads((Path(directory)/'factory-linux-container.json').read_text())
                observed = json.loads(subprocess.check_output(['docker','inspect',cid],text=True))[0]
                self.assertEqual(observed['Config']['Labels']['agent-factory.orx-spec'],saved['specSha256'])
                subprocess.run(['docker','rm',cid],check=True,capture_output=True)
