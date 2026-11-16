"""Native chat Agent with owner-selected models and tools."""
from collections import Counter
from agno.agent import Agent
from agno.agent._messages import get_continue_run_messages
from agno.exceptions import InputCheckError, RunCancelledException
from agno.registry import Registry
from agno.run import RunContext
from agno.session.agent import AgentSession

from .application_runtime import ApplicationTools, execution_instructions, resolve_application_runtime
from .model_dispatch import DelegatingModel
from .native_messages import pair_tool_results
from .personal_mcp import MCPRunConnections


def build_runtime(store, native_db, *, application_runtimes=None):
    runtimes = (getattr(store, 'application_runtimes', {})
                if application_runtimes is None else application_runtimes)
    model = DelegatingModel(store, runtimes)

    def bind_run(run_context: RunContext, session, agent):
        try:
            # Queue deserialization reapplies Agno's omitted-None defaults.
            agent.num_history_runs = None
            agent.max_tool_calls_from_history = None
            # Agno 3.1 omits checkpoint from serialized configurations.
            agent.checkpoint = 'tool-batch'
            plan = store.bind_run(run_context)
            if store.cancellation_requested(run_context.run_id):
                raise RunCancelledException('User stopped this task')
            application = resolve_application_runtime(runtimes, plan)
            if application is not None and application.prepare_history is not None:
                application.prepare_history(run_context, plan, session, agent)
        except (InputCheckError, RunCancelledException):
            raise
        except Exception as error:
            raise InputCheckError(str(error)) from error

    def instructions(run_context: RunContext):
        plan = store.resolve_run(run_context)
        application = resolve_application_runtime(runtimes, plan)
        if application is not None and application.instructions is not None:
            return application.instructions(run_context, plan)
        return execution_instructions(plan, plan.get('inputValues') or {})

    def selected_tools(run_context: RunContext, agent):
        plan = store.resolve_run(run_context)
        application = resolve_application_runtime(runtimes, plan)
        selected = (application.tools(run_context, plan, agent)
                    if application is not None and application.tools is not None else ApplicationTools())
        if not selected.include_personal:
            return selected.functions
        functions = list(selected.functions)
        ssh = getattr(store, 'personal_ssh', None)
        if ssh is not None:
            ssh_functions = ssh.functions(run_context.user_id)
            for function in ssh_functions:
                function.pre_hook = ssh_started
                function.post_hook = ssh_finished
            functions.extend(ssh_functions)
        personal = getattr(store, 'personal_tools', None)
        if personal is not None:
            connections = MCPRunConnections()
            # Agno 3.1's async run finally closes this list; callable tools are not auto-registered.
            agent._mcp_tools_initialized_on_run.append(connections)
            functions.extend(personal.functions(run_context.user_id, run_context, mcp_connections=connections,
                reserved_names={function.name for function in functions} |
                    ({function.name for function in agent.skills.get_tools()} if agent.skills else set())))
        return functions

    def ssh_started(run_context, fc):
        store.event(run_context.run_id, 'tool_started', '开始执行 SSH 工具',
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
        store.event(run_context.run_id, 'tool_finished', 'SSH 工具执行记录', event)

    # Agno replays arun on a reclaimed queue ticket; its native continue API preserves tool observations.
    class RetryAgent(Agent):
        def arun(self, input, **kwargs):
            run_id = kwargs.get('run_id')
            ticket = native_db.get_job(run_id) if native_db is not None and run_id else None
            if run_id and ticket and ticket['status'] == 'running' and ticket['attempt'] > 1 and not ticket['payload'].get('continue'):
                previous = self.get_run_output(run_id, session_id=kwargs.get('session_id'), user_id=kwargs.get('user_id'))
                task = store.task(run_id)
                effects = store.effects(task['id'])
                application = resolve_application_runtime(runtimes, store.execution(task))
                started = (application.retry_calls(store.events(task['id']))
                           if application is not None and application.retry_calls is not None else [])
                if previous and previous.messages and previous.session_id and previous.user_id:
                    prefixes = ('personal-tool:', *(application.effect_prefixes if application is not None else ()))
                    current = [message for message in previous.messages if not message.from_history]
                    calls = [call['id'] for message in current for call in message.tool_calls or []]
                    observed = Counter((call['function']['name'], call['id'])
                        for message in current for call in message.tool_calls or [])
                    recorded = {run_id + ':' + prefix + call for call in calls
                                for prefix in prefixes}
                    if (calls and all(item['effect_key'] in recorded for item in effects)
                            and Counter((name, call) for name, call, _ in started) <= observed):
                        session = self.get_session(session_id=previous.session_id, user_id=previous.user_id)
                        if not isinstance(session, AgentSession):
                            raise InputCheckError('Native retry session is unavailable')
                        context = RunContext(run_id=run_id, session_id=previous.session_id,
                            user_id=previous.user_id, session_state=previous.session_state or {})
                        bind_run(context, session, self)
                        previous.messages = pair_tool_results(get_continue_run_messages(self, previous.messages,
                            session=session, run_response=previous).messages)
                        # The prepared view already supplies valid history; never re-read the unfiltered session.
                        self.add_history_to_context = False
                        # This in-memory RunOutput belongs only to this claim; the marker is not persisted.
                        setattr(previous, '_factory_retry_attempt', ticket['attempt'])
                        return self.acontinue_run(run_response=previous, **kwargs)
                if effects or any(required for _, _, required in started):
                    if application is not None and application.on_retry_blocked is not None:
                        application.on_retry_blocked(task)
                    raise InputCheckError('NATIVE_RETRY_EFFECT_UNMATCHED: cannot resume from the saved tool observations')
            return super().arun(input, **kwargs)

    executor = RetryAgent(id='factory-executor', name='Factory', model=model, db=native_db,
        instructions=instructions, tools=selected_tools, pre_hooks=[bind_run],
        cache_callables=False,  # Agno's owner cache would reuse another run's tools and closed MCP handles.
        store_events=True, events_to_skip=[], checkpoint='tool-batch',
        add_history_to_context=True, add_session_summary_to_context=True, telemetry=False)
    return executor, Registry(models=[model], dbs=[native_db])
