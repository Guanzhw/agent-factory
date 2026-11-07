"""Native Agno workflow child commands on disposable PostgreSQL, scripted provider."""
import json
import ast
import asyncio
import os
from pathlib import Path
import sys
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
class ResearchCommandNativeTests(unittest.TestCase):
    def test_command_yields_original_handle_reads_output_and_waits_without_model_child(self):
        self.exercise()

    def test_session_stop_reaches_original_workflow_command(self):
        self.exercise(cancel=True)

    def test_two_roots_release_workers_for_queued_command_children(self):
        self.exercise(concurrent=2)

    def test_native_parent_completion_keeps_original_command_child_running(self):
        self.exercise(early_final=True)

    def test_stop_during_initial_yield_reconciles_parent_handle_and_child_stop(self):
        self.exercise(cancel=True, cancel_during_start=True)

    def test_duplicate_original_call_returns_same_child_handle(self):
        self.exercise(replay=True)

    def exercise(self, cancel=False, concurrent=1, early_final=False, cancel_during_start=False, replay=False):
        isolated = self.enterContext(IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']))
        scratch = Path(self.enterContext(TemporaryDirectory()))
        workspace = scratch / 'workspaces'
        workspace.mkdir()
        duration = 60 if cancel else 6 if early_final else float(os.getenv('FACTORY_LONG_COMMAND_SECONDS', '1.5'))
        commands, model_calls, handles = [], [], []
        async def wire(request):
            body = json.loads(request.content)
            model_calls.append(body)
            def decoded(content):
                try:
                    return json.loads(content)
                except ValueError:
                    return ast.literal_eval(content)
            results = [decoded(item['content']) for item in body['messages'] if item['role'] == 'tool']
            if not results:
                argv = [sys.executable, '-u', '-c', 'import time;print("started",flush=True);time.sleep('
                        + str(duration) + ');print("finished",flush=True)']
                commands.append(argv)
                while len(commands) < concurrent:
                    await asyncio.sleep(.01)
                message = {'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'command-original',
                    'type': 'function', 'function': {'name': 'research_run',
                    'arguments': json.dumps({'argv': argv, 'yield_time_ms': 30000 if cancel_during_start else 250})}}]}
            else:
                result = results[-1]
                if 'processId' in result:
                    handles.append(result['processId'])
                if replay and len(results) == 1:
                    message = {'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'command-original',
                        'type': 'function', 'function': {'name': 'research_run',
                        'arguments': json.dumps({'argv': commands[0], 'yield_time_ms': 250})}}]}
                elif result.get('status') in {'queued', 'running'} and not early_final:
                    name = 'research_read_process' if len(results) == 1 else 'research_wait_child'
                    arguments = {'processId': result['processId']} if len(results) == 1 else {'childTaskId': result['childTaskId']}
                    message = {'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'read-original' if len(results) == 1 else 'wait-original',
                        'type': 'function', 'function': {'name': name, 'arguments': json.dumps(arguments)}}]}
                else:
                    message = {'role': 'assistant', 'content': 'Original command completed.'}
            response = {'id': 'synthetic-command-response', 'object': 'chat.completion', 'created': 1,
                'model': body['model'], 'choices': [{'index': 0,
                'finish_reason': 'tool_calls' if 'tool_calls' in message else 'stop', 'message': message}],
                'usage': {'prompt_tokens': 10, 'completion_tokens': 8, 'total_tokens': 18}}
            if body.get('stream'):
                choice = response['choices'][0]
                delta = {**message}
                if 'tool_calls' in delta:
                    delta['tool_calls'] = [{**item, 'index': index} for index, item in enumerate(delta['tool_calls'])]
                chunk = {**response, 'object': 'chat.completion.chunk', 'choices': [
                    {'index': 0, 'delta': delta, 'finish_reason': choice['finish_reason']}]}
                return httpx.Response(200, headers={'content-type': 'text/event-stream'},
                    text='data: ' + json.dumps(chunk) + '\n\ndata: [DONE]\n\n')
            return httpx.Response(200, json=response)
        tools = ResearchSessionTools(workspace_root=workspace, host_commands=True)
        app = create_app(Settings(db_url=isolated.url, workspace=scratch / 'factory', max_workers=2,
            owner_model_transport_factory=lambda: httpx.MockTransport(wire)), session_tools=tools)
        state = factory_state(app)
        store = state['store']
        initialize_members(state['auth'])
        self.addCleanup(store.engine.dispose)
        self.addCleanup(store.native_db.db_engine.dispose)
        self.addCleanup(store.dispose_root_locks)
        client = self.enterContext(TestClient(app, base_url='https://testserver'))
        headers = {'Authorization': 'Bearer ' + access_token('alice')}
        model = store.personal_models.configure('alice', {'provider': 'openai-compatible',
            'baseURL': 'http://localhost:8899/v1', 'model': 'synthetic-command-model'}, 'command-model')
        def post(path, body):
            headers['Authorization'] = 'Bearer ' + access_token('alice')
            response = client.post('/api/factory/research' + path, json=body, headers=headers)
            self.assertEqual(response.status_code, 200, response.text)
            return response.json()
        sessions = [post('/sessions', {'requestId': 'command-session-' + str(index), 'title': 'Command handle',
            'goal': 'Run one original command', 'modelConnectionRef': model['connectionRef']}) for index in range(concurrent)]
        session = sessions[0]
        for index, item in enumerate(sessions):
            post('/sessions/' + item['id'] + '/turns', {'requestId': 'command-turn-' + str(index), 'text': 'Run the command'})
        deadline = time.monotonic() + duration + 90
        cancelled = False
        latest = {}
        parent_finished_while_child_active = False
        while time.monotonic() < deadline:
            headers['Authorization'] = 'Bearer ' + access_token('alice')
            latest_sessions = [client.get('/api/factory/research/sessions/' + item['id'], headers=headers).json() for item in sessions]
            latest = latest_sessions[0]
            if early_final and latest.get('turns') and latest['turns'][0].get('runId'):
                ticket = store.native_db.get_job(latest['turns'][0]['runId'])
                if ticket and ticket.get('status') == 'completed' and any(child['status'] in {'running', 'queued'} for child in latest['turns'][0]['children']):
                    parent_finished_while_child_active = True
                    self.assertNotEqual(latest['state'], 'idle', latest)
            started_files = list(workspace.glob('**/.command-process-*/stdout.txt'))
            if cancel and (handles or cancel_during_start) and not cancelled and any('started' in path.read_text() for path in started_files):
                post('/sessions/' + session['id'] + '/stop', {'requestId': 'command-stop'})
                cancelled = True
            if all(item.get('state') in {'idle', 'stopped', 'blocked'} and item.get('turns') for item in latest_sessions):
                break
            time.sleep(.1)
        from agent_factory.input_schema import input_model
        for child_row in store.sql('SELECT child_id FROM af_delegation_links WHERE owner_id=:owner', owner='alice'):
            child_plan = store.plan(store.task(child_row['child_id'], 'alice')['plan_id'], 'alice')
            actual_schema = store.native_workflows.registrations['research-command'].component.input_schema.model_json_schema()
            expected_schema = input_model(child_plan['inputSchema']).model_json_schema()
            self.assertEqual(actual_schema, expected_schema)
        if early_final:
            self.assertTrue(parent_finished_while_child_active, latest)
        self.assertEqual(len(commands), concurrent, latest)
        if cancel_during_start:
            receipts = latest['turns'][0]['toolResults']
            self.assertEqual(receipts[0]['status'], 'DONE', receipts)
            self.assertIn('processId', receipts[0]['result']['output'])
        else:
            self.assertTrue(handles, latest)
            self.assertEqual(len(set(handles)), concurrent)
        children = store.sql('SELECT child_id FROM af_delegation_links WHERE owner_id=:owner', owner='alice')
        self.assertEqual(len(children), concurrent, latest)
        child = store.task(children[0]['child_id'], 'alice')
        plan = store.plan(child['plan_id'], 'alice')
        self.assertEqual(plan['nativeComponent']['id'], 'research-command')
        self.assertEqual(plan['mode'], 'command')
        self.assertTrue(all(body['model'] == 'synthetic-command-model' for body in model_calls))
        effects = store.effects(child['id'])
        self.assertEqual(len(effects), 1)
        if cancel:
            self.assertEqual(latest['state'], 'stopped', latest)
            self.assertEqual(effects[0]['status'], 'CANCELLED', effects)
            self.assertTrue(effects[0]['result']['stopped'])
        else:
            self.assertEqual(latest['state'], 'idle', latest)
            self.assertEqual(effects[0]['status'], 'DONE', effects)
            self.assertEqual(effects[0]['result']['output']['exitCode'], 0)
            self.assertIn('finished', effects[0]['result']['output']['stdout'])
            self.assertTrue(all(item['turns'][0]['result'] == 'Original command completed.' for item in latest_sessions), latest_sessions)
