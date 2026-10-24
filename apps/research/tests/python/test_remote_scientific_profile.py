"""Receiver-only control adapters: synthetic model messages, no external runtime."""
from agent_factory_research.services import ResearchServices, bind_registrations
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from agno.exceptions import InputCheckError
from agno.models.message import Message
from agent_factory_research.remote_scientific_profile import (RemoteScientificControlModel, registrations, adapter_id,
    call_id, phase_pin, TOOLS, MODE_NAMES, CAPABILITIES)
from agent_factory_research.autoresearch_profile import APPLICATION_ID


def context(phase='preparation'):
    receiver = SimpleNamespace(require_phase=Mock(return_value={'comparisonManifest': {'synthetic': True}}), consume_tool=Mock())
    run = SimpleNamespace(user_id='alice', session_id='receiver-task', run_id='original-native')
    store = SimpleNamespace()
    research = ResearchServices(factory_store=store, installed=True, remote_scientific_receiver=receiver)
    ctx = SimpleNamespace(settings=SimpleNamespace(temporary_policy='member-self-service'),
        store=store, run_context=run,
        spec={'config': {'projectId': 'project', 'phase': phase}},
        plan={'application': APPLICATION_ID, 'applicationRef': {'id': APPLICATION_ID}, 'mode': MODE_NAMES[phase],
              'ownerId': 'alice', 'tools': [TOOLS[phase]], 'capabilities': [CAPABILITIES[phase]],
              'remoteHandoff': {'receiptId': 'original-receipt'}})
    return ctx, research


class ProfileTests(unittest.TestCase):
    def test_closed_graph_cannot_debit_from_previously_created_native_hook(self):
        ctx, research = context()
        entry = next(e for e in registrations('project') if e.adapter_id == adapter_id('preparation', 'tool'))
        function = bind_registrations([entry], research)[0].factory(ctx)
        research.release()
        fc = SimpleNamespace(call_id=call_id('preparation'), arguments={}, function=function)
        with self.assertRaises(InputCheckError):
            function.pre_hook(ctx.run_context, fc)
        research.remote_scientific_receiver.consume_tool.assert_not_called()

    def test_exact_remote_profile_only(self):
        ctx, research = context(); phase_pin(ctx, 'preparation', research=research)
        for field, value in [('mode', 'scientific-preparation'), ('remoteHandoff', None), ('ownerId', 'other')]:
            original = ctx.plan[field]; ctx.plan[field] = value
            with self.assertRaises(ValueError): phase_pin(ctx, 'preparation', research=research)
            ctx.plan[field] = original
        ctx.spec['config']['extra'] = True
        with self.assertRaises(ValueError): phase_pin(ctx, 'preparation', research=research)

    def test_deterministic_native_call_and_original_result_identity(self):
        ctx, research = context('training'); model = RemoteScientificControlModel(ctx, 'training', research=research)
        response = model._response([])
        self.assertEqual(response.tool_calls[0]['id'], call_id('training'))
        self.assertEqual(response.tool_calls[0]['function'], {'name': TOOLS['training'], 'arguments': '{}'})
        result = Message(role='tool', content='synthetic custody', tool_name=TOOLS['training'], tool_call_id=call_id('training'))
        self.assertIn('scientificConclusionVerified', str(model._response([result]).content))
        result.tool_call_id = 'replacement'
        with self.assertRaises(ValueError): model._response([result])

    def test_distinct_adapters_and_native_pre_hook_debit_fail_closed(self):
        entries = registrations('project')
        self.assertEqual(len(entries), 12)
        self.assertEqual(len({e.adapter_id for e in entries}), 12)
        entry = next(e for e in entries if e.adapter_id == adapter_id('preparation', 'tool'))
        ctx, research = context(); function = bind_registrations([entry], research)[0].factory(ctx)
        fc = SimpleNamespace(call_id=call_id('preparation'), arguments={}, function=function)
        function.pre_hook(ctx.run_context, fc)
        research.remote_scientific_receiver.consume_tool.assert_called_once_with(ctx, 'preparation', call_id('preparation'))
        fc.call_id = 'replacement'
        with self.assertRaises(InputCheckError): function.pre_hook(ctx.run_context, fc)
        self.assertEqual(research.remote_scientific_receiver.consume_tool.call_count, 1)
        fc.call_id = call_id('preparation')
        research.remote_scientific_receiver.consume_tool.side_effect = ConnectionError('synthetic failure')
        with self.assertRaises(InputCheckError): function.pre_hook(ctx.run_context, fc)

    def test_training_and_evaluation_pause_are_external_native_tools(self):
        for phase in ('training', 'evaluation'):
            entry = next(e for e in registrations('project') if e.adapter_id == adapter_id(phase, 'tool'))
            ctx, research = context(phase)
            function = bind_registrations([entry], research)[0].factory(ctx)
            self.assertTrue(function.external_execution)
