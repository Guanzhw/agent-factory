"""Native ORX profile boundaries with inert services; no ORX/provider/DB execution."""
from agent_factory_research.services import ResearchServices, bind_registrations
from dataclasses import dataclass, replace
import json
from types import SimpleNamespace
from typing import cast
import unittest
from unittest.mock import AsyncMock, Mock, patch

from agno.exceptions import RunCancelledException
from agno.models.message import Message
from agno.run import RunContext
from agent_factory_research import autoresearch_profile as profile
from agent_factory.applications import ApplicationDefinition
from agent_factory.execution_bindings import BindingContext, ExecutionBindings
from agent_factory.material_governance import GovernanceConfig, MaterialDefinition, MaterialGovernance
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
    store = SimpleNamespace(authorize_tool=Mock(), usage_ledger=Mock())
    research = ResearchServices(factory_store=store, installed=True, autoresearch=SimpleNamespace(execute=AsyncMock(return_value={'status': 'reported', 'originalSessionId': 'original-session'}), tool=AsyncMock(return_value={'status': 'original-evidence'})))
    ctx = BindingContext(SimpleNamespace(demo=True, autoresearch_presets={preset.id: preset}), store,
        {'ownerId': 'alice', 'application': profile.APPLICATION_ID, 'applicationRef': {'id': profile.APPLICATION_ID},
         'mode': 'research', 'tools': list(profile.TOOL_NAMES), 'capabilities': list(profile.PERMISSIONS)},
        RunContext(user_id='alice', session_id='original-task', run_id='original-run'),
        {'adapterId': profile.MODEL_ADAPTER_ID, 'revision': '1', 'config': {'presetId': preset.id}})
    return ctx, research


