"""Native chat Agent with owner-selected models and tools."""
import json

from agno.agent import Agent
from agno.exceptions import InputCheckError, RunCancelledException
from agno.registry import Registry
from agno.run import RunContext

from .model_dispatch import DelegatingModel
from .personal_mcp import MCPRunConnections


def build_runtime(store, native_db):
    model = DelegatingModel(store)

    def bind_run(run_context: RunContext, session, agent):
        try:
            # Queue deserialization reapplies Agno's omitted-None defaults.
            agent.num_history_runs = None
            agent.max_tool_calls_from_history = None
            plan = store.bind_run(run_context)
            if store.cancellation_requested(run_context.run_id):
                raise RunCancelledException('User stopped this task')
            inputs = plan.get('inputValues') or {}
            sessions = getattr(store, 'research_sessions', None)
            if sessions is not None and plan.get('mode') == 'autonomous' and inputs.get('sessionId') and inputs.get('turnId'):
                sessions.prepare_history(run_context, session)
        except (InputCheckError, RunCancelledException):
            raise
        except Exception as error:
            raise InputCheckError(str(error)) from error

    def instructions(run_context: RunContext):
        plan = store.resolve_run(run_context)
        text = plan.get('instructions', [])
        if isinstance(text, str):
            text = [text]
        inputs = dict(plan.get('inputValues') or {})
        if plan.get('mode') == 'autonomous' and inputs.get('turnId') and not plan.get('delegation'):
            legacy = inputs.pop('sessionContext', None)
            if legacy:
                previous = json.loads(legacy)
                for key in ('goal', 'boundaries'):
                    if key in previous:
                        inputs.setdefault(key, previous[key])
        return [*text, json.dumps({'goal': plan['normalizedGoal'], **inputs}, ensure_ascii=False)]

    def selected_tools(run_context: RunContext, agent):
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
            connections = MCPRunConnections()
            # Agno 3.1's async run finally closes this list; callable tools are not auto-registered.
            agent._mcp_tools_initialized_on_run.append(connections)
            functions.extend(personal.functions(run_context.user_id, run_context, mcp_connections=connections,
                reserved_names={function.name for function in functions} |
                    ({function.name for function in executor.skills.get_tools()} if executor.skills else set())))
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
            ticket = native_db.get_job(run_id) if run_id else None
            if run_id and ticket and ticket['status'] == 'running' and ticket['attempt'] > 1 and not ticket['payload'].get('continue'):
                previous = self.get_run_output(run_id, session_id=kwargs.get('session_id'), user_id=kwargs.get('user_id'))
                effects = store.effects(store.task(run_id)['id'])
                if previous and previous.messages and effects:
                    calls = {call['id'] for message in previous.messages for call in message.tool_calls or []}
                    results = {message.tool_call_id for message in previous.messages
                               if message.role == 'tool' and message.tool_call_id}
                    if (calls and calls == results
                            and all(any(item['effect_key'].endswith(':' + call) for call in results) for item in effects)):
                        # This in-memory RunOutput belongs only to this claim; the marker is not persisted.
                        setattr(previous, '_factory_retry_attempt', ticket['attempt'])
                        return self.acontinue_run(run_response=previous, **kwargs)
            return super().arun(input, **kwargs)

    executor = RetryAgent(id='factory-executor', name='Factory', model=model, db=native_db,
        instructions=instructions, tools=selected_tools, pre_hooks=[bind_run],
        store_events=True, events_to_skip=[],
        add_history_to_context=True, add_session_summary_to_context=True, telemetry=False)
    return executor, Registry(models=[model], dbs=[native_db])
