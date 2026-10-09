"""Native pause/continuation shapes only; model never invokes a provider."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from agno.models.message import Message
from agent_factory.managed_orx_profile import ManagedAttachmentControlModel, CALL_ID
from agent_factory.process_runtime_profile import TOOL_NAME
from agent_factory.store import canonical


class ManagedControlTests(unittest.IsolatedAsyncioTestCase):
    def model(self):
        run = SimpleNamespace(run_id='original-run', session_id='original-task', user_id='alice')
        ctx = SimpleNamespace(run_context=run, store=SimpleNamespace(process_runtime=SimpleNamespace(
            _original=lambda _: {'lease_id': 'original-lease'})))
        model = ManagedAttachmentControlModel(ctx, 'target')
        model._scope = Mock()
        return model, run

    async def test_native_pause_retains_original_task_and_no_provider_invocation(self):
        model, run = self.model()
        response = SimpleNamespace(**vars(run), requirements=None)
        messages = [Message(role='user', content='One approved turn')]
        outcome = await model.aresponse(messages, run_response=response)
        self.assertEqual(len(response.requirements), 1)
        self.assertTrue(outcome.tool_executions[0].external_execution_required)
        self.assertEqual(outcome.tool_executions[0].tool_call_id, CALL_ID)
        self.assertEqual(messages[-1].tool_calls[0]['function']['name'], TOOL_NAME)
        with self.assertRaisesRegex(ValueError, 'MANAGED_ORX_BROKER_ONLY'):
            await model.ainvoke(messages)

    async def test_continuation_requires_original_reclaimed_lease_and_preserves_native_text(self):
        model, run = self.model()
        value = {'state': 'RECLAIMED', 'leaseId': 'original-lease', 'nativeRunId': run.run_id,
            'stopEvidence': {'allStopped': True}, 'nativeResult': {'sessionId': 'original-native-session', 'text': 'Original response'}}
        messages = [Message(role='tool', tool_name=TOOL_NAME, tool_call_id=CALL_ID, content=canonical(value))]
        outcome = await model.aresponse(messages)
        self.assertIn('Original response', outcome.content)
        value['leaseId'] = 'foreign-lease'
        with self.assertRaises(ValueError):
            await model.aresponse([Message(role='tool', tool_name=TOOL_NAME, tool_call_id=CALL_ID, content=canonical(value))])
