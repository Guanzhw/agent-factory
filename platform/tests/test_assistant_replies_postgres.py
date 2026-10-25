"""Real PG/native original identities, synthetic model; no live QA claim."""
from concurrent.futures import ThreadPoolExecutor
import os
from threading import Barrier, Event
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from sqlalchemy import text

from agent_factory.application_content import ContentPublication
import test_assistant_messages_postgres as fixtures


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires disposable PostgreSQL')
class AssistantRepliesPostgresTests(unittest.TestCase):
    def setUp(self):
        self.base = fixtures.AssistantMessagesPostgresTests('runTest')
        self.addCleanup(self.base.doCleanups)
        self.base.setUp()
        self.fixture = self.base.fixture
        self.store = self.fixture.store
        self.messages = self.fixture.state['assistant_messages']
        self.content = self.fixture.state['application_content']
        response = self.fixture.client.post(self.base.path, json=self.base.body)
        self.assertEqual(response.status_code, 202, response.text)
        self.message = response.json()
        self.task_id = self.message['delivery']['taskId']
        self.fixture.login('bob')
        self.assertEqual(self.fixture.wait_job(self.task_id)['job']['status'], 'completed')
        self.source = self.content.publish('bob', ContentPublication(source={
            'application': 'example', 'record': 'original-evidence', 'revision': '1'},
            content={'observation': 'synthetic negative result'}, visibility='team'), 'reply-source')

    def reply(self):
        return self.messages.reply_for_task('bob', self.task_id, 'Supported negative result.', [self.source['id']])

    def withdraw(self):
        return self.content.set_visibility('bob', self.source['id'], 'personal', 'withdraw-reply-source')

    def test_concurrent_reply_is_original_once_and_no_execution_or_data_loss(self):
        barrier = Barrier(2)
        def reply():
            barrier.wait(timeout=5)
            return self.reply()
        with patch.object(self.fixture.state['bridge'], 'submit', AsyncMock()) as submit:
            with ThreadPoolExecutor(max_workers=2) as pool:
                values = list(pool.map(lambda _: reply(), range(2)))
            self.assertEqual(values[0], values[1])
            self.assertEqual(submit.await_count, 0)
        with self.assertRaises(HTTPException):
            self.messages.reply_for_task('alice', self.task_id, 'Wrong owner')
        with self.assertRaises(HTTPException) as caught:
            self.messages.reply_for_task('bob', self.task_id, 'Changed original response', [self.source['id']])
        self.assertEqual(caught.exception.detail, 'ASSISTANT_REPLY_CONFLICT')
        self.assertEqual(len(self.store.tasks('bob')), 1)
        self.assertEqual(self.messages.read('alice', self.message['id'])['reply'], values[0]['reply'])

    def test_existing_real_table_nullable_migration_preserves_original_request(self):
        self.fixture.stop()
        with self.store.engine.begin() as conn:
            conn.execute(text('ALTER TABLE af_assistant_messages DROP COLUMN reply'))
        self.fixture.start()
        self.messages = self.fixture.state['assistant_messages']
        self.assertEqual(self.messages.request('alice', self.base.body['requestId'])['id'], self.message['id'])
        self.assertIsNone(self.messages.read('alice', self.message['id'])['reply'])
        self.assertEqual(self.reply()['reply']['state'], 'available')
        self.fixture.stop(); self.fixture.start()
        self.messages = self.fixture.state['assistant_messages']
        self.assertEqual(self.messages.read('alice', self.message['id'])['reply']['state'], 'available')

    def test_withdrawal_holds_lock_before_reply_so_no_reply_is_saved(self):
        held, release, attempted = Event(), Event(), Event()
        original_set = self.content.sharing.set
        original_lock = self.store.local_budget_scopes.admission_lock
        def paused_set(*args):
            held.set()
            if not release.wait(5): raise AssertionError('withdrawal barrier not released')
            return original_set(*args)
        def attempted_lock(conn):
            attempted.set()
            return original_lock(conn)
        with ThreadPoolExecutor(max_workers=2) as pool, patch.object(self.content.sharing, 'set', paused_set):
            withdrawal = pool.submit(self.withdraw)
            try:
                self.assertTrue(held.wait(5))
                with patch.object(self.store.local_budget_scopes, 'admission_lock', attempted_lock):
                    reply = pool.submit(self.reply)
                    self.assertTrue(attempted.wait(5))
                    self.assertFalse(reply.done())
                    release.set()
                    withdrawal.result(5)
                    with self.assertRaises(HTTPException): reply.result(5)
            finally:
                release.set()
        self.assertIsNone(self.messages.read('alice', self.message['id'])['reply'])

    def test_reply_and_read_snapshots_precede_withdrawal_without_leaking_afterwards(self):
        for operation in ('reply', 'read'):
            with self.subTest(operation=operation):
                self.content.set_visibility('bob', self.source['id'], 'team', 'restore-' + operation)
                held, release, attempted = Event(), Event(), Event()
                original_read = self.content.read
                def paused_read(*args):
                    if not held.is_set():
                        held.set()
                        if not release.wait(5): raise AssertionError('reply/read barrier not released')
                    return original_read(*args)
                def withdraw():
                    attempted.set()
                    return self.content.set_visibility('bob', self.source['id'], 'personal', 'withdraw-' + operation)
                action = self.reply if operation == 'reply' else lambda: self.messages.read('alice', self.message['id'])
                with ThreadPoolExecutor(max_workers=2) as pool, patch.object(self.content, 'read', paused_read):
                    snapshot = pool.submit(action)
                    try:
                        self.assertTrue(held.wait(5))
                        withdrawal = pool.submit(withdraw)
                        self.assertTrue(attempted.wait(5))
                        self.assertFalse(withdrawal.done())
                        release.set()
                        value = snapshot.result(5)
                        withdrawal.result(5)
                    finally:
                        release.set()
                # Reply returns a fresh projection after committing; withdrawal may win that later read.
                if operation == 'read':
                    self.assertEqual(value['reply']['state'], 'available')
                with self.store.engine.connect() as conn:
                    persisted = conn.execute(self.messages.messages.select().where(
                        self.messages.messages.c.id == self.message['id'])).mappings().one()
                    self.assertEqual(persisted['reply']['text'], 'Supported negative result.')
                after = self.messages.read('alice', self.message['id'])
                self.assertEqual(after['reply'], {'state': 'source_unavailable'})
                self.assertEqual(after['text'], self.base.body['text'])
