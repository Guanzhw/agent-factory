"""Actual Agno external wait over synthetic provider HTTP; no external services."""
from copy import deepcopy
import json
import unittest

from agno.agent import Agent
from agno.exceptions import ModelProviderError
from agno.models.message import Message
import httpx

from agent_factory.byok_model import OwnerChatModel
from agent_factory.native_external_wait import factory_wait_operations
from agent_factory.personal_remote_provider import SecretLease


class ByokNativeWaitTests(unittest.IsolatedAsyncioTestCase):
    def model(self, protocol, wire):
        return OwnerChatModel({'provider': 'openai-compatible', 'model': 'selected-fixture',
            'baseURL': 'https://fixture.invalid/v1', 'protocol': protocol},
            lambda: SecretLease('api-key', 'synthetic-only'),
            transport_factory=lambda: httpx.MockTransport(wire))

    async def test_actual_native_wait_pauses_and_resumes_original_run_in_both_protocols(self):
        original = deepcopy(factory_wait_operations.to_dict())
        for protocol in ('chat-completions', 'responses'):
            with self.subTest(protocol=protocol):
                seen = []
                def wire(request):
                    body = json.loads(request.content)
                    seen.append(body)
                    self.assertEqual(body['model'], 'selected-fixture')
                    self.assertNotIn('external_execution', json.dumps(body['tools']))
                    if protocol == 'chat-completions':
                        message = {'role': 'assistant', 'content': 'Original operation finished'}
                        if len(seen) == 1:
                            message = {'role': 'assistant', 'content': None, 'tool_calls': [{
                                'id': 'original-call', 'type': 'function', 'function': {
                                    'name': 'factory_wait_operations',
                                    'arguments': '{"operationIds":["original-operation"]}'}}]}
                        result = {'choices': [{'finish_reason': 'tool_calls' if len(seen) == 1 else 'stop',
                            'message': message}]}
                    else:
                        output = [{'type': 'function_call', 'id': 'fc_original', 'call_id': 'original-call',
                            'name': 'factory_wait_operations', 'arguments': '{"operationIds":["original-operation"]}',
                            'status': 'completed'}] if len(seen) == 1 else [{
                                'type': 'message', 'id': 'msg_done', 'role': 'assistant', 'status': 'completed',
                                'content': [{'type': 'output_text', 'text': 'Original operation finished', 'annotations': []}]}]
                        result = {'status': 'completed', 'output': output}
                    return httpx.Response(200, json=result)
                agent = Agent(model=self.model(protocol, wire), tools=[factory_wait_operations], markdown=False, telemetry=False)
                paused = await agent.arun('Wait for original-operation')
                self.assertTrue(paused.is_paused)
                self.assertEqual(len(seen), 1)
                self.assertEqual(len(paused.requirements), 1)
                requirement = paused.requirements[0]
                self.assertTrue(requirement.tool_execution.external_execution_required)
                self.assertEqual(requirement.tool_execution.tool_args, {'operationIds': ['original-operation']})
                requirement.set_external_execution_result('original-operation completed with original evidence')
                completed = await agent.acontinue_run(paused, requirements=[requirement])
                self.assertEqual(completed.run_id, paused.run_id)
                self.assertEqual(completed.content, 'Original operation finished')
                self.assertFalse(completed.is_paused)
                self.assertEqual(len(seen), 2)
                self.assertIn('original-operation completed with original evidence', json.dumps(seen[1]))
                self.assertTrue(factory_wait_operations.external_execution)
                self.assertEqual(factory_wait_operations.to_dict(), original)

    async def test_copies_boolean_metadata_but_rejects_bad_types_and_unknown_fields(self):
        for protocol in ('chat-completions', 'responses'):
            model = self.model(protocol, lambda request: self.fail('Invalid tools must not reach HTTP'))
            for value in (True, False):
                tool = {'type': 'function', 'function': {**factory_wait_operations.to_dict(), 'external_execution': value}}
                before = deepcopy(tool)
                body = model._body([Message(role='user', content='fixture')], tools=[tool])
                self.assertNotIn('external_execution', json.dumps(body['tools']))
                self.assertEqual(tool, before)
            for changes in ({'external_execution': 'true'}, {'external_execution': 1},
                    {'external_execution': None}, {'unknown_sdk_field': True}):
                with self.subTest(protocol=protocol, changes=changes):
                    tool = {'type': 'function', 'function': {**factory_wait_operations.to_dict(), **changes}}
                    before = deepcopy(tool)
                    with self.assertRaisesRegex(ValueError, '^MODEL_PROTOCOL_TOOL$'):
                        model._body([Message(role='user', content='fixture')], tools=[tool])
                    with self.assertRaises(ModelProviderError):
                        await model.ainvoke([Message(role='user', content='fixture')], tools=[tool])
                    self.assertEqual(tool, before)
