"""Shell commands and script argv use their distinct Windows quoting contracts."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from agno.run import RunContext
from agno.tools.function import Function, FunctionCall
from research.session_tools import ResearchSessionTools
from research.skills import ResearchSkills


class CodingWindows(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='factory-quoting-')
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.context = RunContext(user_id='owner', session_id='session', run_id='run')
        self.tools = ResearchSessionTools(workspace_root=self.root)
        self.tools.sessions = SimpleNamespace(
            authorize_tool=lambda *_: {'ownerId': 'owner', 'id': 'session'},
            store=SimpleNamespace(event=Mock()))
        self.coding = self.tools.coding(self.context)

    async def test_windows_shell_tail_preserves_quotes(self):
        command = '"C:\\Program Files\\Python\\python.exe" -c "print(42)" | more'
        with patch('research.coding.sys.platform', 'win32'), patch.dict(os.environ, {'COMSPEC': 'C:\\Windows\\System32\\cmd.exe'}), \
                patch.object(self.coding, '_run_command', new_callable=AsyncMock) as run:
            await self.coding.run_shell(command)
        self.assertEqual(run.call_args.kwargs['windows_command_line'],
            'C:\\Windows\\System32\\cmd.exe /d /s /c "' + command + '"')
        self.assertEqual(run.call_args.args[1], [])

    async def test_skill_arguments_are_not_shell_code(self):
        scripts = self.root / 'scripts'
        scripts.mkdir()
        (scripts / 'args.py').write_text('import json,sys,os; print(json.dumps([sys.argv[1:], os.getcwd()]))', encoding='utf-8')
        directory = self.root / 'dir & literal'
        directory.mkdir()
        skill = SimpleNamespace(source_path=str(self.root))
        skills = ResearchSkills(self.tools, paths=[])
        args = ['a&b', '%PATH%', '|', 'a>b', '"quoted"', '', 'a b', '尾部\\']
        with patch.object(skills, '_script_execution', return_value=(skill, 'args.py')):
            result = await skills._get_skill_script('fixture', 'args.py', execute=True, args=args,
                cwd=str(directory), run_context=self.context, fc=FunctionCall(function=Function(name='get_skill_script'), call_id='call', arguments={}))
        self.assertTrue(result.startswith('Exit code: 0\n'), result)
        actual_args, actual_directory = json.loads(result.split('\n', 1)[1])
        self.assertEqual(actual_args, args)
        self.assertEqual(Path(actual_directory), directory)

    @unittest.skipUnless(sys.platform == 'win32', 'requires Windows cmd.exe')
    async def test_windows_quoted_executable_and_pipe(self):
        result = await self.coding.run_shell(f'"{sys.executable}" -c "print(12345)" | findstr 12345')
        self.assertIn('Exit code: 0', result)
        self.assertIn('12345', result)
