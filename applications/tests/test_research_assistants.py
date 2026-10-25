"""Portable identity and original-request contracts; synthetic message port."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select

from research.assistants import CreateAssistant, QuestionBudget, ResearchAssistants
from agent_factory.assistant_messages import SendAssistantMessage
import test_applications_composition as fixtures


class ResearchAssistantsTests(fixtures.ApplicationCompositionFixture):
    def setUp(self):
        super().setUp()
        self.messages = Mock()
        self.messages.send = AsyncMock()
        self.service = ResearchAssistants(self.store, self.auth, Mock(), self.messages, Mock(),
            pin={}, tool_registrations=(), environment_registration=SimpleNamespace())

    def test_read_does_not_create_and_repeat_creation_keeps_stable_owner_identity(self):
        self.assertEqual(self.service.me('alice'), {'assistant': None})
        first = self.service.create('alice', CreateAssistant(requestId='create-first'))
        second = self.service.create('alice', CreateAssistant(requestId='create-second'))
        self.assertEqual(first, second)
        self.assertEqual(self.service.create('alice', CreateAssistant(requestId='create-first')), first)
        with self.store.engine.connect() as conn:
            self.assertEqual(conn.execute(select(func.count()).select_from(self.service.identities)).scalar(), 1)
        with self.assertRaises(HTTPException):
            self.service.owned('bob', first['id'])
        self.assertEqual(self.service.list('bob')['items'][0], {'id': first['id'], 'ownerId': 'alice',
            'displayName': self.auth.identity('alice')['name'], 'qaAvailable': False})

    def test_original_question_recovers_historical_endpoint_after_reconfiguration(self):
        identity = self.service.create('alice', CreateAssistant(requestId='create-first'))
        with self.service.db.write() as conn:
            conn.execute(self.service.configurations.insert().values(assistant_id=identity['id'], revision=1,
                endpoint_id='old-endpoint', body={}))
            conn.execute(self.service.identities.update().where(self.service.identities.c.id == identity['id']).values(
                configuration_revision=2, qa_endpoint_id='new-endpoint'))
        original = {'id': 'original-message', 'senderId': 'bob', 'recipientId': 'alice', 'endpointId': 'old-endpoint',
            'text': 'Original question', 'delivery': {'state': 'unknown', 'taskId': 'original-task', 'runId': None}}
        self.messages.request.return_value = original
        body = SendAssistantMessage(requestId='original-question', text=original['text'])
        self.assertEqual(asyncio.run(self.service.question('bob', identity['id'], body)), original)
        self.messages.send.assert_not_called()
        for target, value in [(identity['id'], 'changed text'), ('other-assistant', original['text'])]:
            with self.assertRaises(HTTPException) as error:
                asyncio.run(self.service.question('bob', target, body.model_copy(update={'text': value})))
            self.assertEqual(error.exception.status_code, 409)
        self.messages.send.assert_not_called()

    def test_non_not_found_receipt_errors_are_not_treated_as_permission_to_send(self):
        self.messages.request.side_effect = HTTPException(503, 'Unavailable')
        with self.assertRaises(HTTPException) as error:
            asyncio.run(self.service.question('bob', 'target', SendAssistantMessage(requestId='original-question', text='Question')))
        self.assertEqual(error.exception.status_code, 503)
        self.messages.send.assert_not_called()

    def test_only_absent_original_request_resolves_current_target(self):
        identity = self.service.create('alice', CreateAssistant(requestId='create-first'))
        self.messages.request.side_effect = HTTPException(404, 'ASSISTANT_MESSAGE_NOT_FOUND')
        body = SendAssistantMessage(requestId='new-question', text='Question')
        with self.assertRaises(HTTPException) as error:
            asyncio.run(self.service.question('bob', identity['id'], body))
        self.assertEqual(error.exception.detail, 'RESEARCH_ASSISTANT_UNCONFIGURED')
        with self.service.db.write() as conn:
            conn.execute(self.service.identities.update().where(self.service.identities.c.id == identity['id']).values(qa_endpoint_id='current'))
        asyncio.run(self.service.question('bob', identity['id'], body))
        self.messages.send.assert_awaited_once_with('bob', 'current', body)

    def test_owner_model_budget_cannot_be_implicit_or_unmetered(self):
        caps = dict(rounds=1, toolCalls=2, tokenLimit=None, amountMicros=None, currency=None)
        with self.assertRaises(ValidationError):
            QuestionBudget(caps=caps, perQuestionCaps=caps, deadline=9999999999.0)
