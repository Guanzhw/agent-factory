"""Native ORX profile boundaries with inert services; no ORX/provider/DB execution."""
from contextlib import nullcontext
from dataclasses import dataclass, replace
import json
from types import SimpleNamespace
from typing import cast
import unittest
from unittest.mock import AsyncMock, Mock

from agno.exceptions import RunCancelledException
from agno.models.message import Message
from agno.run import RunContext
from agent_factory import autoresearch_profile as profile
from agent_factory.applications import ApplicationDefinition
from agent_factory.execution_bindings import BindingContext
from agent_factory.material_governance import MaterialDefinition, MaterialGovernance
from agent_factory.plan_policy import tools_for_contract
from agent_factory.model_dispatch import DelegatingModel
from agent_factory.usage_ledger import zero_local_usage


@dataclass
class Preset:
    id: str = 'approved-project'
    owner_id: str = 'alice'
    name: str = 'Approved public research'
    instructions: str = 'Use original evidence; evaluate independently.'

    def public_context(self):
        return {'name': self.name, 'instructions': self.instructions,
                'manifest': {'schema': 1, 'originalSource': 'synthetic-test-only'}}


def context():
    preset = Preset()
    store = SimpleNamespace(autoresearch=SimpleNamespace(
        execute=AsyncMock(return_value={'status': 'reported', 'originalSessionId': 'original-session'}),
        tool=AsyncMock(return_value={'status': 'original-evidence'})),
        authorize_tool=Mock(), usage_ledger=Mock())
    return BindingContext(SimpleNamespace(demo=True, autoresearch_presets={preset.id: preset}), store,
        {'ownerId': 'alice', 'application': profile.APPLICATION_ID, 'applicationRef': {'id': profile.APPLICATION_ID},
         'mode': 'research', 'tools': list(profile.TOOL_NAMES), 'capabilities': list(profile.PERMISSIONS)},
        RunContext(user_id='alice', session_id='original-task', run_id='original-run'),
        {'adapterId': profile.MODEL_ADAPTER_ID, 'revision': '1', 'config': {'presetId': preset.id}})


