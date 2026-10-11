"""Governance bridge for operator-built Agno workflows; no progress engine.

Function executors remain trusted operator adapters and must use original-effect
custody for external writes. A tool-budget receipt is not an effect receipt.
"""
from dataclasses import dataclass
from typing import Any
from functools import wraps
import inspect
import re

from agno.run import RunContext
from agno.workflow.workflow import Workflow
from agno.workflow.step import Step
from agno.workflow.parallel import Parallel
from agno.workflow.router import Router
from agno.workflow.condition import Condition
from agno.workflow.steps import Steps
from fastapi import HTTPException

from .store import digest
from .auth import EXECUTOR_ID
from .workflow_model import WorkflowDecisionModel
from .native_external_wait import factory_wait_operations


@dataclass(frozen=True)
class NativeWorkflowRegistration:
    component: Workflow
    revision: str
    tool_names: tuple[str, ...]
    implementation_sha256: str


def _identifier(value):
    if type(value) is not str or re.fullmatch(r'[A-Za-z0-9_.:-]{1,100}', value) is None:
        raise ValueError('Stable native workflow identity required')
    return value


def _nodes(items, in_parallel=False):
    for node in items:
        if type(node) not in (Step, Parallel, Router, Condition, Steps):
            raise ValueError('Unsupported native workflow primitive')
        if (in_parallel and isinstance(node, Step) and node.agent is not None and node.agent.tools):
            raise ValueError('External wait must be outside native Parallel')
        yield node
        if isinstance(node, Router):
            yield from _nodes(node.choices, in_parallel)
        elif isinstance(node, Condition):
            yield from _nodes(node.steps, in_parallel or isinstance(node, Parallel))
            yield from _nodes(node.else_steps or [], in_parallel)
        elif isinstance(node, (Parallel, Steps)):
            yield from _nodes(node.steps, in_parallel or isinstance(node, Parallel))


