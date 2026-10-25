"""Reply custody with real content permissions; synthetic original task fixture."""
import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import text

from agent_factory.application_content import ApplicationContent, ContentPublication
from agent_factory.assistant_messages import AssistantMessages
from agent_factory.resource_sharing import ResourceSharing
import test_assistant_messages as fixtures


class AssistantRepliesTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.AssistantMessagesTests('runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.store, self.auth = self.fixture.store, self.fixture.auth
        self.content = ApplicationContent(self.store, self.auth, ResourceSharing(self.store, self.auth))
        self.service = self.fixture.service
        self.service.content = self.content
        self.message = self.fixture.send()
        self.task_id = self.message['delivery']['taskId']
        self.store.local_budget_scopes = SimpleNamespace(request_delivery=lambda *_: None)
        self.store.task = self.task
        self.fixture.endpoints.owned = lambda owner, endpoint: {'id': endpoint, 'ownerId': owner}
        self.source = self.content.publish('bob', ContentPublication(source={
            'application': 'example', 'record': 'evidence', 'revision': '1'},
            content={'observation': 'synthetic negative result'}, visibility='team'), 'publish-source')

    def task(self, task_id, owner):
        if task_id != self.task_id or owner != 'bob':
            raise HTTPException(404, 'TASK_NOT_FOUND')
        return {'id': task_id, 'request_id': 'application-start:assistant-message:' + self.message['id']}

    def reply(self, sources=None, answer='Evidence supports a negative result.'):
        return self.service.reply_for_task('bob', self.task_id, answer,
            [self.source['id']] if sources is None else sources)

    def test_all_read_entrypoints_hide_whole_reply_after_source_withdrawal(self):
        original = self.reply()
        self.assertEqual(original['reply']['state'], 'available')
        self.content.set_visibility('bob', self.source['id'], 'personal', 'withdraw-source')
        reads = [self.service.read('alice', self.message['id']),
            self.service.request('alice', self.fixture.body.requestId), self.fixture.send(),
            asyncio.run(self.service.recover('bob', self.message['id']))]
        for value in reads:
            self.assertEqual(value['reply'], {'state': 'source_unavailable'})
            self.assertEqual(value['text'], self.fixture.body.text)
        self.assertEqual(len(self.fixture.runs.calls), 1)
        self.content.set_visibility('bob', self.source['id'], 'team', 'restore-source')
        self.assertEqual(self.service.read('alice', self.message['id'])['reply'], original['reply'])
        with self.assertRaises(HTTPException): self.service.read('charlie', self.message['id'])

    def test_private_source_denied_and_plain_reply_idempotent_without_more_execution(self):
        self.content.set_visibility('bob', self.source['id'], 'personal', 'make-private')
        with self.assertRaises(HTTPException): self.reply()
        self.assertIsNone(self.service.read('alice', self.message['id'])['reply'])
        first = self.reply([])
        self.assertEqual(first, self.reply([]))
        with self.assertRaises(HTTPException) as caught:
            self.reply([], 'Changed answer')
        self.assertEqual(caught.exception.detail, 'ASSISTANT_REPLY_CONFLICT')
        self.auth.members.remove('bob')
        self.assertEqual(self.service.read('alice', self.message['id'])['reply'], {'state': 'source_unavailable'})
        self.assertEqual(len(self.fixture.runs.calls), 1)

    def test_original_identity_and_limits_and_unexpected_errors_are_not_hidden(self):
        for owner, task in [('alice', self.task_id), ('bob', 'another-task')]:
            with self.assertRaises(HTTPException): self.service.reply_for_task(owner, task, 'No reply')
        for value in ('x', 'x' * 2001):
            with self.assertRaises(ValidationError): self.reply(answer=value)
        with self.assertRaises(ValidationError): self.reply([self.source['id']] * 21)
        with self.assertRaises(ValidationError): self.reply(['not-content-id'])
        self.reply()
        for error in (RuntimeError('database failed'), HTTPException(409, 'INTEGRITY_FAILED')):
            with patch.object(self.content, 'read', side_effect=error), self.assertRaises(type(error)):
                self.service.read('alice', self.message['id'])
        self.auth.members.remove('alice')
        with self.assertRaises(HTTPException): self.reply()

    def test_legacy_table_migrates_without_losing_original_message_or_command(self):
        with self.store.engine.begin() as conn:
            conn.execute(text('ALTER TABLE af_assistant_messages DROP COLUMN reply'))
        for _ in range(2):
            service = AssistantMessages(self.store, self.auth, self.fixture.endpoints, self.fixture.runs, self.content)
            self.assertEqual(service.request('alice', self.fixture.body.requestId), self.message)
        self.service = service
        self.assertEqual(self.reply()['reply']['state'], 'available')

    def test_source_set_is_canonical_and_old_reads_do_not_check_content(self):
        with patch.object(self.content, 'read', Mock(side_effect=AssertionError('unexpected content read'))):
            self.assertEqual(self.service.read('alice', self.message['id']), self.message)
        first = self.reply([self.source['id'], self.source['id']])
        self.assertEqual(first, self.reply([self.source['id']]))
