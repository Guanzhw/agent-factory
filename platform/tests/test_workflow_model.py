"""Decision bridge identity tests; no provider, DB or execution resources."""
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from agno.exceptions import InputCheckError
from agno.run import RunContext
from agno.run.agent import RunOutput

from agent_factory.demo_model import DemoModel
from agent_factory.model_dispatch import DelegatingModel
from agent_factory.workflow_model import WorkflowDecisionModel


class WorkflowDecisionModelTests(TestCase):
    def setup_bridge(self):
        original = RunOutput(run_id='child', session_id='task', user_id='alice', agent_id='decider')
        context = RunContext(run_id='root', session_id='task', user_id='alice', session_state={})
        store = SimpleNamespace(task=Mock(return_value={'plan_id': 'plan'}), plan=Mock(return_value={}),
                                event=Mock(), usage_ledger=Mock())
        model = DemoModel()
        model.invoke = Mock(return_value='provider-result')
        bindings = SimpleNamespace(store=store, model_from_binding=Mock(return_value=model),
                                   manifest=Mock(return_value={'sha256': 'pin'}))
        validator = Mock(return_value=context)
        bridge = WorkflowDecisionModel(bindings, workflow_id='workflow', step_id='step',
                                       agent_id='decider', validator=validator)
        return bridge, original, context, store, model, validator

    def test_root_ledger_event_original_response_and_current_guard(self):
        bridge, original, context, store, model, validator = self.setup_bridge()
        current = Mock()

        def prepare(arguments, kwargs, **unused):
            proxy = kwargs['run_response']
            self.assertEqual(proxy.run_id, 'root')
            self.assertIsNot(proxy, original)
            return proxy, {}, context, current, Mock(), object()

        with patch.object(DelegatingModel, '_prepare_selection', side_effect=prepare):
            selected = bridge._select((), {'run_response': original})
        self.assertIs(selected, model)
        self.assertEqual(original.run_id, 'child')
        self.assertIsNone(original.parent_run_id)
        self.assertEqual(original.model, model.id)
        self.assertEqual(store.event.call_args.args[0], 'root')
        selected.invoke([])
        self.assertIs(store.usage_ledger.begin_attempt.call_args.args[0], context)
        self.assertGreaterEqual(validator.call_count, 3)
        validator.side_effect = InputCheckError('revoked')
        before = store.usage_ledger.begin_attempt.call_count
        with self.assertRaises(InputCheckError): selected.invoke([])
        self.assertEqual(store.usage_ledger.begin_attempt.call_count, before)

    def test_invalid_root_or_lineage_rejects_before_material_dispatch(self):
        for changes in ({'run_id': 'child'}, {'session_id': 'other'}, {'user_id': 'bob'}):
            bridge, original, context, _, _, validator = self.setup_bridge()
            for key, value in changes.items(): setattr(context, key, value)
            with self.assertRaises(InputCheckError): bridge._prepare_selection((), {'run_response': original})
        bridge, original, _, _, _, validator = self.setup_bridge()
        validator.return_value = None
        with self.assertRaises(InputCheckError): bridge._prepare_selection((), {'run_response': original})
        for field in ('agent_id', 'parent_run_id', 'workflow_id', 'workflow_step_id'):
            bridge, original, _, _, _, _ = self.setup_bridge()
            setattr(original, field, 'wrong')
            with self.assertRaises(InputCheckError): bridge._prepare_selection((), {'run_response': original})

    def test_positional_stream_identity_is_replaced_without_mutating_original(self):
        bridge, original, context, _, _, _ = self.setup_bridge()
        def prepare(arguments, kwargs, **unused):
            self.assertEqual(arguments[6].run_id, 'root')
            self.assertNotIn('run_response', kwargs)
            return arguments[6], {}, context, Mock(), Mock(), object()
        with patch.object(DelegatingModel, '_prepare_selection', side_effect=prepare):
            bridge._prepare_selection((None,) * 6 + (original,), {}, streaming=True)
        self.assertEqual(original.run_id, 'child')
