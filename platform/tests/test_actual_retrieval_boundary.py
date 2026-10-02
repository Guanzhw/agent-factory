"""Actual selected Linux cgroup/PID namespace; no public network request."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from uuid import uuid4

from agent_factory.orx_pins import approved_pin
from agent_factory.orx_retrieval import TaskLinuxRetrievalProvider
from agent_factory.orx_linux import PYTHON_BINARY


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
                self.assertIs(first._resource_lock, second._resource_lock)
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
