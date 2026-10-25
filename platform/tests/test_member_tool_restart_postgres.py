"""A published member command executes in a fresh native worker without tool registration."""
from fixture_identity import access_token
from fixture_auth import initialize_members
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import unittest

from agno.models.base import Model
from agno.models.response import ModelResponse
from fastapi import HTTPException
from fastapi.testclient import TestClient

from fixture_settings import Settings
from agent_factory.execution_bindings import AdapterRegistration, EnvironmentLimits
from agent_factory.main import create_app
from agent_factory.personal_tool_contract import ToolInvocation
from agent_factory.personal_tool_contract import ToolInvocationError
from pg_fixture import IsolatedPostgres

APPLICATION = 'member-custom-command-app'
TOOL = 'member_custom_command'
MODEL = 'member-command-model-fixture'
ENVIRONMENT = 'member-command-environment-fixture'


class CommandModel(Model):
    def __init__(self):
        super().__init__(id=MODEL, name='Deterministic member command driver', provider='controlled-fixture', retries=0)

    def response(self, messages):
        results = [message for message in messages if message.role == 'tool' and message.tool_name == TOOL]
        if results:
            if any(message.tool_call_error for message in results):
                raise ValueError('MEMBER_COMMAND_FIXTURE_FAILED')
            return ModelResponse(role='assistant', content='Member command completed.')
        return ModelResponse(role='assistant', tool_calls=[{'id': 'original-member-command', 'type': 'function',
            'function': {'name': TOOL, 'arguments': json.dumps({'query': 'native-worker'})}}])

    def invoke(self, messages, **kwargs): return self.response(messages)
    async def ainvoke(self, messages, **kwargs): return self.response(messages)
    def invoke_stream(self, messages, **kwargs): yield self.response(messages)
    async def ainvoke_stream(self, messages, **kwargs): yield self.response(messages)
    def _parse_provider_response(self, response, **kwargs): return response
    def _parse_provider_response_delta(self, response): return response


def settings(database, workspace):
    return Settings(db_url=database, workspace=Path(workspace), max_workers=1,
        runtime_adapters=(AdapterRegistration('model', MODEL, '1', lambda _: CommandModel(), ),
            AdapterRegistration('environment', ENVIRONMENT, '1', lambda _: EnvironmentLimits())))


def request(client, auth, method, path, body=None, expected=200, owner='alice'):
    response = client.request(method, '/api/factory' + path, json=body,
        headers={'Authorization': 'Bearer ' + access_token(owner), 'X-Factory-Expected-Owner': owner})
    if response.status_code != expected:
        raise AssertionError(f'{path}: {response.status_code} {response.text}')
    return response.json()


def run_worker():
    """Start before resource creation to exercise another worker's lazy lookup."""
    app = create_app(settings(sys.argv[1], sys.argv[2]))
    state = app.app.state.factory
    store, auth = state['store'], state['auth']
    try:
        with TestClient(app, base_url="https://testserver") as client:
            assert not store.personal_tools.adapters
            (Path(sys.argv[2]) / 'member-worker-ready').write_text('ready')
            print('MEMBER_WORKER_READY', flush=True)
            command = json.loads(sys.stdin.readline())
            body = command['body']
            first = request(client, auth, 'POST', '/application-interface/v1/starts', body, 202)
            task_id = first['job']['id']
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                task = store.task(task_id, 'alice')
                job = store.native_db.get_job(task['run_id']) or {}
                if job.get('status') in {'completed', 'failed', 'cancelled'}:
                    assert job['status'] == 'completed', job
                    break
                time.sleep(.03)
            else:
                raise AssertionError('MEMBER_WORKER_TERMINAL_TIMEOUT')
            repeated = request(client, auth, 'POST', '/application-interface/v1/starts', body, 202)
            assert repeated['job']['id'] == task_id
            effects = store.effects(task_id)
            assert len(effects) == 1 and effects[0]['status'] == 'DONE', effects
            assert command['adapterId'] in store.personal_tools.adapters
            print('MEMBER_WORKER_RESULT ' + json.dumps({'taskId': task_id, 'runId': task['run_id'],
                'output': effects[0]['result']['output'], 'adapterLoaded': True}), flush=True)
    finally:
        store.engine.dispose()
        store.native_db.db_engine.dispose()


