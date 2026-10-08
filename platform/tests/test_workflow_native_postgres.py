# pyright: reportMissingImports=false
"""Real native queue and HTTP process restart; external operations are synthetic.

This is a representative workflow, not a ConvertD implementation. The fixture
model uses ordinary Model.invoke tool calls. SQLite represents a durable inert
external backend; no model/provider network or subprocess tool is available.
"""
from contextlib import ExitStack
import asyncio
import json
import os
from pathlib import Path
import secrets
import socket
import sqlite3
import subprocess
import sys
import sysconfig
import tempfile
import time
import unittest
from uuid import uuid4

import httpx
from agno.models.base import Model
from agno.models.response import ModelResponse

from agent_factory.config import Settings
from agent_factory.execution_bindings import AdapterRegistration, EnvironmentLimits, KnowledgeContext
from agent_factory.main import create_app
from agent_factory.tool_policy_registry import ToolPolicyRegistration
from agent_factory.usage_ledger import PricingRevision
from agent_factory.workflow_contracts import WorkflowAcknowledgementUnknown, workflow_fingerprint
from agent_factory.workflow_profile import PERMISSION, TOOLS, registrations
from pg_fixture import IsolatedPostgres

PROJECT = Path(__file__).resolve().parents[2]
APP = 'representative-workflow-fixture-v1'
MODEL = 'workflow-native-fixture-model-v1'
PROVIDER = 'controlled-workflow-model'
ADAPTER = 'controlled-durable-workflow-v1'


def definition():
    stages = []
    for name, dependencies, gate, routes in (
        ('ingest', [], False, {}), ('analyze', ['ingest'], False, {}),
        ('validate', ['ingest'], False, {}), ('review', ['analyze', 'validate'], True, {}),
        ('convert', ['review'], False, {'CONTROLLED_FAILURE': 'alternative'}),
        ('alternative', ['convert'], False, {}), ('publish', ['review'], False, {})):
        stages.append({'id': name, 'adapterId': ADAPTER, 'revision': '1',
            'dependencies': dependencies, 'humanGate': gate, 'failureRoutes': routes, 'inputs': {}})
    return {'schema': 1, 'id': APP, 'revision': '1', 'maxParallel': 2, 'stages': stages}


