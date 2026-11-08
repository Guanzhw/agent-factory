"""Real local commands keep output and respond to Stop in long session paths."""
import asyncio
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from agno.exceptions import RunCancelledException
from agno.run import RunContext
from agent_factory._personal_cli_process import run_cli_process
from agent_factory.personal_cli import MemberCliAdapter
from agent_factory.personal_tool_contract import ToolDescriptor, ToolInvocation, ToolInvocationError
from test_tool_unknown import Effects, call
from research.session_tools import ResearchSessionTools, _directory, _open_file, _windows_path


class CommandPaths(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='factory-command-path-')
        self.addCleanup(folder.cleanup)
        root = Path(folder.name)
        self.addCleanup(lambda: shutil.rmtree(_windows_path(root) if sys.platform == 'win32' else root))
        self.workspace = root / ('x' * (240 - len(str(root)) - 1))
        self.workspace.mkdir()
        self.tools = ResearchSessionTools(workspace_root=self.workspace, host_commands=True)

    async def test_long_command_output_exit7_and_native_file_read(self):
        for code in (0, 7):
            result = await self.tools._run(self.workspace, {'argv': [sys.executable, '-c',
                'import sys;print("long command output");print("diagnostic",file=sys.stderr);sys.exit(int(sys.argv[1]))',
                str(code)]}, lambda: None, {})
            self.assertEqual((result['exitCode'], result['stdout'], result['stderr'], result['stopped']),
                             (code, 'long command output\r\n' if sys.platform == 'win32' else 'long command output\n',
                              'diagnostic\r\n' if sys.platform == 'win32' else 'diagnostic\n', True))
        expected = ('x' * 50000 + ('\r\n' if sys.platform == 'win32' else '\n')).encode()
        result = await self.tools._run(self.workspace, {'argv': [sys.executable, '-c', 'print("x"*50000)'],
            'max_output_tokens': 10}, lambda: None, {})
        self.assertTrue(result['truncated'])
        relative = Path(result['stdoutPath'])
        self.assertFalse(relative.is_absolute())
        self.assertGreater(len(str(self.workspace / relative)), 260)
        with _directory(self.workspace, relative.parts[:-1]) as parent:
            with os.fdopen(_open_file(parent, relative.name), 'rb') as stream:
                self.assertEqual(stream.read(), expected)

    async def test_stop_reaps_actual_long_path_command(self):
        pid_file = self.workspace / 'pid.txt'
        stopped = False
        def guard():
            if stopped:
                raise RunCancelledException('synthetic user Stop')
        task = asyncio.create_task(self.tools._run(self.workspace, {'argv': [sys.executable, '-c',
            'import os,sys,time;from pathlib import Path;Path(sys.argv[1]).write_text(str(os.getpid()));time.sleep(60)',
            str(pid_file)]}, guard, {}))
        async def cleanup():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self.addAsyncCleanup(cleanup)
        async with asyncio.timeout(5):
            while not pid_file.exists():
                await asyncio.sleep(.01)
        pid = int(pid_file.read_text())
        handle = None
        if sys.platform == 'win32':
            import win32api
            import win32con
            import win32event
            handle = win32api.OpenProcess(win32con.SYNCHRONIZE, False, pid)
            self.addCleanup(handle.Close)
        stopped = True
        with self.assertRaises(ToolInvocationError) as error:
            await task
        self.assertEqual(error.exception.outcome, 'cancelled')
        self.assertTrue(error.exception.stopped)
        if handle is not None:
            self.assertEqual(win32event.WaitForSingleObject(handle, 5000), win32con.WAIT_OBJECT_0)
        else:
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)

    async def test_output_preparation_failure_does_not_dispatch_or_keep_directory_handles(self):
        process = AsyncMock()
        with (patch('research.session_tools.tempfile.mkdtemp', side_effect=OSError('synthetic storage failure')),
                patch('research.session_tools.run_cli_process', process)):
            with self.assertRaises(ToolInvocationError) as error:
                await self.tools._run(self.workspace, {'argv': [sys.executable, '-c', 'print("unused")']}, lambda: None, {})
        self.assertEqual(error.exception.code, 'RESEARCH_COMMAND_OUTPUT_UNAVAILABLE')
        self.assertEqual(error.exception.outcome, 'failed')
        self.assertTrue(error.exception.stopped)
        process.assert_not_awaited()
        renamed = self.workspace.with_name(self.workspace.name + '-renamed')
        self.workspace.rename(renamed)
        renamed.rename(self.workspace)

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

    async def test_native_edit_diagnostic_allows_correction_and_read(self):
        with tempfile.TemporaryDirectory() as root:
            store = Effects()
            context = RunContext(run_id='run', session_id='task', user_id='owner')
            tools = ResearchSessionTools(workspace_root=Path(root))
            tools.sessions = SimpleNamespace(store=store, authorize_tool=lambda *_:
                {'ownerId': 'owner', 'id': 'session', 'turnId': 'turn'})
            edit = tools._function(store, context, 'research_edit_file')
            read = tools._function(store, context, 'research_read_file')
            await call(edit, context, 'create', path='note.txt', old='', new='one one')
            missing = await call(edit, context, 'missing', path='note.txt', old='missing', new='two')
            self.assertEqual(missing['outcome'], 'failed')
            self.assertIn('old_str not found', missing['message'])
            ambiguous = await call(edit, context, 'ambiguous', path='note.txt', old='one', new='two')
            self.assertEqual(ambiguous['outcome'], 'failed')
            self.assertIn('matches 2 times', ambiguous['message'])
            self.assertEqual((await call(read, context, 'unchanged', path='note.txt'))['text'], 'one one')
            await call(edit, context, 'corrected', path='note.txt', old='one one', new='two')
            self.assertEqual((await call(read, context, 'read', path='note.txt'))['text'], 'two')
