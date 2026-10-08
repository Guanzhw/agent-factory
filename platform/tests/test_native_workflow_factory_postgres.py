# pyright: reportMissingImports=false
"""Actual Factory-governed Agno Workflow, durable queue and subprocess restart.

This is a representative workflow, not a ConvertD implementation. The fixture
model only requests the native external wait. Agno owns all workflow progress. SQLite represents a durable inert
external backend; no model/provider network or subprocess tool is available.
"""
from contextlib import ExitStack
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

from typing import Any, cast
from agno.agent import Agent
from agno.run import RunContext
from agno.tools import tool
from agno.workflow import Workflow
from agno.workflow.parallel import Parallel
from agno.workflow.step import Step
from agno.workflow.types import HumanReview, OnError, OnReject, StepInput, StepOutput
from agent_factory.input_schema import input_model
from agent_factory.config import Settings
from agent_factory.execution_bindings import AdapterRegistration, EnvironmentLimits, KnowledgeContext
from agent_factory.main import create_app
from agent_factory.native_workflows import NativeWorkflowRegistration
from agent_factory.native_external_wait import factory_wait_operations
from agent_factory.tool_policy_registry import ToolPolicyRegistration
from agent_factory.usage_ledger import PricingRevision
from agent_factory.workflow_contracts import WorkflowAcknowledgementUnknown
from pg_fixture import IsolatedPostgres

PROJECT = Path(__file__).resolve().parents[2]
APP = 'native-workflow-factory-fixture-v1'
MODEL = 'native-workflow-factory-model-v1'
PROVIDER = 'controlled-native-workflow-model'
ADAPTER = 'controlled-original-operations-v1'
PIN = {'adapterId': ADAPTER, 'revision': '1', 'configFingerprint': 'a' * 64}
PERMISSION = 'workflow:execute'
FUNCTION_TOOLS = ('fixture_prepare', 'fixture_left', 'fixture_right', 'fixture_review', 'fixture_report')
TOOLS = (*FUNCTION_TOOLS, 'factory_wait_operations')

INPUT_SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': ['scenario'],
    'properties': {'scenario': {'type': 'string', 'maxLength': 20, 'enum': ['success', 'lost-ack']}}}
WorkflowInput = input_model(INPUT_SCHEMA)

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
        state = 'RUNNING' if context.stage_id in {'fixture_left', 'fixture_right'} else 'COMPLETED'
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
        if inputs['values']['scenario'] == 'lost-ack' and context.stage_id == 'fixture_left':
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
    def __init__(self, ctx):
        super().__init__(id=MODEL, provider=PROVIDER)
        self.context = ctx

    def _response(self, messages):
        if any(message.role == 'tool' for message in messages):
            return ModelResponse(role='assistant', content='Original operations resolved; synthetic evidence only.')
        ctx = self.context
        rows = ctx.store.sql('SELECT id FROM af_external_operations WHERE task_id=:id ORDER BY id',
                             id=ctx.run_context.session_id)
        return ModelResponse(role='assistant', tool_calls=[{'id': 'original-operations-wait', 'type': 'function',
            'function': {'name': 'factory_wait_operations', 'arguments': json.dumps({'operationIds': [row['id'] for row in rows]})}}])

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


def build_workflow(holder):
    def step(name):
        async def execute(step_input: StepInput, run_context: RunContext):
            store = holder['state']['store']
            task = store.task(run_context.session_id, run_context.user_id)
            plan = store.plan(task['plan_id'], run_context.user_id)
            record = await store.workflow.start(run_context, name, 'original', PIN, {'values': plan['inputValues']})
            return StepOutput(content=json.dumps({'operationId': record['id'], 'modelLive': False}))
        return Step(name=name, step_id=name, executor=cast(Any, execute), max_retries=0, human_review=HumanReview(on_error=OnError.fail))
    review = step('fixture_review')
    review.human_review = HumanReview(requires_confirmation=True, on_reject=OnReject.cancel, on_error=OnError.fail)
    return Workflow(id=APP, name='Representative native Workflow', input_schema=WorkflowInput,
        steps=cast(Any, [step('fixture_prepare'), Parallel(cast(Any, step('fixture_left')), cast(Any, step('fixture_right')), name='parallel-original'),
            Step(name='original_wait', step_id='original_wait', agent=Agent(id='native-original-wait',
                tools=[factory_wait_operations], telemetry=False), max_retries=0, human_review=HumanReview(on_error=OnError.fail)),
            review, step('fixture_report')]), telemetry=False)


