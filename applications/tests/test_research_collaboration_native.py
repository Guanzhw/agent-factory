"""Real Agno queue/tools and PostgreSQL; explicitly scripted provider, no live model."""
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest

from fastapi.testclient import TestClient
import httpx

from agent_factory.application_content import ContentPublication
from agent_factory_server.main import factory_state
from agent_factory_server.research import create_app
from fixture_auth import initialize_members
from fixture_identity import access_token
from fixture_settings import Settings
from pg_fixture import IsolatedPostgres
from research.session_tools import ResearchSessionTools


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'requires disposable loopback PostgreSQL')
class ResearchAutonomousNativeContracts(unittest.TestCase):
    def test_native_tool_event_offline_qa_and_single_automatic_continuation(self):
        self.run_collaboration()

    def test_native_qa_failure_has_terminal_feedback_without_another_b_task(self):
        self.run_collaboration(fail_recipient=True)

    def run_collaboration(self, *, fail_recipient=False):
        isolated = self.enterContext(IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']))
        scratch = Path(self.enterContext(TemporaryDirectory()))
        workspace = scratch / 'workspace'
        workspace.mkdir()
        calls, evidence_ids, recipient = [], [], {}
        def wire(request):
            body = json.loads(request.content)
            calls.append(body)
            text = json.dumps(body, ensure_ascii=False)
            if body['model'] == 'scripted-colleague':
                self.assertNotIn('tools', body)
                self.assertNotIn('sender-private-goal', text)
                self.assertNotIn('recipient-private-evidence', text)
                self.assertIn('shared-measurement', text)
                content = json.dumps({'answer': 'Scripted answer: measured evidence is limited.',
                    'citations': evidence_ids, 'evidenceLevel': 'agent_analysis'})
                message = {'role': 'assistant', 'content': content}
                if fail_recipient:
                    message = {'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'not-authorized',
                        'type': 'function', 'function': {'name': 'not_a_qa_tool', 'arguments': '{}'}}]}
            else:
                self.assertEqual(body['model'], 'scripted-researcher')
                self.assertIn('sender-private-goal', text)
                if not any(item['model'] == 'scripted-researcher' for item in calls[:-1]):
                    message = {'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'native-autonomous-question',
                        'type': 'function', 'function': {'name': 'research_ask_assistant',
                            'arguments': json.dumps({'assistant_id': recipient['id'], 'text': 'shared-measurement'})}}]}
                elif 'Scripted answer:' in text:
                    message = {'role': 'assistant', 'content': 'Scripted continuation adopted the original evidence.'}
                else:
                    message = {'role': 'assistant', 'content': 'Question saved; awaiting the colleague reply.'}
            return httpx.Response(200, json={'choices': [{
                'finish_reason': 'tool_calls' if 'tool_calls' in message else 'stop', 'message': message}],
                'usage': {'prompt_tokens': 10, 'completion_tokens': 8, 'total_tokens': 18}})
        app = create_app(Settings(db_url=isolated.url, workspace=scratch / 'factory', max_workers=1,
            owner_model_transport_factory=lambda: httpx.MockTransport(wire)),
            session_tools=ResearchSessionTools(workspace_root=workspace, host_commands=True))
        state = factory_state(app)
        initialize_members(state['auth'])
        store = state['store']
        self.addCleanup(store.engine.dispose)
        self.addCleanup(store.native_db.db_engine.dispose)
        self.addCleanup(store.dispose_root_locks)
        client = self.enterContext(TestClient(app, base_url='https://testserver'))
        headers = {owner: {'Authorization': 'Bearer ' + access_token(owner)} for owner in ('alice', 'bob')}
        def post(path, body, owner='alice', expected=200):
            result = client.post('/api/factory/research' + path, json=body, headers=headers[owner])
            self.assertEqual(result.status_code, expected, result.text)
            return result.json()
        models = {owner: store.personal_models.configure(owner, {'provider': 'openai-compatible',
            'baseURL': 'http://localhost:8899/v1', 'model': model}, 'native-collaboration-model-' + owner)
            for owner, model in (('alice', 'scripted-researcher'), ('bob', 'scripted-colleague'))}
        draft = post('/setup/qa/drafts', {'requestId': 'native-collaboration-qa', 'name': 'Scripted colleague',
            'modelConnectionRef': models['bob']['connectionRef'], 'budget': {'toolCalls': 4}}, owner='bob')
        published = post('/setup/' + draft['id'] + '/publish', {'requestId': 'native-collaboration-publish'}, owner='bob')
        recipient.update(post('/assistants', {'requestId': 'native-collaboration-bob'}, owner='bob'))
        caps = {'rounds': 1, 'toolCalls': 4, 'tokenLimit': None, 'amountMicros': None, 'currency': None}
        post('/assistants/me/configurations', {'requestId': 'native-collaboration-configure', 'expectedRevision': 0,
            'applicationRef': published['applicationRef'], 'connectionRefs': published['connectionRefs'],
            'budget': {'caps': caps, 'perQuestionCaps': caps, 'deadline': time.time() + 120}}, owner='bob')
        for visibility, text in (('team', 'shared-measurement'), ('personal', 'recipient-private-evidence')):
            content = state['application_content'].publish('bob', ContentPublication(
                source={'application': 'research', 'record': text, 'revision': '1'}, content={'conclusion': text},
                visibility=visibility), 'native-collaboration-source-' + visibility)
            if visibility == 'team':
                evidence_ids.append(content['id'])
        session = post('/sessions', {'requestId': 'native-autonomous-session', 'title': 'Synthetic collaboration',
            'goal': 'sender-private-goal: find measurements', 'boundaries': 'Use only the shared evidence. Do not train.',
            'modelConnectionRef': models['alice']['connectionRef'],
            'limits': {'maxTurns': 2, 'toolCallsPerTurn': 4, 'operationSeconds': 5}})
        post('/sessions/' + session['id'] + '/turns', {'requestId': 'native-autonomous-first',
            'text': 'Ask the colleague about shared measurements, then continue with the reply.'})
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            result = client.get('/api/factory/research/sessions/' + session['id'], headers=headers['alice']).json()
            questions = state['research_conversations'].listing('alice', session['id'])['items']
            if fail_recipient and questions and questions[0]['collaboration']['state'] == 'blocked':
                break
            if (len(result['turns']) == 2 and result['turns'][-1]['status'] == 'completed'
                    and questions and questions[0]['collaboration']['state'] == 'included'):
                break
            time.sleep(.1)
        if fail_recipient:
            self.assertEqual(len(result['turns']), 1, result)
            self.assertEqual(questions[0]['collaboration']['state'], 'blocked', questions)
            self.assertEqual(questions[0]['collaboration']['code'], 'RESEARCH_ASSISTANT_REPLY_UNAVAILABLE')
            self.assertEqual(len(store.tasks('bob')), 1)
            self.assertEqual(len(calls), 3)
            return
        self.assertEqual(len(result['turns']), 2, {'session': result, 'questions': questions, 'calls': calls})
        self.assertEqual(result['turns'][-1]['status'], 'completed', result)
        self.assertEqual(len(questions), 1)
        question = questions[0]
        self.assertEqual(question['origin'], 'agent')
        self.assertEqual(question['collaboration']['state'], 'included')
        self.assertEqual(question['collaboration']['includedTurnId'], result['turns'][-1]['id'])
        self.assertEqual(result['turns'][-1]['continuation']['questionIds'], [question['id']])
        self.assertEqual(result['turns'][-1]['assistantReplies'][0]['reply']['contentIds'], evidence_ids)
        self.assertEqual(len(store.tasks('alice')), 2)
        self.assertEqual(len(store.tasks('bob')), 1)
        self.assertEqual(len(calls), 4)
        self.assertEqual(len(store.sql('SELECT * FROM research_collaboration_intents')), 1)
        self.assertEqual(len(store.sql('SELECT * FROM af_delegation_links')), 0)
