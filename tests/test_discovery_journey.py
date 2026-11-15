"""Discovery decisions and actual destination work through HTTP, native queue and Chromium."""
import json
from http.server import BaseHTTPRequestHandler
from pathlib import Path
import time
from types import MethodType, SimpleNamespace
import unittest
from uuid import uuid4

from playwright.sync_api import expect

import test_chat_journey as journey


GOAL = '找出语言模型回答被截断的原因，并固定输出长度后复测。'
RELEVANT = 'At inference the reply ends at max_tokens=256; rerun with a matched generation cap.'
SIMILAR = GOAL + ' This is the title of a theatre performance; the observation concerns ticket sales only.'
INDEPENDENT = 'Bacillus cultures survived the saline medium; compare viability across salt concentrations.'


class DiscoveryModel(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.server.requests.append(request)
        messages = request['messages']
        current = max(i for i, message in enumerate(messages) if message['role'] == 'user')
        instruction = messages[current]['content']
        results = [message for message in messages[current:] if message['role'] == 'tool']
        advertised = {item['function']['name'] for item in request.get('tools', [])}
        tool, arguments, reply = None, {}, 'Prepared the research task.'
        if 'routingContext' in instruction and not results:
            event = json.loads(instruction[instruction.index('{'):])
            context = event['payload']['routingContext']
            assert context['projects'] and context['work'], context
            assert event['eventId'] == 'content:' + event['payload']['contentId'], event
            assert 'research_route_discovery' in advertised
            publication = json.dumps(event, ensure_ascii=False)
            if RELEVANT in publication:
                destination = next(item for item in context['work'] if item['goal'] == GOAL)
                tool, arguments = 'research_route_discovery', {
                    'decision': 'attach', 'sessionId': destination['sessionId'],
                    'instruction': 'Read the incoming evidence and plan a matched generation-cap comparison.',
                    'reason': 'The generation cap explains the existing truncation investigation despite different wording.'}
            elif SIMILAR in publication:
                tool, arguments = 'research_route_discovery', {
                    'decision': 'ignore',
                    'reason': 'The matching title describes theatre ticket sales, unrelated to model generation.'}
            elif INDEPENDENT in publication:
                tool, arguments = 'research_route_discovery', {
                    'decision': 'new', 'title': 'Salinity survival experiment',
                    'instruction': 'Read the incoming culture evidence and write a salinity follow-up plan.',
                    'reason': 'Culture viability is an independent research direction with no existing work.'}
            else:
                raise AssertionError('Unexpected discovery publication: ' + publication)
        elif 'contentId' in instruction and 'routingContext' not in instruction:
            event = json.loads(instruction[instruction.index('{'):])
            if not results:
                tool, arguments = 'research_read_shared_evidence', {'content_id': event['payload']['contentId']}
            elif len(results) == 1:
                independent = INDEPENDENT in results[0]['content']
                filename = 'salinity-followup.txt' if independent else 'matched-generation-cap.txt'
                tool, arguments = 'write_file', {'file_path': filename,
                    'contents': 'Compare survival across salt concentrations.' if independent
                    else 'Repeat the truncation comparison with an identical generation cap.'}
            else:
                reply = 'Completed evidence-based destination work.'
        delta = {'role': 'assistant', 'content': reply}
        if tool:
            delta['tool_calls'] = [{'index': 0, 'id': 'call_' + uuid4().hex, 'type': 'function',
                'function': {'name': tool, 'arguments': json.dumps(arguments)}}]
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.end_headers()
        for change, finish in [(delta, None), ({}, 'tool_calls' if tool else 'stop')]:
            chunk = {'id': 'discovery-fixture', 'object': 'chat.completion.chunk', 'created': 1,
                     'model': 'regression', 'choices': [{'index': 0, 'delta': change, 'finish_reason': finish}]}
            self.wfile.write(('data: ' + json.dumps(chunk) + '\n\n').encode())
        self.wfile.write(b'data: [DONE]\n\n')


class DiscoveryJourney(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        journey.ChatJourney.setUpClass.__func__(cls)
        cls.model.RequestHandlerClass = DiscoveryModel

    post, session, send = journey.ChatJourney.post, journey.ChatJourney.session, journey.ChatJourney.send

    def setUp(self):
        journey.ChatJourney.setUp(self)

    def get(self, path):
        response = self.context.request.get(self.origin + '/api/factory' + path)
        self.assertTrue(response.ok, f'{response.status}: {response.text()}')
        return response.json()

    def wait_snapshot(self, identifier, count):
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            snapshot = self.get('/research/sessions/' + identifier)
            if len(snapshot['turns']) >= count and snapshot['state'] == 'idle':
                self.assertEqual(len(snapshot['turns']), count, snapshot)
                self.assertEqual(snapshot['turns'][-1]['status'], 'completed', snapshot)
                return snapshot
            self.page.wait_for_timeout(100)
        self.fail('Discovery destination did not complete: ' + json.dumps(snapshot, ensure_ascii=False)[-5000:])

    def wait_decisions(self, count):
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            value = self.get('/research/discovery')
            if len(value['decisions']) >= count:
                self.assertEqual(len(value['decisions']), count, value)
                return value
            self.page.wait_for_timeout(100)
        self.fail('Discovery decision missing: ' + json.dumps(value, ensure_ascii=False)[-5000:])

    def test_semantic_discovery_routes_once_and_executes_native_destination_work(self):
        self.send(GOAL)
        existing = self.wait_snapshot(self.session()['id'], 1)
        project = self.post('/research/projects', {'title': 'Controlled generation comparison'})
        self.post('/research/projects/' + project['id'] + '/goals', {
            'expectedVersion': 0, 'agreement': {'objective': GOAL}})
        model_ref = next(item['connectionRef'] for item in self.get('/research/sessions/options')['models']
                         if item['available'])
        self.page.goto(self.origin + '/?tab=resources')
        self.page.get_by_label('启用我的团队资料发现', exact=True).check()
        self.page.get_by_label('发现助手模型').select_option(model_ref)
        self.page.get_by_label('关注方向与处理指令', exact=True).fill(
            'Understand incoming work semantically. Attach relevant evidence, ignore title coincidences, '
            'and create independent research when useful.')
        self.page.get_by_role('button', name='保存发现设置', exact=True).click()
        expect(self.page.get_by_text('团队资料发现设置已保存。', exact=True)).to_be_visible()
        configured = self.get('/research/discovery')
        discovery_id = configured['sessionId']
        self.assertNotEqual(discovery_id, existing['id'])
        peer = SimpleNamespace(browser=self.browser, state=self.state, origin=self.origin, model=self.model,
                               addCleanup=self.addCleanup, assertTrue=self.assertTrue)
        peer.post = MethodType(journey.ChatJourney.post, peer)
        journey.ChatJourney.setUp(peer)
        publications = []
        for index, text in enumerate((RELEVANT, SIMILAR, INDEPENDENT), start=1):
            publication = peer.post('/application-content', {'source': {
                'application': 'research', 'record': 'discovery-' + uuid4().hex, 'revision': '1'},
                'content': {'observation': text}, 'visibility': 'team'})
            publications.append(publication)
            discovery = self.wait_decisions(index)
            decision = next(item for item in discovery['decisions']
                            if item['contentId'] == publication['id'])
            self.assertTrue(decision['reason'])
            self.assertEqual(decision['ownerId'], peer.owner)
            self.assertEqual(decision['discoverySessionId'], discovery_id)
            if index == 1:
                self.assertEqual(decision['decision'], 'attach')
                self.assertEqual(decision['sessionId'], existing['id'])
                attached = self.wait_snapshot(existing['id'], 2)
                self.assertEqual(attached['turns'][-1]['origin']['contentId'], publication['id'])
                self.assertEqual(attached['turns'][-1]['origin']['eventId'], 'content:' + publication['id'])
                file = self.context.request.get(self.origin + '/api/factory/research/sessions/' + existing['id']
                    + '/files/download', params={'path': 'matched-generation-cap.txt'})
                self.assertTrue(file.ok, file.text())
                self.assertEqual(file.text(), 'Repeat the truncation comparison with an identical generation cap.')
            elif index == 2:
                self.assertEqual(decision['decision'], 'ignore')
                self.assertIsNone(decision['sessionId'])
                self.assertEqual(len(self.get('/research/sessions/' + existing['id'])['turns']), 2)
            else:
                self.assertEqual(decision['decision'], 'new')
                new_id = decision['sessionId']
                self.assertNotIn(new_id, {existing['id'], discovery_id})
                created = self.wait_snapshot(new_id, 1)
                turn = created['turns'][0]
                self.assertTrue(turn['runId'])
                self.assertTrue(turn['taskId'])
                self.assertEqual(turn['origin']['contentId'], publication['id'])
                self.assertEqual(turn['origin']['eventId'], 'content:' + publication['id'])
                self.assertTrue(any(event['data'].get('toolName') == 'research_read_shared_evidence'
                                    for event in turn['events']))
                self.page.goto(self.origin + '/?researchSession=' + new_id)
                expect(self.page.get_by_text('Completed evidence-based destination work.', exact=True)).to_be_visible()
                self.page.get_by_role('button', name='会话文件', exact=True).click()
                with self.page.expect_download() as download:
                    self.page.get_by_role('link', name='salinity-followup.txt', exact=True).click()
                self.assertEqual(Path(download.value.path()).read_text(), 'Compare survival across salt concentrations.')
        routing = self.wait_snapshot(discovery_id, 3)
        self.assertEqual(len(routing['turns']), 3)
        self.assertEqual([turn['origin']['contentId'] for turn in routing['turns']],
                         [publication['id'] for publication in publications])
        share = {'requestId': str(uuid4()), 'visibility': 'team'}
        peer.post('/application-content/' + publications[0]['id'] + '/sharing', share)
        peer.post('/application-content/' + publications[0]['id'] + '/sharing', share)
        self.page.wait_for_timeout(1200)
        self.assertEqual(len(self.get('/research/discovery')['decisions']), 3)
        self.assertEqual(len(self.get('/research/sessions/' + discovery_id)['turns']), 3)
        self.assertEqual(len(self.get('/research/sessions/' + existing['id'])['turns']), 2)
        self.assertEqual(len(self.get('/research/sessions/' + new_id)['turns']), 1)
        self.page.goto(self.origin + '/?tab=resources')
        expect(self.page.get_by_role('heading', name='发现决策 · 3', exact=True)).to_be_visible()
        for decision in self.get('/research/discovery')['decisions']:
            expect(self.page.get_by_text(decision['reason'], exact=True)).to_be_visible()
        expect(self.page.get_by_role('link', name='打开目标对话', exact=True)).to_have_count(2)
        self.page.get_by_role('link', name='查看发现助手完整对话', exact=True).click()
        expect(self.page.get_by_role('button', name='会话文件', exact=True)).to_be_visible()
        self.assertEqual(self.session()['id'], discovery_id)
        peer.post('/application-content/' + publications[-1]['id'] + '/sharing', {'visibility': 'personal'})
        self.post('/research/sessions/' + new_id + '/turns', {
            'text': 'Continue with an independent question about sterile controls.'})
        self.wait_snapshot(new_id, 2)
        first_request = len(self.model.requests)
        after_withdrawal = peer.post('/application-content', {'source': {
            'application': 'research', 'record': 'after-withdrawal-' + uuid4().hex, 'revision': '1'},
            'content': {'observation': RELEVANT}, 'visibility': 'team'})
        self.wait_decisions(4)
        self.wait_snapshot(existing['id'], 3)
        routed_contexts = []
        for request in self.model.requests[first_request:]:
            instruction = next(message['content'] for message in reversed(request['messages'])
                               if message['role'] == 'user')
            if 'routingContext' in instruction:
                event = json.loads(instruction[instruction.index('{'):])
                self.assertEqual(event['payload']['contentId'], after_withdrawal['id'])
                routed_contexts.append(event['payload']['routingContext'])
        self.assertTrue(routed_contexts)
        for context in routed_contexts:
            self.assertNotIn(new_id, {item['sessionId'] for item in context['work']})
        disabled = self.post('/research/discovery', {'enabled': False, 'modelConnectionRef': None})
        self.assertFalse(disabled['enabled'])
        self.assertIsNone(disabled['modelConnectionRef'])
        peer.post('/application-content', {'source': {
            'application': 'research', 'record': 'disabled-' + uuid4().hex, 'revision': '1'},
            'content': {'observation': RELEVANT}, 'visibility': 'team'})
        self.page.wait_for_timeout(1200)
        self.assertEqual(len(self.get('/research/discovery')['decisions']), 4)
        self.assertEqual(len(self.get('/research/sessions/' + discovery_id)['turns']), 4)


if __name__ == '__main__':
    unittest.main()