class DurableOperations:
    """Only this fixture writes its own SQLite operation state, never real work."""
    def __init__(self, path):
        self.path = str(path)
        self.cancel_ack_unknown = False
        with self.connect() as conn:
            conn.execute('CREATE TABLE IF NOT EXISTS operations(id TEXT PRIMARY KEY, stage TEXT, body TEXT, starts INTEGER, inspections INTEGER, cancels INTEGER)')

    def connect(self):
        return sqlite3.connect(self.path, timeout=5)

    def rows(self):
        with self.connect() as conn:
            return [{'operationId': row[0], 'stage': row[1], 'observation': json.loads(row[2]),
                'starts': row[3], 'inspections': row[4], 'cancels': row[5]}
                for row in conn.execute('SELECT * FROM operations ORDER BY id')]

    async def start(self, context, operation_id, inputs):
        state = 'RUNNING' if context.stage_id in {'analyze', 'validate'} else 'COMPLETED'
        if context.stage_id == 'convert' and inputs['values']['scenario'] == 'failure':
            state = 'FAILED'
        result = {'schema': 1, 'operationId': operation_id,
            'handle': {'adapterId': ADAPTER, 'revision': '1', 'id': operation_id},
            'state': state, 'allStopped': state in {'COMPLETED', 'FAILED'},
            'output': {'fixture': True, 'stage': context.stage_id} if state == 'COMPLETED' else None,
            'failure': {'schema': 1, 'code': 'CONTROLLED_FAILURE', 'messageCode': 'CONTROLLED_FAILURE',
                'retryable': False} if state == 'FAILED' else None}
        with self.connect() as conn:
            # A duplicate start is observable and fails, not hidden by an UPSERT.
            conn.execute('INSERT INTO operations VALUES(?,?,?,1,0,0)',
                (operation_id, context.stage_id, json.dumps(result)))
        if inputs['values']['scenario'] == 'exit-before-pause' and context.stage_id == 'analyze':
            # Real native execution remains in flight after durable external
            # admission. Only fixture process shutdown interrupts this await;
            # there is no timer, busy loop, or second attempt.
            await asyncio.Event().wait()
        if inputs['values']['scenario'] == 'lost-ack' and context.stage_id == 'analyze':
            raise WorkflowAcknowledgementUnknown()
        return result

    async def inspect(self, context, handle):
        with self.connect() as conn:
            row = conn.execute('SELECT body,stage FROM operations WHERE id=?', (handle['id'],)).fetchone()
            if row is None or row[1] != context.stage_id:
                raise ValueError('CONTROLLED_OPERATION_MISMATCH')
            conn.execute('UPDATE operations SET inspections=inspections+1 WHERE id=?', (handle['id'],))
            return json.loads(row[0])

    async def lookup(self, context, operation_id):
        with self.connect() as conn:
            row = conn.execute('SELECT body,stage FROM operations WHERE id=?', (operation_id,)).fetchone()
            if row is None:
                return {'schema': 1, 'operationId': operation_id, 'handle': None,
                    'state': 'UNKNOWN', 'allStopped': False, 'output': None, 'failure': None}
            if row[1] != context.stage_id:
                raise ValueError('CONTROLLED_OPERATION_MISMATCH')
            return json.loads(row[0])

    async def cancel(self, context, handle):
        result = await self.inspect(context, handle)
        if result['state'] not in {'COMPLETED', 'FAILED', 'CANCELLED'}:
            result.update(state='UNKNOWN' if self.cancel_ack_unknown else 'CANCELLED',
                allStopped=not self.cancel_ack_unknown, output=None, failure=None)
        with self.connect() as conn:
            conn.execute('UPDATE operations SET body=?,cancels=cancels+1 WHERE id=?',
                (json.dumps(result), handle['id']))
        return result

    def complete(self):
        with self.connect() as conn:
            for row in conn.execute('SELECT id,stage,body FROM operations').fetchall():
                result = json.loads(row[2])
                if result['state'] == 'RUNNING':
                    result.update(state='COMPLETED', allStopped=True,
                        output={'fixture': True, 'stage': row[1]}, failure=None)
                    conn.execute('UPDATE operations SET body=? WHERE id=?', (json.dumps(result), row[0]))


class WorkflowFixtureModel(Model):
    """Tool selection over actual observations; explicit synthetic model label."""
    def __init__(self):
        super().__init__(id=MODEL, provider=PROVIDER, name='Synthetic workflow driver', retries=0)

    def _response(self, messages):
        tools = [m for m in messages if m.role == 'tool']
        def call(name, **arguments):
            return ModelResponse(role='assistant', tool_calls=[{'id': 'fixture-' + str(len(tools)),
                'type': 'function', 'function': {'name': name, 'arguments': json.dumps(arguments)}}])
        if not tools or tools[-1].tool_name == 'workflow_wait' or tools[-1].tool_call_error:
            return call('workflow_read', requestId='open')
        if tools[-1].tool_name == 'workflow_finish':
            return ModelResponse(role='assistant', content='Representative synthetic workflow completed; modelLive=false.')
        body = json.loads(tools[-1].content)
        if 'stages' not in body:
            return call('workflow_read', requestId='open')
        stages = body['stages']
        if (body['inputValues']['scenario'] == 'explicit-resume'
                and stages['ingest']['state'] == 'PENDING'
                and not any(message.tool_name == 'workflow_wait' for message in tools)):
            return call('workflow_wait', stageId='ingest')
        for stage in body['definition']['stages']:
            name = stage['id']; entry = stages[name]
            if name == 'alternative' and stages['convert']['state'] != 'FAILED':
                continue
            if name == 'publish' and not (stages['convert']['state'] == 'COMPLETED' or
                    stages['alternative']['state'] == 'COMPLETED'):
                continue
            dependencies = stage['dependencies']
            eligible = all(stages[d]['state'] == 'COMPLETED' or
                (name == 'alternative' and d == 'convert' and stages[d]['state'] == 'FAILED') for d in dependencies)
            if eligible and entry['state'] == 'PENDING':
                return call('workflow_choose', stageId=name, requestId='choose-' + name)
        for stage in body['definition']['stages']:
            if stages[stage['id']]['state'] in {'RUNNING', 'WAITING', 'UNKNOWN', 'HUMAN_WAIT'}:
                return call('workflow_wait', stageId=stage['id'])
        return call('workflow_finish', requestId='finish')

    def invoke(self, messages, **kwargs):
        return self._response(messages)

    async def ainvoke(self, messages, **kwargs):
        return self._response(messages)

    def invoke_stream(self, messages, **kwargs):
        yield self._response(messages)

    async def ainvoke_stream(self, messages, **kwargs):
        yield self._response(messages)

    def _parse_provider_response(self, response, **kwargs):
        return response

    def _parse_provider_response_delta(self, response):
        return response


