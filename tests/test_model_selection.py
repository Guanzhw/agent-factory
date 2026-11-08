"""Per-turn model choices use verified capabilities and immutable run settings."""
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from agno.models.message import Message
from fastapi import HTTPException

from agent_factory.byok_model import OwnerChatModel
from agent_factory.model_dispatch import DelegatingModel
from agent_factory.model_reasoning import reasoning_efforts
from research.session_routes import SessionTurn
from research.session_setup import ResearchSessionSetup
from research.sessions import ResearchSessions


GO = 'https://opencode.ai/inference/go/openai/v1'


class ModelSelection(unittest.TestCase):
    def test_efforts_match_endpoint_model_and_protocol(self):
        luna = {'baseURL': GO, 'model': 'gpt-6-luna', 'protocol': 'responses'}
        self.assertEqual(reasoning_efforts(luna), ['none', 'low', 'medium', 'high', 'xhigh', 'max'])
        self.assertEqual(reasoning_efforts({**luna, 'baseURL': 'https://custom.example/v1'}), [])
        self.assertEqual(reasoning_efforts({**luna, 'protocol': 'chat-completions'}), [])
        self.assertEqual(reasoning_efforts({**luna, 'baseURL': 'https://api.openai.com/v1',
            'protocol': 'chat-completions'}), ['none'])
        deepseek = {'baseURL': GO, 'model': 'deepseek-v4.1-flash'}
        self.assertEqual(reasoning_efforts(deepseek), ['low', 'high', 'max'])
        self.assertEqual(reasoning_efforts({**deepseek, 'protocol': 'responses'}), [])
        self.assertEqual(reasoning_efforts({**deepseek, 'model': 'unknown-model'}), [])

    def test_boundary_rejects_unsupported_effort(self):
        models = SimpleNamespace(list=Mock(return_value=[{'connectionRef': 'model-one', 'provider': 'openai-compatible',
            'baseURL': GO, 'model': 'deepseek-v4.1-flash', 'available': True}]))
        tools = SimpleNamespace(available_tools=set())
        setup = ResearchSessionSetup(None, None, models, tools)
        with self.assertRaises(HTTPException) as rejected:
            setup.prepare('owner', 'model-one', 'medium')
        self.assertEqual(rejected.exception.status_code, 422)
        self.assertEqual(setup.prepare('owner', 'model-one', 'high')['model']['reasoningEffort'], 'high')
        self.assertNotIn('baseURL', setup.options('owner')['models'][0])

    def test_turn_choice_pins_history_and_default_can_be_restored(self):
        service = object.__new__(ResearchSessions)
        previous = {'connectionRefs': {'model': 'model-one'}, 'model': {'reasoningEffort': 'high'}}
        row = {'body': {'configuration': deepcopy(previous)}}
        prior = {'body': {}}
        saved = []
        service._save_turn = lambda conn, turn, body: saved.append(body)
        service.setup = SimpleNamespace(prepare=Mock(return_value={'connectionRefs': {'model': 'model-two'}, 'model': {}}))
        request = SessionTurn(requestId='request-one', text='next', modelConnectionRef='model-two', reasoningEffort=None)
        changed = service._prepare_turn_configuration(None, 'owner', row, [prior], request)
        service.setup.prepare.assert_called_with('owner', 'model-two', None)
        self.assertEqual(saved[0]['configuration'], previous)
        self.assertEqual(row['body']['configuration'], previous)
        self.assertEqual(changed['body']['configuration']['connectionRefs']['model'], 'model-two')
        original = {'id': 'turn-one', 'application_request_id': 'application-one',
            'body': {**saved[0], 'context': 'saved context', 'messages': [{'text': 'original'}]}}
        start = service._start({**changed, 'id': 'session-one'}, original)
        self.assertEqual(start.connectionRefs['model'], 'model-one')
        self.assertEqual(start.inputValues['reasoningEffort'], 'high')
        service._prepare_turn_configuration(None, 'owner', row, [],
            SessionTurn(requestId='request-two', text='default', reasoningEffort=None))
        service.setup.prepare.assert_called_with('owner', 'model-one', None)
        service._prepare_turn_configuration(None, 'owner', row, [])
        service.setup.prepare.assert_called_with('owner', 'model-one', 'high')

    def test_wire_parameters_use_selected_effort(self):
        configuration = {'baseURL': GO, 'provider': 'openai-compatible', 'model': 'deepseek-v4.1-flash',
            'reasoningEffort': 'high'}
        chat = OwnerChatModel(configuration, lambda: None)
        body = chat._body([Message(role='user', content='hello')])
        self.assertEqual(body['reasoning_effort'], 'high')
        self.assertNotIn('reasoning', body)
        response = OwnerChatModel({**configuration, 'model': 'gpt-6-luna', 'protocol': 'responses'}, lambda: None)
        body = response._body([Message(role='user', content='hello')])
        self.assertEqual(body['reasoning']['effort'], 'high')
        self.assertNotIn('reasoning_effort', body)
        default = OwnerChatModel({key: value for key, value in configuration.items() if key != 'reasoningEffort'}, lambda: None)
        self.assertNotIn('reasoning_effort', default._body([Message(role='user', content='hello')]))

    def test_dispatch_passes_pinned_effort_to_model_and_auxiliary(self):
        native = SimpleNamespace(_on_text=Mock(), _on_reasoning=Mock())
        summary = SimpleNamespace(_on_text=Mock(), _on_reasoning=Mock())
        models = SimpleNamespace(model_for=Mock(side_effect=[native, summary]))
        dispatcher = DelegatingModel(SimpleNamespace(personal_models=models))
        dispatcher._provider_hooks = lambda model, context, current, auxiliary, plan: auxiliary()
        context = SimpleNamespace(user_id='owner')
        response = SimpleNamespace()
        native.id, native.provider = 'gpt-6-luna', 'openai-compatible'
        plan = {'connectionRefs': {'model': 'model-two'}, 'inputValues': {'reasoningEffort': 'max'}}
        dispatcher._complete_selection((response, plan, context, Mock(), None, None))
        self.assertEqual(models.model_for.call_count, 2)
        models.model_for.assert_called_with('owner', 'model-two', context, reasoning_effort='max')
        self.assertIsNotNone(native._on_text)
        self.assertIsNotNone(native._on_reasoning)
        self.assertIsNone(summary._on_text)
        self.assertIsNone(summary._on_reasoning)


if __name__ == '__main__':
    unittest.main()
