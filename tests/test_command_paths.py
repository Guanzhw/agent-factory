"""Native coding tools read real research paths, preserve failures, and stop commands."""
import asyncio
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace

from agno.exceptions import RunCancelledException
from agno.run import RunContext
from agent_factory._personal_cli_process import run_cli_process
from agent_factory.personal_cli import MemberCliAdapter
from agent_factory.personal_tool_contract import ToolDescriptor, ToolInvocation
from research.session_tools import ResearchSessionTools


def shell_command(argv):
    return subprocess.list2cmdline(argv) if sys.platform == 'win32' else shlex.join(argv)


class CommandPaths(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='factory-native-coding-')
        self.addCleanup(folder.cleanup)
        self.workspace = Path(folder.name)
        self.stopped = False
        def authorize(*_):
            if self.stopped:
                raise RunCancelledException('User stopped')
            return {'ownerId': 'owner', 'id': 'session'}
        self.tools = ResearchSessionTools(workspace_root=self.workspace)
        self.tools.sessions = SimpleNamespace(authorize_tool=authorize)
        self.coding = self.tools.coding(RunContext(user_id='owner', session_id='session', run_id='run'))

    async def test_find_external_research_directory(self):
        target = self.workspace / 'external'
        target.mkdir()
        (target / 'PROTOCOL.md').write_text('research protocol')
        self.assertEqual(self.coding.find('*.md', path=str(target)), 'PROTOCOL.md')

    async def test_native_absolute_read_edit_write_and_errors(self):
        # Outside the default session cwd, as in the user's PROTOCOL.md failure.
        target = self.workspace / 'PROTOCOL.md'
        self.assertIn('Wrote', self.coding.write_file(str(target), 'one one'))
        self.assertIn('one one', self.coding.read_file(str(target)))
        self.assertIn('Error', self.coding.edit_file(str(target), 'missing', 'two'))
        self.assertIn('Error', self.coding.edit_file(str(target), 'one', 'two'))
        self.assertEqual(target.read_text(), 'one one')
        self.coding.edit_file(str(target), 'one one', 'two')
        self.assertEqual(target.read_text(), 'two')
        self.assertIn('Error', self.coding.read_file(str(target.with_name('missing'))))
        self.assertTrue({'read_file', 'edit_file', 'write_file', 'grep', 'run_shell'} <= set(self.tools.available_tools))
        self.assertNotIn('research_read_file', self.tools.available_tools)

    async def test_shell_failure_preserves_output_and_full_output_is_readable(self):
        result = await self.coding.run_shell(shell_command([sys.executable, '-c',
            'import sys;print("output");print("diagnostic",file=sys.stderr);sys.exit(7)']))
        self.assertIn('Exit code: 7', result)
        self.assertIn('output', result)
        self.assertIn('diagnostic', result)
        self.coding.max_bytes = 100
        result = await self.coding.run_shell(shell_command([sys.executable, '-c', 'print("x"*10000)']))
        path = result.split('Full output saved to: ')[1].split(']')[0]
        self.assertEqual(len(Path(path).read_text().strip()), 10000)
        self.assertNotIn('outside', self.coding.read_file(path))

    async def test_stop_reaps_actual_command(self):
        pid_file = self.workspace / 'pid.txt'
        task = asyncio.create_task(self.coding.run_shell(shell_command([sys.executable, '-c',
            'import os,sys,time;from pathlib import Path;Path(sys.argv[1]).write_text(str(os.getpid()));time.sleep(60)',
            str(pid_file)])))
        async def cleanup():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self.addAsyncCleanup(cleanup)
        async with asyncio.timeout(10):
            while not pid_file.exists():
                await asyncio.sleep(.01)
        pid = int(pid_file.read_text())
        self.stopped = True
        with self.assertRaises(RunCancelledException):
            await task
        if sys.platform == 'win32':
            import win32api
            import win32con
            import win32event
            try:
                handle = win32api.OpenProcess(win32con.SYNCHRONIZE, False, pid)
            except Exception:
                return
            self.addCleanup(handle.Close)
            self.assertEqual(win32event.WaitForSingleObject(handle, 5000), win32con.WAIT_OBJECT_0)
        elif Path(f'/proc/{pid}/stat').exists():
            self.assertEqual(Path(f'/proc/{pid}/stat').read_text().split(') ')[1][0], 'Z')

    async def test_personal_cli_runs_with_asyncio_debug_enabled(self):
        self.assertTrue(asyncio.get_running_loop().get_debug())
        descriptor = ToolDescriptor(adapter_id='debug-cli', revision='1', tool_name='debug_cli', description='Diagnostic',
            input_schema={'type': 'object'}, transport='cli', credential_provider_id='fixture',
            credential_destination=sys.executable, capabilities=('tool:invoke',))
        adapter = MemberCliAdapter(descriptor, {'executable': sys.executable, 'arguments': ['-c', 'print(42)'],
            'stdinJson': False, 'outputFormat': 'text'})
        result = await adapter.invoke(ToolInvocation(owner_id='owner', connection_ref='fixture', connection_revision='1',
            call_id='debug', arguments={}, run_context=None, check_authorized=lambda: None, resolve_credential=lambda: None))
        self.assertEqual(result['text'].strip(), '42')

    async def test_streamed_output_can_skip_duplicate_capture(self):
        chunks = {'stdout': bytearray(), 'stderr': bytearray()}
        result = await run_cli_process(executable=sys.executable, argv=['-c',
            'import sys;sys.stdout.write("x"*100000);sys.stderr.write("diagnostic");sys.exit(7)'],
            env=dict(os.environ), cwd=self.workspace, stdin=b'', timeout_seconds=None, max_output_bytes=None,
            capture_max_bytes=0, on_output=lambda channel, chunk: chunks[channel].extend(chunk),
            before_spawn=lambda: None, check_authorized=lambda: None)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (7, b'', b''))
        self.assertEqual(chunks, {'stdout': b'x' * 100000, 'stderr': b'diagnostic'})
        self.assertTrue(result.stopped)
