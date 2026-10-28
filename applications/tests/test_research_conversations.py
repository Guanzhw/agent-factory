"""Real PG message origins and authority; scripted admission, no provider requests."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import os
from threading import Barrier
import time
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import event, func, select

from agent_factory.assistant_messages import SendAssistantMessage
from research.assistants import ConfigureAssistant, CreateAssistant
from research.conversations import ResearchConversations, SessionQuestion
from research.setup import PrepareQASetup, PublishSetup
import test_research_assistants_postgres as assistant_fixture
import test_research_sessions as session_fixture


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'requires disposable loopback PostgreSQL')
class ResearchConversationContracts(unittest.TestCase):
    def setUp(self):
        session_fixture.ResearchSessionContracts.setUp(self)
        self.conversations = self.state['research_conversations']
        self.assistants = self.state['research_assistants']
        self.messages = self.state['assistant_messages']
        self.admission = assistant_fixture.Admission()
        self.messages.runs = self.admission
        model = self.store.personal_models.configure('bob', {'provider': 'openai-compatible',
            'baseURL': 'http://localhost:8899/v1', 'model': 'synthetic-qa'}, 'conversation-bob-model')
        setup = self.state['research_setup']
        draft = setup.prepare_qa('bob', PrepareQASetup(requestId='conversation-qa-draft', name='QA',
            modelConnectionRef=model['connectionRef'], budget={'toolCalls': 4}))
        published = setup.publish('bob', draft['id'], PublishSetup(requestId='conversation-qa-publish'))
        identity = self.assistants.create('bob', CreateAssistant(requestId='conversation-bob'))
        self.assistant_id = identity['id']
        caps = {'rounds': 3, 'toolCalls': 12, 'tokenLimit': None, 'amountMicros': None, 'currency': None}
        self.config = ConfigureAssistant(requestId='conversation-qa-configure', expectedRevision=0,
            applicationRef=published['applicationRef'], connectionRefs=published['connectionRefs'],
            budget={'caps': caps, 'perQuestionCaps': {**caps, 'rounds': 1, 'toolCalls': 4},
                'deadline': time.time() + 300})
        configured = self.assistants.configure('bob', self.config)
        self.endpoint_id = configured['qa']['endpointId']
        self.body = SessionQuestion(requestId='conversation-original', assistantId=identity['id'],
            text='What evidence supports the measurement?')

    def counts(self):
        with self.store.engine.connect() as conn:
            return tuple(conn.execute(select(func.count()).select_from(table)).scalar_one() for table in
                (self.messages.messages, self.store.local_budget_scopes.allocations, self.conversations.origins))

    def reserve(self, body=None):
        return self.conversations._reserve('alice', self.identifier, body or self.body)

    def test_atomic_concurrent_original_and_only_recipient_can_recover(self):
        barrier = Barrier(2)
        def reserve(_):
            barrier.wait(5)
            return self.reserve()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(reserve, (0, 1)))
        self.assertEqual(sum(fresh for _, fresh in results), 1)
        self.assertEqual(results[0][0]['id'], results[1][0]['id'])
        self.assertEqual(self.counts(), (1, 1, 1))
        message_id = results[0][0]['id']
        sender = self.conversations.listing('alice', self.identifier)['items'][0]
        receiver = self.conversations.inbox('bob')['items'][0]
        self.assertEqual(sender['sessionId'], self.identifier)
        self.assertEqual(sender['allowedActions'], [])
        self.assertEqual(receiver['allowedActions'], ['recover'])
        self.assertNotIn('sessionId', receiver)
        self.assertNotIn('requestId', receiver)
        self.assertNotIn(self.create.goal, str(receiver))
        with self.assertRaises(HTTPException) as denied:
            asyncio.run(self.conversations.recover('alice', message_id))
        self.assertEqual(denied.exception.status_code, 404)
        original = asyncio.run(self.conversations.recover('bob', message_id))
        self.assertEqual(original['delivery']['state'], 'unknown')
        self.assertEqual(original['allowedActions'], [])
        self.assertEqual(asyncio.run(self.conversations.recover('bob', message_id)), original)
        self.assertEqual(len(self.admission.calls), 1)
        self.assertEqual(self.counts(), (1, 1, 1))

    def test_origin_insert_failure_rolls_back_message_and_budget(self):
        def fail(_conn, _cursor, statement, _parameters, _context, _many):
            if statement.startswith('INSERT INTO research_question_origins'):
                raise RuntimeError('synthetic origin write failure')
        event.listen(self.store.engine, 'before_cursor_execute', fail)
        try:
            with self.assertRaisesRegex(RuntimeError, 'origin write failure'):
                self.reserve()
        finally:
            event.remove(self.store.engine, 'before_cursor_execute', fail)
        self.assertEqual(self.counts(), (0, 0, 0))
        self.assertEqual(self.conversations.inbox('bob')['items'], [])

    def test_committed_before_admission_is_findable_after_service_reconstruction(self):
        with patch.object(self.messages, 'recover', side_effect=RuntimeError('synthetic exit before admission')):
            with self.assertRaisesRegex(RuntimeError, 'before admission'):
                asyncio.run(self.conversations.question('alice', self.identifier, self.body))
        reopened = ResearchConversations(self.store, self.state['auth'], self.assistants, self.service)
        item = reopened.listing('alice', self.identifier, request_id=self.body.requestId)['items'][0]
        self.assertIsNone(item['delivery']['taskId'])
        self.assertEqual(reopened.inbox('bob')['items'][0]['id'], item['id'])
        with patch.object(self.messages, 'recover', side_effect=AssertionError('No automatic recovery')):
            duplicate = asyncio.run(reopened.question('alice', self.identifier, self.body))
        self.assertEqual(duplicate['id'], item['id'])
        self.assertEqual(self.admission.calls, [])

    def test_changed_request_or_legacy_question_cannot_rebind(self):
        self.reserve()
        second = self.service.create('alice', self.create.model_copy(update={'requestId': 'second-session'}))
        for session_id, body in [(second, self.body), (self.identifier, self.body.model_copy(update={'text': 'Changed question'})),
                                 (self.identifier, self.body.model_copy(update={'assistantId': self.service.assistants.me('alice')['assistant']['id']}))]:
            with self.assertRaises(HTTPException) as caught:
                self.conversations._reserve('alice', session_id, body)
            self.assertEqual(caught.exception.status_code, 409)
        legacy = SendAssistantMessage(requestId='legacy-original', text=self.body.text)
        self.messages.reserve('alice', self.endpoint_id, legacy)
        with self.assertRaises(HTTPException) as caught:
            self.reserve(self.body.model_copy(update={'requestId': legacy.requestId}))
        self.assertEqual(caught.exception.detail['code'], 'RESEARCH_QUESTION_REQUEST_CONFLICT')
        self.assertEqual(self.counts(), (2, 2, 1))
        with self.assertRaises(HTTPException):
            self.conversations.listing('bob', self.identifier)
        with self.assertRaises(HTTPException):
            self.conversations._reserve('bob', self.identifier, self.body)

    def test_old_endpoint_and_current_sender_authority_block_missing_task(self):
        message, _ = self.reserve()
        self.state['assistant_endpoints'].set_enabled('bob', self.endpoint_id, False, 'disable-original')
        item = self.conversations.inbox('bob')['items'][0]
        self.assertEqual(item['allowedActions'], [])
        self.assertEqual(item['recoveryCode'], 'ASSISTANT_ENDPOINT_DISABLED')
        with self.assertRaises(HTTPException):
            asyncio.run(self.conversations.recover('bob', message['id']))
        self.assertEqual(self.admission.calls, [])
        self.state['assistant_endpoints'].set_enabled('bob', self.endpoint_id, True, 'enable-original')
        self.state['auth'].directory.set_disabled('alice', True)
        self.assertEqual(self.conversations.inbox('bob')['items'][0]['allowedActions'], [])
        with self.assertRaises(HTTPException):
            asyncio.run(self.conversations.recover('bob', message['id']))
        self.assertEqual(self.admission.calls, [])

    def test_post_commit_failure_has_distinct_uncertain_code_and_receipt(self):
        with patch.object(self.messages, 'recover', side_effect=HTTPException(429, 'LOCAL_BUDGET_EXHAUSTED')):
            with self.assertRaises(HTTPException) as caught:
                asyncio.run(self.conversations.question('alice', self.identifier, self.body))
        self.assertEqual(caught.exception.detail['code'], 'RESEARCH_QUESTION_ADMISSION_UNCONFIRMED')
        self.assertEqual(len(self.conversations.listing('alice', self.identifier,
            request_id=self.body.requestId)['items']), 1)
        with self.assertRaises(HTTPException) as missing:
            self.conversations.listing('alice', self.identifier, request_id='no-such-question')
        self.assertEqual(missing.exception.status_code, 404)

    def test_pagination_does_not_expose_other_recipients_or_private_origin(self):
        for index in range(3):
            self.reserve(self.body.model_copy(update={'requestId': f'page-{index}'}))
        first = self.conversations.listing('alice', self.identifier, limit=2)
        second = self.conversations.listing('alice', self.identifier, after=first['nextCursor'], limit=2)
        self.assertEqual([item['requestId'] for item in first['items'] + second['items']], ['page-0', 'page-1', 'page-2'])
        inbox = self.conversations.inbox('bob', limit=2)
        remaining = self.conversations.inbox('bob', after=inbox['nextCursor'], limit=2)
        self.assertEqual(len({item['id'] for item in inbox['items'] + remaining['items']}), 3)
        self.assertEqual(self.conversations.inbox('alice')['items'], [])

    def test_unconfigured_recipient_rejects_before_message_commit(self):
        other = self.assistants.me('alice')['assistant']
        with self.assertRaises(HTTPException) as caught:
            self.reserve(self.body.model_copy(update={'assistantId': other['id']}))
        self.assertEqual(caught.exception.detail, 'RESEARCH_ASSISTANT_UNCONFIGURED')
        self.assertEqual(self.counts(), (0, 0, 0))

    def test_event_delivery_binding_cannot_be_recovered_as_ordinary_question(self):
        message, fresh = self.messages.reserve('alice', self.endpoint_id,
            SendAssistantMessage(requestId='trusted-event-message', text='Synthetic existing event'),
            delivery_id='synthetic-trusted-delivery')
        self.assertTrue(fresh)
        item = self.conversations.inbox('bob')['items'][0]
        self.assertEqual(item['allowedActions'], [])
        self.assertEqual(item['recoveryCode'], 'ASSISTANT_EVENT_RECOVERY_MANAGED')
        with self.assertRaises(HTTPException) as denied:
            asyncio.run(self.conversations.recover('bob', message['id']))
        self.assertEqual(denied.exception.detail['code'], 'ASSISTANT_EVENT_RECOVERY_MANAGED')
        self.assertEqual(self.admission.calls, [])
        with self.store.transaction() as conn:
            self.assertEqual(self.store.local_budget_scopes.request_delivery(conn, 'bob',
                'application-start:assistant-message:' + message['id']), 'synthetic-trusted-delivery')
