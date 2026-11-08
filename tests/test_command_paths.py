"""Real local commands keep output and respond to Stop in long session paths."""
import asyncio
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from agno.exceptions import RunCancelledException
from agent_factory.personal_tool_contract import ToolInvocationError
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
