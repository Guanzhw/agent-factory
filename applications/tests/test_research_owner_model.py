"""Real text adapter and native wrappers; synthetic authority/HTTP, no live provider."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

from agno.db.sqlite import SqliteDb
from agno.run import RunContext
from agno.workflow.types import StepInput, StepOutput
import httpx
from pydantic import ValidationError

from agent_factory.byok_model import ADAPTER_ID, OwnerChatModel
from agent_factory.execution_bindings import BindingContext
from agent_factory.native_workflows import NativeWorkflows
from agent_factory.personal_remote_provider import SecretLease
from research.workflow import Decision, Evaluation, FUNCTION_TOOLS, ResearchWorkflow


class ResearchOwnerModelTests(unittest.IsolatedAsyncioTestCase):
    def harness(self, replies):
        calls = []
        credentials = Mock(return_value=SecretLease('api-key', 'synthetic-research-key'))
        recheck = Mock()
        def wire(request):
            value = json.loads(request.content)
            calls.append(value)
            return httpx.Response(200, json={'choices': [{'finish_reason': 'stop',
                'message': {'role': 'assistant', 'content': replies[len(calls) - 1]}}],
                'usage': {'prompt_tokens': 12, 'completion_tokens': 4, 'total_tokens': 16}})
        def selected(binding):
            return OwnerChatModel({'provider': 'openai-compatible', 'model': 'member-selected-text-model',
                'baseURL': 'https://synthetic.invalid/v1'}, credentials,
                transport_factory=lambda: httpx.MockTransport(wire), recheck=recheck)
        rounds = SimpleNamespace(context=Mock(return_value={'agreement': {'objective': 'Synthetic goal'}, 'evidenceIds': []}),
            launch=AsyncMock(return_value={'id': 'original-operation'}),
            results=Mock(return_value={'operation': {'state': 'COMPLETED', 'output': {'result': 'actual fixture output'}},
                'evidenceIds': ['original-operation']}), record_decision=Mock(return_value={'recorded': True}))
        task = {'id': 'original-task', 'plan_id': 'original-plan', 'run_id': 'original-run',
                'owner_id': 'alice', 'request_id': 'original-request'}
        plan = {'tools': [*FUNCTION_TOOLS, 'factory_wait_operations'],
                'executionBindings': {'model': {'adapterId': ADAPTER_ID}}}
        store = SimpleNamespace(task=Mock(return_value=task), plan=Mock(return_value=plan), bind_run=Mock(),
            resolve_run=Mock(return_value=plan), require_plan_execution=Mock(), cancellation_requested=Mock(return_value=False),
            authorize_tool=Mock(), delegation=SimpleNamespace(consume_tool_budget=Mock()), event=Mock())
        bindings = SimpleNamespace(store=store, model_from_binding=Mock(side_effect=selected),
            manifest=Mock(return_value={'sha256': 'a' * 64}))
        bindings.resolve = Mock(side_effect=lambda p, ctx: {'model': BindingContext(None, store, p, ctx, {})})
        store.execution_bindings = bindings
        folder = TemporaryDirectory(); self.addCleanup(folder.cleanup)
        native_db = SqliteDb(db_file=str(Path(folder.name) / 'native.sqlite'))
        self.addCleanup(native_db.db_engine.dispose)
        native_db.get_job = lambda *_: {'id': task['run_id'], 'session_id': task['id'], 'user_id': 'alice',
            'component_type': 'workflow', 'component_id': 'research-round', 'status': 'running'}
        workflow = ResearchWorkflow(); workflow.bind(rounds)
        bridge = NativeWorkflows(store, SimpleNamespace(require_member=Mock()), native_db, [workflow.registration])
        plan['nativeComponent'] = bridge.pin('research-round')
        context = RunContext(run_id=task['run_id'], session_id=task['id'], user_id='alice', workflow_id='research-round',
            session_state={'factory_envelope': {'plan_ref': task['plan_id'], 'task_id': task['id'],
                'user_id': 'alice', 'request_id': task['request_id']}})
        return SimpleNamespace(workflow=workflow.registration.component, steps={s.name: s for s in workflow.registration.component.steps},
            rounds=rounds, context=context, calls=calls, store=store, credentials=credentials, recheck=recheck, bindings=bindings)

    async def model_step(self, harness, name):
        ctx = harness.context
        response = await harness.steps[name].agent.arun('Synthetic original evidence',
            session_id=ctx.session_id, user_id=ctx.user_id, session_state=ctx.session_state)
        return StepOutput(content=response.content)

    def assert_original_wire(self, harness, count):
        self.assertEqual(len(harness.calls), count)
        self.assertEqual(harness.credentials.call_count, count)
        self.assertEqual(harness.recheck.call_count, count * 2)
        self.assertEqual(harness.bindings.model_from_binding.call_count, count)
        for body in harness.calls:
            self.assertEqual(body['model'], 'member-selected-text-model')
            self.assertNotIn('response_format', body)
        self.assertGreater(harness.store.require_plan_execution.call_count, 0)

    async def test_real_owner_model_json_decision_and_evaluation_keep_native_guards(self):
        h = self.harness([json.dumps({'action': 'experiment', 'reason': 'Measure', 'hypothesis': 'H',
            'conditions': 'C', 'goal': 'G'}), json.dumps({'action': 'stop', 'outcome': 'not_met',
            'reason': 'Actual negative result', 'evidenceIds': ['original-operation']})])
        initial = await self.model_step(h, 'research_decide')
        await h.steps['research_launch'].executor(StepInput(previous_step_outputs={'research_decide': initial}), h.context)
        h.rounds.launch.assert_awaited_once()
        evaluated = await self.model_step(h, 'research_evaluate')
        await h.steps['research_record_decision'].executor(StepInput(previous_step_outputs={'research_evaluate': evaluated}), h.context)
        self.assertEqual(h.rounds.record_decision.call_args.args[1]['outcome'], 'not_met')
        self.assert_original_wire(h, 2)
        self.assertEqual([call.args[2] for call in h.store.delegation.consume_tool_budget.call_args_list],
                         ['research_launch', 'research_record_decision'])
        for name, schema in (('research_decide', Decision), ('research_evaluate', Evaluation)):
            self.assertIsNone(h.steps[name].agent.output_schema)
            self.assertIn(json.dumps(schema.model_json_schema(), ensure_ascii=False), h.steps[name].agent.instructions)
        self.assertIsNone(h.steps['research_wait'].agent.output_schema)

    async def test_invalid_initial_json_never_launches_child_or_reasks_model(self):
        for reply in ('not json', '```json\n{"action":"stop"}\n```',
                      '{"action":"experiment","reason":"Missing experiment fields"}',
                      '{"action":"stop","outcome":"met","reason":"No evidence"}',
                      '{"action":"stop","outcome":"not_met","reason":"No route","owner":"bob"}'):
            with self.subTest(reply=reply):
                h = self.harness([reply])
                initial = await self.model_step(h, 'research_decide')
                with self.assertRaises(ValidationError):
                    await h.steps['research_launch'].executor(StepInput(previous_step_outputs={'research_decide': initial}), h.context)
                h.rounds.launch.assert_not_awaited()
                h.rounds.record_decision.assert_not_called()
                self.assert_original_wire(h, 1)

    async def test_invalid_evaluation_keeps_original_child_without_final_decision(self):
        h = self.harness([json.dumps({'action': 'experiment', 'reason': 'Measure', 'hypothesis': 'H',
            'conditions': 'C', 'goal': 'G'}), '{"action":"stop","outcome":"met","reason":"No source","evidenceIds":[]}'])
        initial = await self.model_step(h, 'research_decide')
        await h.steps['research_launch'].executor(StepInput(previous_step_outputs={'research_decide': initial}), h.context)
        evaluated = await self.model_step(h, 'research_evaluate')
        with self.assertRaises(ValidationError):
            await h.steps['research_record_decision'].executor(StepInput(previous_step_outputs={'research_evaluate': evaluated}), h.context)
        h.rounds.launch.assert_awaited_once()
        h.rounds.record_decision.assert_not_called()
        self.assert_original_wire(h, 2)

    async def test_actual_workflow_stop_returns_without_child(self):
        h = self.harness(['{"action":"stop","outcome":"not_met","reason":"No justified experiment"}'])
        ctx = h.context
        result = await h.workflow.arun(input={'goal': 'Synthetic goal'}, run_id=ctx.run_id,
            session_id=ctx.session_id, user_id=ctx.user_id, session_state=ctx.session_state)
        self.assertEqual(result.status.value, 'COMPLETED')
        h.rounds.launch.assert_not_awaited()
        h.rounds.record_decision.assert_called_once()
        self.assert_original_wire(h, 1)

    async def test_current_credential_and_native_tool_budget_denials_are_not_bypassed(self):
        h = self.harness(['{"action":"stop","outcome":"not_met","reason":"No experiment"}'])
        h.credentials.side_effect = PermissionError('Synthetic credential revoked')
        ctx = h.context
        response = await h.steps['research_decide'].agent.arun('Synthetic original evidence',
            session_id=ctx.session_id, user_id=ctx.user_id, session_state=ctx.session_state)
        self.assertEqual(response.status.value, 'ERROR')
        self.assertEqual(response.content, 'PERSONAL_MODEL_REQUEST_FAILED')
        self.assertEqual(h.credentials.call_count, 1)
        self.assertEqual(h.calls, [])
        h.rounds.launch.assert_not_awaited()
        h.rounds.record_decision.assert_not_called()

        h = self.harness(['{"action":"experiment","reason":"Measure","hypothesis":"H","conditions":"C","goal":"G"}'])
        initial = await self.model_step(h, 'research_decide')
        h.store.delegation.consume_tool_budget.side_effect = PermissionError('Synthetic original tool budget exhausted')
        with self.assertRaises(PermissionError):
            await h.steps['research_launch'].executor(StepInput(previous_step_outputs={'research_decide': initial}), h.context)
        h.rounds.launch.assert_not_awaited()
        h.rounds.record_decision.assert_not_called()
        self.assert_original_wire(h, 1)