class AutoResearchProfileTests(unittest.IsolatedAsyncioTestCase):
    async def test_entire_native_response_delegates_once_appends_terminal_message_no_provider_or_ledger(self):
        ctx = context(); model = profile.ORXResearchModel(ctx)
        messages = [Message(role='user', content='Research the approved goal')]
        model.invoke = Mock(side_effect=AssertionError('No provider'))
        model.ainvoke = AsyncMock(side_effect=AssertionError('No provider'))
        # Actual dispatcher accounting wraps invoke only; this response never enters it.
        ledger, current = ctx.store.usage_ledger, Mock()
        DelegatingModel._guard_provider_calls(model, current, ledger=ledger, plan=ctx.plan, context=ctx.run_context)
        result = await model.aresponse(messages, tools=[{'unused': 'ORX owns tool loop'}])
        ctx.store.autoresearch.execute.assert_awaited_once_with(ctx)
        self.assertEqual(json.loads(cast(str, result.content))['originalSessionId'], 'original-session')
        self.assertEqual(messages[-1].role, 'assistant'); self.assertEqual(messages[-1].content, result.content)
        self.assertFalse(result.tool_calls); self.assertIsNone(result.response_usage)
        self.assertEqual((model.id, model.provider, model.retries), ('deepseek-flash', 'opencode-go-development', 0))
        self.assertEqual(ledger.mock_calls, []); current.assert_not_called()

    async def test_stream_emits_one_terminal_response_and_executes_only_once(self):
        ctx = context(); model = profile.ORXResearchModel(ctx); messages = []
        result = [item async for item in model.aresponse_stream(messages=messages)]
        self.assertEqual(len(result), 1); self.assertEqual(len(messages), 1)
        ctx.store.autoresearch.execute.assert_awaited_once_with(ctx)

    async def test_cancellation_and_unknown_are_preserved_without_retry_or_assistant_success(self):
        for error in (RunCancelledException('synthetic cancel'), ValueError('AUTORESEARCH_UNKNOWN')):
            ctx = context(); ctx.store.autoresearch.execute.side_effect = error
            model = profile.ORXResearchModel(ctx); messages = []
            with self.assertRaises(type(error)) as caught: await model.aresponse(messages)
            self.assertIs(caught.exception, error)
            ctx.store.autoresearch.execute.assert_awaited_once(); self.assertEqual(messages, [])

    async def test_all_nonresponse_paths_fail_closed_without_service_execution(self):
        ctx = context(); model = profile.ORXResearchModel(ctx)
        for call in (lambda: model.response([]), lambda: list(model.response_stream([])),
                     lambda: model.invoke([]), lambda: list(model.invoke_stream([])),
                     lambda: model._parse_provider_response({}), lambda: model._parse_provider_response_delta({})):
            with self.assertRaises(ValueError): call()
        with self.assertRaises(ValueError): await model.ainvoke([])
        with self.assertRaises(ValueError): _ = [item async for item in model.ainvoke_stream([])]
        ctx.store.autoresearch.execute.assert_not_awaited()

    async def test_current_preset_owner_scope_checked_again_before_execute(self):
        ctx = context(); model = profile.ORXResearchModel(ctx)
        ctx.settings.autoresearch_presets['approved-project'].owner_id = 'bob'
        with self.assertRaises(ValueError): await model.aresponse([])
        ctx.store.autoresearch.execute.assert_not_awaited()
        for change in ({'application': 'other'}, {'mode': 'other'}, {'ownerId': 'bob'},
                       {'delegation': {'parent': 'x'}}, {'tools': ['research_context']}):
            fresh = context()
            with self.subTest(change=change), self.assertRaises(ValueError):
                profile.ORXResearchModel(replace(fresh, plan={**fresh.plan, **change}))

    async def test_catalog_tools_route_exact_original_context_and_name(self):
        ctx = context()
        for entry in profile.registrations():
            if entry.kind != 'tool': continue
            ctx.store.autoresearch.tool.reset_mock(); ctx.store.authorize_tool.reset_mock()
            function = entry.factory(ctx)
            payload = {'requestId': 'original-tool-call', 'hypothesis': 'inert synthetic hypothesis'}
            result = await function.entrypoint(run_context=ctx.run_context, payload=payload)
            ctx.store.autoresearch.tool.assert_awaited_once_with(ctx, entry.tool_name, payload)
            self.assertEqual(json.loads(result)['status'], 'original-evidence')
            self.assertEqual(ctx.store.authorize_tool.call_count, 2)
            with self.assertRaises(ValueError):
                await function.entrypoint(run_context=RunContext(user_id='bob', session_id='other', run_id='other'), payload={})

    def test_governed_materials_application_and_trusted_knowledge(self):
        rows = profile.material_drafts('approved-project')
        self.assertEqual(len(rows), 10)
        for row in rows: MaterialDefinition.model_validate(row)
        published = [dict(row, version=1, sha256='a'*64) for row in rows]
        limits = {'toolCalls': 32, 'maxDepth': 1, 'maxChildren': 1, 'experimentSeconds': 30, 'outputBytes': 65536}
        definition = profile.application_definition(published, 'approved-project', limits=limits)
        ApplicationDefinition.model_validate(definition)
        limits['toolCalls'] = 1
        self.assertEqual(definition['modes']['research']['budget']['toolCalls'], 32)
        entries = {entry.kind: entry for entry in profile.registrations() if entry.kind != 'tool'}
        knowledge = entries['knowledge'].factory(context())
        self.assertEqual(json.loads(knowledge.content)['instructions'], Preset().instructions)
        self.assertEqual(entries['environment'].factory(context()).runtime_id, profile.RUNTIME_ID)
        for bad in ({'presetId': 'x', 'command': 'x'}, {'presetId': '../x'}, {'presetId': True}):
            with self.assertRaises(ValueError): profile._config(bad)

    def test_actual_governance_validation_matches_registered_tool_catalog(self):
        # Run the real validation function; only the persisted config read is inert.
        governance = object.__new__(MaterialGovernance)
        governance._read = Mock(side_effect=lambda: nullcontext(None))
        catalog = tools_for_contract('autoresearch-session-v1')
        governance._config = Mock(return_value=SimpleNamespace(known_tools=catalog))
        registered = {entry.tool_name: entry for entry in profile.registrations() if entry.kind == 'tool'}
        for material in profile.material_drafts('approved-project'):
            checked = governance.validate_definition(material)
            if material['kind'] == 'tool':
                name = checked['content']
                self.assertIn(name, catalog)
                self.assertEqual(checked['permissions'], [catalog[name]])
                self.assertEqual(registered[name].permissions, (catalog[name],))
                self.assertEqual(checked['description'], profile.DESCRIPTIONS[name])

    async def test_all_development_registrations_reject_production_context(self):
        entries = profile.registrations()
        self.assertTrue(all(entry.demo_only is True for entry in entries))
        ctx = context(); ctx.settings.demo = False
        for entry in entries:
            with self.subTest(kind=entry.kind), self.assertRaises(ValueError): entry.factory(ctx)
        ctx = context(); model = profile.ORXResearchModel(ctx)
        ctx.settings.demo = False
        with self.assertRaises(ValueError): await model.aresponse([])
        ctx.store.autoresearch.execute.assert_not_awaited()

    def test_session_resource_contract_is_explicit_and_reviewable(self):
        self.assertEqual(dict(profile.SESSION_RESOURCE_LIMITS),
            {'cpus': 1, 'memoryMb': 1024, 'pids': 64, 'maxSessionSeconds': 3600})
        registration = next(row for row in profile.registrations() if row.kind == 'environment')
        limits = registration.factory(context())
        self.assertEqual((limits.memory_bytes, limits.process_limit, limits.cpu_percent), (1024**3, 64, 100))
        self.assertEqual((limits.timeout_seconds, limits.output_bytes), (30, 65536))
        material = next(row for row in profile.material_drafts('approved-project') if row['kind'] == 'environment')
        content = json.loads(material['content'])
        self.assertEqual(content['sessionResourceLimits'], dict(profile.SESSION_RESOURCE_LIMITS))
        self.assertEqual(content['adapterRevision'], registration.revision)
        self.assertEqual(content['nativePhaseTimeoutSeconds'], 30)
        self.assertIn('3600', material['description'])
        MaterialDefinition.model_validate(material)

    def test_broker_pricing_is_authoritative_and_request_body_is_bounded(self):
        price = profile.pricing_registration()
        self.assertIsNone(price.local_model_type); self.assertIsNot(price.usage_reader, zero_local_usage)
        self.assertIsNone(price.usage_reader({'arbitrary': 'usage'}))
        model = profile.ORXResearchModel(context())
        body = {'model': 'deepseek-flash', 'stream': True, 'messages': [{'role': 'user', 'content': 'inert'}], 'max_tokens': 32}
        profile.request_guard(model, (body,), {}, price.body)
        for change in ({'model': 'alias'}, {'stream': False}, {'messages': []}, {'max_tokens': True},
                       {'max_tokens': price.per_attempt_output_tokens+1}, {'max_completion_tokens': 32},
                       {'messages': [{'content': 'x' * price.per_attempt_input_tokens}]}):
            with self.subTest(change=list(change)), self.assertRaises(ValueError):
                profile.request_guard(model, ({**body, **change},), {}, price.body)
        callback, usage = Mock(), Mock()
        custom = profile.pricing_registration(request_guard=callback, usage_reader=usage)
        self.assertIs(custom.request_guard, callback); self.assertIs(custom.usage_reader, usage)
