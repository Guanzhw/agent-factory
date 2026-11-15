"""Two members contribute and synthesize through HTTP, native queue and Chromium."""
from io import BytesIO
import json
import re
import time
from types import MethodType, SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from playwright.sync_api import expect

import test_chat_journey as journey
from test_triggers_journey import TriggerModel
from test_native_model import chunk, reply


class TeamModel(TriggerModel):
    def do_POST(self):
        raw = self.rfile.read(int(self.headers['Content-Length']))
        request = json.loads(raw)
        messages = request['messages']
        current = max(i for i, value in enumerate(messages) if value['role'] == 'user')
        instruction = messages[current]['content']
        resumed = instruction.startswith('同事提供的参考回答：') and 'autonomous-team-context:' in instruction
        if not instruction.startswith(('native-team-review:', 'autonomous-team-lead:')) and not resumed:
            self.rfile = BytesIO(raw)
            return super().do_POST()
        self.server.requests.append(request)
        if resumed:
            answer = json.loads(instruction.split('\n', 1)[1])
            payload = json.loads(answer['questionText'].split('autonomous-team-context:', 1)[1])
            assert answer['reply']['citedContentIds'] == [payload['evidenceIds'][1]]
        else:
            payload = json.loads(instruction.split(':', 1)[1])
        results = [value for value in messages[current:] if value['role'] == 'tool']
        steps = [('research_team_work', {'work_id': payload['workId']}),
                 ('research_contribute', {'work_id': payload['workId'],
                     'text': 'Native review: compare the 4096 protocol with the required 2048 budget.',
                     'evidence_ids': [payload['evidenceId']]})] if instruction.startswith('native-team-review:') else []
        if instruction.startswith('autonomous-team-lead:'):
            steps = [('research_request_contribution', {'work_id': payload['workId'],
                'assistant_id': payload['assistantId'], 'text':
                    'Review peer-research-observation against required budget 2048; cite protocol. '
                    'autonomous-team-context:' + json.dumps(payload)})]
        elif resumed:
            steps = [('research_synthesize_team_work', {'work_id': payload['workId'],
                'text': 'Autonomous synthesis: ' + payload['peerOwner'] +
                        ' reviewed the 4096 protocol; the requested 2048 comparison remains unconfirmed.',
                'evidence_ids': payload['evidenceIds']})]
        if len(results) < len(steps):
            name, arguments = steps[len(results)]
            assert name in {tool['function']['name'] for tool in request['tools']}
            changes = [chunk({'role': 'assistant', 'tool_calls': [{'index': 0,
                'id': 'team_' + str(len(results)), 'type': 'function',
                'function': {'name': name, 'arguments': json.dumps(arguments)}}]}), chunk({}, 'tool_calls')]
        else:
            changes = reply('Autonomous synthesis saved.' if resumed else
                            'Native team review saved with protocol evidence.')
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.end_headers()
        for change in changes:
            self.wfile.write(('data: ' + json.dumps(change) + '\n\n').encode())
        self.wfile.write(b'data: [DONE]\n\n')


