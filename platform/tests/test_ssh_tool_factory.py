from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from agno.tools.function import FunctionCall

from agent_factory.ssh_tool_factory import ssh_tool_registrations


class SSHNativeToolTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.runtime = SimpleNamespace(launch=AsyncMock(return_value={
            'id': 'original-operation', 'closed': False, 'observation': None}))
        self.context = SimpleNamespace(user_id='alice', session_id='child', run_id='native-run')
        self.registration, self.wait = ssh_tool_registrations(self.runtime)
        self.function = self.registration.factory(SimpleNamespace(run_context=self.context,
            spec={'config': {'targetRef': 'personal-training'}}))
        self.function._run_context = self.context
        self.call = FunctionCall(function=self.function, call_id='original-call', arguments={})

    async def test_native_identity_and_configured_target_are_forwarded_without_model_fields(self):
        result = await self.function.entrypoint(run_context=self.context, fc=self.call)
        self.runtime.launch.assert_awaited_once_with(self.context, 'personal-training', 'original-call')
        self.assertEqual(result['operationId'], 'original-operation')
        self.assertEqual(self.function.parameters['properties'], {})
        self.assertTrue(self.wait.factory(None).external_execution)

    async def test_foreign_call_or_run_has_zero_launch(self):
        other = SimpleNamespace(user_id='alice', session_id='other', run_id='native-run')
        for context, call in ((other, self.call), (self.context, None)):
            with self.subTest(context=context, call=call), self.assertRaises(PermissionError):
                await self.function.entrypoint(run_context=context, fc=call)
        self.runtime.launch.assert_not_awaited()

    def test_configuration_cannot_inject_remote_command(self):
        with self.assertRaises(ValueError):
            self.registration.validator({'targetRef': 'personal-training', 'command': 'untrusted'})