class AutoResearchProfileTests(unittest.IsolatedAsyncioTestCase):
    async def test_rebound_factories_and_created_models_keep_their_own_graph(self):
        first, first_graph = context()
        second, second_graph = context()
        entries = profile.registrations()
        installed = bind_registrations(entries, first_graph)
        rebound = bind_registrations(installed, second_graph)
        first_model = next(row for row in installed if row.kind == 'model').factory(first)
        second_model = next(row for row in rebound if row.kind == 'model').factory(second)
        first_tool = next(row for row in installed if row.tool_name == 'research_context').factory(first)
        await first_model.aresponse([])
        first_graph.autoresearch.execute.assert_awaited_once_with(first)
        second_graph.autoresearch.execute.assert_not_awaited()
        first_graph.release()
        with self.assertRaisesRegex(ValueError, 'RESEARCH_STORE_MISMATCH'):
            await first_model.aresponse([])
        with self.assertRaisesRegex(ValueError, 'RESEARCH_STORE_MISMATCH'):
            await first_tool.entrypoint(run_context=first.run_context, payload={})
        first_graph.autoresearch.tool.assert_not_awaited()
        await second_model.aresponse([])
        second_graph.autoresearch.execute.assert_awaited_once_with(second)

    def test_graph_factory_rejects_unbound_unready_and_foreign_store(self):
        ctx, research = context()
        entry = next(row for row in profile.registrations() if row.kind == 'model')
        with self.assertRaisesRegex(ValueError, 'RESEARCH_SERVICES_NOT_READY'):
            entry.factory(ctx)
        research.installed = False
        bound = bind_registrations([entry], research)[0]
        with self.assertRaisesRegex(ValueError, 'RESEARCH_SERVICES_NOT_READY'):
            bound.factory(ctx)
        research.installed = True
        foreign, _ = context()
        with self.assertRaisesRegex(ValueError, 'RESEARCH_STORE_MISMATCH'):
            bound.factory(foreign)
        research.autoresearch.execute.assert_not_awaited()

    async def test_entire_native_response_delegates_once_appends_terminal_message_no_provider_or_ledger(self):
        ctx, research = context(); model = profile.ORXResearchModel(ctx, research=research)
        messages = [Message(role='user', content='Research the approved goal')]
        model.invoke = Mock(side_effect=AssertionError('No provider'))
        model.ainvoke = AsyncMock(side_effect=AssertionError('No provider'))
        # Actual dispatcher accounting wraps invoke only; this response never enters it.
        ledger, current = ctx.store.usage_ledger, Mock()
        DelegatingModel._guard_provider_calls(model, current, ledger=ledger, plan=ctx.plan, context=ctx.run_context)
        result = await model.aresponse(messages, tools=[{'unused': 'ORX owns tool loop'}])
        research.autoresearch.execute.assert_awaited_once_with(ctx)
        self.assertEqual(json.loads(cast(str, result.content))['originalSessionId'], 'original-session')
        self.assertEqual(messages[-1].role, 'assistant'); self.assertEqual(messages[-1].content, result.content)
        self.assertFalse(result.tool_calls); self.assertIsNone(result.response_usage)
        self.assertEqual((model.id, model.provider, model.retries), ('deepseek-flash', 'opencode-go-development', 0))
        self.assertEqual(ledger.mock_calls, []); current.assert_not_called()

    async def test_stream_emits_one_terminal_response_and_executes_only_once(self):
        ctx, research = context(); model = profile.ORXResearchModel(ctx, research=research); messages = []
        result = [item async for item in model.aresponse_stream(messages=messages)]
        self.assertEqual(len(result), 1); self.assertEqual(len(messages), 1)
        research.autoresearch.execute.assert_awaited_once_with(ctx)

    async def test_cancellation_and_unknown_are_preserved_without_retry_or_assistant_success(self):
        for error in (RunCancelledException('synthetic cancel'), ValueError('AUTORESEARCH_UNKNOWN')):
            ctx, research = context(); research.autoresearch.execute.side_effect = error
            model = profile.ORXResearchModel(ctx, research=research); messages = []
            with self.assertRaises(type(error)) as caught: await model.aresponse(messages)
            self.assertIs(caught.exception, error)
            research.autoresearch.execute.assert_awaited_once(); self.assertEqual(messages, [])

    async def test_all_nonresponse_paths_fail_closed_without_service_execution(self):
        ctx, research = context(); model = profile.ORXResearchModel(ctx, research=research)
        for call in (lambda: model.response([]), lambda: list(model.response_stream([])),
                     lambda: model.invoke([]), lambda: list(model.invoke_stream([])),
                     lambda: model._parse_provider_response({}), lambda: model._parse_provider_response_delta({})):
            with self.assertRaises(ValueError): call()
        with self.assertRaises(ValueError): await model.ainvoke([])
        with self.assertRaises(ValueError): _ = [item async for item in model.ainvoke_stream([])]
        research.autoresearch.execute.assert_not_awaited()

    async def test_current_preset_owner_scope_checked_again_before_execute(self):
        ctx, research = context(); model = profile.ORXResearchModel(ctx, research=research)
        ctx.settings.autoresearch_presets['approved-project'].owner_id = 'bob'
        with self.assertRaises(ValueError): await model.aresponse([])
        research.autoresearch.execute.assert_not_awaited()
        for change in ({'application': 'other'}, {'mode': 'other'}, {'ownerId': 'bob'},
                       {'delegation': {'parent': 'x'}}, {'tools': ['research_context']}):
            fresh, research = context()
            with self.subTest(change=change), self.assertRaises(ValueError):
                profile.ORXResearchModel(replace(fresh, plan={**fresh.plan, **change}), research=research)

    async def test_catalog_tools_route_exact_original_context_and_name(self):
        ctx, research = context()
        for entry in profile.registrations():
            if entry.kind != 'tool': continue
            research.autoresearch.tool.reset_mock(); ctx.store.authorize_tool.reset_mock()
            function = bind_registrations([entry], research)[0].factory(ctx)
            payload = {'requestId': 'original-tool-call', 'hypothesis': 'inert synthetic hypothesis'}
            result = await function.entrypoint(run_context=ctx.run_context, payload=payload)
            research.autoresearch.tool.assert_awaited_once_with(ctx, entry.tool_name, payload)
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
        knowledge = entries['knowledge'].factory(context()[0])
        self.assertEqual(json.loads(knowledge.content)['instructions'], Preset().instructions)
        self.assertEqual(entries['environment'].factory(context()[0]).runtime_id, profile.RUNTIME_ID)
        for bad in ({'presetId': 'x', 'command': 'x'}, {'presetId': '../x'}, {'presetId': True}):
            with self.assertRaises(ValueError): profile._config(bad)

    def test_actual_governance_validation_matches_registered_tool_catalog(self):
        # Run the real validation function against the installed tool contract.
        governance = object.__new__(MaterialGovernance)
        governance.seed_materials = ()
        catalog = tools_for_contract('autoresearch-session-v1')
        governance.config = GovernanceConfig(tool_contract='autoresearch-session-v1')
        settings = SimpleNamespace(runtime_tool_contract='autoresearch-session-v1', demo=True)
        store = SimpleNamespace(settings=settings)
        bindings = ExecutionBindings(settings, store)
        for entry in profile.registrations():
            bindings.register(entry.kind, entry.adapter_id, entry.revision, entry.factory,
                tool_name=entry.tool_name, connection_kind=entry.connection_kind,
                required_capabilities=entry.required_capabilities, permissions=entry.permissions,
                demo_only=entry.demo_only, validator=entry.validator,
                connection_adapter_ref=entry.connection_adapter_ref)
        store.execution_bindings = bindings
        governance.store = store
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
        ctx, research = context(); ctx.settings.demo = False
        for entry in entries:
            with self.subTest(kind=entry.kind), self.assertRaises(ValueError): bind_registrations([entry], research)[0].factory(ctx)
        ctx, research = context(); model = profile.ORXResearchModel(ctx, research=research)
        ctx.settings.demo = False
        with self.assertRaises(ValueError): await model.aresponse([])
        research.autoresearch.execute.assert_not_awaited()

    def test_session_resource_contract_is_explicit_and_reviewable(self):
        self.assertEqual(dict(profile.SESSION_RESOURCE_LIMITS),
            {'cpus': 1, 'memoryMb': 1024, 'pids': 64, 'maxSessionSeconds': 3600})
        registration = next(row for row in profile.registrations() if row.kind == 'environment')
        limits = registration.factory(context()[0])
        self.assertEqual((limits.memory_bytes, limits.process_limit, limits.cpu_percent), (1024**3, 64, 100))
        self.assertEqual((limits.timeout_seconds, limits.output_bytes), (30, 65536))
        material = next(row for row in profile.material_drafts('approved-project') if row['kind'] == 'environment')
        content = json.loads(material['content'])
        self.assertEqual(content['sessionResourceLimits'], dict(profile.SESSION_RESOURCE_LIMITS))
        self.assertEqual(content['adapterRevision'], registration.revision)
        self.assertEqual(content['nativePhaseTimeoutSeconds'], 30)
        self.assertIn('3600', material['description'])
        MaterialDefinition.model_validate(material)

    async def test_scientific_opt_in_has_closed_child_authority_and_same_go_tariff(self):
        ctx, research = context()
        ctx.settings.autoresearch_presets['approved-project'].external_session = True
        cast(dict, ctx.plan)['tools'] = list(profile.SCIENTIFIC_TOOLS)
        entries = profile.registrations(external_session=True)
        for entry in entries:
            if entry.tool_name in profile.SCIENTIFIC_AUTHORITY_TOOLS:
                fn = bind_registrations([entry], research)[0].factory(ctx)
                with self.assertRaisesRegex(ValueError, 'AUTORESEARCH_CHILD_EXECUTION_ONLY'): fn.entrypoint()
        research.autoresearch.tool.assert_not_awaited()
        with patch('agent_factory_research.autoresearch_session_control.model_factory', return_value='original-pause') as factory:
            model = bind_registrations([next(e for e in entries if e.kind == 'model')], research)[0].factory(ctx)
            self.assertEqual(model, 'original-pause'); factory.assert_called_once_with(ctx, research=research)
        with self.assertRaises(ValueError):
            bind_registrations([next(e for e in profile.registrations() if e.kind == 'model')], research)[0].factory(ctx)
        broker_model = profile.ORXResearchModel(ctx, research=research)
        price = profile.pricing_registration()
        self.assertIsNone(price.local_model_type); self.assertEqual(broker_model.provider, price.provider)
        self.assertEqual(broker_model.id, price.model)
        rows = profile.material_drafts('approved-project', external_session=True)
        self.assertEqual(len(rows), 13)
        from agent_factory_research.autoresearch_scientific_child import PHASES, MODE_NAMES, material_drafts, mode_definition
        budget = {'toolCalls': 32, 'maxDepth': 1, 'maxChildren': 3, 'experimentSeconds': 30, 'outputBytes': 65536}
        modes = {MODE_NAMES[phase]: mode_definition([dict(row, version=1, sha256='b'*64)
            for row in material_drafts('approved-project', phase)], phase, limits=budget) for phase in PHASES}
        definition = profile.application_definition([dict(row, version=1, sha256='a'*64) for row in rows],
            'approved-project', limits=budget, external_session=True, scientific_modes=modes)
        ApplicationDefinition.model_validate(definition)
        self.assertEqual(len(definition['modes']), 4)
        self.assertEqual(definition['modes']['research']['toolOrder'], list(profile.SCIENTIFIC_TOOLS))
        self.assertEqual(profile.TOOL_NAMES, ('research_context', 'research_candidate', 'research_experiment',
            'research_result', 'research_decision'))

    def test_broker_pricing_is_authoritative_and_request_body_is_bounded(self):
        price = profile.pricing_registration()
        self.assertIsNone(price.local_model_type); self.assertIsNot(price.usage_reader, zero_local_usage)
        self.assertIsNone(price.usage_reader({'arbitrary': 'usage'}))
        ctx, research = context()
        model = profile.ORXResearchModel(ctx, research=research)
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