def _configuration(registration):
    component = registration.component
    if type(component) is not Workflow or not isinstance(component.steps, list):
        raise ValueError('An operator-built native Workflow is required')
    if component.agent is not None or component.dependencies or component.media_storage:
        raise ValueError('Unsupported executable workflow extension')
    if re.fullmatch('[a-f0-9]{64}', registration.implementation_sha256) is None:
        raise ValueError('Reviewed implementation fingerprint required')
    _identifier(component.id)
    _identifier(registration.revision)
    if type(registration.tool_names) is not tuple or len(set(registration.tool_names)) != len(registration.tool_names):
        raise ValueError('Unique workflow tool names required')
    names, ids, decisions = [], set(), []
    step_names, agent_ids = set(), set()
    for node in _nodes(component.steps):
        if isinstance(node, Step):
            identifier = _identifier(node.step_id)
            if node.skip_on_failure or node.human_review.on_error != 'fail':
                raise ValueError('Native steps must fail on execution errors')
            name = _identifier(node.name)
            if name in step_names:
                raise ValueError('Unique native step names required')
            step_names.add(name)
            # Agno generates UUIDs for omitted step_id; require an explicit semantic ID.
            if re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', identifier):
                raise ValueError('Explicit semantic step_id required')
            if identifier in ids or node.workflow is not None or node.team is not None:
                raise ValueError('Repeated or nested workflow step is unsupported')
            ids.add(identifier)
            if node.executor is not None:
                if node.max_retries != 0 or not callable(node.executor):
                    raise ValueError('Function steps require zero retries')
                names.append(_identifier(node.name))
            elif node.agent is not None:
                tools: Any = node.agent.tools
                if (tools and (type(tools) is not list or len(tools) != 1 or tools[0] is not factory_wait_operations)) or not node.agent.id:
                    raise ValueError('Decision agents must be tool-free and named')
                agent = node.agent
                if agent.id in agent_ids:
                    raise ValueError('Unique native decision agent IDs required')
                agent_ids.add(agent.id)
                if callable(agent.instructions) or callable(agent.system_message):
                    raise ValueError('Decision instructions must be static')
                forbidden = ('pre_hooks', 'post_hooks', 'tool_hooks', 'fallback_config', 'fallback_models',
                    'reasoning_model', 'reasoning_agent', 'parser_model', 'output_model', 'followup_model',
                    'knowledge', 'knowledge_retriever', 'skills', 'filesystem', 'dependencies',
                    'memory_manager', 'session_summary_manager', 'compression_manager', 'media_storage',
                    'learning', 'save_response_to_file', 'additional_input', 'enable_agentic_state',
                    'enable_agentic_memory', 'update_memory_on_run', 'enable_session_summaries',
                    'compress_tool_results', 'offload_tool_results', 'search_past_sessions', 'read_chat_history',
                    'read_tool_call_history', 'update_knowledge', 'followups')
                if any(getattr(agent, name) for name in forbidden) or agent.retries != 0:
                    raise ValueError('Unsupported executable decision-agent extension')
                def agent_schema(value):
                    return value.model_json_schema() if hasattr(value, 'model_json_schema') else value
                options = {name: getattr(agent, name) for name in ('expected_output', 'additional_context',
                    'introduction', 'system_message_role', 'user_message_role', 'markdown', 'build_context',
                    'build_user_context', 'use_instruction_tags', 'add_name_to_context', 'add_datetime_to_context',
                    'add_location_to_context', 'datetime_format', 'timezone_identifier', 'parse_response',
                    'structured_outputs', 'use_json_mode', 'tool_choice', 'tool_call_limit', 'num_history_messages',
                    'max_tool_calls_from_history', 'add_session_state_to_context', 'add_dependencies_to_context')}
                options.update(inputSchema=agent_schema(agent.input_schema), outputSchema=agent_schema(agent.output_schema))
                decisions.append({'stepId': identifier, 'agentId': agent.id,
                    'name': agent.name, 'description': agent.description, 'options': options,
                    'instructions': agent.instructions, 'systemMessage': agent.system_message,
                    'externalWait': bool(tools),
                    'addHistory': agent.add_history_to_context, 'historyRuns': agent.num_history_runs})
            else:
                raise ValueError('Unsupported native executor')
    if sorted(names) != sorted(registration.tool_names):
        raise ValueError('Function steps must match governed tools exactly')
    schema: Any = component.input_schema
    schema = schema.model_json_schema() if hasattr(schema, 'model_json_schema') else schema
    return {'id': component.id, 'revision': registration.revision, 'name': component.name,
            'description': component.description, 'implementationSha256': registration.implementation_sha256, 'tools': list(registration.tool_names),
            'inputSchema': schema, 'decisions': decisions, 'steps': [node.to_dict() for node in component.steps]}