def settings(configuration, backend, holder):
    def registered_tool(name):
        @tool(name=name)
        def denied() -> str:
            """This function is invoked only by the registered native Workflow step."""
            raise ValueError('NATIVE_WORKFLOW_STEP_REQUIRED')
        return denied
    entries = [AdapterRegistration('tool', name + '-v1', '1', lambda ctx, name=name: factory_wait_operations if name == 'factory_wait_operations' else registered_tool(name),
        tool_name=name, permissions=(PERMISSION,)) for name in TOOLS]
    entries += [AdapterRegistration('model', MODEL, '1', WorkflowFixtureModel, demo_only=True),
        AdapterRegistration('environment', 'native-fixture-environment-v1', '1',
            lambda ctx: EnvironmentLimits(timeout_seconds=30), demo_only=True),
        AdapterRegistration('knowledge', 'native-fixture-knowledge-v1', '1',
            lambda ctx: KnowledgeContext('Representative synthetic source.', {'evidenceKind': 'synthetic'}), demo_only=True)]
    return Settings(db_url=configuration['dbUrl'], workspace=Path(configuration['workspace']),
        jwt_key=configuration['jwtKey'], max_workers=1, max_tool_calls=32, max_user_tasks=3,
        temporary_policy='admin-review', policy_revision=APP, material_policy_revision=APP,
        runtime_adapters=entries,
        tool_policies=tuple(ToolPolicyRegistration(adapter_id=name+'-v1', adapter_revision='1', revision='1', read_only=False) for name in TOOLS),
        native_workflows=(NativeWorkflowRegistration(build_workflow(holder), '1', FUNCTION_TOOLS, 'a' * 64),),
        workflow_runtimes={(ADAPTER, '1', PIN['configFingerprint']): backend},
        usage_pricing=(PricingRevision(MODEL, '1', PROVIDER, MODEL, 'controlled-local-zero-v1',
            local_model_type=WorkflowFixtureModel, per_attempt_input_tokens=32768, per_attempt_output_tokens=4096),))

def publish(state):
    governance, apps = state['material_governance'], state['applications']
    refs = []
    items = [('prompt', 'instructions', None), ('skill', 'workflow-skill', None),
        ('knowledge', 'knowledge', 'native-fixture-knowledge-v1'), ('model', 'model', MODEL),
        ('environment', 'environment', 'native-fixture-environment-v1')]
    items += [('tool', name, name + '-v1') for name in TOOLS]
    for kind, name, adapter in items:
        identifier = APP + '-' + name
        value = {'id': identifier, 'kind': kind, 'name': name, 'description': 'Synthetic native workflow acceptance.',
            'content': name if kind == 'tool' else 'Use the approved workflow tools and original observations.',
            'license': 'MIT', 'compatibility': ['agno:3.1.0'], 'dependencies': [],
            'permissions': [PERMISSION] if kind == 'tool' else [],
            'provenance': {'kind': 'original', 'notice': 'Representative synthetic fixture; not ConvertD.'}}
        if adapter:
            value['runtimeBinding'] = {'adapterId': adapter, 'revision': '1', 'config': {}}
        material = governance.create_draft('manager', value, identifier + ':draft')
        review = governance.request_publication('manager', identifier, material['version'], identifier + ':review')
        governance.decide_publication('bob', review['id'], True, identifier + ':approve')
        refs.append({key: material[key] for key in ('id', 'version', 'sha256')})
    value = {'id': APP, 'name': 'Representative workflow', 'description': 'Synthetic original-native workflow.',
        'defaultMode': 'workflow', 'discoveryKeywords': [], 'modes': {'workflow': {
            'nativeComponent': state['store'].native_workflows.pin(APP), 'materialRefs': refs, 'toolOrder': list(TOOLS), 'capabilities': [PERMISSION], 'config': {},
            'inputSchema': INPUT_SCHEMA,
            'connectionRequirements': [], 'budget': {'toolCalls': 32, 'maxDepth': 1, 'maxChildren': 1,
                'experimentSeconds': 30, 'outputBytes': 65536}}}}
    application = apps.create_draft('manager', value, APP + ':draft')
    review = apps.request_publication('manager', APP, application['version'], APP + ':review')
    apps.decide_publication('bob', review['id'], True, APP + ':approve')
    return application


