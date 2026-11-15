"""Standing tasks through authenticated HTTP, PostgreSQL, native queue and Chromium."""
import json
import re
import time
from http.server import BaseHTTPRequestHandler
from types import MethodType, SimpleNamespace
import unittest
from uuid import uuid4

from playwright.sync_api import expect

import test_chat_journey as journey


class TriggerModel(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.server.requests.append(request)
        messages = request['messages']
        current = max(i for i, value in enumerate(messages) if value['role'] == 'user')
        instruction = messages[current]['content']
        results = [value['content'] for value in messages[current:] if value['role'] == 'tool']
        tool, arguments = None, {}
        if not results and instruction == 'publish-team-research':
            tool = 'research_record_experiment'
            arguments = {'observations': ['peer-research-observation'], 'evidenceIds': ['synthetic.csv']}
        elif not results and 'read-trigger-source' in instruction:
            source = re.search(r'"contentId"\s*:\s*"([a-f0-9-]+)"', instruction)
            if source:
                tool, arguments = 'research_read_shared_evidence', {'content_id': source[1]}
        delta = {'role': 'assistant', 'content': 'trigger-result ' + '\n'.join(map(str, results))}
        if tool:
            delta['tool_calls'] = [{'index': 0, 'id': 'call_' + uuid4().hex, 'type': 'function',
                'function': {'name': tool, 'arguments': json.dumps(arguments)}}]
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.end_headers()
        for change, finish in [(delta, None), ({}, 'tool_calls' if tool else 'stop')]:
            chunk = {'id': 'trigger-fixture', 'object': 'chat.completion.chunk', 'created': 1,
                     'model': 'regression', 'choices': [{'index': 0, 'delta': change, 'finish_reason': finish}]}
            self.wfile.write(('data: ' + json.dumps(chunk) + '\n\n').encode())
        self.wfile.write(b'data: [DONE]\n\n')


class TriggersJourney(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        journey.ChatJourney.setUpClass.__func__(cls)
        cls.model.RequestHandlerClass = TriggerModel

    post, session, send = journey.ChatJourney.post, journey.ChatJourney.session, journey.ChatJourney.send

    def setUp(self):
        journey.ChatJourney.setUp(self)
        self.send('standing-task-chat')
        self.wait_turns(1)
        self.identifier = self.session()['id']
        self.path = '/research/sessions/' + self.identifier + '/triggers'

    def wait_turns(self, count, timeout=60):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            snapshot = self.session()
            if len(snapshot['turns']) >= count and snapshot['state'] == 'idle':
                self.assertEqual(len(snapshot['turns']), count)
                self.assertEqual(snapshot['turns'][-1]['status'], 'completed')
                return snapshot
            self.page.wait_for_timeout(100)
        self.fail('Standing task did not complete: ' + json.dumps(snapshot, ensure_ascii=False)[-4000:])

    def add_trigger(self, source, title, instruction, **fields):
        self.page.get_by_role('button', name='自动触发', exact=True).click()
        self.page.get_by_role('combobox', name='触发来源', exact=True).select_option(source)
        self.page.get_by_label('名称（可选）', exact=True).fill(title)
        self.page.get_by_label('触发后执行的指令', exact=True).fill(instruction)
        for label, value in fields.items():
            self.page.get_by_label(label, exact=True).fill(value)
        self.page.get_by_role('button', name='添加触发器', exact=True).click()
        expect(self.page.get_by_role('button', name='删除触发器 ' + title, exact=True)).to_be_visible()
        listing = self.context.request.get(self.origin + '/api/factory' + self.path).json()
        return next(item for item in listing['items'] if item['title'] == title)

    def test_external_event_continues_existing_chat_once_and_repeats_after_idle(self):
        trigger = self.add_trigger('external', 'Event journey', 'Continue this chat from the event.', 事件名称='qa.ready')
        body = {'requestId': str(uuid4()), 'eventType': 'qa.ready', 'payload': {'sequence': 1}}
        original = self.post('/research/events', body)
        first = self.wait_turns(2)
        self.assertEqual(first['turns'][-1]['origin']['triggerId'], trigger['id'])
        self.assertEqual(first['turns'][-1]['origin']['source'], 'external')
        self.assertEqual(self.post('/research/events', body), original)
        self.page.reload()
        expect(self.page.get_by_text('自动触发：Event journey', exact=False)).to_be_visible()
        self.assertEqual(len(self.session()['turns']), 2)
        self.post('/research/events', {**body, 'requestId': str(uuid4()), 'payload': {'sequence': 2}})
        second = self.wait_turns(3)
        self.assertEqual(second['id'], first['id'])
        self.assertEqual(second['turns'][:2], first['turns'])
        self.assertNotEqual(second['turns'][-1]['origin']['eventId'], first['turns'][-1]['origin']['eventId'])
        self.page.get_by_role('button', name='自动触发', exact=True).click()
        self.page.get_by_role('button', name='删除触发器 Event journey', exact=True).click()
        expect(self.page.get_by_role('button', name='删除触发器 Event journey', exact=True)).not_to_be_visible()
        items = self.context.request.get(self.origin + '/api/factory' + self.path).json()['items']
        self.assertFalse(any(item['enabled'] for item in items))

    def test_peer_chat_research_publication_triggers_readable_source_once(self):
        trigger = self.add_trigger('research', 'Peer research', 'read-trigger-source', **{'关键词（可选）': 'peer-research-observation'})
        peer = SimpleNamespace(browser=self.browser, state=self.state, origin=self.origin, model=self.model,
                               addCleanup=self.addCleanup, assertTrue=self.assertTrue)
        for method in ('post', 'session', 'send'):
            setattr(peer, method, MethodType(getattr(journey.ChatJourney, method), peer))
        journey.ChatJourney.setUp(peer)
        peer.send('publish-team-research')
        result = self.wait_turns(2)
        turn = result['turns'][-1]
        self.assertEqual(turn['origin']['triggerId'], trigger['id'])
        self.assertEqual(turn['origin']['source'], 'research')
        source_id = turn['origin']['contentId']
        source = self.context.request.get(self.origin + '/api/factory/application-content/' + source_id).json()
        self.assertEqual(source['ownerId'], peer.owner)
        self.assertEqual(source['visibility'], 'team')
        self.assertIn('peer-research-observation', turn['result'])
        reads = [event for event in turn['events'] if event['type'] == 'research_tool_finished'
                 and event['data'].get('toolName') == 'research_read_shared_evidence']
        self.assertEqual(len(reads), 1)
        self.assertIn('peer-research-observation', json.dumps(reads[0], ensure_ascii=False))
        share = {'requestId': str(uuid4()), 'visibility': 'team'}
        peer.post('/application-content/' + source_id + '/sharing', share)
        peer.post('/application-content/' + source_id + '/sharing', share)
        self.page.wait_for_timeout(1200)
        self.page.reload()
        expect(self.page.get_by_text('自动触发：Peer research', exact=False)).to_be_visible()
        self.assertEqual(len(self.session()['turns']), 2)

if __name__ == '__main__':
    unittest.main()
