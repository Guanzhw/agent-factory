"""One registered native Agent bound to immutable persisted factory plans."""
import inspect
import json

from agno.agent import Agent
from agno.exceptions import InputCheckError, RunCancelledException, StopAgentRun
from agno.registry import Registry
from agno.run import RunContext
from agno.tools import tool
from agno.tools.function import Function

from .demo_model import CONTEXT_MARKER, DemoModel
from .tools import build_tools


def build_runtime(settings, store, native_db):
    catalog = build_tools(settings, store)
    model = DemoModel()

    def shared_budget(run_context: RunContext, fc):
        service = getattr(store, "delegation", None)
        if service is None:
            return
        try:
            store.authorize_tool(run_context, fc.function.name)
            service.consume_tool_budget(run_context, fc.call_id, fc.function.name)
        except RunCancelledException:
            raise
        except Exception as error:
            store.event(run_context.run_id, "protected_denied", "Shared durable tool budget or current authority denied execution", {"tool": fc.function.name})
            # Native tool pre-hooks stop only on AgentRunException subclasses.
            raise StopAgentRun(str(error)) from error

    catalog = {name: function if isinstance(function, Function) else tool(function)
               for name, function in catalog.items()}
    for function in catalog.values():
        function.pre_hook = shared_budget

    def bind_plan(run_context: RunContext):
        try:
            plan = store.bind_run(run_context)
            store.event(run_context.run_id, 'plan_bound', 'Native run bound to immutable plan snapshot', {'planId':plan['id'],'fingerprint':plan['fingerprint'],'modelId':model.id})
            if store.cancellation_requested(run_context.run_id):
                raise InputCheckError('Factory cancellation requested before execution')
        except (InputCheckError, RunCancelledException):
            raise
        except Exception as error:
            # Agno swallows ordinary pre-hook exceptions. Its native guardrail
            # exception is required to stop before model/tool execution.
            raise InputCheckError(str(error)) from error

    def instructions(run_context: RunContext):
        plan = store.resolve_run(run_context)
        text = plan.get('instructions', [])
        if isinstance(text, str): text = [text]
        context = {key:plan.get(key) for key in ['id','application','mode','normalizedGoal','config']}
        return [*text, 'This model and all literature/experiment sources are synthetic integration fixtures. Do not claim real research success.', CONTEXT_MARKER + json.dumps(context, sort_keys=True, separators=(',', ':'))]

    def selected_tools(run_context: RunContext):
        plan = store.resolve_run(run_context)
        names = plan.get('tools', [])
        if not isinstance(names, list) or any(name not in catalog for name in names):
            raise InputCheckError('Plan contains a tool outside the registered runtime catalog')
        return [catalog[name] for name in names]

    async def protected_boundary(run_context: RunContext, function_name, function_call, arguments):
        try:
            if store.cancellation_requested(run_context.run_id):
                raise RunCancelledException('Factory cancellation requested before tool execution')
            store.authorize_tool(run_context, function_name)
        except RunCancelledException:
            raise
        except BaseException as error:
            store.event(run_context.run_id, 'protected_denied', 'Protected tool denied by current authority or cancellation', {'tool':function_name,'error':str(error)})
            raise
        try:
            result = function_call(**arguments)
            return await result if inspect.isawaitable(result) else result
        except RunCancelledException:
            raise
        except BaseException as error:
            store.event(run_context.run_id, 'tool_failed', 'Native protected tool did not establish successful domain evidence', {'tool':function_name,'error':str(error)})
            raise

    executor = Agent(id='factory-executor', name='Factory executor', model=model, db=native_db,
                     instructions=instructions, tools=selected_tools, pre_hooks=[bind_plan], tool_hooks=[protected_boundary],
                     tool_call_limit=int(getattr(settings, 'max_tool_calls', 8)), add_history_to_context=False,
                     telemetry=False)
    registry = Registry(models=[model], dbs=[native_db], tools=list(catalog.values()))
    return executor, registry
