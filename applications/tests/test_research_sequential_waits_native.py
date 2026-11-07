"""Five actual native delegate/wait continuations over one original PostgreSQL run."""
import ast
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest

from fastapi.testclient import TestClient
import httpx

from agent_factory.runtime import CONTEXT_MARKER
from agent_factory_server.main import factory_state
from agent_factory_server.research import create_app
from fixture_auth import initialize_members
from fixture_identity import access_token
from fixture_settings import Settings
from pg_fixture import IsolatedPostgres
from research.session_tools import ResearchSessionTools


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'requires disposable PostgreSQL')
class SequentialChildWaitNativeTests(unittest.TestCase):
    def test_five_sequential_children_resume_the_same_parent_run(self):
        isolated = self.enterContext(IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']))
        scratch = Path(self.enterContext(TemporaryDirectory()))
        children_seen, parent_requests = [], []

        def wire(request):
            body = json.loads(request.content)
            envelope = next(json.loads(line.split(CONTEXT_MARKER, 1)[1])
                for item in body['messages'] if item['role'] == 'system'
                for line in item['content'].splitlines() if CONTEXT_MARKER in line)
            if envelope['normalizedGoal'].startswith('independent-sequential-'):
                children_seen.append(envelope['normalizedGoal'])
                message = {'role': 'assistant', 'content': 'Verified child ' + envelope['normalizedGoal']}
            else:
                parent_requests.append(body)
                names = {call['id']: call['function']['name'] for item in body['messages']
                    if item['role'] == 'assistant' for call in item.get('tool_calls', [])}
                outputs = []
                for item in body['messages']:
                    if item['role'] != 'tool':
                        continue
                    try:
                        output = json.loads(item['content'])
                    except json.JSONDecodeError:
                        output = ast.literal_eval(item['content'])
                    outputs.append((names.get(item.get('tool_call_id')), output))
                delegated = [output for name, output in outputs if name == 'research_delegate']
                waited = [output for name, output in outputs if name == 'research_wait_child']
                if len(waited) == 5:
                    self.assertTrue(all(item['status'] == 'completed' and item['result'] for item in waited))
                    message = {'role': 'assistant', 'content': 'Five original children integrated.'}
                else:
                    number = len(waited) + 1
                    name = 'research_wait_child' if len(delegated) > len(waited) else 'research_delegate'
                    arguments = ({'childTaskId': delegated[-1]['childTaskId']} if name == 'research_wait_child'
                                 else {'goal': 'independent-sequential-' + str(number)})
                    message = {'role': 'assistant', 'tool_calls': [{'id': name + '-' + str(number),
                        'type': 'function', 'function': {'name': name, 'arguments': json.dumps(arguments)}}]}
            return httpx.Response(200, json={'choices': [{'index': 0,
                'finish_reason': 'tool_calls' if 'tool_calls' in message else 'stop', 'message': message}],
                'usage': {'prompt_tokens': 10, 'completion_tokens': 8, 'total_tokens': 18}})

        app = create_app(Settings(db_url=isolated.url, workspace=scratch / 'factory', max_workers=2,
            owner_model_transport_factory=lambda: httpx.MockTransport(wire)),
            session_tools=ResearchSessionTools(host_commands=False))
        state = factory_state(app)
        store = state['store']
        initialize_members(state['auth'])
        self.addCleanup(store.engine.dispose)
        self.addCleanup(store.native_db.db_engine.dispose)
        self.addCleanup(store.dispose_root_locks)
        client = self.enterContext(TestClient(app, base_url='https://testserver'))
        model = store.personal_models.configure('alice', {'provider': 'openai-compatible',
            'baseURL': 'http://localhost:8899/v1', 'model': 'scripted-sequential-waits'}, 'five-child-model')

        def headers():
            return {'Authorization': 'Bearer ' + access_token('alice')}

        def post(path, body):
            response = client.post('/api/factory/research' + path, json=body, headers=headers())
            self.assertEqual(response.status_code, 200, response.text)
            return response.json()

        session = post('/sessions', {'requestId': 'five-child-session', 'title': 'Sequential children',
            'goal': 'Integrate five sequential independent children.', 'modelConnectionRef': model['connectionRef']})
        post('/sessions/' + session['id'] + '/turns', {'requestId': 'five-child-turn', 'text': 'Delegate and wait for each child.'})
        deadline = time.monotonic() + 180
        value = None
        parent_runs = set()
        while time.monotonic() < deadline:
            response = client.get('/api/factory/research/sessions/' + session['id'], headers=headers())
            self.assertEqual(response.status_code, 200, response.text)
            value = response.json()
            parent_runs.update(turn['runId'] for turn in value['turns'] if turn.get('runId'))
            if value['turns'] and value['state'] in {'idle', 'blocked', 'stopped'}:
                break
            time.sleep(.1)
        assert value is not None
        self.assertEqual(value['state'], 'idle', value)
        self.assertEqual(len(value['turns']), 1)
        self.assertEqual(len(parent_runs), 1)
        turn = value['turns'][0]
        self.assertEqual(turn['status'], 'completed', turn)
        self.assertEqual(turn['result'], 'Five original children integrated.')
        self.assertEqual(len(turn['children']), 5)
        self.assertTrue(all(item['status'] == 'completed' for item in turn['children']))
        self.assertEqual(len(set(children_seen)), 5)
        self.assertEqual(len(children_seen), 5)
        self.assertEqual(len(parent_requests), 11)
        decisions = store.sql("SELECT data FROM af_events WHERE task_id=:task AND type='approval_decided'",
            task=turn['taskId'])
        self.assertEqual(len(decisions), 5)
        self.assertEqual(len({item['data']['requirementId'] for item in decisions}), 5)
