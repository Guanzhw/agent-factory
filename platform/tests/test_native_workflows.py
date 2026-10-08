"""Native registration only: no provider, process, or queue execution."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock
from unittest import TestCase
from agno.run import RunContext
from agno.agent import Agent
from agent_factory.workflow_model import WorkflowDecisionModel
from agno.workflow.workflow import Workflow
from agno.workflow.step import Step
from agno.workflow.types import HumanReview, OnError
from agno.workflow.loop import Loop
from fastapi import HTTPException
from agent_factory.native_workflows import NativeWorkflowRegistration, NativeWorkflows


def operation(step_input):
    return step_input


class NativeWorkflowsTests(TestCase):
    def setUp(self):
        self.auth = SimpleNamespace(require=Mock())

    def registration(self):
        return NativeWorkflowRegistration(Workflow(id='test-workflow', name='Test', steps=[
            Step(name='protected', step_id='protected-v1', executor=operation, max_retries=0, human_review=HumanReview(on_error=OnError.fail))]), '1', ('protected',), 'a' * 64)

    def test_pin_excludes_runtime_database_session(self):
        registration = self.registration()
        bridge = NativeWorkflows(SimpleNamespace(), self.auth, object(), [registration])
        before = bridge.pin('test-workflow')
        registration.component.session_id = 'runtime-session'
        registration.component.user_id = 'runtime-owner'
        registration.component.session_state = {'runtime': 'value'}
        self.assertEqual(bridge.pin('test-workflow'), before)
        registration.component.steps[0].description = 'changed'
        with self.assertRaises(HTTPException):
            bridge.pin('test-workflow')

    def test_retries_loop_and_implicit_step_ids_rejected(self):
        for change in ('retry', 'loop', 'implicit'):
            registration = self.registration()
            if change == 'retry':
                registration.component.steps[0].max_retries = 1
            elif change == 'loop':
                registration.component.steps = [Loop(steps=registration.component.steps)]
            else:
                registration.component.steps = [Step(name='protected', executor=operation, max_retries=0, human_review=HumanReview(on_error=OnError.fail))]
            with self.assertRaises(ValueError):
                NativeWorkflows(SimpleNamespace(), self.auth, None, [registration])

    def test_function_cannot_run_without_native_context(self):
        registration = self.registration()
        NativeWorkflows(SimpleNamespace(), self.auth, None, [registration])
        with self.assertRaises(PermissionError):
            registration.component.steps[0].executor(None, None)

    def test_plan_pin_and_tool_closure(self):
        bridge = NativeWorkflows(SimpleNamespace(), self.auth, None, [self.registration()])
        pin = bridge.pin('test-workflow')
        bridge.require_plan_current('alice', {'nativeComponent': pin, 'tools': ['protected']})
        with self.assertRaises(HTTPException):
            bridge.require_plan_current('alice', {'nativeComponent': pin, 'tools': []})

    def test_original_ticket_authority_and_budget_precede_effect(self):
        events = []
        registration = self.registration()
        registration.component.steps[0].executor = lambda step_input: events.append('effect')
        task = {'id': 'task', 'plan_id': 'plan', 'run_id': 'run', 'owner_id': 'alice', 'request_id': 'request'}
        plan = {'tools': ['protected']}
        store = SimpleNamespace(task=lambda *args: task, plan=lambda *args: plan,
            bind_run=lambda ctx: events.append('bind'),
            authorize_tool=lambda ctx, name: events.append('authorize'),
            delegation=SimpleNamespace(consume_tool_budget=lambda *args: events.append('budget')))
        ticket = {'id': 'run', 'session_id': 'task', 'user_id': 'alice',
                  'component_type': 'workflow', 'component_id': 'test-workflow', 'status': 'running'}
        bridge = NativeWorkflows(store, self.auth, SimpleNamespace(get_job=lambda run: ticket), [registration])
        plan['nativeComponent'] = bridge.pin('test-workflow')
        context = RunContext(run_id='run', session_id='task', user_id='alice', workflow_id='test-workflow',
                             session_state={'factory_envelope': {'plan_ref': 'plan', 'user_id': 'alice',
                             'task_id': 'task', 'request_id': 'request'}})
        registration.component.steps[0].executor(None, context)
        self.assertEqual(events, ['bind', 'authorize', 'budget', 'effect'])
        self.auth.require.assert_called_with('alice', 'run', 'workflows', 'test-workflow')
        original_ticket = deepcopy(ticket)
        original_envelope = deepcopy(context.session_state)
        for key in ('id', 'session_id', 'user_id', 'component_type', 'component_id', 'status'):
            ticket[key] = 'changed'
            with self.subTest(ticket_field=key), self.assertRaises(PermissionError):
                registration.component.steps[0].executor(None, context)
            ticket.clear(); ticket.update(original_ticket)
        for key in ('plan_ref', 'user_id', 'task_id', 'request_id'):
            context.session_state['factory_envelope'][key] = 'changed'
            with self.subTest(envelope_field=key), self.assertRaises(PermissionError):
                registration.component.steps[0].executor(None, context)
            context.session_state = deepcopy(original_envelope)
        self.assertEqual(events, ['bind', 'authorize', 'budget', 'effect'])
        task['cancel_requested'] = True
        with self.assertRaises(PermissionError):
            registration.component.steps[0].executor(None, context)
        self.assertEqual(events.count('effect'), 1)

    def test_decision_model_replaced_and_instruction_drift_rejected(self):
        agent = Agent(id='decision-agent', instructions=['Choose a route'])
        registration = NativeWorkflowRegistration(Workflow(id='decision-workflow', steps=[
            Step(name='decision', step_id='decision-v1', agent=agent, max_retries=0, human_review=HumanReview(on_error=OnError.fail))]), '1', (), 'a' * 64)
        bridge = NativeWorkflows(SimpleNamespace(execution_bindings=SimpleNamespace()), self.auth, None, [registration])
        self.assertIsInstance(agent.model, WorkflowDecisionModel)
        bridge.pin('decision-workflow')
        agent.instructions = ['Changed instruction']
        with self.assertRaises(HTTPException):
            bridge.pin('decision-workflow')

    def test_only_fixed_wait_tool_outside_parallel_allowed(self):
        from agno.workflow.parallel import Parallel
        from agno.tools import tool
        from agent_factory.native_external_wait import factory_wait_operations
        agent = Agent(id='wait-agent', tools=[factory_wait_operations])
        step = Step(name='wait', step_id='wait-v1', agent=agent, max_retries=0, human_review=HumanReview(on_error=OnError.fail))
        registration = NativeWorkflowRegistration(Workflow(id='wait-workflow', steps=[step]), '1', (), 'a' * 64)
        bridge = NativeWorkflows(SimpleNamespace(execution_bindings=SimpleNamespace()), self.auth, None, [registration])
        bridge.pin('wait-workflow')
        registration.component.steps = [Parallel(step)]
        with self.assertRaises(ValueError):
            NativeWorkflows(SimpleNamespace(), self.auth, None, [registration])
        @tool(external_execution=True)
        def unapproved(operationIds: list[str]) -> str:
            return 'unreachable'
        agent.tools = [unapproved]
        registration.component.steps = [step]
        with self.assertRaises(ValueError):
            NativeWorkflows(SimpleNamespace(), self.auth, None, [registration])

    def test_current_workflow_authority_is_required_before_function_effect(self):
        registration = self.registration()
        bridge = NativeWorkflows(SimpleNamespace(), self.auth, None, [registration])
        plan = {'nativeComponent': bridge.pin('test-workflow'), 'tools': ['protected']}
        self.auth.require.side_effect = HTTPException(403, 'CONTROLLED_REVOKED')
        with self.assertRaises(HTTPException) as raised:
            bridge.require_plan_current('alice', plan)
        self.assertEqual(raised.exception.status_code, 403)
        self.auth.require.assert_called_once_with('alice', 'run', 'workflows', 'test-workflow')

    def test_plan_input_schema_must_match_registered_native_schema(self):
        from agent_factory.input_schema import input_model
        schema = {'type': 'object', 'additionalProperties': False, 'required': ['scenario'],
                  'properties': {'scenario': {'type': 'string', 'maxLength': 20, 'enum': ['controlled']}}}
        registration = self.registration()
        registration.component.input_schema = input_model(schema)
        bridge = NativeWorkflows(SimpleNamespace(), self.auth, None, [registration])
        plan = {'nativeComponent': bridge.pin('test-workflow'), 'tools': ['protected'], 'inputSchema': schema}
        bridge.require_plan_current('alice', plan)
        changed = deepcopy(plan)
        changed['inputSchema']['properties']['scenario']['enum'] = ['different']
        with self.assertRaises(HTTPException) as raised:
            bridge.require_plan_current('alice', changed)
        self.assertEqual(raised.exception.detail, 'NATIVE_WORKFLOW_INPUT_SCHEMA_CHANGED')
        registration.component.input_schema = input_model(changed['inputSchema'])
        with self.assertRaises(HTTPException):
            bridge.require_plan_current('alice', plan)

    def test_external_wait_requires_exact_governed_wait_tool_policy(self):
        from agent_factory.native_external_wait import factory_wait_operations
        agent = Agent(id='wait-agent', tools=[factory_wait_operations])
        registration = NativeWorkflowRegistration(Workflow(id='wait-workflow', steps=[
            Step(name='wait', step_id='wait-v1', agent=agent, max_retries=0, human_review=HumanReview(on_error=OnError.fail))]), '1', (), 'a' * 64)
        bridge = NativeWorkflows(SimpleNamespace(execution_bindings=SimpleNamespace()), self.auth, None, [registration])
        plan = {'nativeComponent': bridge.pin('wait-workflow'), 'tools': []}
        with self.assertRaises(HTTPException) as raised:
            bridge.require_plan_current('alice', plan)
        self.assertEqual(raised.exception.detail, 'NATIVE_WORKFLOW_WAIT_POLICY_MISSING')
        plan['tools'] = ['factory_wait_operations']
        bridge.require_plan_current('alice', plan)
        self.auth.require.assert_called_with('alice', 'run', 'workflows', 'wait-workflow')

    def test_same_name_executor_replacement_rejected(self):
        registration = self.registration()
        bridge = NativeWorkflows(SimpleNamespace(), self.auth, None, [registration])
        original = registration.component.steps[0].executor
        def replacement(step_input): return step_input
        replacement.__name__ = original.__name__
        replacement.__qualname__ = original.__qualname__
        registration.component.steps[0].executor = replacement
        with self.assertRaises((HTTPException, ValueError)):
            bridge.pin('test-workflow')

    def test_same_name_selector_replacement_rejected(self):
        from agno.workflow.router import Router
        def select(step_input): return ['protected']
        registration = self.registration()
        router = Router(name='route', selector=select, choices=registration.component.steps)
        registration.component.steps = [router]
        bridge = NativeWorkflows(SimpleNamespace(), self.auth, None, [registration])
        def replacement(step_input): return ['protected']
        replacement.__name__ = select.__name__
        replacement.__qualname__ = select.__qualname__
        router.selector = replacement
        with self.assertRaises((HTTPException, ValueError)):
            bridge.pin('test-workflow')

    def test_decision_hooks_and_output_schema_drift_rejected(self):
        for field, value in [('pre_hooks', [lambda: None]),
                             ('output_schema', {'type': 'object', 'properties': {'changed': {'type': 'string'}}})]:
            with self.subTest(field=field):
                agent = Agent(id='decision-agent', instructions=['Fixed decision'])
                registration = NativeWorkflowRegistration(Workflow(id='decision-workflow', steps=[
                    Step(name='decision', step_id='decision-v1', agent=agent, max_retries=0, human_review=HumanReview(on_error=OnError.fail))]), '1', (), 'a' * 64)
                bridge = NativeWorkflows(SimpleNamespace(execution_bindings=SimpleNamespace()), self.auth, None, [registration])
                bridge.pin('decision-workflow')
                setattr(agent, field, value)
                with self.assertRaises((HTTPException, ValueError)):
                    bridge.pin('decision-workflow')

    def test_implementation_commitment_changes_registered_pin(self):
        original = self.registration()
        first = NativeWorkflows(SimpleNamespace(), self.auth, None, [original]).pin('test-workflow')
        replacement = self.registration()
        replacement = NativeWorkflowRegistration(replacement.component, '1', ('protected',), 'b' * 64)
        second = NativeWorkflows(SimpleNamespace(), self.auth, None, [replacement]).pin('test-workflow')
        self.assertNotEqual(first['sha256'], second['sha256'])

    def test_active_executor_replacement_rejected_even_when_executor_unchanged(self):
        registration = self.registration()
        bridge = NativeWorkflows(SimpleNamespace(), self.auth, None, [registration])
        step = registration.component.steps[0]
        original = step.executor
        def replacement(step_input): return step_input
        step.active_executor = replacement
        self.assertIs(step.executor, original)
        with self.assertRaises(HTTPException):
            bridge.pin('test-workflow')

    def test_actual_executor_type_change_rejected(self):
        registration = self.registration()
        bridge = NativeWorkflows(SimpleNamespace(), self.auth, None, [registration])
        step = registration.component.steps[0]
        original = step.executor
        step._executor_type = 'agent'
        self.assertIs(step.executor, original)
        self.assertIs(step.active_executor, original)
        with self.assertRaises(HTTPException):
            bridge.pin('test-workflow')

    def test_same_json_schema_different_validation_class_cannot_replace_original(self):
        from pydantic import BaseModel, ConfigDict, ValidationError, field_validator
        class Original(BaseModel):
            model_config = ConfigDict(title='SamePublishedSchema')
            value: str
            @field_validator('value')
            @classmethod
            def approved(cls, value):
                if value != 'approved': raise ValueError('controlled restriction')
                return value
        class Replacement(BaseModel):
            model_config = ConfigDict(title='SamePublishedSchema')
            value: str
        self.assertEqual(Original.model_json_schema(), Replacement.model_json_schema())
        with self.assertRaises(ValidationError):
            Original(value='unapproved')
        self.assertEqual(Replacement(value='unapproved').value, 'unapproved')
        for field in ('input_schema', 'output_schema'):
            with self.subTest(field=field):
                agent = Agent(id='decision-agent')
                setattr(agent, field, Original)
                registration = NativeWorkflowRegistration(Workflow(id='decision-workflow', steps=[
                    Step(name='decision', step_id='decision-v1', agent=agent, max_retries=0, human_review=HumanReview(on_error=OnError.fail))]), '1', (), 'a' * 64)
                bridge = NativeWorkflows(SimpleNamespace(execution_bindings=SimpleNamespace()), self.auth, None, [registration])
                bridge.pin('decision-workflow')
                setattr(agent, field, Replacement)
                with self.assertRaises(HTTPException):
                    bridge.pin('decision-workflow')

    def test_continuation_without_workflow_id_still_requires_original_ticket(self):
        effects = []
        registration = self.registration()
        def execute(step_input, run_context):
            effects.append(run_context)
        registration.component.steps[0].executor = execute
        task = {'id': 'task', 'plan_id': 'plan', 'run_id': 'run', 'owner_id': 'alice', 'request_id': 'request'}
        plan = {'tools': ['protected']}
        store = SimpleNamespace(task=lambda *args: task, plan=lambda *args: plan,
            bind_run=Mock(), authorize_tool=Mock(),
            delegation=SimpleNamespace(consume_tool_budget=Mock()))
        ticket = {'id': 'run', 'session_id': 'task', 'user_id': 'alice',
                  'component_type': 'workflow', 'component_id': 'test-workflow', 'status': 'running'}
        bridge = NativeWorkflows(store, self.auth, SimpleNamespace(get_job=lambda run: ticket), [registration])
        plan['nativeComponent'] = bridge.pin('test-workflow')
        context = RunContext(run_id='run', session_id='task', user_id='alice', workflow_id=None,
            session_state={'factory_envelope': {'plan_ref': 'plan', 'user_id': 'alice',
                           'task_id': 'task', 'request_id': 'request'}})
        registration.component.steps[0].executor(None, context)
        self.assertEqual(effects[0].workflow_id, 'test-workflow')
        self.assertIsNone(context.workflow_id)
        for field in ('id', 'session_id', 'user_id', 'component_type', 'component_id', 'status'):
            before = ticket[field]; ticket[field] = 'foreign'
            with self.subTest(field=field), self.assertRaises(PermissionError):
                registration.component.steps[0].executor(None, context)
            ticket[field] = before
        context.workflow_id = 'foreign'
        with self.assertRaises(PermissionError):
            registration.component.steps[0].executor(None, context)
        context.workflow_id = None
        context.session_state['factory_envelope']['request_id'] = 'replacement'
        with self.assertRaises(PermissionError):
            registration.component.steps[0].executor(None, context)
        self.assertEqual(len(effects), 1)
        self.assertEqual(store.delegation.consume_tool_budget.call_count, 1)

    def test_dynamic_step_uuid_requires_original_persisted_native_lineage(self):
        from agno.db.base import SessionType
        from agno.run.agent import RunOutput
        from agno.run.workflow import WorkflowRunOutput
        from agno.session.workflow import WorkflowSession
        from agno.workflow.types import StepOutput, StepRequirement
        actual = '8b08d4df-b54e-46ba-9527-c9104826bb7a'
        agent = Agent(id='decision-agent')
        step = Step(name='decision', step_id='semantic-decision-v1', agent=agent, max_retries=0, human_review=HumanReview(on_error=OnError.fail))
        registration = NativeWorkflowRegistration(Workflow(id='decision-workflow', steps=[step]), '1', (), 'a' * 64)
        task = {'id': 'task', 'plan_id': 'plan', 'run_id': 'root', 'owner_id': 'alice', 'request_id': 'request'}
        plan = {'tools': []}
        store = SimpleNamespace(task=lambda *args: task, plan=lambda *args: plan,
                                bind_run=Mock(), execution_bindings=SimpleNamespace())
        envelope = {'factory_envelope': {'plan_ref': 'plan', 'user_id': 'alice', 'task_id': 'task', 'request_id': 'request'}}
        child = RunOutput(run_id='child', parent_run_id='root', session_id='task', user_id='alice',
            agent_id='decision-agent', workflow_id='decision-workflow', workflow_step_id=actual,
            session_state=deepcopy(envelope))
        result = StepOutput(step_id=actual, step_name='decision', step_run_id='child')
        run = WorkflowRunOutput(run_id='root', workflow_id='decision-workflow', session_id='task', user_id='alice',
                                step_executor_runs=[deepcopy(child)], step_results=[result])
        session = WorkflowSession(session_id='task', user_id='alice', workflow_id='decision-workflow', runs=[run])
        db = SimpleNamespace(get_session=Mock(return_value=session), get_job=Mock(return_value={
            'id': 'root', 'session_id': 'task', 'user_id': 'alice', 'component_type': 'workflow',
            'component_id': 'decision-workflow', 'status': 'running'}))
        bridge = NativeWorkflows(store, self.auth, db, [registration])
        plan['nativeComponent'] = bridge.pin('decision-workflow')
        validate = bridge._validator('decision-workflow', step)
        trusted = validate(child, task, plan)
        self.assertEqual(trusted.metadata, {'factory_native_step_id': actual})
        db.get_session.assert_called_with('task', session_type=SessionType.WORKFLOW, user_id='alice')
        # Require both original child identity and registered step-name evidence.
        mutations = [(child, 'run_id'), (child, 'agent_id'), (child, 'workflow_step_id'),
                     (run, 'run_id'), (run, 'session_id'), (run, 'user_id'),
                     (run.step_executor_runs[0], 'session_id'), (run.step_executor_runs[0], 'user_id'),
                     (result, 'step_name'), (session, 'user_id'),
                     (session, 'workflow_id'), (session, 'session_id')]
        for target, field in mutations:
            original = getattr(target, field)
            setattr(target, field, 'foreign')
            with self.subTest(field=field, target=type(target).__name__), self.assertRaises(PermissionError):
                validate(child, task, plan)
            setattr(target, field, original)
        # A persisted paused requirement supplies the same proof when no step result exists yet.
        run.step_results = []
        run.step_requirements = [StepRequirement(step_id=actual, step_name='decision',
            requires_executor_input=True, executor_run_id='child', executor_id='decision-agent')]
        self.assertEqual(validate(child, task, plan).metadata['factory_native_step_id'], actual)
        run.step_requirements[0].executor_run_id = 'foreign'
        with self.assertRaises(PermissionError):
            validate(child, task, plan)

    def test_guard_error_cannot_be_configured_as_successful_skip(self):
        for field in ('skip_on_failure', 'on_error'):
            with self.subTest(field=field):
                registration = self.registration()
                step = registration.component.steps[0]
                if field == 'skip_on_failure':
                    step.skip_on_failure = True
                else:
                    step.human_review.on_error = OnError.skip
                with self.assertRaises(ValueError):
                    NativeWorkflows(SimpleNamespace(), self.auth, None, [registration])