def settings(configuration, backend):
    workflow = definition()
    entries = registrations({APP: workflow})
    entries += [AdapterRegistration('model', MODEL, '1', lambda ctx: WorkflowFixtureModel(), demo_only=True),
        AdapterRegistration('environment', 'workflow-fixture-environment-v1', '1',
            lambda ctx: EnvironmentLimits(timeout_seconds=30), demo_only=True),
        AdapterRegistration('knowledge', 'workflow-fixture-knowledge-v1', '1',
            lambda ctx: KnowledgeContext('Representative synthetic source only.', {'evidenceKind': 'synthetic'}), demo_only=True)]
    policies = tuple(ToolPolicyRegistration(item.tool_name, PERMISSION, '1', False, item.adapter_id, '1')
        for item in entries if item.kind == 'tool' and item.tool_name is not None)
    return Settings(db_url=configuration['dbUrl'], workspace=Path(configuration['workspace']),
        jwt_key=configuration['jwtKey'], max_workers=1, max_tool_calls=32, max_user_tasks=3,
        temporary_policy='admin-review', policy_revision=APP, material_policy_revision=APP,
        runtime_adapters=entries, tool_policies=policies, workflow_definitions={APP: workflow},
        workflow_runtimes={(ADAPTER, '1'): backend},
        usage_pricing=(PricingRevision(MODEL, '1', PROVIDER, MODEL, 'controlled-local-zero-v1',
            local_model_type=WorkflowFixtureModel, per_attempt_input_tokens=32768, per_attempt_output_tokens=4096),))


def publish(state):
    governance, apps = state['material_governance'], state['applications']
    config = {'workflowId': APP, 'workflowSha256': workflow_fingerprint(definition())}
    refs = []
    items = [('prompt', 'instructions', None), ('skill', 'workflow-skill', None),
        ('knowledge', 'knowledge', 'workflow-fixture-knowledge-v1'), ('model', 'model', MODEL),
        ('environment', 'environment', 'workflow-fixture-environment-v1')]
    items += [('tool', name, 'workflow-' + name.removeprefix('workflow_') + '-v1') for name in TOOLS]
    for kind, name, adapter in items:
        identifier = APP + '-' + name
        value = {'id': identifier, 'kind': kind, 'name': name, 'description': 'Synthetic native workflow acceptance.',
            'content': name if kind == 'tool' else 'Use the approved workflow tools and original observations.',
            'license': 'MIT', 'compatibility': ['agno:3.1.0'], 'dependencies': [],
            'permissions': [PERMISSION] if kind == 'tool' else [],
            'provenance': {'kind': 'original', 'notice': 'Representative synthetic fixture; not ConvertD.'}}
        if adapter:
            value['runtimeBinding'] = {'adapterId': adapter, 'revision': '1', 'config': config if kind == 'tool' else {}}
        material = governance.create_draft('manager', value, identifier + ':draft')
        review = governance.request_publication('manager', identifier, material['version'], identifier + ':review')
        governance.decide_publication('bob', review['id'], True, identifier + ':approve')
        refs.append({key: material[key] for key in ('id', 'version', 'sha256')})
    value = {'id': APP, 'name': 'Representative workflow', 'description': 'Synthetic original-native workflow.',
        'defaultMode': 'workflow', 'discoveryKeywords': [], 'modes': {'workflow': {
            'materialRefs': refs, 'toolOrder': list(TOOLS), 'capabilities': [PERMISSION], 'config': {},
            'inputSchema': {'type': 'object', 'additionalProperties': False, 'required': ['scenario'],
                'properties': {'scenario': {'type': 'string', 'maxLength': 20,
                    'enum': ['success', 'failure', 'lost-ack', 'explicit-resume', 'exit-before-pause']}}},
            'connectionRequirements': [], 'budget': {'toolCalls': 32, 'maxDepth': 1, 'maxChildren': 1,
                'experimentSeconds': 30, 'outputBytes': 65536}}}}
    application = apps.create_draft('manager', value, APP + ':draft')
    review = apps.request_publication('manager', APP, application['version'], APP + ':review')
    apps.decide_publication('bob', review['id'], True, APP + ':approve')
    return application