def persisted_steps(store, task, configuration):
    """Bounded diagnostics from original persisted native results, no replay."""
    if not task or not task['run_id']:
        return []
    component = store.native_workflows.registrations[APP].component
    output = component.get_run_output(run_id=task['run_id'], session_id=task['id'])
    if output is None:
        return []
    projected = []
    def collect(items, depth=0):
        if depth > 4:
            raise AssertionError('FIXTURE_STEP_DIAGNOSTIC_DEPTH')
        for item in items or []:
            if len(projected) >= 32:
                raise AssertionError('FIXTURE_STEP_DIAGNOSTIC_COUNT')
            value = item.to_dict() if hasattr(item, 'to_dict') else item
            content = value.get('content')
            content = content if type(content) is str else json.dumps(content, default=lambda _: 'UNSUPPORTED')
            for key in ('jwtKey', 'controlKey', 'dbUrl', 'workspace'):
                content = content.replace(configuration[key], '[REDACTED_FIXTURE_VALUE]')
            content = ''.join(char for char in content[:2048] if char.isprintable() or char == '\n')
            projected.append({'stepId': value.get('step_id'), 'name': value.get('step_name'),
                'success': value.get('success'), 'paused': value.get('is_paused'), 'content': content})
            collect(value.get('steps'), depth + 1)
    collect(output.step_results)
    return projected