class NativeWorkflows:
    def __init__(self, store, auth, native_db, registrations):
        self.store, self.auth, self.native_db = store, auth, native_db
        self.registrations, self._pins, self._identities = {}, {}, {}
        for registration in registrations:
            config = _configuration(registration)
            identifier = config['id']
            if identifier in self.registrations:
                raise ValueError('Duplicate native workflow')
            self.registrations[identifier] = registration
            self._pins[identifier] = {'kind': 'workflow', 'id': identifier,
                                     'revision': registration.revision, 'sha256': digest(config)}
            registration.component.db = native_db
            for step in _nodes(registration.component.steps):
                if isinstance(step, Step) and step.executor is not None:
                    self._wrap(identifier, step)
                elif isinstance(step, Step) and step.agent is not None:
                    agent = step.agent
                    agent.model = WorkflowDecisionModel(store.execution_bindings, workflow_id=identifier,
                        step_id=_identifier(step.step_id), agent_id=_identifier(agent.id),
                        validator=self._validator(identifier, step))

            self._identities[identifier] = self._references(registration)

    @staticmethod
    def _references(registration):
        refs = [registration.component, registration.component.input_schema]
        for node in _nodes(registration.component.steps):
            refs.append(node)
            if isinstance(node, Step):
                refs.extend((node.executor, node.agent, node.active_executor, node._executor_type))
                if node.agent is not None:
                    refs.extend((node.agent.model, node.agent.input_schema, node.agent.output_schema))
            elif isinstance(node, Router):
                refs.append(node.selector)
            elif isinstance(node, Condition):
                refs.append(node.evaluator)
        return refs

    @property
    def components(self):
        return [row.component for row in self.registrations.values()]

    def pin(self, identifier):
        registration = self.registrations.get(identifier)
        if registration is None:
            raise HTTPException(409, 'NATIVE_WORKFLOW_UNAVAILABLE')
        refs = self._references(registration)
        original = self._identities[identifier]
        if len(refs) != len(original) or any(a is not b for a, b in zip(refs, original)):
            raise HTTPException(409, 'NATIVE_WORKFLOW_CHANGED')
        if digest(_configuration(registration)) != self._pins[identifier]['sha256']:
            raise HTTPException(409, 'NATIVE_WORKFLOW_UNAVAILABLE')
        return dict(self._pins[identifier])

    def require_plan_current(self, owner, plan, run_context=None, tool_name=None):
        selected = plan.get('nativeComponent')
        if selected is None:
            return
        if selected != self.pin(selected.get('id')):
            raise HTTPException(409, 'NATIVE_WORKFLOW_CHANGED')
        self.auth.require(owner, 'run', 'workflows', selected['id'])
        from .input_schema import input_model
        schema = plan.get('inputSchema')
        configured_schema = self.registrations[selected['id']].component.input_schema
        if schema is not None and (configured_schema is None or
                configured_schema.model_json_schema() != input_model(schema).model_json_schema()):
            raise HTTPException(409, 'NATIVE_WORKFLOW_INPUT_SCHEMA_CHANGED')
        if any(isinstance(node, Step) and node.agent is not None and node.agent.tools
                for node in _nodes(self.registrations[selected['id']].component.steps)) and 'factory_wait_operations' not in plan['tools']:
            raise HTTPException(409, 'NATIVE_WORKFLOW_WAIT_POLICY_MISSING')
        if not set(self.registrations[selected['id']].tool_names).issubset(plan['tools']):
            raise HTTPException(409, 'NATIVE_WORKFLOW_TOOLS_CHANGED')

    def component_for_task(self, session_id, owner):
        task = self.store.task(session_id, owner)
        plan = self.store.plan(task['plan_id'], owner)
        from .native_component import NativeWorkflowPin
        if plan.get("nativeComponent") is not None:
            NativeWorkflowPin.model_validate(plan["nativeComponent"])
        return dict(plan.get('nativeComponent') or {'kind': 'agent', 'id': EXECUTOR_ID,
                    'revision': '1', 'sha256': digest({'id': EXECUTOR_ID, 'revision': '1'})})

    def _root(self, identifier, response):
        task = self.store.task(response.session_id, response.user_id)
        plan = self.store.plan(task['plan_id'], response.user_id)
        self.require_plan_current(response.user_id, plan)
        if plan.get('nativeComponent') != self.pin(identifier):
            raise PermissionError('Native workflow plan mismatch')
        run_id = task.get('run_id')
        if run_id is None:
            # Admission may commit its native ticket before Factory receives
            # the acknowledgement. Resolve only the original queued intent.
            from sqlalchemy import MetaData, Table, select
            table = Table(self.native_db.job_table_name, MetaData(),
                schema=getattr(self.native_db, 'db_schema', None), autoload_with=self.native_db.db_engine)
            with self.native_db.db_engine.connect() as connection:
                candidates = list(connection.execute(select(table).where(table.c.session_id == task['id'],
                    table.c.user_id == response.user_id, table.c.component_type == 'workflow',
                    table.c.component_id == identifier).limit(2)).mappings())
            if len(candidates) != 1:
                raise PermissionError('Unique original workflow admission required')
            run_id = candidates[0]['id']
        ticket = self.native_db.get_job(run_id) or {}
        if (ticket.get('id') != run_id or ticket.get('session_id') != task['id']
                or ticket.get('user_id') != response.user_id or ticket.get('component_type') != 'workflow'
                or ticket.get('component_id') != identifier or ticket.get('status') != 'running'
                or task.get('terminal') or task.get('cancel_requested')
                or (response.session_state or {}).get('factory_envelope') != {'plan_ref': task['plan_id'],
                    'user_id': task['owner_id'], 'task_id': task['id'], 'request_id': task['request_id']}):
            raise PermissionError('Original active workflow ticket required')
        root = RunContext(run_id=run_id, session_id=task['id'], user_id=response.user_id,
                          workflow_id=identifier, session_state=response.session_state)
        self.store.bind_run(root)
        return root

    def _validator(self, identifier, step):
        def validate(response, task, plan):
            registration = self.registrations[identifier]
            if not any(node is step for node in _nodes(registration.component.steps)) or response.agent_id != step.agent.id:
                raise PermissionError('Original registered decision step required')
            root = self._root(identifier, response)
            actual_step_id = response.workflow_step_id
            if actual_step_id is not None:
                # Agno's OS copies mint runtime step UUIDs; continuation restores
                # those original UUIDs. A declaration ID is not that runtime ID.
                from agno.db.base import SessionType
                session = self.native_db.get_session(root.session_id,
                    session_type=SessionType.WORKFLOW, user_id=root.user_id)
                if session is None or session.session_id != root.session_id or session.user_id != root.user_id or session.workflow_id != identifier:
                    raise PermissionError('Original native workflow session required')
                runs = [run for run in session.runs or [] if run.run_id == root.run_id and run.workflow_id == identifier
                    and run.session_id == root.session_id and run.user_id == root.user_id]
                if len(runs) != 1:
                    raise PermissionError('Original native workflow run required')
                run = runs[0]
                children = [child for child in run.step_executor_runs or [] if child.run_id == response.run_id]
                if not children or any(child.agent_id != step.agent.id or child.parent_run_id != root.run_id
                        or child.session_id != root.session_id or child.user_id != root.user_id
                        or child.workflow_step_id != actual_step_id for child in children):
                    raise PermissionError('Original native executor continuation required')
                def results(items):
                    for item in items or []:
                        yield item
                        yield from results(getattr(item, 'steps', None))
                matched = any(item.step_id == actual_step_id and item.step_name == step.name
                    for item in results(run.step_results)) or any(req.step_id == actual_step_id
                    and req.step_name == step.name and req.executor_run_id == response.run_id
                    and req.executor_id == step.agent.id for req in run.step_requirements or [])
                if not matched:
                    raise PermissionError('Original registered native step required')
            root.metadata = {'factory_native_step_id': actual_step_id}
            return root
        return validate

    def _wrap(self, identifier, step):
        original = step.executor
        accepts_context = 'run_context' in inspect.signature(original).parameters
        accepts_application = 'application_context' in inspect.signature(original).parameters

        def arguments(root):
            values = {'run_context': root} if accepts_context else {}
            if accepts_application:
                from ._application_context import FactoryApplicationContext
                values['application_context'] = FactoryApplicationContext(self.store, root, step.name)
            return values

        def authorize(run_context):
            if not isinstance(run_context, RunContext) or run_context.workflow_id not in (None, identifier):
                raise PermissionError('Native workflow context required')
            root = self._root(identifier, run_context)
            if root.run_id != run_context.run_id:
                raise PermissionError('Original workflow run required')
            self.store.authorize_tool(root, step.name)
            self.store.delegation.consume_tool_budget(root, f'native-step:{step.step_id}', step.name)
            return root

        if inspect.iscoroutinefunction(original):
            @wraps(original)
            async def async_wrapped(step_input, run_context):
                root = authorize(run_context)
                return await original(step_input, **arguments(root))
            wrapped: Any = async_wrapped
        else:
            @wraps(original)
            def sync_wrapped(step_input, run_context):
                root = authorize(run_context)
                return original(step_input, **arguments(root))
            wrapped = sync_wrapped
        # Agno inspects the executor signature to decide context injection.
        wrapped.__signature__ = inspect.Signature([
            inspect.Parameter('step_input', inspect.Parameter.POSITIONAL_OR_KEYWORD),
            inspect.Parameter('run_context', inspect.Parameter.POSITIONAL_OR_KEYWORD)])
        step.executor = wrapped
        step._set_active_executor()
