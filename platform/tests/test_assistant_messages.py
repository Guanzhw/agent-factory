"""Message custody contracts with synthetic admission; not live model evidence."""
import asyncio
from contextvars import ContextVar
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import MethodType, SimpleNamespace
import unittest
from unittest.mock import Mock

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from agent_factory.store import Store
from agent_factory.assistant_messages import AssistantMessages, SendAssistantMessage, assistant_messages_router


class Auth:
    def __init__(self):
        self.members = {'alice', 'bob', 'charlie'}

    def require_member(self, owner):
        if owner not in self.members:
            raise HTTPException(403, 'MEMBER_REQUIRED')

    def user(self, request):
        return {'id': request.headers['x-test-member']}


class Endpoints:
    def __init__(self, auth):
        self.auth, self.enabled = auth, True
        self.text_input = False

    def resolve(self, endpoint_id):
        self.auth.require_member('bob')
        if endpoint_id != 'bobs-assistant':
            raise HTTPException(404, 'ASSISTANT_ENDPOINT_NOT_FOUND')
        if not self.enabled:
            raise HTTPException(409, 'ASSISTANT_ENDPOINT_DISABLED')
        return {'id': endpoint_id, 'ownerId': 'bob', 'textInput': self.text_input, 'defaults': {
            'application': 'example', 'mode': 'answer',
            'applicationRef': {'id': 'example', 'version': 1, 'sha256': 'a' * 64},
            'connectionRefs': {'model': 'bobs-private-model-ref'}, 'materialChoices': {}}}


class Runs:
    def __init__(self):
        self.calls, self.receipts = [], {}
        self.error = None

    async def start(self, owner, body):
        self.calls.append((owner, body.model_dump()))
        if self.error:
            raise self.error
        self.receipts[(owner, body.requestId)] = {'state': 'unknown', 'taskId': 'original-task',
            'runId': None, 'handoff': {'secret': 'never-project'}, 'planId': 'private-plan'}

    def _request_receipt(self, owner, request_id):
        result = self.receipts.get((owner, request_id))
        if result is None:
            raise HTTPException(404, 'APPLICATION_START_RECEIPT_NOT_FOUND')
        return deepcopy(result)


class AssistantMessagesTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.engine = create_engine('sqlite:///' + str(Path(directory.name) / 'messages.sqlite'))
        self.addCleanup(self.engine.dispose)
        self.store = SimpleNamespace(engine=self.engine, _connection=ContextVar('message-test', default=None))
        self.store.transaction = MethodType(Store.transaction, self.store)
        self.auth, self.runs = Auth(), Runs()
        self.endpoints = Endpoints(self.auth)
        self.service = AssistantMessages(self.store, self.auth, self.endpoints, self.runs, Mock())
        self.body = SendAssistantMessage(requestId='sender-request-001', text='What did the earlier experiment show?')

    def send(self, body=None):
        return asyncio.run(self.service.send('alice', 'bobs-assistant', body or self.body))

    def test_duplicate_after_reopen_only_reads_original_unknown_admission(self):
        first = self.send()
        self.service = AssistantMessages(self.store, self.auth, self.endpoints, self.runs, Mock())
        self.endpoints.enabled = False
        repeated = self.send()
        self.assertEqual(first, repeated)
        self.assertEqual(len(self.runs.calls), 1)
        owner, start = self.runs.calls[0]
        self.assertEqual(owner, 'bob')
        self.assertEqual(start['connectionRefs'], {'model': 'bobs-private-model-ref'})
        self.assertEqual(start['goal'], self.body.text)
        self.assertIsNone(start['inputValues'])
        self.assertEqual(first['delivery'], {'state': 'unknown', 'taskId': 'original-task', 'runId': None})
        self.assertNotIn('handoff', str(first)); self.assertNotIn('private', str(first))
        self.assertFalse(first['automaticReplay'])

    def test_schema_text_input_is_explicit_and_cannot_be_overridden_by_sender(self):
        self.endpoints.text_input = True
        self.send()
        self.assertEqual(self.runs.calls[0][1]['inputValues'], {'goal': self.body.text})

    def test_changed_intent_conflicts_and_new_disabled_message_never_starts(self):
        self.send()
        with self.assertRaises(HTTPException) as caught:
            self.send(self.body.model_copy(update={'text': 'Different question'}))
        self.assertEqual(caught.exception.status_code, 409)
        self.endpoints.enabled = False
        with self.assertRaises(HTTPException):
            self.send(self.body.model_copy(update={'requestId': 'new-request-002'}))
        self.assertEqual(len(self.runs.calls), 1)

    def test_both_parties_read_but_third_member_and_disabled_sender_cannot(self):
        result = self.send()
        self.assertEqual(self.service.read('bob', result['id']), result)
        self.assertEqual(self.service.request('alice', self.body.requestId), result)
        with self.assertRaises(HTTPException) as caught:
            self.service.read('charlie', result['id'])
        self.assertEqual(caught.exception.status_code, 404)
        with self.assertRaises(HTTPException):
            self.service.request('bob', self.body.requestId)
        self.auth.members.remove('alice')
        with self.assertRaises(HTTPException): self.send()
        self.assertEqual(len(self.runs.calls), 1)

    def test_failure_before_receipt_is_visible_and_never_automatically_replayed(self):
        self.runs.error = TimeoutError('synthetic interruption before admission receipt')
        with self.assertRaises(TimeoutError): self.send()
        result = self.service.request('alice', self.body.requestId)
        self.assertEqual(result['delivery'], {'state': 'unconfirmed', 'taskId': None, 'runId': None})
        self.runs.error = None
        self.assertEqual(self.send(), result)
        self.assertEqual(len(self.runs.calls), 1)

    def test_http_rejects_owner_config_override_and_unbounded_input(self):
        app = FastAPI(); app.include_router(assistant_messages_router(self.auth, self.service))
        with TestClient(app) as client:
            path = '/api/factory/assistants/bobs-assistant/messages'
            for changes in ({'owner': 'alice'}, {'connectionRefs': {}}, {'text': 'x' * 2001}):
                response = client.post(path, headers={'x-test-member': 'alice'},
                    json={**self.body.model_dump(), **changes})
                self.assertEqual(response.status_code, 422, response.text)
            self.assertEqual(self.runs.calls, [])
            response = client.post(path, headers={'x-test-member': 'alice'}, json=self.body.model_dump())
            self.assertEqual(response.status_code, 202, response.text)
            receipt = client.get('/api/factory/assistant-message-requests/' + self.body.requestId,
                headers={'x-test-member': 'alice'})
            self.assertEqual(receipt.json(), response.json())
