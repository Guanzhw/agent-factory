"""Research-owned tools, instructions, history and provider-request hooks."""
import json

from agent_factory.application_runtime import ApplicationRuntime, ApplicationTools, execution_instructions
from .session_tools import EFFECT_PREFIX


class ResearchRuntime(ApplicationRuntime):
    def __init__(self, sessions, tools, qa, skills):
        self.sessions, self.session_tools, self.qa, self.skills = sessions, tools, qa, skills
        super().__init__(instructions=self._instructions, tools=self._tools,
            prepare_history=self._prepare_history, before_model=self._before_model,
            effect_prefixes=(EFFECT_PREFIX,))

    def _instructions(self, context, plan):
        inputs = dict(plan.get('inputValues') or {})
        if plan.get('mode') == 'autonomous' and inputs.get('turnId') and not plan.get('delegation'):
            legacy = inputs.pop('sessionContext', None)
            if legacy:
                previous = json.loads(legacy)
                for key in ('goal', 'boundaries'):
                    if key in previous:
                        inputs.setdefault(key, previous[key])
        snippet = self.skills.get_system_prompt_snippet()
        return [*execution_instructions(plan, inputs), *([snippet] if snippet else [])]

    def _tools(self, context, plan, agent):
        qa = plan.get('mode') == 'qa'
        functions = (self.qa if qa else self.session_tools).functions(context)
        return ApplicationTools([*functions, *self.skills.get_tools()], include_personal=not qa)

    def _prepare_history(self, context, plan, session, agent):
        inputs = plan.get('inputValues') or {}
        if plan.get('mode') == 'autonomous' and inputs.get('sessionId') and inputs.get('turnId'):
            self.sessions.prepare_history(context, session)

    def _before_model(self, context, plan, messages, auxiliary, *, auxiliary_request=False):
        inputs = plan.get('inputValues') or {}
        if plan.get('mode') != 'qa' and inputs.get('sessionId') and inputs.get('turnId'):
            if auxiliary_request:
                self.sessions.authorize_model(context)
            else:
                self.sessions.before_model(context, messages, auxiliary)