class TeamWorkJourney(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        journey.ChatJourney.setUpClass.__func__(cls)
        cls.model.RequestHandlerClass = TeamModel

    setUp = journey.ChatJourney.setUp
    post = journey.ChatJourney.post
    session = journey.ChatJourney.session
    send = journey.ChatJourney.send
    wait_for = journey.ChatJourney.wait_for

    def test_members_contribute_review_and_lead_synthesizes_with_original_sources(self):
        peer = SimpleNamespace(browser=self.browser, state=self.state, origin=self.origin, model=self.model,
                               addCleanup=self.addCleanup, assertTrue=self.assertTrue)
        for method in ('post', 'session', 'send'):
            setattr(peer, method, MethodType(getattr(journey.ChatJourney, method), peer))
        journey.ChatJourney.setUp(peer)
        for member, goal in ((self, 'publish-team-research'), (peer, 'publish-peer-protocol')):
            assistant = member.post('/research/assistants', {})
            options = member.context.request.get(self.origin + '/api/factory/research/sessions/options').json()
            member.model_ref = next(item['connectionRef'] for item in options['models'] if item['available'])
            member.assistant = member.post('/research/assistants/me/configurations', {
                'expectedRevision': assistant['configurationRevision'],
                'connectionRefs': {'model': member.model_ref}})
            member.send(goal)
            completed = journey.ChatJourney.wait_for(member, lambda value: value['state'] == 'idle')
            self.assertEqual(completed['turns'][-1]['status'], 'completed')
            self.assertEqual(completed['model']['connectionRef'], member.model_ref)
            member.session_id = completed['id']
            member.evidence_id = next(event['data']['output']['terminalRecordId']
                for event in completed['turns'][-1]['events']
                if event['type'] == 'research_tool_finished'
                and event['data'].get('toolName') == 'research_record_experiment')
        self.assertNotEqual(self.model_ref, peer.model_ref)
        self.assertNotEqual(self.session_id, peer.session_id)

        self.page.get_by_role('button', name='团队协作', exact=True).click()
        panel = self.page.get_by_role('region', name='团队协作记录', exact=True)
        panel.get_by_text('创建团队协作记录', exact=True).click()
        panel.get_by_label('共同目标', exact=True).fill('Determine whether the score gain holds at output budget 2048.')
        panel.get_by_label('名称（可选）', exact=True).fill('Matched-budget team review')
        with self.page.expect_response(lambda response: response.request.method == 'POST'
                                       and response.url.endswith('/research/team-work')) as created:
            panel.get_by_role('button', name='创建团队记录', exact=True).click()
        self.assertTrue(created.value.ok, created.value.text())
        work = created.value.json()
        path = '/research/team-work/' + work['id']
        self.assertEqual(work['leadId'], self.owner)
        self.assertEqual(work['sessionId'], self.session_id)

        panel.get_by_label('贡献内容', exact=True).fill('Score rose from 40 to 60; output budget needs review.')
        panel.get_by_label('证据标识（可选，空格或逗号分隔）', exact=True).fill(self.evidence_id)
        panel.get_by_role('button', name='提交到团队记录', exact=True).click()
        expect(panel.get_by_text('证据：' + self.evidence_id, exact=True)).to_be_visible()
        panel.get_by_label('添加到团队记录').select_option('request')
        panel.get_by_role('combobox', name=re.compile('^同事助手')).select_option(peer.assistant['id'])
        panel.get_by_label('问题', exact=True).fill(
            'Review peer-research-observation: does the score gain hold at output budget 2048? Cite the protocol.')
        messages = self.state['research_sessions'].conversations.messages
        # Lose dispatch after the durable request commits; the existing event worker must recover it.
        with patch.object(messages, 'recover', AsyncMock(side_effect=RuntimeError('synthetic lost dispatch'))):
            with self.page.expect_response(lambda response: response.request.method == 'POST'
                                           and response.url.endswith('/requests')) as dispatched:
                panel.get_by_role('button', name='提交到团队记录', exact=True).click()
            self.assertEqual(dispatched.value.status, 500)

        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            work = self.context.request.get(self.origin + '/api/factory' + path).json()
            question = next(entry for entry in work['entries'] if entry['kind'] == 'request')
            if question['reply'] is not None and question['reply']['state'] == 'available':
                break
            self.page.wait_for_timeout(100)
        self.assertIsNotNone(question['reply'], json.dumps(work))
        self.assertEqual(question['reply']['state'], 'available', json.dumps(work))
        self.assertIn('4096', question['reply']['text'])
        self.assertEqual(question['reply']['citedContentIds'], [peer.evidence_id])
        self.assertEqual(question['memberId'], self.owner)
        self.assertEqual(question['recipientId'], peer.owner)
        self.assertTrue(question['eventId'])
        questions = self.context.request.get(self.origin + '/api/factory/research/sessions/' +
                                            self.session_id + '/questions').json()['items']
        self.assertEqual(len(questions), 1)
        self.assertEqual(questions[0]['id'], question['questionId'])
        self.assertEqual(questions[0]['endpointId'], peer.assistant['qa']['endpointId'])
        store = self.state['store']
        task = store.task(question['delivery']['taskId'], peer.owner)
        self.assertEqual(task['owner_id'], peer.owner)
        self.assertEqual(store.execution(task)['connectionRefs']['model'], peer.model_ref)
        self.assertIsNotNone(store.native_db.get_job(task['run_id']))
        self.assertEqual(len([item for item in store.tasks(peer.owner)
                              if item['request_id'] == task['request_id']]), 1)
        panel.get_by_role('button', name='刷新记录', exact=True).click()
        expect(panel.get_by_text('接收助手：' + peer.owner, exact=True)).to_be_visible()

        peer.page.get_by_role('button', name='团队协作', exact=True).click()
        peer_panel = peer.page.get_by_role('region', name='团队协作记录', exact=True)
        peer_panel.get_by_role('button', name='Matched-budget team review', exact=True).click()
        expect(peer_panel.get_by_text('牵头人：' + self.owner, exact=True)).to_be_visible()
        self.assertEqual(peer_panel.get_by_label('添加到团队记录')
                         .locator('option[value="synthesis"]').count(), 0)
        peer_panel.get_by_label('贡献内容', exact=True).fill('Review: protocol uses 4096; the 2048 comparison is unconfirmed.')
        peer_panel.get_by_label('证据标识（可选，空格或逗号分隔）', exact=True).fill(peer.evidence_id)
        peer_panel.get_by_role('button', name='提交到团队记录', exact=True).click()
        expect(peer_panel.get_by_role('heading', name='成员贡献 · ' + peer.owner, exact=True)).to_be_visible()

        request = {'requestId': str(uuid4()), 'text': 'native-team-review:' + json.dumps({
            'workId': work['id'], 'evidenceId': peer.evidence_id})}
        self.post('/research/sessions/' + self.session_id + '/turns', request)
        native = self.wait_for(lambda value: len(value['turns']) == 2 and value['state'] == 'idle')
        turn = native['turns'][-1]
        self.assertEqual(turn['status'], 'completed')
        self.assertIn('Native team review saved', turn['result'])
        self.assertIn(peer.evidence_id, native['sharedSourceIds'])
        native_work = self.context.request.get(self.origin + '/api/factory' + path).json()
        self.assertEqual(native_work['entries'][0]['origin'], {'sessionId': self.session_id})
        self.assertEqual(native_work['entries'][2]['origin'], {'sessionId': peer.session_id})
        self.assertEqual(native_work['entries'][3]['origin'], {
            'sessionId': self.session_id, 'turnId': turn['id'], 'taskId': turn['taskId'], 'runId': turn['runId']})
        native_task = store.task(turn['taskId'], self.owner)
        context = SimpleNamespace(user_id=self.owner, session_id=store.native_session_id(native_task), run_id=turn['runId'])
        self.assertEqual(journey.ChatJourney.run_async(self.state['research_sessions'].team_work.reconcile(context, 'team_1')), native_work)
        self.post('/research/sessions/' + self.session_id + '/turns', request)
        self.assertEqual(self.context.request.get(self.origin + '/api/factory' + path).json(), native_work)
        self.assertEqual(len(self.session()['turns']), 2)

        panel.get_by_role('button', name='刷新记录', exact=True).click()
        peer_entry = panel.locator('article').filter(has=self.page.get_by_role(
            'heading', name='成员贡献 · ' + peer.owner, exact=True))
        expect(peer_entry.get_by_text('证据：' + peer.evidence_id, exact=True)).to_be_visible()
        expect(panel.get_by_text('回复来源：', exact=False)).to_contain_text(peer.evidence_id)
        source = peer_entry.locator('.rs-sources')
        source.get_by_text('查看来源 ' + peer.evidence_id, exact=True).click()
        expect(source).to_contain_text('protocol-budget-4096')
        expect(source).to_contain_text(peer.owner)
        panel.get_by_label('添加到团队记录').select_option('synthesis')
        conclusion = 'The score gain is unconfirmed at 2048: the recorded protocol used 4096.'
        panel.get_by_role('textbox', name=re.compile('^综合结论')).fill(conclusion)
        panel.get_by_label('证据标识（可选，空格或逗号分隔）', exact=True).fill(
            self.evidence_id + ' ' + peer.evidence_id)
        panel.get_by_role('button', name='提交到团队记录', exact=True).click()
        expect(panel.get_by_role('region', name='当前综合结论', exact=True)).to_contain_text(conclusion)
        final = self.context.request.get(self.origin + '/api/factory' + path).json()
        self.assertEqual([entry['kind'] for entry in final['entries']],
                         ['contribution', 'request', 'contribution', 'contribution', 'synthesis'])
        self.assertEqual([entry['memberId'] for entry in final['entries']],
                         [self.owner, self.owner, peer.owner, self.owner, self.owner])
        self.assertEqual(final['synthesis']['evidenceIds'], [self.evidence_id, peer.evidence_id])
        synthesis = panel.locator('article').filter(has=self.page.get_by_role(
            'heading', name='牵头人综合 · ' + self.owner, exact=True))
        synthesis.get_by_text('查看来源 ' + peer.evidence_id, exact=True).click()
        expect(synthesis).to_contain_text('protocol-budget-4096')
        for member in (self, peer):
            member.page.reload()
            member.page.get_by_role('button', name='团队协作', exact=True).click()
            reopened = member.page.get_by_role('region', name='团队协作记录', exact=True)
            reopened.get_by_role('button', name='Matched-budget team review', exact=True).click()
            expect(reopened.get_by_role('region', name='当前综合结论', exact=True)).to_contain_text(conclusion)
            expect(reopened.get_by_role('heading', name='成员贡献 · ' + peer.owner, exact=True)).to_be_visible()
            self.assertEqual(member.context.request.get(self.origin + '/api/factory' + path).json(), final)
            url = member.page.url
            member.page.close()
            member.page = member.context.new_page()
            member.page.goto(url)
            member.page.get_by_role('button', name='团队协作', exact=True).click()
            reopened = member.page.get_by_role('region', name='团队协作记录', exact=True)
            reopened.get_by_role('button', name='Matched-budget team review', exact=True).click()
            expect(reopened.get_by_role('region', name='当前综合结论', exact=True)).to_contain_text(conclusion)
            self.assertEqual(member.context.request.get(self.origin + '/api/factory' + path).json(), final)

        autonomous = self.post('/research/team-work', {'title': 'Autonomous lead review',
            'goal': 'Ask the protocol author and synthesize the matched-budget evidence.', 'sessionId': self.session_id})
        self.post('/research/sessions/' + self.session_id + '/turns', {'text': 'autonomous-team-lead:' + json.dumps({
            'workId': autonomous['id'], 'assistantId': peer.assistant['id'], 'peerOwner': peer.owner,
            'evidenceIds': [self.evidence_id, peer.evidence_id]})})
        autonomous_session = self.wait_for(lambda value: len(value['turns']) == 4 and value['state'] == 'idle')
        requested, synthesized = autonomous_session['turns'][-2:]
        self.assertEqual([requested['status'], synthesized['status']], ['completed', 'completed'])
        autonomous = self.context.request.get(self.origin + '/api/factory/research/team-work/' + autonomous['id']).json()
        self.assertEqual([entry['kind'] for entry in autonomous['entries']], ['request', 'synthesis'])
        asked, synthesis = autonomous['entries']
        self.assertEqual(asked['memberId'], self.owner)
        self.assertEqual(asked['recipientId'], peer.owner)
        self.assertEqual(asked['reply']['citedContentIds'], [peer.evidence_id])
        self.assertEqual(synthesized['continuation']['questionIds'], [asked['questionId']])
        self.assertEqual(synthesized['assistantReplies'][0]['questionId'], asked['questionId'])
        self.assertEqual(synthesis['origin'], {'sessionId': self.session_id, 'turnId': synthesized['id'],
            'taskId': synthesized['taskId'], 'runId': synthesized['runId']})
        self.assertEqual(synthesis['evidenceIds'], [self.evidence_id, peer.evidence_id])
        self.assertIn(peer.owner, synthesis['text'])
        self.assertIn('unconfirmed', synthesis['text'])
        for turn, tool in ((requested, 'research_request_contribution'), (synthesized, 'research_synthesize_team_work')):
            receipts = [event['data'] for event in turn['events'] if event['type'] == 'research_tool_finished'
                        and event['data'].get('toolName') == tool]
            self.assertEqual(len(receipts), 1)
            self.assertEqual(receipts[0]['outcome'], 'completed')
        peer_task = store.task(asked['delivery']['taskId'], peer.owner)
        self.assertEqual(store.execution(peer_task)['connectionRefs']['model'], peer.model_ref)
        self.assertIsNotNone(store.native_db.get_job(peer_task['run_id']))
        self.page.get_by_role('button', name='关闭团队协作', exact=True).click()
        self.page.get_by_role('button', name='团队协作', exact=True).click()
        panel = self.page.get_by_role('region', name='团队协作记录', exact=True)
        panel.get_by_role('button', name='全部团队记录', exact=True).click()
        panel.get_by_role('button', name='Autonomous lead review', exact=True).click()
        expect(panel.get_by_role('region', name='当前综合结论', exact=True)).to_contain_text('Autonomous synthesis:')


if __name__ == '__main__':
    unittest.main()
