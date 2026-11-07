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
        skill = self.get_skill(skill_name)
        if not execute or skill is None or not script_path or script_path not in skill.scripts:
            return super()._get_skill_script(skill_name, script_path, execute=False)
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
