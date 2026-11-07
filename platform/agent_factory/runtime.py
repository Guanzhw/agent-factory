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
        personal = getattr(store, 'personal_tools', None)
        if personal is not None:
            functions.extend(personal.functions(run_context.user_id, run_context,
                reserved_names={function.name for function in functions}))
        ssh = getattr(store, 'personal_ssh', None)
        if ssh is not None:
            functions.extend(ssh.functions(run_context.user_id))
        return functions

    executor = Agent(id='factory-executor', name='Factory', model=model, db=native_db,
        instructions=instructions, tools=selected_tools, pre_hooks=[bind_run],
        add_history_to_context=False, telemetry=False)
    return executor, Registry(models=[model], dbs=[native_db])
