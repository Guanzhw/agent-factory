"""Native chat Agent with owner-selected models and tools."""
import json

from agno.agent import Agent
from agno.exceptions import InputCheckError, RunCancelledException
from agno.registry import Registry
from agno.run import RunContext

from .model_dispatch import DelegatingModel


def build_runtime(store, native_db):
    model = DelegatingModel(store)

    def bind_run(run_context: RunContext):
        try:
            store.bind_run(run_context)
            if store.cancellation_requested(run_context.run_id):
                raise RunCancelledException('User stopped this task')
        except (InputCheckError, RunCancelledException):
            raise
        except Exception as error:
            raise InputCheckError(str(error)) from error

    def instructions(run_context: RunContext):
        plan = store.resolve_run(run_context)
        text = plan.get('instructions', [])
        if isinstance(text, str):
            text = [text]
        return [*text, json.dumps({'goal': plan['normalizedGoal'],
            **plan.get('inputValues', {})}, ensure_ascii=False)]

    def selected_tools(run_context: RunContext):
        plan = store.resolve_run(run_context)
        if plan.get("mode") == "qa":
            return store.research_qa.functions(run_context)
        research = getattr(store, 'research_tools', None)
        functions = research.functions(run_context) if research is not None else []
        ssh = getattr(store, 'personal_ssh', None)
        if ssh is not None:
            ssh_functions = ssh.functions(run_context.user_id)
            for function in ssh_functions:
                function.pre_hook = ssh_started
                function.post_hook = ssh_finished
            functions.extend(ssh_functions)
        personal = getattr(store, 'personal_tools', None)
        if personal is not None:
            functions.extend(personal.functions(run_context.user_id, run_context,
                reserved_names={function.name for function in functions} |
                    ({function.name for function in executor.skills.get_tools()} if executor.skills else set())))
        return functions

    def ssh_started(run_context, fc):
        store.event(run_context.session_id, 'tool_started', '开始执行 SSH 工具',
            {'toolName': fc.function.name, 'callId': fc.call_id, 'arguments': fc.arguments or {}})

    def ssh_finished(run_context, fc):
        event = {'toolName': fc.function.name, 'callId': fc.call_id, 'arguments': fc.arguments or {}}
        if fc.result is not None:
            event['output'] = fc.result
        if fc.function.name == 'ssh_run' and fc.result is not None and 'outcome' in fc.result:
            event.update(outcome=fc.result['outcome'], code=fc.result['code'])
        elif fc.result is None or fc.function.name == 'ssh_run' and fc.result['stopped'] is False:
            # Native post-hooks also run after cancellation, when remote stop is unconfirmed.
            event.update(outcome='unknown', code='SSH_TOOL_OUTCOME_UNKNOWN')
            if fc.error:
                event['message'] = fc.error
        else:
            event['outcome'] = 'completed'
        store.event(run_context.session_id, 'tool_finished', 'SSH 工具执行记录', event)

    executor = Agent(id='factory-executor', name='Factory', model=model, db=native_db,
        instructions=instructions, tools=selected_tools, pre_hooks=[bind_run],
        add_history_to_context=False, telemetry=False)
    return executor, Registry(models=[model], dbs=[native_db])