def serve(configuration):
    import uvicorn
    from fastapi import HTTPException, Request
    backend = DurableOperations(Path(configuration['workspace']) / 'controlled-operations.sqlite')
    app = create_app(settings(configuration, backend))
    state = app.app.state.factory
    state['auth'].authorization.unassign('bob', 'factory-user')
    state['auth'].authorization.assign('bob', 'factory-manager')
    application = publish(state)

    def control(request):
        if request.headers.get('X-Fixture-Control') != configuration['controlKey']:
            raise HTTPException(403, 'FIXTURE_CONTROL_DENIED')

    @app.app.get('/__workflow_fixture/facts')
    async def facts(request: Request, taskId: str | None = None):
        control(request)
        store = state['store']
        task = store.task(taskId, 'alice') if taskId else None
        held = store.workflow.task_held(taskId) if taskId else False
        disk = store.sql('SELECT state FROM af_disk_holds WHERE task_id=:id', id=taskId) if taskId else []
        failures = store.sql("SELECT type,data FROM af_events WHERE task_id=:id AND type IN "
            "('tool_failed','protected_denied','lifecycle_cleanup_requested') ORDER BY id LIMIT 20",
            id=taskId) if taskId else []
        return {'application': application, 'operations': backend.rows(), 'pid': os.getpid(),
            'failureEvents': [{'type': row['type'],
                'errorType': row['data'].get('errorType') if row['data'].get('errorType') in
                    {'ConnectionError', 'ValueError', 'RunCancelledException', 'WorkflowAcknowledgementUnknown'} else None,
                'reason': row['data'].get('reason') if row['data'].get('reason') in
                    {'protected-failure', 'cancel-requested', 'native-failure', 'native-ended',
                     'current-authority-ended', 'native-ended-unfinished-workflow'} else None} for row in failures],
            'task': task, 'native': store.native_db.get_job(task['run_id']) if task and task['run_id'] else None,
            'workflow': store.workflow.snapshot_task('alice', taskId) if taskId else None,
            'workflowHeld': held,
            'diskHold': disk[0]['state'] if disk else None,
            'nativeCount': store.sql('SELECT count(*) AS n FROM ai.agno_jobs WHERE session_id=:id', id=taskId)[0]['n'] if taskId else 0}

    @app.app.post('/__workflow_fixture/control')
    async def change(request: Request):
        control(request)
        value = await request.json()
        if value == {'op': 'complete'}:
            backend.complete()
        elif value == {'op': 'revoke'}:
            state['auth'].authorization.unassign('alice', 'factory-user')
        elif value == {'op': 'restore'}:
            state['auth'].authorization.assign('alice', 'factory-user')
        elif value == {'op': 'observer-stop'}:
            await state['store'].lifecycle_observer.stop()
        elif value == {'op': 'observer-start'}:
            await state['store'].lifecycle_observer.start()
        elif value == {'op': 'cancel-ack-unknown'}:
            backend.cancel_ack_unknown = True
        elif value == {'op': 'confirm-cancel'}:
            backend.cancel_ack_unknown = False
        else:
            raise HTTPException(400, 'FIXTURE_CONTROL_INVALID')
        return {'ok': True}

    uvicorn.run(app, host='127.0.0.1', port=configuration['port'], log_level='error', access_log=False)


