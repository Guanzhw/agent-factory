"""Real PostgreSQL/native queue/tool execution with a scripted, non-live provider."""
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest

from fastapi.testclient import TestClient
import httpx

from agent_factory_server.main import factory_state
from agent_factory_server.research import create_app
from fixture_auth import initialize_members
from fixture_identity import access_token
from fixture_settings import Settings
from pg_fixture import IsolatedPostgres
from research.session_tools import ResearchSessionTools


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'requires disposable PostgreSQL')
class ResearchUnboundedNativeTests(unittest.TestCase):
    def test_129_real_tools_then_model_window_summary_preserve_original_history(self):
        isolated = self.enterContext(IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']))
        scratch = Path(self.enterContext(TemporaryDirectory()))
        workspace = scratch / 'workspace'
        workspace.mkdir()
        calls, summaries = [], []
        history = 'Verified synthetic observation abcdefgh. ' * 10000

        def wire(request):
            body = json.loads(request.content)
            if not body.get('tools'):
                summaries.append(body)
                message = {'role': 'assistant', 'content': json.dumps({
                    'summary': 'Synthetic native summary: 129 original file reads succeeded.', 'topics': ['verified reads']})}
            else:
                calls.append(body)
                if len(calls) == 1:
                    message = {'role': 'assistant', 'tool_calls': [
                        {'id': 'actual-read-' + str(index), 'type': 'function', 'function': {
                            'name': 'research_read_file', 'arguments': json.dumps({'path': 'evidence.txt'})}}
                        for index in range(129)]}
                elif len(calls) == 2:
                    results = [item for item in body['messages'] if item.get('role') == 'tool']
                    self.assertEqual(len(results), 129)
                    self.assertTrue(all('original-evidence-marker' in item['content'] for item in results))
                    message = {'role': 'assistant', 'content': history}
                else:
                    self.assertIn('Synthetic native summary:', json.dumps(body))
                    self.assertNotIn(history, json.dumps(body))
                    message = {'role': 'assistant', 'content': 'Continued using the preserved native summary.'}
            return httpx.Response(200, json={'id': 'scripted-response', 'model': body['model'],
                'choices': [{'index': 0, 'finish_reason': 'tool_calls' if 'tool_calls' in message else 'stop',
                             'message': message}],
                'usage': {'prompt_tokens': 10, 'completion_tokens': 8, 'total_tokens': 18}})

        tools = ResearchSessionTools(workspace_root=workspace, host_commands=False)
        app = create_app(Settings(db_url=isolated.url, workspace=scratch / 'factory', max_workers=1,
            owner_model_transport_factory=lambda: httpx.MockTransport(wire)), session_tools=tools)
        state = factory_state(app)
        store = state['store']
        initialize_members(state['auth'])
        self.addCleanup(store.engine.dispose)
        self.addCleanup(store.native_db.db_engine.dispose)
        self.addCleanup(store.dispose_root_locks)
        client = self.enterContext(TestClient(app, base_url='https://testserver'))
        model = store.personal_models.configure('alice', {'provider': 'openai-compatible',
            'baseURL': 'http://localhost:8899/v1', 'model': 'scripted-large-context', 'contextWindow': 40000},
            'native-unbounded-model')

        def post(path, body):
            response = client.post('/api/factory/research' + path, json=body,
                headers={'Authorization': 'Bearer ' + access_token('alice')})
            self.assertEqual(response.status_code, 200, response.text)
            return response.json()

        session = post('/sessions', {'requestId': 'native-unbounded-session', 'title': 'Native capacity evidence',
            'goal': 'Read the original evidence and continue.', 'modelConnectionRef': model['connectionRef']})
        tools._workspace({'ownerId': 'alice', 'id': session['id']}).joinpath('evidence.txt').write_text('original-evidence-marker')

        def completed(count):
            deadline = time.monotonic() + 180
            value = None
            while time.monotonic() < deadline:
                response = client.get('/api/factory/research/sessions/' + session['id'],
                    headers={'Authorization': 'Bearer ' + access_token('alice')})
                self.assertEqual(response.status_code, 200, response.text)
                value = response.json()
                if len(value['turns']) == count and value['state'] in {'idle', 'blocked', 'stopped'}:
                    break
                time.sleep(.1)
            self.assertIsNotNone(value)
            assert value is not None
            self.assertEqual(value['state'], 'idle', value)
            self.assertEqual(value['turns'][-1]['status'], 'completed', value)
            return value

        post('/sessions/' + session['id'] + '/turns', {'requestId': 'native-129-reads', 'text': 'Read all 129 observations.'})
        first = completed(1)
        self.assertEqual(first['turns'][0]['result'], history)
        events = store.sql("SELECT data FROM af_events WHERE task_id=:task AND type='research_tool_finished'",
            task=first['turns'][0]['taskId'])
        self.assertEqual(len(events), 129)
        self.assertTrue(all(event['data']['outcome'] == 'completed' for event in events))
        post('/sessions/' + session['id'] + '/turns', {'requestId': 'native-after-long-history', 'text': 'Continue from the observations.'})
        final = completed(2)
        self.assertEqual(final['turns'][0]['result'], history)
        self.assertEqual(final['turns'][1]['result'], 'Continued using the preserved native summary.')
        self.assertEqual(final['context']['compaction']['status'], 'ready')
        self.assertEqual(len(summaries), 1)
        self.assertIn(history, json.dumps(summaries[0]))
        self.assertEqual(len(calls), 3)