def serve(configuration):
    import uvicorn
    from fastapi import HTTPException, Request
    backend = DurableOperations(Path(configuration['workspace']) / 'controlled-operations.sqlite')
    holder = {}
    app = create_app(settings(configuration, backend, holder))
    state = app.app.state.factory
    holder['state'] = state
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
        roots = store.sql('SELECT reclaimed FROM af_delegation_roots WHERE root_id=:id', id=taskId) if taskId else []
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
            'commands': [{'commandId': row['command_id'], 'status': row['body'].get('receipt', {}).get('status'),
                'errorCode': row['body'].get('receipt', {}).get('errorCode')} for row in
                store.sql('SELECT command_id,body FROM af_native_workflow_commands WHERE task_id=:id ORDER BY command_id LIMIT 32', id=taskId)] if taskId else [],
            'nativeSteps': persisted_steps(store, task, configuration),
            'task': task, 'native': store.native_db.get_job(task['run_id']) if task and task['run_id'] else None,
            'custody': [store.workflow.read('alice', row['id']) for row in store.sql('SELECT id FROM af_external_operations WHERE task_id=:id ORDER BY id', id=taskId)] if taskId else [],
            'workflowHeld': held,
            'diskHold': disk[0]['state'] if disk else None,
            'rootReclaimed': roots[0]['reclaimed'] if roots else None,
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
            '-m', 'test_native_workflow_factory_postgres', '--serve', str(self.config)], cwd=PROJECT,
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
class NativeWorkflowFactoryPostgresTests(unittest.TestCase):
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

    def view(self, task):
        return self.request('GET', '/workflows/' + task['id'])['workflow']

    def command(self, task, action, **values):
        if action != 'cancel':
            values.setdefault('version', self.view(task)['version'])
        return self.request('POST', '/workflows/' + task['id'] + '/commands',
            {'commandId': str(uuid4()), 'action': action, **values})

    def assert_original(self, task, original):
        current = self.server.facts(task['id'])
        self.assertEqual(current['task']['run_id'], original['task']['run_id'])
        self.assertEqual(current['task']['plan_id'], original['task']['plan_id'])
        self.assertEqual(current['nativeCount'], 1)
        self.assertTrue(all(row['starts'] == 1 for row in current['operations']))
        self.assertTrue({row['id'] for row in original['custody']} <= {row['id'] for row in current['custody']})
        return current

    def complete_operations(self, task):
        self.server.control('complete')
        for record in self.server.facts(task['id'])['custody']:
            if not record['closed']:
                self.command(task, 'reconcile', operationId=record['id'])
        return self.until(task, lambda facts: facts['native']['status'] == 'paused' and
            all(record['closed'] for record in facts['custody']) and
            any(req['kind'] == 'confirmation' for req in self.view(task)['requirements']))

    def assert_completed_native(self, task, facts=None):
        facts = facts or self.server.facts(task['id'])
        diagnostic = json.dumps({'nativeSteps': facts['nativeSteps'], 'custody': facts['custody']}, default=str)
        self.assertEqual(facts['native']['status'], 'completed', diagnostic)
        self.assertEqual({record['stepId'] for record in facts['custody']}, set(FUNCTION_TOOLS), diagnostic)
        self.assertEqual(len(facts['custody']), len(FUNCTION_TOOLS), diagnostic)
        original_ids = {record['id'] for record in facts['custody']}
        operations = [row for row in facts['operations'] if row['operationId'] in original_ids]
        self.assertEqual({row['stage'] for row in operations}, set(FUNCTION_TOOLS), diagnostic)
        self.assertTrue(all(row['starts'] == 1 for row in operations), diagnostic)
        self.assertTrue(all(record['closed'] for record in facts['custody']), diagnostic)
        leaves = [step for step in facts['nativeSteps'] if step['name'] in {*FUNCTION_TOOLS, 'original_wait'}]
        self.assertEqual({step['name'] for step in leaves}, {*FUNCTION_TOOLS, 'original_wait'}, diagnostic)
        self.assertTrue(all(step['success'] is True and not step['paused'] for step in facts['nativeSteps']), diagnostic)

    def test_single_worker_pause_restart_same_run_continue(self):
        task = self.start_task()
        original = self.paused(task)
        self.assertEqual(len(original['custody']), 3)
        self.assertEqual(sum(not row['closed'] for row in original['custody']), 2)
        # Native pause releases the only worker, demonstrated by a second task.
        second = self.start_task()
        self.paused(second)
        self.command(second, 'cancel')
        self.server.stop()
        self.server.start()
        self.assertNotEqual(self.server.pids[-1], self.server.pids[-2])
        self.assert_original(task, original)
        self.complete_operations(task)
        view = self.view(task)
        self.assertEqual(len(view['requirements']), 1)
        requirement = view['requirements'][0]
        self.assertEqual(requirement['kind'], 'confirmation')
        command = {'commandId': str(uuid4()), 'action': 'decide', 'version': view['version'],
            'requirementId': requirement['id'], 'approved': True}
        path = '/workflows/' + task['id'] + '/commands'
        receipt = self.request('POST', path, command)
        self.assertEqual(self.request('POST', path, command)['commandId'], receipt['commandId'])
        self.request('POST', path, {**command, 'approved': False}, expected=409)
        self.until(task, lambda facts: facts['native']['status'] == 'completed')
        final = self.assert_original(task, original)
        self.assert_completed_native(task, final)
        self.request('GET', '/workflows/' + task['id'], owner='bob', expected=404)

    def test_unknown_lookup_original_operation_external_wait(self):
        task = self.start_task('lost-ack')
        original = self.paused(task)
        unknown = next(row for row in original['custody'] if row['stepId'] == 'fixture_left')
        self.assertIsNone(unknown['handle'])
        self.assertFalse(unknown['closed'])
        self.server.stop()
        self.server.start()
        self.command(task, 'reconcile', operationId=unknown['id'])
        current = self.assert_original(task, original)
        recovered = next(row for row in current['custody'] if row['id'] == unknown['id'])
        self.assertEqual(recovered['handle']['id'], unknown['id'])
        self.assertFalse(recovered['closed'])
        self.assertEqual(current['native']['status'], 'paused')
        self.command(task, 'cancel')
        self.until(task, lambda facts: not facts['workflowHeld'])

    def test_cancel_unknown_retains_until_positive_original_stop(self):
        task = self.start_task()
        original = self.paused(task)
        self.server.control('observer-stop')
        self.server.control('cancel-ack-unknown')
        try:
            self.command(task, 'cancel')
            held = self.assert_original(task, original)
            self.assertTrue(held['task']['cancel_requested'])
            self.assertFalse(held['task']['terminal'])
            self.assertTrue(held['workflowHeld'])
            self.assertEqual(held['diskHold'], 'HELD')
            for record in held['custody']:
                if record['stepId'] in {'fixture_left', 'fixture_right'}:
                    self.assertFalse(record['closed'])
                    self.assertEqual(record['observation']['state'], 'UNKNOWN')
                    self.assertEqual(record['handle']['id'], record['id'])
        finally:
            self.server.control('confirm-cancel')
            self.server.control('observer-start')
        final = self.until(task, lambda facts: not facts['workflowHeld'] and facts['task']['terminal'])
        self.assertTrue(all(row['observation']['allStopped'] for row in final['operations']))
        self.assert_original(task, original)

    def test_withdrawal_preserves_owner_custody_and_unknown_cancel_hold(self):
        task = self.start_task()
        original = self.paused(task)
        self.assertEqual(sum(not row['closed'] for row in original['custody']), 2)
        self.server.control('observer-stop')
        self.server.control('cancel-ack-unknown')
        try:
            # Real governance withdrawal, not fabricated native progress or
            # broadened owner roles. Read/cancel are retained original custody.
            self.post('/applications/' + self.application['id'] + '/versions/' +
                str(self.application['version']) + '/withdraw',
                {'reason': 'Synthetic current-publication revocation'}, owner='manager')
            view = self.view(task)
            self.assertEqual(view['nativeRunId'], original['task']['run_id'])
            self.request('GET', '/jobs/' + task['id'])
            self.request('GET', '/workflows/' + task['id'], owner='bob', expected=404)
            self.request('POST', '/workflows/' + task['id'] + '/commands',
                {'commandId': str(uuid4()), 'action': 'cancel'}, owner='bob', expected=404)
            # A current execution request still checks the withdrawn original
            # publication, while historical reads do not grant continuation.
            denied = self.request('POST', '/workflows/' + task['id'] + '/commands',
                {'commandId': str(uuid4()), 'action': 'decide', 'version': view['version'],
                 'requirementId': view['requirements'][0]['id'], 'approved': True}, expected=409)
            self.assertEqual(denied['code'], 'INACTIVE_APPLICATION')
            self.command(task, 'cancel')
            held = self.assert_original(task, original)
            self.assertTrue(held['task']['cancel_requested'])
            self.assertFalse(held['task']['terminal'])
            self.assertTrue(held['workflowHeld'])
            self.assertEqual(held['diskHold'], 'HELD')
            self.assertIs(held['rootReclaimed'], False)
            self.assertEqual(len(held['custody']), len(original['custody']))
            for record in held['custody']:
                if record['stepId'] in {'fixture_left', 'fixture_right'}:
                    self.assertFalse(record['closed'])
                    self.assertEqual(record['observation']['state'], 'UNKNOWN')
                    self.assertEqual(record['handle']['id'], record['id'])
            self.view(task)
        finally:
            self.server.control('confirm-cancel')
            self.server.control('observer-start')
        final = self.until(task, lambda facts: not facts['workflowHeld'] and facts['task']['terminal'])
        self.assertTrue(all(row['observation']['allStopped'] for row in final['operations']))
        self.assertEqual(final['diskHold'], 'RELEASED')
        self.assert_original(task, original)


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--serve':
        serve(json.loads(Path(sys.argv[2]).read_text(encoding='utf-8')))
    else:
        unittest.main()
