"""Native Agno skills; script execution uses the existing cancellable command tool."""
import json
import os
import shlex
from pathlib import Path
import sys

from agno.run import RunContext
from agno.skills import LocalSkills, Skills
from agno.skills.utils import get_interpreter_command
from agno.tools.function import FunctionCall
from agno.utils.path_safety import safe_join_relative_path
from pydantic import TypeAdapter, ValidationError


class ProjectSkills(LocalSkills):
    # Agno 3.1.0 only lists immediate files; standard skills can nest resources.
    def _discover_scripts(self, folder):
        return self._files(folder / 'scripts')

    def _discover_references(self, folder):
        return self._files(folder / 'references')

    @staticmethod
    def _files(root):
        return sorted(path.relative_to(root).as_posix() for path in root.rglob('*') if path.is_file())


class ResearchSkills(Skills):
    def __init__(self, tools, paths=None):
        self.tools = tools
        if paths is None:
            paths = [Path(__file__).with_name('skills'), Path.cwd() / '.agents' / 'skills',
                     *(Path(value).expanduser() for value in os.environ.get('FACTORY_SKILL_PATHS', '').split(os.pathsep) if value)]
        # Extra frontmatter used by standard clients need not prevent loading.
        super().__init__([ProjectSkills(str(path), validate=False) for path in paths if Path(path).is_dir()])

    def get_tools(self):
        tools = super().get_tools()
        for tool in tools:
            tool.pre_hook = self._read_started
            tool.post_hook = self._read_finished
        return tools

    def _script_execution(self, skill_name, script_path: str | None, execute: bool):
        skill = self.get_skill(skill_name)
        if execute and skill is not None and script_path and script_path in skill.scripts:
            return skill, script_path
        return None

    def _read_event(self, fc):
        arguments = fc.arguments or {}
        # Executed scripts already have research_run events with this call ID.
        if fc.function.name == 'get_skill_script':
            try:
                execute = TypeAdapter(bool).validate_python(arguments.get('execute', False))
            except ValidationError:
                # The native entrypoint still rejects invalid values; record that failure.
                execute = False
            if self._script_execution(arguments.get('skill_name'), arguments.get('script_path'), execute) is not None:
                return None
        return {'toolName': fc.function.name, 'callId': fc.call_id, 'arguments': arguments}

    def _read_started(self, run_context, fc):
        event = self._read_event(fc)
        if event is not None:
            self.tools.sessions.store.event(run_context.run_id, 'tool_started', '开始读取技能资源', event)

    def _read_finished(self, run_context, fc):
        event = self._read_event(fc)
        if event is None:
            store = self.tools.sessions.store
            if fc.result is not None or any(
                item['data'].get('callId') == fc.call_id
                for item in store.events(store.task_for_context(run_context)["id"])
                if item['type'] in {'research_tool_started', 'research_tool_finished'}
            ):
                return
            event = {'toolName': fc.function.name, 'callId': fc.call_id, 'arguments': fc.arguments or {}}
            store.event(run_context.run_id, 'tool_started', '技能脚本调用', event)
        if fc.result is None:
            event['outcome'] = 'failed' if fc.error else 'unknown'
            if fc.error:
                event['message'] = fc.error
        else:
            result = json.loads(fc.result)
            event.update(outcome='failed' if 'error' in result else 'completed', output=fc.result)
            if 'error' in result:
                event['message'] = result['error']
        self.tools.sessions.store.event(run_context.run_id, 'tool_finished', '技能资源读取记录', event)

    def _get_skill_instructions(self, skill_name: str) -> str:
        """Load native skill instructions and the directory containing their resources."""
        result = json.loads(super()._get_skill_instructions(skill_name))
        skill = self.get_skill(skill_name)
        if skill is not None:
            result['source_path'] = skill.source_path
        return json.dumps(result, ensure_ascii=False)

    async def _get_skill_script(self, skill_name: str, script_path: str | None = None,
                               execute: bool = False, args: list[str] | None = None,
                               cwd: str = '.', *, run_context: RunContext, fc: FunctionCall):
        """Read or run a skill script. Execution has no default time limit and responds to Stop.

        Args:
            skill_name: Loaded skill name.
            script_path: Path from the skill's available_scripts list.
            execute: Run when true; otherwise read source.
            args: Script arguments, passed unchanged as separate argv entries.
            cwd: Working directory; relative paths use the session workspace. Use source_path from skill instructions for skill resources.
        """
        execution = self._script_execution(skill_name, script_path, execute)
        if execution is None:
            return super()._get_skill_script(skill_name, script_path, execute=False)
        skill, script_path = execution
        script = safe_join_relative_path(Path(skill.source_path) / 'scripts', script_path)
        with script.open(encoding='utf-8') as stream:
            first_line = stream.readline().strip()
        prefix = shlex.split(first_line[2:]) if first_line.startswith('#!') else {
            '.py': [sys.executable], '.sh': ['sh'], '.js': ['node'],
        }.get(script.suffix, [])
        if sys.platform == 'win32' and prefix:
            if Path(prefix[0]).name == 'env':
                prefix = prefix[1:]
                if prefix and prefix[0] == '-S':
                    prefix = prefix[1:]
            if prefix:
                interpreter = Path(prefix[0]).name if prefix[0].startswith('/') else prefix[0]
                prefix = [*get_interpreter_command(interpreter), *prefix[1:]]
        command = self.tools._function(self.tools.sessions.store, run_context, 'research_run')
        command._run_context = run_context
        call = FunctionCall(function=command, call_id=fc.call_id)
        return await command.entrypoint(run_context=run_context, fc=call,
            argv=[*prefix, str(script), *(args or [])], cwd=cwd)