@unittest.skipUnless(os.name == 'posix' and os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires Linux and isolated PostgreSQL')
class MemberToolRestartPostgresTests(unittest.TestCase):
    def setUp(self):
        database = IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']).__enter__()
        self.addCleanup(database.__exit__, None, None, None)
        self.directory = TemporaryDirectory(prefix='member-tool-restart-')
        self.addCleanup(self.directory.cleanup)
        self.settings = settings(database.url, self.directory.name)
        self.client = None
        self.start()
        self.addCleanup(self.stop)

    def start(self):
        self.app = create_app(self.settings)
        self.state = self.app.app.state.factory
        self.store, self.auth = self.state['store'], self.state['auth']
        initialize_members(self.auth)
        self.addCleanup(self.store.engine.dispose)
        self.addCleanup(self.store.native_db.db_engine.dispose)
        self.client = TestClient(self.app, base_url="https://testserver").__enter__()

    def stop(self):
        if self.client is not None:
            self.client.__exit__(None, None, None)
            self.client = None

    def call(self, method, path, body=None, expected=200, owner='alice'):
        return request(self.client, self.auth, method, path, body, expected, owner)

    def configure(self, **changes):
        return self.call('POST', '/personal-tools/resources', {
            'transport': 'cli', 'toolName': TOOL, 'description': 'Member-defined native command',
            'executable': sys.executable, 'arguments': ['-c',
                'import os,json,sys,pathlib; p=pathlib.Path("dispatches"); '
                'p.write_text(p.read_text()+"x" if p.exists() else "x"); '
                'print(json.dumps({"query":json.load(sys.stdin)["query"],"config":os.environ["MEMBER_CONFIG"],"cwd":os.getcwd()}))'],
            'workingDirectory': self.directory.name, 'environment': {'MEMBER_CONFIG': 'owner-selected'},
            'inputSchema': {'type': 'object', 'properties': {'query': {'type': 'string'}}, 'required': ['query']},
            'requestId': 'member-command-config', **changes}, 201)

    def publish(self, resource):
        refs = []
        for kind, adapter in (('prompt', None), ('model', MODEL), ('tool', resource['adapterId']), ('environment', ENVIRONMENT)):
            definition = {'id': APPLICATION + '-' + kind, 'kind': kind, 'name': 'Member command ' + kind,
                'content': TOOL if kind == 'tool' else 'Call the selected member command once.',
                'license': 'MIT', 'permissions': ['tool:invoke'] if kind == 'tool' else [], 'compatibility': ['agno:3.1.0'],
                'dependencies': [], 'provenance': {'kind': 'original', 'notice': 'Synthetic member command fixture.'}}
            if adapter:
                definition['runtimeBinding'] = {'adapterId': adapter, 'revision': '1',
                    'config': {'connectionName': 'command'} if kind == 'tool' else {}}
            draft = self.call('POST', '/material-governance/drafts', {'definition': definition, 'requestId': kind + '-draft'}, 201)
            self.call('POST', f'/material-governance/versions/{draft["id"]}/{draft["version"]}/publish', {'requestId': kind + '-publish'})
            refs.append({key: draft[key] for key in ('id', 'version', 'sha256')})
        definition = {'contractVersion': 2, 'id': APPLICATION, 'name': 'Member custom command',
            'description': 'A runtime-discovered member command, published directly by its author.', 'defaultMode': 'execute',
            'modes': {'execute': {'materialRefs': refs, 'capabilities': ['tool:invoke'], 'toolOrder': [TOOL],
                'connectionRequirements': [{'name': 'command', 'kind': 'tool', 'requiredCapabilities': ['tool:invoke']}],
                'budget': {'toolCalls': 2, 'maxDepth': 1, 'maxChildren': 1, 'operationSeconds': 8, 'outputBytes': 65536}}}}
        draft = self.call('POST', '/applications/drafts', {'definition': definition, 'requestId': 'member-application-draft'}, 201)
        self.call('POST', f'/applications/{draft["id"]}/versions/{draft["version"]}/publish', {'requestId': 'member-application-publish'})

    def test_resource_created_after_worker_start_publishes_and_executes_in_another_process(self):
        worker = subprocess.Popen([sys.executable, '-c', 'from test_member_tool_restart_postgres import run_worker; run_worker()',
            self.settings.db_url, str(self.settings.workspace)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: worker.kill() if worker.poll() is None else None)
        deadline = time.monotonic() + 30
        ready = Path(self.directory.name) / 'member-worker-ready'
        while not ready.exists() and worker.poll() is None and time.monotonic() < deadline:
            time.sleep(.03)
        self.assertTrue(ready.exists(), 'Worker did not initialize within 30 seconds')
        resource = self.configure()
        bound = self.call('POST', '/user-connections', {'registrationRef': resource['registrationRef'], 'requestId': 'member-command-bind'}, 201)
        self.publish(resource)
        self.assertFalse(self.settings.personal_tool_adapters)
        self.stop()
        body = {'application': APPLICATION, 'mode': 'execute', 'goal': 'Run the owner-selected command in another process.',
            'requestId': 'cross-process-member-run', 'connectionRefs': {'command': bound['ref']}}
        stdout, stderr = worker.communicate(json.dumps({'body': body, 'adapterId': resource['adapterId']}) + '\n', timeout=55)
        self.assertEqual(worker.returncode, 0, stdout + stderr)
        result = json.loads(next(line.removeprefix('MEMBER_WORKER_RESULT ') for line in stdout.splitlines()
            if line.startswith('MEMBER_WORKER_RESULT ')))
        self.assertEqual(result['output'], {'query': 'native-worker', 'config': 'owner-selected', 'cwd': self.directory.name})
        self.assertEqual((Path(self.directory.name) / 'dispatches').read_text(), 'x')
        self.start()
        self.assertIn(resource['adapterId'], self.store.personal_tools.adapters)
        recovered = self.call('GET', '/application-interface/v1/starts/' + body['requestId'])
        self.assertEqual((recovered['taskId'], recovered['runId']), (result['taskId'], result['runId']))
        repeated = self.call('POST', '/application-interface/v1/starts', body, 202)
        self.assertEqual(repeated['job']['id'], result['taskId'])
        self.assertEqual((Path(self.directory.name) / 'dispatches').read_text(), 'x')

    def test_retained_cli_handle_rechecks_disabled_member_withdrawal_and_revoked_credential(self):
        credential = self.call('POST', '/personal-credentials', {'providerId': 'member-cli', 'destination': sys.executable,
            'username': 'bearer', 'password': 'synthetic-member-cli-token', 'requestId': 'member-cli-key'}, 201)
        resource = self.configure(credentialRef=credential['credentialRef'], credentialRevision=credential['credentialRevision'],
            credentialEnvironmentVariable='MEMBER_TOKEN')
        service = self.store.personal_tools
        service.share('alice', resource['registrationRef'], 'team', 'share-command')
        with self.store.connections._read() as conn:
            handle = service.binding(conn, 'bob', resource['registrationRef']).opaque_handle
        adapter = handle.adapter
        invocation = ToolInvocation('bob', resource['registrationRef'], resource['revision'], 'retained-call', {'query': 'before'},
            None, handle.check_authorized, handle.resolve_credential)
        self.assertEqual(asyncio.run(adapter.invoke(invocation))['query'], 'before')
        self.auth.directory.set_disabled('bob', True)
        with self.assertRaises(ToolInvocationError) as disabled: asyncio.run(adapter.invoke(invocation))
        self.assertEqual((disabled.exception.outcome, disabled.exception.stopped), ('failed', True))
        self.auth.directory.set_disabled('bob', False)
        service.share('alice', resource['registrationRef'], 'personal', 'withdraw-command')
        with self.assertRaises(ToolInvocationError) as withdrawn: asyncio.run(adapter.invoke(invocation))
        self.assertEqual((withdrawn.exception.outcome, withdrawn.exception.stopped), ('failed', True))
        service.share('alice', resource['registrationRef'], 'team', 'restore-command')
        self.call('POST', '/personal-credentials/' + credential['credentialRef'] + '/revoke',
            {'credentialRevision': credential['credentialRevision'], 'requestId': 'revoke-command-key'})
        with self.assertRaises(ToolInvocationError) as revoked: asyncio.run(adapter.invoke(invocation))
        self.assertEqual((revoked.exception.outcome, revoked.exception.stopped), ('failed', True))
        self.assertEqual((Path(self.directory.name) / 'dispatches').read_text(), 'x')
        self.assertNotIn('synthetic-member-cli-token', json.dumps(service.list('bob')))
        with self.assertRaises(HTTPException): service.revoke('bob', resource['registrationRef'], 'not-owner')

    def test_runtime_adapter_http_catalog_respects_current_personal_team_and_revoked_visibility(self):
        resource = self.configure()
        adapter_id = resource['adapterId']
        bindings = self.store.execution_bindings
        bindings.register('tool', 'installed-public-fixture', '1', lambda _: None, tool_name='installed_public_tool')
        def ids(owner):
            return {entry['adapterId'] for entry in self.call('GET', '/runtime-adapters', owner=owner)}
        self.assertIn(adapter_id, ids('alice'))
        self.assertNotIn(adapter_id, ids('bob'))
        self.assertNotIn(adapter_id, ids('manager'))
        self.assertIn('installed-public-fixture', ids('bob'))
        reference = resource['registrationRef']
        self.call('POST', f'/personal-tools/{reference}/sharing', {'visibility': 'team', 'requestId': 'catalog-share'})
        self.assertIn(adapter_id, ids('bob'))
        self.call('POST', f'/personal-tools/{reference}/sharing', {'visibility': 'personal', 'requestId': 'catalog-withdraw'})
        self.assertNotIn(adapter_id, ids('bob'))
        self.call('POST', f'/personal-tools/{reference}/sharing', {'visibility': 'team', 'requestId': 'catalog-restore'})
        self.call('POST', f'/personal-tools/{reference}/revoke', {'requestId': 'catalog-revoke'})
        self.assertNotIn(adapter_id, ids('bob'))
        self.assertNotIn(adapter_id, ids('alice'))
        self.assertIn(adapter_id, {entry['adapterId'] for entry in bindings.describe()}, 'Internal registry remains cached')
