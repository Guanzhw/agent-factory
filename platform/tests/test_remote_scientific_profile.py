"""Receiver-only control adapters: synthetic model messages, no external runtime."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from agno.exceptions import InputCheckError
from agno.models.message import Message
from agent_factory.remote_scientific_profile import (RemoteScientificControlModel, registrations, adapter_id,
    call_id, phase_pin, TOOLS, MODE_NAMES, CAPABILITIES)
from agent_factory.autoresearch_profile import APPLICATION_ID


def context(phase='preparation'):
    receiver = SimpleNamespace(require_phase=Mock(return_value={'comparisonManifest': {'synthetic': True}}), consume_tool=Mock())
    run = SimpleNamespace(user_id='alice', session_id='receiver-task', run_id='original-native')
    return SimpleNamespace(settings=SimpleNamespace(temporary_policy='admin-review'),
        store=SimpleNamespace(remote_scientific_receiver=receiver), run_context=run,
        spec={'config': {'projectId': 'project', 'phase': phase}},
        plan={'application': APPLICATION_ID, 'applicationRef': {'id': APPLICATION_ID}, 'mode': MODE_NAMES[phase],
              'ownerId': 'alice', 'tools': [TOOLS[phase]], 'capabilities': [CAPABILITIES[phase]],
              'remoteHandoff': {'receiptId': 'original-receipt'}})


class ProfileTests(unittest.TestCase):
    def test_exact_remote_profile_only(self):
        ctx = context(); phase_pin(ctx, 'preparation')
        for field, value in [('mode', 'scientific-preparation'), ('remoteHandoff', None), ('ownerId', 'other')]:
            original = ctx.plan[field]; ctx.plan[field] = value
            with self.assertRaises(ValueError): phase_pin(ctx, 'preparation')
            ctx.plan[field] = original
        ctx.spec['config']['extra'] = True
        with self.assertRaises(ValueError): phase_pin(ctx, 'preparation')

    def test_deterministic_native_call_and_original_result_identity(self):
        ctx = context('training'); model = RemoteScientificControlModel(ctx, 'training')
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
        ctx = context(); function = entry.factory(ctx)
        fc = SimpleNamespace(call_id=call_id('preparation'), arguments={}, function=function)
        function.pre_hook(ctx.run_context, fc)
        ctx.store.remote_scientific_receiver.consume_tool.assert_called_once_with(ctx, 'preparation', call_id('preparation'))
        fc.call_id = 'replacement'
        with self.assertRaises(InputCheckError): function.pre_hook(ctx.run_context, fc)
        self.assertEqual(ctx.store.remote_scientific_receiver.consume_tool.call_count, 1)
        fc.call_id = call_id('preparation')
        ctx.store.remote_scientific_receiver.consume_tool.side_effect = ConnectionError('synthetic failure')
        with self.assertRaises(InputCheckError): function.pre_hook(ctx.run_context, fc)

    def test_training_and_evaluation_pause_are_external_native_tools(self):
        for phase in ('training', 'evaluation'):
            entry = next(e for e in registrations('project') if e.adapter_id == adapter_id(phase, 'tool'))
            function = entry.factory(context(phase))
            self.assertTrue(function.external_execution)