class WorkflowServer:
    def __init__(self, database_url, root):
        self.root = Path(root)
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        self.configuration = {'dbUrl': database_url, 'workspace': str(self.root / 'workspace'),
            'jwtKey': secrets.token_urlsafe(48), 'controlKey': secrets.token_urlsafe(32), 'port': port}
        Path(self.configuration['workspace']).mkdir(mode=0o700)
        self.config = self.root / 'server.json'
        self.config.write_text(json.dumps(self.configuration), encoding='utf-8')
        self.config.chmod(0o600)
        self.url = 'http://127.0.0.1:' + str(port)
        self.process = self.log = None
        self.pids = []

    def start(self):
        environment = {key: value for key, value in os.environ.items() if key != 'OPENCODE_GO'}
        environment['PYTHONPATH'] = os.pathsep.join([str(PROJECT / 'platform'), str(PROJECT / 'platform/tests'), sysconfig.get_path('purelib')])
        environment['AGNO_TELEMETRY'] = 'false'
        self.log = (self.root / 'server.log').open('ab')
        self.process = subprocess.Popen([getattr(sys, '_base_executable', sys.executable), '-B',
            '-m', 'test_workflow_native_postgres', '--serve', str(self.config)], cwd=PROJECT,
            env=environment, stdin=subprocess.DEVNULL, stdout=self.log, stderr=subprocess.STDOUT)
        self.pids.append(self.process.pid)
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise AssertionError('Controlled workflow server failed: ' + self.diagnostic_tail())
            try:
                if httpx.get(self.url + '/api/health', timeout=1, trust_env=False).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(.1)
        raise AssertionError('Controlled workflow server startup deadline')

    def stop(self):
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(5)
        if self.log:
            self.log.close()

    def diagnostic_tail(self):
        """Only failed synthetic fixtures expose a bounded, credential-redacted tail."""
        path = self.root / 'server.log'
        if not path.exists():
            return 'CONTROLLED_SERVER_LOG_UNAVAILABLE'
        with path.open('rb') as source:
            source.seek(0, 2)
            source.seek(max(0, source.tell() - 12000))
            result = source.read(12000).decode('utf-8', errors='replace')
        for key in ('jwtKey', 'controlKey', 'dbUrl'):
            result = result.replace(self.configuration[key], '[REDACTED_FIXTURE_VALUE]')
        return result

    def request(self, method, path, body=None, *, owner='alice', fixture=False):
        import jwt
        now = int(time.time())
        token = jwt.encode({'sub': owner, 'aud': 'agent-factory', 'iat': now, 'exp': now + 3600},
            self.configuration['jwtKey'], algorithm='HS256')
        headers = {'Authorization': 'Bearer ' + token}
        if fixture:
            headers['X-Fixture-Control'] = self.configuration['controlKey']
        return httpx.request(method, self.url + path, json=body, headers=headers,
            timeout=30, trust_env=False, follow_redirects=False)

    def facts(self, task=None):
        response = self.request('GET', '/__workflow_fixture/facts' + ('?taskId=' + task if task else ''), fixture=True)
        if response.status_code != 200:
            raise AssertionError(response.text)
        return response.json()

    def control(self, operation):
        response = self.request('POST', '/__workflow_fixture/control', {'op': operation}, fixture=True)
        if response.status_code != 200:
            raise AssertionError(response.text)


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires isolated PostgreSQL/native queue')
class WorkflowNativePostgresTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        database = self.stack.enter_context(IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']))
        root = self.stack.enter_context(tempfile.TemporaryDirectory(prefix='native-workflow-'))
        self.server = WorkflowServer(database.url, root)
        self.stack.callback(self.server.stop)
        self.server.start()
        self.application = self.server.facts()['application']

    def request(self, method, path, body=None, *, owner='alice', expected=None):
        response = self.server.request(method, '/api/factory' + path, body, owner=owner)
        diagnostic = response.text
        if response.status_code >= 500:
            # Uvicorn can emit its exception traceback after sending the 500.
            # This request is already a failed fixture: stop/reap this owned
            # server before reading, rather than retrying the mutation.
            self.server.stop()
            diagnostic += '\n' + self.server.diagnostic_tail()
        if expected is None:
            self.assertTrue(response.is_success, diagnostic)
        else:
            self.assertEqual(response.status_code, expected, diagnostic)
        return response.json()

    def post(self, path, body=None, **kwargs):
        return self.request('POST', path, {'requestId': str(uuid4()), **(body or {})}, **kwargs)

    def start_task(self, scenario='success'):
        proposal = self.post('/compositions/proposals', {'goal': 'Representative synthetic workflow',
            'mode': 'workflow', 'applicationRef': {key: self.application[key] for key in ('id', 'version', 'sha256')},
            'inputValues': {'scenario': scenario}})
        plan = self.post('/compositions/proposals/' + proposal['id'] + '/accept')
        self.assertEqual(plan['inputValues'], {'scenario': scenario})
        review = self.post('/plan-reviews', {'planId': plan['id']})
        self.post('/plan-reviews/' + review['id'] + '/decision', {'approved': True}, owner='manager')
        return self.post('/instances', {'planId': plan['id']})

    def until(self, task, predicate):
        deadline = time.monotonic() + 45
        last = None
        while time.monotonic() < deadline:
            last = self.server.facts(task['id'])
            if predicate(last):
                return last
            time.sleep(.15)
        self.server.stop()
        self.fail('Original workflow observation deadline: ' + json.dumps(last, default=str)
            + '\n' + self.server.diagnostic_tail())

    def paused(self, task):
        return self.until(task, lambda value: value['native'] and value['native']['status'] == 'paused')

    def workflow_post(self, task, action, body=None, **kwargs):
        body = dict(body or {})
        if 'expectedVersion' in body:
            body['version'] = body.pop('expectedVersion')
        if action in {'reconcile', 'resume', 'decide'} and 'version' not in body:
            body['version'] = self.server.facts(task['id'])['workflow']['version']
        return self.request('POST', '/workflows/' + task['id'] + '/commands',
            {'commandId': str(uuid4()), 'action': action, **body}, **kwargs)

    def settle_parallel(self, task):
        self.server.control('complete')
        for stage in ('validate', 'analyze'):
            result = self.workflow_post(task, 'reconcile', {'stageId': stage})
            self.assertEqual(result['status'], 'completed', result)
        return self.until(task, lambda value: value['native']['status'] == 'paused' and
            value['workflow']['stages']['analyze']['state'] == 'COMPLETED' and
            value['workflow']['stages']['validate']['state'] == 'COMPLETED')

    def approve_review(self, task, facts):
        result = self.workflow_post(task, 'decide', {'stageId': 'review', 'approved': True,
            'expectedVersion': facts['workflow']['version']})
        self.assertEqual(result['status'], 'completed', result)

    def assert_once(self, task, original):
        facts = self.server.facts(task['id'])
        self.assertEqual(facts['task']['run_id'], original['task']['run_id'])
        self.assertEqual(facts['task']['plan_id'], original['task']['plan_id'])
        self.assertEqual(facts['workflow']['id'], original['workflow']['id'])
        self.assertEqual(facts['nativeCount'], 1)
        self.assertTrue(all(row['starts'] == 1 for row in facts['operations']))
        for name, entry in original['workflow']['stages'].items():
            if entry['operationId']:
                self.assertEqual(facts['workflow']['stages'][name]['operationId'], entry['operationId'])
        return facts

    def test_parallel_pause_process_restart_same_native_and_report(self):
        task = self.start_task('explicit-resume')
        before = self.paused(task)
        self.assertEqual(before['workflow']['stages']['ingest']['state'], 'PENDING')
        self.assertEqual(before['operations'], [])
        command = {'commandId': str(uuid4()), 'action': 'resume', 'stageId': 'ingest',
            'version': before['workflow']['version']}
        path = '/workflows/' + task['id'] + '/commands'
        receipt = self.request('POST', path, command)
        self.assertEqual(receipt['status'], 'completed', receipt)
        self.assertEqual(self.request('POST', path, command), receipt)
        self.assertEqual(self.request('GET', path + '/' + command['commandId']), receipt)
        self.request('POST', path, {**command, 'version': command['version'] + 1}, expected=409)
        original = self.until(task, lambda value: value['native']['status'] == 'paused'
            and value['workflow']['stages']['analyze']['state'] == 'RUNNING'
            and value['workflow']['stages']['validate']['state'] == 'RUNNING')
        self.assertEqual(original['nativeCount'], 1)
        self.assertEqual(original['task']['run_id'], before['task']['run_id'])
        self.assertEqual(original['task']['plan_id'], before['task']['plan_id'])
        self.assertEqual(original['workflow']['id'], before['workflow']['id'])
        ingest = [row for row in original['operations'] if row['stage'] == 'ingest']
        self.assertEqual(len(ingest), 1)
        self.assertEqual(ingest[0]['starts'], 1)
        self.assertEqual({row['stage'] for row in original['operations']}, {'ingest', 'analyze', 'validate'})
        self.assertEqual(original['workflow']['stages']['analyze']['state'], 'RUNNING')
        self.assertEqual(original['workflow']['stages']['validate']['state'], 'RUNNING')
        # A second actual task can reach its own pause with one worker.
        second = self.start_task()
        self.paused(second)
        self.request('POST', '/jobs/' + second['id'] + '/cancel', {})
        self.server.stop()
        self.server.start()
        self.assertNotEqual(self.server.pids[-1], self.server.pids[-2])
        self.assert_once(task, original)
        waiting = self.settle_parallel(task)
        self.assertEqual(waiting['workflow']['stages']['review']['state'], 'HUMAN_WAIT')
        self.approve_review(task, waiting)
        self.until(task, lambda value: value['native']['status'] == 'completed')
        final = self.assert_once(task, original)
        self.assertEqual(final['workflow']['stages']['publish']['state'], 'COMPLETED')
        self.assertEqual(final['workflow']['status'], 'COMPLETED')
        self.request('GET', '/jobs/' + task['id'])
        self.request('GET', '/jobs/' + task['id'], owner='bob', expected=404)

    def test_failure_route_and_lost_ack_lookup_do_not_duplicate_start(self):
        task = self.start_task('failure')
        original = self.paused(task)
        self.assertFalse(any(row['stage'] == 'alternative' for row in original['operations']))
        waiting = self.settle_parallel(task)
        self.approve_review(task, waiting)
        self.until(task, lambda value: value['native']['status'] == 'completed')
        final = self.assert_once(task, original)
        self.assertEqual(final['workflow']['stages']['convert']['state'], 'FAILED')
        self.assertEqual(final['workflow']['stages']['alternative']['state'], 'COMPLETED')
        lost = self.start_task('lost-ack')
        observed = self.until(lost, lambda value: value['workflow'] is not None and
            value['workflow']['stages']['analyze']['state'] == 'UNKNOWN' and
            value['native'] is not None and value['native']['status'] == 'paused')
        self.server.stop()
        self.server.start()
        self.workflow_post(lost, 'reconcile', {'stageId': 'analyze'})
        recovered = self.assert_once(lost, observed)
        self.assertIsNotNone(recovered['workflow']['stages']['analyze']['handle'])
        self.request('POST', '/jobs/' + lost['id'] + '/cancel', {})

    def test_current_revocation_and_owner_isolation_cancel_original(self):
        task = self.start_task()
        original = self.paused(task)
        self.request('GET', '/workflows/' + task['id'], owner='bob', expected=404)
        self.server.control('revoke')
        try:
            self.workflow_post(task, 'decide', {'stageId': 'review', 'approved': True,
                'expectedVersion': original['workflow']['version']}, expected=403)
        finally:
            self.server.control('restore')
        self.server.control('observer-stop')
        self.server.control('cancel-ack-unknown')
        try:
            self.request('POST', '/jobs/' + task['id'] + '/cancel', {})
            held = self.assert_once(task, original)
            self.assertTrue(held['task']['cancel_requested'])
            self.assertFalse(held['task']['terminal'])
            self.assertTrue(held['workflowHeld'])
            self.assertEqual(held['diskHold'], 'HELD')
            for name in ('analyze', 'validate'):
                entry = held['workflow']['stages'][name]
                self.assertEqual(entry['state'], 'UNKNOWN')
                self.assertEqual(entry['handle'], original['workflow']['stages'][name]['handle'])
                self.assertFalse(entry['observation']['allStopped'])
            detail = self.request('GET', '/jobs/' + task['id'])
            self.assertEqual(detail['job']['status'], 'unknown')
        finally:
            self.server.control('confirm-cancel')
            self.server.control('observer-start')
        self.until(task, lambda value: all(row['observation']['allStopped'] for row in value['operations'])
            and not value['workflowHeld'] and value['task']['terminal'])
        final = self.assert_once(task, original)
        self.assertEqual(len(final['operations']), len(original['operations']))
        self.assertTrue(final['task']['cancel_requested'])
        self.assertFalse(final['workflowHeld'])
        self.assertEqual(final['diskHold'], 'RELEASED')

    def test_exit_before_native_pause_preserves_original_unknown_custody(self):
        task = self.start_task('exit-before-pause')
        original = self.until(task, lambda value: value['workflow'] is not None
            and value['workflow']['stages']['analyze']['state'] == 'UNKNOWN'
            and value['native'] is not None and value['native']['status'] == 'running'
            and any(row['stage'] == 'analyze' for row in value['operations']))
        self.assertTrue(original['workflowHeld'])
        self.assertNotEqual(original['native']['status'], 'paused')
        self.assertFalse(original['workflow']['stages']['analyze']['handle'])
        self.assertEqual([row['observation']['state'] for row in original['operations']
            if row['stage'] == 'analyze'], ['RUNNING'])
        self.server.stop()
        self.server.start()
        self.assertNotEqual(self.server.pids[-1], self.server.pids[-2])
        restored = self.assert_once(task, original)
        self.assertEqual({row['operationId'] for row in restored['operations']},
            {row['operationId'] for row in original['operations']})
        # A failed native run may deny admission-oriented reconciliation. Its
        # explicit receipt is still required, never an unclassified HTTP 500.
        receipt = self.workflow_post(task, 'reconcile', {'stageId': 'analyze'})
        self.assertIn(receipt['status'], {'completed', 'unknown', 'rejected', 'recorded'})
        projection = self.request('GET', '/workflows/' + task['id'])
        self.assertTrue(projection['available'])
        self.assertIsInstance(projection['allowedActions'], list)
        current = self.assert_once(task, original)
        stopped = all(row['observation']['allStopped'] for row in current['operations'])
        if not stopped:
            self.assertTrue(current['workflowHeld'], 'Uncertain external work must retain custody')
            self.assertFalse(current['task']['terminal'], 'Native cancellation alone cannot release custody')
        # Explicit operator cancellation is original-only even if the native
        # worker was cancelled during shutdown; no synthetic replacement task.
        cancel = self.workflow_post(task, 'cancel')
        self.assertIn(cancel['status'], {'completed', 'unknown', 'rejected', 'recorded'})
        final = self.assert_once(task, original)
        self.assertEqual({row['operationId'] for row in final['operations']},
            {row['operationId'] for row in original['operations']})
        if not final['workflowHeld'] or final['task']['terminal']:
            self.assertTrue(all(row['observation']['allStopped'] for row in final['operations']))
        else:
            self.assertIn(final['workflow']['stages']['analyze']['state'], {'UNKNOWN', 'RUNNING', 'WAITING'})


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--serve':
        serve(json.loads(Path(sys.argv[2]).read_text(encoding='utf-8')))
    else:
        unittest.main()
