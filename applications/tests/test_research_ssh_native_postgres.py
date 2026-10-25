"""Actual setup/native PG/helper integration; synthetic model HTTP/local SSH transport.

No live provider, sshd, external host or GPU. Reuses the existing SSH custody
fixture and its cleanup, not a second executor or recovery controller.
"""
from dataclasses import replace
from io import BytesIO
import json
import os
import sys
import time
from types import SimpleNamespace
import unittest
from zipfile import ZipFile

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import select

from agent_factory.ssh_process_contract import LAUNCH_TOOL, WAIT_TOOL
from agent_factory_server.main import factory_state
from agent_factory_server.research import create_app
from fixture_auth import initialize_members
from fixture_identity import access_token
import test_ssh_native_postgres as ssh_native
from agno.models.response import ModelResponse
from test_research_workflow_postgres import ResearchModel, objects


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL') and sys.platform == 'linux',
                     'Requires isolated PostgreSQL and Linux process custody')
class ResearchSSHNativePostgresTests(unittest.TestCase):
    def setUp(self):
        self.base = ssh_native.SSHNativePostgresTests('runTest')
        self.addCleanup(self.base.doCleanups)
        self.base.start = self.start_research_host
        self.model_calls = []
        self.child_measurement = None
        self.root_measurement = None
        self.base.setUp()

    def start_research_host(self):
        base = self.base
        script = base.remote / 'selected-training.py'
        script.write_text(
            'import json, pathlib, sys\n'
            'inputs = json.loads(sys.argv[-1])\n'
            'metrics = {"value": inputs["sample"] + 2, "target": 4}\n'
            'print(json.dumps({"metrics": metrics, "source": pathlib.Path(__file__).read_text(),\n'
            ' "recipe": {"command": ["python", "source.py", "--experiment-inputs", json.dumps(inputs)],\n'
            ' "dependencies": "Python standard library", "data": inputs, "expected": metrics},\n'
            ' "privateCanary": pathlib.Path("private.txt").read_text() if pathlib.Path("private.txt").exists() else ""}))\n')
        (base.remote / 'private.txt').write_text('PRIVATE_SSH_STDOUT_NOT_SELECTED')
        wrapper = ('import pathlib, runpy, time; '
            f'pathlib.Path({str(base.started)!r}).open("a").write("started\\n"); '
            f'release=pathlib.Path({str(base.release)!r}); '
            "exec('while not release.exists():\\n time.sleep(.05)'); "
            f'runpy.run_path({str(script)!r}, run_name="__main__")')
        base.profile = replace(base.profile, spec=replace(base.profile.spec, argv=('-I', '-S', '-c', wrapper)),
            input_schema={'type': 'object', 'properties': {'sample': {'type': 'integer', 'minimum': 1, 'maximum': 10}},
                          'required': ['sample'], 'additionalProperties': False}, input_argument='--experiment-inputs')
        base.settings = replace(base.settings, ssh_training_profiles={'native-fixture': base.profile},
            owner_model_transport_factory=lambda: httpx.MockTransport(self.model_wire))
        base.app = create_app(base.settings)
        base.state = factory_state(base.app)
        base.store, base.auth = base.state['store'], base.state['auth']
        initialize_members(base.auth)
        base.client = TestClient(base.app, base_url='https://testserver').__enter__()

    def model_wire(self, request):
        body = json.loads(request.content)
        tool_names = {call['id']: call['function']['name'] for message in body['messages']
                      for call in message.get('tool_calls', [])}
        messages = [SimpleNamespace(**message, tool_name=tool_names.get(message.get('tool_call_id')),
                                    tool_call_error=False) for message in body['messages']]
        names = {tool['function']['name'] for tool in body.get('tools', [])}
        self.model_calls.append(sorted(names))
        if LAUNCH_TOOL in names:
            result = ssh_native.SSHSequenceModel({'sample': 1}, []).response(messages)
            if result.tool_calls and result.tool_calls[0]['function']['name'] == LAUNCH_TOOL:
                result.tool_calls[0]['function']['arguments'] = json.dumps({'inputs': {'sample': 1}})
            waits = [message for message in messages if message.role == 'tool' and message.tool_name == WAIT_TOOL]
            if waits:
                observed = json.loads(waits[-1].content)['operations']
                self.assertEqual(len(observed), 1)
                original = observed[0]
                self.assertTrue(original['allStopped'])
                self.assertEqual(original['exitCode'], 0)
                self.assertTrue(original['output']['utf8Valid'])
                self.assertFalse(original['output']['truncated'])
                measured = json.loads(original['output']['text'])
                self.child_measurement = {'operationId': original['operationId'],
                    'executionStatus': original['executionStatus'], 'metrics': measured['metrics']}
                result.content = json.dumps(self.child_measurement)
        else:
            observed = next((value for value in objects(messages) if 'operation' in value and 'evidenceIds' in value), None)
            if observed:
                original = observed['operation']['output']['result']
                child = json.loads(original) if isinstance(original, str) else original
                metrics = child['metrics']
                self.assertEqual(metrics['target'], 4)
                self.root_measurement = child
                result = ModelResponse(role='assistant', content=json.dumps({'action': 'stop',
                    'outcome': 'met' if metrics['value'] >= metrics['target'] else 'not_met',
                    'reason': 'Compared actual SSH child measurement with the agreed target',
                    'evidenceIds': observed['evidenceIds']}))
            else:
                result = ResearchModel(SimpleNamespace(plan={'mode': 'research'}))._response(messages)
        message = {'role': 'assistant', 'content': result.content}
        if result.tool_calls:
            message['tool_calls'] = result.tool_calls
        return httpx.Response(200, json={'choices': [{'index': 0, 'finish_reason': 'tool_calls' if result.tool_calls else 'stop',
            'message': message}], 'usage': {'prompt_tokens': 100, 'completion_tokens': 50, 'total_tokens': 150}})

    def test_setup_to_original_ssh_child_and_selected_team_evidence(self):
        base = self.base
        request = base.request
        model = request('POST', '/personal-models', {'requestId': 'research-ssh-model',
            'provider': 'openai-compatible', 'baseURL': 'http://localhost:9/v1', 'model': 'controlled-ssh-research'}, expected=201)
        candidates = request('GET', '/research/setup')
        pins = [{key: item[key] for key in ('id', 'version', 'sha256')}
                for item in candidates['experimentMaterials'] if item['id'] in {'ssh-native-launch', 'ssh-native-wait'}]
        self.assertEqual(len(pins), 2)
        launch = next(pin for pin in pins if pin['id'] == 'ssh-native-launch')
        draft = request('POST', '/research/setup/drafts', {'requestId': 'research-ssh-prepare',
            'name': 'Actual SSH research fixture', 'modelConnectionRef': model['connectionRef'],
            'environment': {'adapterId': 'ssh-native-environment', 'revision': '1'},
            'experimentMaterialRefs': pins, 'connectionRefs': {'compute': base.connection},
            'budget': {'toolCalls': 32, 'maxDepth': 1, 'maxChildren': 1, 'operationSeconds': 120, 'outputBytes': 65536}})
        self.assertIsNone(draft['applicationRef'])
        self.assertFalse(base.started.exists())
        published = request('POST', '/research/setup/' + draft['id'] + '/publish', {'requestId': 'research-ssh-publish'})
        application = base.state['applications'].require_current(published['applicationRef'])
        self.assertEqual(application['modes']['experiment']['toolOrder'], [LAUNCH_TOOL, WAIT_TOOL])
        self.assertIn('factory_wait_operations', application['modes']['research']['toolOrder'])
        self.assertTrue(set(application['modes']['experiment']['toolOrder']).issubset(application['modes']['research']['toolOrder']))
        self.assertEqual(base.store.tasks('alice'), [])
        project = request('POST', '/research/projects', {'requestId': 'research-ssh-project', 'title': 'Actual selected SSH output'}, expected=201)
        url = '/research/projects/' + project['id']
        agreement = {'objective': 'Measure the original SSH experiment', 'evaluation': 'Compare actual measurement to target four',
            'stopConditions': 'One controlled experiment', 'budget': {'rounds': 1, 'toolCalls': 32},
            'execution': {'applicationRef': published['applicationRef'], 'mode': 'research',
                'connectionRefs': published['connectionRefs'], 'perRoundCaps': {'rounds': 1, 'toolCalls': 32},
                'deadline': time.time() + 180},
            'evidence': {'kind': 'ssh-process', 'toolMaterial': launch,
                'fields': {'metrics': 'metrics', 'source': 'source', 'run_recipe': 'recipe'}}}
        request('POST', url + '/goals', {'requestId': 'research-ssh-goal', 'expectedVersion': 0, 'agreement': agreement})
        request('POST', url + '/confirm', {'requestId': 'research-ssh-confirm', 'expectedVersion': 1})
        started = request('POST', url + '/start', {'requestId': 'research-ssh-start', 'expectedVersion': 1}, expected=202)
        root_id = started['execution']['taskId']
        root_run = base.store.task(root_id, 'alice')['run_id']
        base.until(base.started.exists, 'actual helper training start')
        rounds = base.state['research_rounds']
        with base.store.engine.connect() as conn:
            attempt = dict(conn.execute(select(rounds.legacy.attempts)).mappings().one())
        child = rounds.legacy.runs.delegated_child('alice', attempt['operation_id'])
        self.assertIsNotNone(child)
        base.until(lambda: (base.store.native_db.get_job(child['runId']) or {}).get('status') == 'paused', 'original SSH child native wait')
        base.release.touch()
        base.until(lambda: base.store.task(root_id, 'alice')['terminal'], 'original research root terminal')
        def terminal_records():
            current = request('GET', url + '/experiments')
            return current if current['rounds'][0]['terminal'] is not None else None
        records = base.until(terminal_records, 'original research terminal record')
        terminal = records['rounds'][0]['terminal']
        self.assertIsNotNone(terminal)
        self.assertEqual(records['rounds'][0]['decision']['outcome'], 'not_met')
        self.assertEqual(base.store.task(root_id, 'alice')['run_id'], root_run)
        self.assertEqual(base.store.task(child['taskId'], 'alice')['run_id'], child['runId'])
        self.assertEqual({row['taskId'] for row in terminal['runtime']}, {root_id, child['taskId']})
        self.assertTrue(all(row['status'] == 'completed' for row in terminal['runtime']))
        self.assertEqual(base.started.read_text().splitlines(), ['started'])
        original = rounds.legacy.runs.ssh_results('alice', child['taskId'], child['runId'])
        self.assertEqual(original['receipt']['executionStatus'], 'COMPLETED')
        self.assertEqual(original['receipt']['exitCode'], 0)
        self.assertTrue(original['output']['utf8Valid'])
        self.assertFalse(original['output']['truncated'])
        self.assertIn('PRIVATE_SSH_STDOUT_NOT_SELECTED', original['output']['text'])
        manifest = request('POST', url + '/deliveries', {'requestId': 'research-ssh-delivery', 'expectedVersion': 1}, expected=201)
        self.assertEqual(manifest['missingEvidence'], [])
        self.assertNotIn('PRIVATE_SSH_STDOUT_NOT_SELECTED', json.dumps(manifest))
        bob = {'Authorization': 'Bearer ' + access_token('bob')}
        endpoint = '/api/factory/research/deliveries/' + manifest['id']
        self.assertEqual(base.client.get(endpoint, headers=bob).status_code, 200)
        download = base.client.get(endpoint + '/download', headers=bob)
        self.assertEqual(download.status_code, 200)
        with ZipFile(BytesIO(download.content)) as archive:
            selected = [json.loads(archive.read(name)) for name in archive.namelist() if name.startswith('evidence/')]
        values = {item['role']: item['value'] for item in selected}
        self.assertEqual(set(values), {'metrics', 'source', 'run_recipe'})
        self.assertEqual(values['metrics'], {'value': 3, 'target': 4})
        self.assertEqual(self.child_measurement, self.root_measurement)
        self.assertEqual(self.root_measurement['metrics'], values['metrics'])
        self.assertEqual(self.root_measurement['operationId'], original['operationId'])
        self.assertNotIn('PRIVATE_SSH_STDOUT_NOT_SELECTED', json.dumps(selected))
        self.assertTrue(all(item['provenance']['operationId'] == original['operationId'] for item in selected))
        base.state['application_content'].set_visibility('alice', manifest['sourceIds'][0], 'personal', 'withdraw-ssh-evidence')
        self.assertEqual(base.client.get(endpoint, headers=bob).status_code, 404)
        self.assertEqual(base.client.get(endpoint + '/download', headers=bob).status_code, 404)
