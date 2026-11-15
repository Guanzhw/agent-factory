"""Standing tasks through authenticated HTTP, PostgreSQL, native queue and Chromium."""
import ast
import json
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
        names = {call['id']: call['function']['name'] for message in messages
                 for call in message.get('tool_calls', [])}
        current = max(i for i, value in enumerate(messages) if value['role'] == 'user')
        instruction = messages[current]['content']
        results = [value['content'] for value in messages[current:] if value['role'] == 'tool']
        outputs = {names[value['tool_call_id']]: ast.literal_eval(value['content'])
                   for value in messages[current:] if value['role'] == 'tool'}
        advertised = {item['function']['name'] for item in request.get('tools', [])}
        tool, arguments = None, {}
        reply = 'trigger-result ' + '\n'.join(map(str, results))
        if 'research_qa_context' in advertised:
            if not results:
                tool = 'research_qa_context'
            elif 'research_qa_record' not in outputs:
                context = outputs['research_qa_context']
                protocol = next(source for source in context['sources']
                                if 'protocol-budget-4096' in json.dumps(source['content']))
                assert 'peer-research-observation' in context['question']
                tool, arguments = 'research_qa_record', {
                    'answer': 'The result used output budget 4096, as the shared protocol records. '
                              'Conditions differ from the requested 2048; a matched-budget improvement is unconfirmed.',
                    'citations': [protocol['id']]}
            else:
                reply = 'Saved the answer with the shared protocol citation.'
        elif instruction == 'publish-peer-protocol' and not results:
            tool = 'research_record_experiment'
            arguments = {'conditions': 'protocol-budget-4096: output budget 4096, same model and benchmark.',
                         'observations': ['Protocol fixes the output budget at 4096.'],
                         'evidenceIds': ['protocol.json']}
        elif instruction == 'publish-team-research' and not results:
            tool = 'research_record_experiment'
            arguments = {'observations': ['peer-research-observation: score improved from 40 to 60; '
                                          'output budget is missing from this result.'],
                         'evidenceIds': ['result.csv']}
        elif 'read-trigger-source' in instruction:
            payload = json.loads(instruction[instruction.index('{'):])['payload']
            if not results:
                tool, arguments = 'research_read_shared_evidence', {'content_id': payload['contentId']}
            elif 'research_assistant_directory' not in outputs:
                assert 'output budget is missing' in json.dumps(outputs['research_read_shared_evidence'])
                tool, arguments = 'research_assistant_directory', {'owner_id': payload['ownerId']}
            elif 'research_ask_assistant' not in outputs:
                assistant = next(item for item in outputs['research_assistant_directory']['items']
                                 if item['ownerId'] == payload['ownerId'] and item['qaAvailable'])
                tool, arguments = 'research_ask_assistant', {'assistant_id': assistant['id'],
                    'text': 'For peer-research-observation ' + payload['contentId'] +
                            ', what was the output budget? My original comparison requires 2048. '
                            'Please cite a shared protocol record.'}
            else:
                reply = 'The result omits output budget. I asked its publishing colleague; conclusion pending.'
        elif instruction.startswith('同事提供的参考回答：'):
            answer = json.loads(instruction.split('\n', 1)[1])
            assert answer['reply']['citedContentIds']
            assert '4096' in answer['reply']['text']
            reply = ('Revised conclusion: conditions differ (4096 versus required 2048); '
                     'the matched-budget improvement is unconfirmed. Publisher: ' + answer['recipientId'] +
                     '. Shared protocol: ' + answer['reply']['citedContentIds'][0])
        delta = {'role': 'assistant', 'content': reply}
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

    def test_independent_event_waits_and_records_model_adoption(self):
        from pathlib import Path
        import sys
        from test_native_model import Endpoint, chunk, reply

        started, release = Path(self.folder.name) / 'evidence-started', Path(self.folder.name) / 'evidence-release'
        original = self.model.RequestHandlerClass
        self.model.RequestHandlerClass, self.model.hold = Endpoint, None
        self.addCleanup(setattr, self.model, 'RequestHandlerClass', original)
        self.addCleanup(lambda: release.touch())
        requests = []
        def answer(body):
            requests.append(body)
            current = max(i for i, message in enumerate(body['messages']) if message['role'] == 'user')
            latest = body['messages'][current]['content']
            results = any(message['role'] == 'tool' for message in body['messages'][current:])
            if latest == 'Compare conditions while the tool runs' and not results:
                code = (f"from pathlib import Path; import time; Path({str(started)!r}).touch(); "
                        f"p=Path({str(release)!r}); exec('while not p.exists(): time.sleep(.05)'); print('ready')")
                return 200, [chunk({'role': 'assistant', 'tool_calls': [{'index': 0, 'id': 'wait-evidence',
                    'type': 'function', 'function': {'name': 'run_shell',
                    'arguments': json.dumps({'command': journey.shell_command([sys.executable, '-c', code])})}}]}),
                    chunk({}, 'tool_calls')]
            return 200, reply('done')
        self.model.answer = answer
        self.post('/research/sessions/' + self.identifier + '/turns', {'text': 'Compare conditions while the tool runs'})
        deadline = time.monotonic() + 30
        while not started.exists() and time.monotonic() < deadline:
            self.page.wait_for_timeout(100)
        self.assertTrue(started.exists())
        self.post(self.path, {'title': 'Independent', 'instruction': 'Do independent work', 'source': 'external', 'eventType': 'independent-work'})
        self.post('/research/events', {'requestId': 'independent-work', 'eventType': 'independent-work'})
        self.assertTrue(all(not item.get('adoptedAt') for item in self.session()['deliveries']))
        expect(self.page.get_by_role('region', name='收到的团队事项')).to_contain_text('独立新任务')
        release.touch()
        completed = self.wait_turns(3)
        task = next(item for item in completed['deliveries'] if item['kind'] == 'task')
        self.assertEqual(task['turnId'], completed['turns'][2]['id'])
        self.assertTrue(task['adoptedAt'])
        self.assertEqual(len(requests), 3)
        self.assertNotIn('independent-work', json.dumps(requests[1]['messages']))
        self.assertIn('independent-work', json.dumps(requests[2]['messages']))
        self.post('/research/events', {'requestId': 'independent-work', 'eventType': 'independent-work'})
        self.page.reload()
        self.assertEqual(len(self.session()['turns']), 3)
        expect(self.page.get_by_role('region', name='收到的团队事项')).to_contain_text('已纳入模型请求')

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
        trigger = self.add_trigger('research', 'Peer research',
            'read-trigger-source: compare with my original required output budget 2048',
            **{'关键词（可选）': 'peer-research-observation'})
        peer = SimpleNamespace(browser=self.browser, state=self.state, origin=self.origin, model=self.model,
                               addCleanup=self.addCleanup, assertTrue=self.assertTrue)
        for method in ('post', 'session', 'send'):
            setattr(peer, method, MethodType(getattr(journey.ChatJourney, method), peer))
        journey.ChatJourney.setUp(peer)
        for member in (self, peer):
            assistant = member.post('/research/assistants', {})
            options = member.context.request.get(self.origin + '/api/factory/research/sessions/options').json()
            member.assistant = member.post('/research/assistants/me/configurations', {
                'expectedRevision': assistant['configurationRevision'],
                'connectionRefs': {'model': next(item['connectionRef'] for item in options['models']
                                                 if item['available'])}})
        peer.send('publish-peer-protocol')
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            protocol_session = peer.session()
            if protocol_session['state'] == 'idle':
                break
            self.page.wait_for_timeout(100)
        self.assertEqual(protocol_session['turns'][-1]['status'], 'completed')
        protocol_id = next(event['data']['output']['terminalRecordId']
            for event in protocol_session['turns'][-1]['events']
            if event['type'] == 'research_tool_finished'
            and event['data'].get('toolName') == 'research_record_experiment')
        self.assertEqual(len(self.session()['turns']), 1)
        peer.post('/research/sessions/' + protocol_session['id'] + '/turns', {'text': 'publish-team-research'})
        result = journey.ChatJourney.wait_for(self, lambda value: value['state'] == 'idle'
            and 'Revised conclusion:' in (value['turns'][-1]['result'] or ''))
        turn, resumed = result['turns'][1], result['turns'][-1]
        self.assertEqual(turn['origin']['triggerId'], trigger['id'])
        self.assertEqual(turn['origin']['source'], 'research')
        self.assertEqual(turn['origin']['ownerId'], peer.owner)
        source_id = turn['origin']['contentId']
        source = self.context.request.get(self.origin + '/api/factory/application-content/' + source_id).json()
        self.assertEqual(source['ownerId'], peer.owner)
        self.assertEqual(source['visibility'], 'team')
        reads = [event for event in turn['events'] if event['type'] == 'research_tool_finished'
                 and event['data'].get('toolName') == 'research_read_shared_evidence']
        self.assertEqual(len(reads), 1)
        self.assertIn('peer-research-observation', json.dumps(reads[0], ensure_ascii=False))
        questions = self.context.request.get(self.origin + '/api/factory/research/sessions/' +
                                            self.identifier + '/questions').json()['items']
        self.assertEqual(len(questions), 1)
        question = questions[0]
        self.assertEqual(question['senderId'], self.owner)
        self.assertEqual(question['recipientId'], peer.owner)
        self.assertEqual(question['endpointId'], peer.assistant['qa']['endpointId'])
        self.assertEqual(question['reply']['state'], 'available')
        self.assertEqual(set(question['reply']['contentIds']), {protocol_id, source_id})
        self.assertEqual(question['reply']['citedContentIds'], [protocol_id])
        self.assertEqual(resumed['assistantReplies'][0]['recipientId'], peer.owner)
        self.assertEqual(resumed['assistantReplies'][0]['reply']['citedContentIds'], [protocol_id])
        self.assertEqual(result['id'], self.identifier)
        for text in ('conditions differ', '4096', '2048', 'unconfirmed', peer.owner, protocol_id):
            self.assertIn(text, resumed['result'])
        share = {'requestId': str(uuid4()), 'visibility': 'team'}
        peer.post('/application-content/' + source_id + '/sharing', share)
        peer.post('/application-content/' + source_id + '/sharing', share)
        self.page.wait_for_timeout(1200)
        self.page.reload()
        expect(self.page.get_by_text('自动触发：Peer research', exact=False)).to_be_visible()
        expect(self.page.get_by_text('发布成员：' + peer.owner, exact=True)).to_be_visible()
        expect(self.page.get_by_text('回答引用：' + protocol_id, exact=True)).to_be_visible()
        self.assertEqual(len(self.session()['turns']), len(result['turns']))
        self.assertEqual(len(self.context.request.get(self.origin + '/api/factory/research/sessions/' +
            self.identifier + '/questions').json()['items']), 1)

if __name__ == '__main__':
    unittest.main()
