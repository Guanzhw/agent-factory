import json
from contextvars import ContextVar
from types import SimpleNamespace
import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine, event
from agent_factory.application_content import ApplicationContent, ContentPublication, ContentSource
from agent_factory.assistant_messages import AssistantMessages
from agent_factory.resource_sharing import ResourceSharing
from agent_factory.store import Store
from research.qa import ResearchQA


class SharedSearch(unittest.TestCase):
    def setUp(self):
        engine = create_engine('sqlite://')
        self.addCleanup(engine.dispose)
        store = Store.__new__(Store)
        store.engine = engine
        store._connection = ContextVar('connection', default=None)
        disabled = set()
        def require_member(owner):
            if owner in disabled:
                raise HTTPException(403)
        auth = SimpleNamespace(require_member=require_member)
        sharing = ResourceSharing(store, auth)
        content = ApplicationContent(store, auth, sharing)
        self.store, self.sharing, self.content, self.disabled = store, sharing, content, disabled

    def test_chinese_question_and_per_page_dependencies(self):
        store, sharing, content = self.store, self.sharing, self.content
        engine = store.engine
        records = [{'id': str(i), 'source': {'application': 'research'}, 'visibility': 'team',
                    'verificationStatus': 'unverified', 'content': {'note': '该模型采用小样本学习，准确率为92%。' * 100}}
                   for i in range(151)]
        records[-1]['visibility'] = 'personal'
        records[0]['content'] = {'conditions': 'protocol-budget-4096', 'note': '甲' * 280 + '小样本'}
        with engine.begin() as conn:
            conn.execute(content.contents.insert(), [
                {'id': item['id'], 'owner_id': 'bob', 'reference': 'content:' + item['id'],
                 'created_at': '', 'body': {'content': item['content'], 'source': item['source'],
                 'sourceContentIds': ['150'] if item['id'] == '149' else []}} for item in records])
            conn.execute(sharing.resources.insert(), [
                {'reference': 'content:' + item['id'], 'owner_id': 'bob', 'visibility': item['visibility']} for item in records])
        qa = ResearchQA(store, None, SimpleNamespace(read=lambda *args: {'reply': None}), None, content)
        message = {'text': '这个模型在小样本场景下表现如何？', 'messageId': 'question',
                   'senderId': 'alice', 'recipientId': 'bob', 'hasReply': False}
        qa._original = lambda ctx: (message, {})
        ctx = SimpleNamespace(user_id='bob', session_id='task', run_id='run')
        self.assertEqual(qa.context(ctx, source_id='42')['source']['id'], '42')
        result = qa.context(ctx)
        self.assertEqual(result['search']['total'], 149)
        seen = set()
        while True:
            for source in result['sources']:
                self.assertLessEqual(len(source['excerpt']), 500)
                if source['id'] == '0':
                    self.assertEqual(json.loads(source['excerpt']), records[0]['content'])
                self.assertNotIn(source['id'], seen)
                seen.add(source['id'])
            next_offset = result['search']['nextOffset']
            if next_offset is None:
                break
            result = qa.context(ctx, next_offset)
        self.assertEqual(len(seen), 149)
        statements = []
        event.listen(engine, 'before_cursor_execute', lambda conn, cursor, statement, *args: statements.append(statement))
        qa.context(ctx, offset=10)
        # Revalidating 149 earlier deliveries reads ACL metadata in batches.
        self.assertLess(len(statements), 12)
        revised = qa.context(ctx, query='实验输出 protocol-budget-4096')
        self.assertEqual([item['id'] for item in revised['sources']], ['0'])
        selected = next(iter(seen))
        self.assertEqual(qa.context(ctx, source_id=selected)['source']['content'], records[int(selected)]['content'])
        with self.assertRaises(HTTPException):
            qa.context(ctx, source_id='150')
        with engine.begin() as conn:
            conn.execute(sharing.resources.update().where(sharing.resources.c.reference == 'content:42').values(visibility='personal'))
        with self.assertRaises(HTTPException):
            qa.context(ctx, offset=10)
        self.disabled.add('bob')
        with self.assertRaises(HTTPException):
            qa.context(ctx, source_id='0')

    def test_saved_answer_tracks_transitive_dependencies(self):
        def publish(owner, revision, sources):
            record = ContentPublication(source=ContentSource(application='research', record='note', revision=revision),
                content={'text': 'Source ' + revision}, visibility='team', sourceContentIds=sources)
            return self.content.publish(owner, record, 'publish-' + revision)['id']
        first = publish('carol', 'first', [])
        second = publish('bob', 'second', [first])
        last = publish('bob', 'last', [second])
        runs = SimpleNamespace(_request_receipt=lambda *args: {'state': 'submitted', 'taskId': 'task', 'runId': 'run'})
        messages = AssistantMessages(self.store, self.content.auth, None, runs, self.content)
        with self.store.engine.begin() as conn:
            conn.execute(messages.messages.insert().values(id='message', sender_id='alice', recipient_id='bob',
                endpoint_id='endpoint', text='question', created_at='now'))
        message = {'messageId': 'message', 'senderId': 'alice', 'recipientId': 'bob', 'hasReply': False}
        messages.message_for_task = lambda owner, task_id: message
        qa = ResearchQA(self.store, None, messages, None, self.content)
        qa._original = lambda ctx: (message, {})
        ctx = SimpleNamespace(user_id='bob', session_id='task', run_id='run')
        qa.context(ctx, source_id=last)
        saved = messages.reply_for_task('bob', 'task', 'Answer', [last], cited_content_ids=[last])
        message['hasReply'] = True
        self.assertEqual(qa.context(ctx)['savedReply'], saved)
        self.content.set_visibility('carol', first, 'personal', 'withdraw-original')
        self.assertEqual(messages.read('alice', 'message')['reply'], {'state': 'source_unavailable'})
        with self.assertRaises(HTTPException):
            qa.context(ctx)
        self.content.set_visibility('carol', first, 'team', 'restore-original')
        self.assertEqual(qa.context(ctx)['savedReply'], saved)
