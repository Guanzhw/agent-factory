"""Agno CodingTools with cancellable local shell execution."""
import asyncio
import os
from pathlib import Path
import sys
import shutil
import subprocess
import tempfile

from agno.exceptions import RunCancelledException
from agno.tools.coding import CodingTools

from agent_factory._personal_cli_process import run_cli_process
from agent_factory.personal_tool_contract import ToolInvocationError


class SessionCodingTools(CodingTools):
    def __init__(self, research, context, workspace):
        self.research, self.context = research, context
        super().__init__(base_dir=workspace, restrict_to_base_dir=False,
            enable_run_shell=research.host_commands, enable_grep=True, enable_find=True, enable_ls=True)
        for function in self.get_async_functions().values():
            function.pre_hook = self._started
            function.post_hook = self._finished

    def _started(self, run_context, fc):
        self.research.sessions.authorize_tool(run_context, fc.function.name)
        self.research.sessions.store.event(run_context.run_id, 'tool_started', '开始执行工具',
            {'toolName': fc.function.name, 'callId': fc.call_id, 'arguments': fc.arguments or {}})

    def _finished(self, run_context, fc):
        self.research.sessions.store.event(run_context.run_id, 'tool_finished', '工具返回结果',
            {'toolName': fc.function.name, 'callId': fc.call_id, 'arguments': fc.arguments or {},
             'outcome': 'failed' if fc.error else 'completed', 'output': fc.result,
             **({'message': fc.error} if fc.error else {})})

    def find(self, pattern: str, path: str | None = None, limit: int = 500) -> str:
        """Find files by glob, returning paths relative to the search directory.

        Args:
            pattern: Glob pattern such as **/*.py.
            path: Search directory; defaults to the session workspace.
            limit: Maximum number of results.
        """
        # Agno 3.1 relativizes matches to base_dir even with restrictions disabled,
        # silently dropping all external matches. Use the requested search root.
        if path:
            root = Path(path).expanduser()
            if not root.is_absolute():
                root = self.base_dir / root
            return CodingTools(base_dir=root, restrict_to_base_dir=False).find(pattern, limit=limit)
        return super().find(pattern, limit=limit)

    async def run_shell(self, command: str, timeout: int | None = None) -> str:
        """Run a shell command in the session workspace and return output and exit code.

        Uses cmd.exe on Windows and /bin/sh on POSIX. Use cd in the command to change
        directory. There is no default deadline; Stop terminates owned local processes.

        Args:
            command: Shell command, including pipes or redirection when useful.
            timeout: Optional deadline in seconds, only when the task needs one.
        """
        executable = os.environ.get('COMSPEC', 'cmd.exe') if sys.platform == 'win32' else '/bin/sh'
        # cmd parses its command tail itself, not with C-runtime argv quoting.
        raw = f'{subprocess.list2cmdline([executable])} /d /s /c "{command}"' if sys.platform == 'win32' else None
        return await self._run_command(executable, ['-c', command] if raw is None else [],
            timeout=timeout, windows_command_line=raw)

    async def _run_command(self, executable, argv, *, cwd=None, timeout=None, windows_command_line=None):
        # Agno 3.1's synchronous subprocess.run has no native Stop/child-tree cleanup.
        def check():
            try:
                self.research.sessions.authorize_tool(self.context, 'run_shell')
            except RunCancelledException:
                raise asyncio.CancelledError() from None

        environment = dict(os.environ, PATH=self.research.command_path)
        executable = shutil.which(executable, path=self.research.command_path) or executable
        try:
            result = await run_cli_process(executable=executable, argv=argv, env=environment,
                cwd=cwd or self.base_dir, stdin=b'', timeout_seconds=timeout, max_output_bytes=None,
                before_spawn=check, check_authorized=check, windows_command_line=windows_command_line)
        except ToolInvocationError as error:
            if error.outcome == 'cancelled' and error.stopped:
                raise RunCancelledException('Command stopped') from error
            return f'Error running shell command: {error.code}; outcome={error.outcome}, stopped={error.stopped}'
        output = result.stdout.decode(errors='replace') + result.stderr.decode(errors='replace')
        preview, truncated, total_lines = self._truncate_output(output)
        if truncated:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', delete=False,
                    suffix='.txt', prefix='coding-output-', dir=self.base_dir) as stream:
                stream.write(output)
            preview += f'\n[Output truncated: {total_lines} lines total. Full output saved to: {Path(stream.name)}]'
        return f'Exit code: {result.returncode}\n' + preview
