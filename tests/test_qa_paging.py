from types import SimpleNamespace
import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine
from research.qa import ResearchQA


class SharedSearch(unittest.TestCase):
    def test_chinese_question_and_per_page_dependencies(self):
        engine = create_engine('sqlite://')
        self.addCleanup(engine.dispose)
        records = [{'id': str(i), 'source': {'application': 'research'}, 'visibility': 'team',
                    'verificationStatus': 'unverified', 'content': {'note': '该模型采用小样本学习，准确率为92%。' * 100}}
                   for i in range(151)]
        records[-1]['visibility'] = 'personal'
        def read(owner, key):
            if key == '149' and owner == 'alice':
                raise HTTPException(403)
            return records[int(key)]
        def listing(owner, after, limit):
            start = int(after or 0)
            return {'items': records[start:start + limit], 'nextCursor': str(start + limit)
                    if start + limit < len(records) else None}
        qa = ResearchQA(SimpleNamespace(engine=engine), None, SimpleNamespace(
            read=lambda *args: {'reply': None}), None, SimpleNamespace(read=read, list=listing))
        message = {'text': '这个模型在小样本场景下表现如何？', 'messageId': 'question',
                   'senderId': 'alice', 'recipientId': 'bob'}
        qa._original = lambda ctx: (message, {})
        ctx = SimpleNamespace(user_id='bob', session_id='task', run_id='run')
        result = qa.context(ctx)
        self.assertEqual(result['search']['total'], 149)
        seen = set()
        while True:
            for source in result['sources']:
                self.assertLessEqual(len(source['excerpt']), 500)
                self.assertNotIn(source['id'], seen)
                seen.add(source['id'])
            next_offset = result['search']['nextOffset']
            if next_offset is None:
                break
            result = qa.context(ctx, next_offset)
        self.assertEqual(len(seen), 149)
        selected = next(iter(seen))
        self.assertEqual(qa.context(ctx, source_id=selected)['source']['content'], records[int(selected)]['content'])
        with self.assertRaises(HTTPException):
            qa.context(ctx, source_id='150')
