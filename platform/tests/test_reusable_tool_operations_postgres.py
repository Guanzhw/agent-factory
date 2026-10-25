"""Real PG/native loops and CLI/MCP IO; only synthetic credentials and peers.

Restart below means fresh application/services against the original PG database,
not an OS process crash. No resolver-only substitute for native workflow evidence.
"""
import asyncio
from concurrent.futures import Future
from collections import deque
from contextvars import ContextVar
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import threading
import time
import traceback
import unittest
from unittest.mock import patch

from sqlalchemy import event

from fastapi import HTTPException
from fixture_settings import Settings
from agent_factory.credential_vault import EncryptedCredentialVault
from agent_factory.execution_bindings import AdapterRegistration, EnvironmentLimits
from agent_factory.personal_cli import cli_destination
from agent_factory.personal_mcp import mcp_url
from agent_factory.personal_tool_contract import ToolInvocationError
from mcp_protocol_fixture import MCPProtocolServer
from pg_fixture import IsolatedPostgres
import test_personal_tool_native_postgres as native

CAPABILITY = 'tool:invoke'


class DestinationPolicy:
    """Use production transport normalization without changing global functions."""
    def __init__(self, normalize):
        self.normalize_destination = normalize

    def __call__(self, destination):
        return self.normalize_destination(destination)


class CallbackTimings:
    """Bounded metadata only; wrap real callback execution without replacing it."""
    def __init__(self):
        self.rows = []
        self.events = deque(maxlen=8192)
        self.events_dropped = 0
        self.detailed = os.environ.get("FACTORY_MCP_DIAGNOSTICS") == "1"
        self.dropped = 0
        self.lock = threading.Lock()
        self.active = ContextVar('reusable-mcp-callback-timing', default=None)

    def record(self, phase, **details):
        if self.detailed:
            with self.lock:
                if len(self.events) == self.events.maxlen:
                    self.events_dropped += 1
                self.events.append({'phase': phase, 'at': time.monotonic(),
                    'thread': threading.get_ident(), **details})

    def stacks(self, loops, run_id):
        def frame_rows(frames):
            return [{'file': frame.filename, 'line': frame.lineno, 'function': frame.name}
                    for frame in frames]
        threads = {str(identifier): frame_rows(traceback.extract_stack(frame))
                   for identifier, frame in sys._current_frames().items()}
        self.record('thread-stacks', runId=run_id, threads=threads)

        def tasks(loop, label):
            self.record('asyncio-stacks', runId=run_id, loop=label, tasks=[{
                'done': task.done(), 'cancelled': task.cancelled(),
                'frames': [{'file': frame.f_code.co_filename, 'line': frame.f_lineno,
                            'function': frame.f_code.co_name} for frame in task.get_stack()]
            } for task in asyncio.all_tasks(loop)])
        for label, loop in loops:
            loop.call_soon_threadsafe(tasks, loop, label)

    def attach_sql(self, engine, cleanup):
        if self.detailed:
            label = str(id(engine.pool))
            original_connect = engine.pool.connect
            def connect():
                self.record('pool-acquire-enter', pool=label)
                try:
                    return original_connect()
                finally:
                    self.record('pool-acquire-exit', pool=label)
            replacement = patch.object(engine.pool, 'connect', connect)
            replacement.start()
            cleanup(replacement.stop)
            def checkout(*args):
                self.record('pool-checkout', pool=label)
            def checkin(*args):
                self.record('pool-checkin', pool=label)
            for name, callback in [('checkout', checkout), ('checkin', checkin)]:
                event.listen(engine.pool, name, callback)
                cleanup(event.remove, engine.pool, name, callback)
        def before(conn, cursor, statement, parameters, context, executemany):
            row = self.active.get()
            if row is not None:
                context._reusable_callback_timing = (row, time.monotonic())
                self.record('sql-enter', runId=row['runId'], callId=row['callId'])
                with self.lock:
                    row['sqlCount'] += 1

        def finish(context):
            timing = getattr(context, '_reusable_callback_timing', None)
            if timing is not None:
                del context._reusable_callback_timing
                row, began = timing
                self.record('sql-exit', runId=row['runId'], callId=row['callId'], seconds=time.monotonic() - began)
                with self.lock:
                    row['sqlSeconds'] += time.monotonic() - began

        def after(conn, cursor, statement, parameters, context, executemany):
            finish(context)

        def failed(exception_context):
            if exception_context.execution_context is not None:
                finish(exception_context.execution_context)

        for name, callback in [('before_cursor_execute', before), ('after_cursor_execute', after), ('handle_error', failed)]:
            event.listen(engine, name, callback)
            cleanup(event.remove, engine, name, callback)

    def wrap(self, original):
        async def checked(state, callback):
            with self.lock:
                if len(self.rows) >= 4096:
                    self.dropped += 1
                    row = None
                else:
                    row = {'runId': state.invocation.run_context.run_id, 'callId': state.invocation.call_id,
                           'callback': 'credential' if callback == state.invocation.resolve_credential else 'authorization',
                           'queuedAt': time.monotonic(), 'sqlCount': 0, 'sqlSeconds': 0.0}
                    self.rows.append(row)
            if row is None:
                return await original(state, callback)

            def measured():
                marker = self.active.set(row)
                with self.lock:
                    row['startedAt'] = time.monotonic()
                    row['threadCPUStarted'] = time.thread_time()
                try:
                    return callback()
                finally:
                    with self.lock:
                        row['endedAt'] = time.monotonic()
                        row['threadCPUEnded'] = time.thread_time()
                    self.active.reset(marker)
            try:
                return await original(state, measured)
            finally:
                with self.lock:
                    row['awaitEndedAt'] = time.monotonic()
                    row['transportStarted'] = state.transport_started
                    row['transportClosed'] = state.transport_closed
                    row['sdkClosed'] = state.sdk_closed
                    row['dispatched'] = state.dispatched
        return checked

    def snapshot(self, run_id):
        with self.lock:
            return {'callbacks': deepcopy([row for row in self.rows if row['runId'] == run_id]),
                    'dropped': self.dropped, 'events': deepcopy(list(self.events)) if self.detailed else [], 'eventsDropped': self.events_dropped}


class OperationModel(native.InventoryModel):
    def response(self, messages):
        if hasattr(self, 'phase'):
            self.phase('model-response', toolResults=sum(message.role == 'tool' for message in messages))
        result = super().response(messages)
        for call in result.tool_calls or []:
            args = json.loads(call['function']['arguments'])
            call['function']['arguments'] = json.dumps({'value': args['item']})
        return result


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires disposable loopback PostgreSQL/native queue')
class ReusableToolOperationPostgresTests(unittest.TestCase):
    def start(self):
        native.PersonalToolNativePostgresTests.start(self)
        if self.transport == 'mcp':
            self.callback_timings.attach_sql(self.store.engine, self.addCleanup)
            if self.store.native_db.db_engine is not self.store.engine:
                self.callback_timings.attach_sql(self.store.native_db.db_engine, self.addCleanup)

    stop = native.PersonalToolNativePostgresTests.stop
    def wait(self, started, owner, *, expected='completed'):
        began = time.monotonic()
        watcher = None
        if self.transport == 'mcp' and self.callback_timings.detailed:
            async def current_loop():
                return asyncio.get_running_loop()
            loop = self.client.portal.call(current_loop)
            original = self.store.task(started['job']['id'], owner)
            watcher = threading.Timer(15, self.callback_timings.stacks, args=([('native', loop), ('mcp-server', self.mcp_loop)], original['run_id']))
            watcher.daemon = True
            watcher.start()
        try:
            # Keep the existing 20-second native wait and terminal assertions.
            return native.PersonalToolNativePostgresTests.wait(self, started, owner, expected=expected)
        except AssertionError as failure:
            task = self.store.task(started['job']['id'], owner)
            job = self.store.native_db.get_job(task['run_id']) or {}
            run = self.store.native_db.get_run(task['run_id'])
            observer = self.state['lifecycle_observer']
            worker = observer.worker_getter()
            fields = ('status', 'created_at', 'updated_at', 'started_at', 'completed_at',
                      'scheduled_at', 'locked_at', 'lock_expires_at', 'worker_id', 'attempts')
            effects = []
            for effect in self.store.effects(task['id']):
                receipt = effect.get('result')
                effects.append({key: effect.get(key) for key in ('effect_key', 'status', 'created_at', 'updated_at')} | {
                    'receipt': {key: receipt[key] for key in ('outcome', 'stopped', 'cancelled') if key in receipt}
                        if isinstance(receipt, dict) else None})
            diagnostics = {'elapsedSeconds': round(time.monotonic() - began, 3),
                'task': {key: task.get(key) for key in ('id', 'run_id', 'request_id', 'terminal', 'cancel_requested',
                    'admission', 'created_at', 'updated_at')},
                'job': {key: job.get(key) for key in fields},
                'run': {key: getattr(run, key, None) for key in ('run_id', 'status', 'created_at')},
                'effects': effects, 'businessCalls': self.calls(),
                'phases': self.phases.get(task['run_id'], []),
                'workerPresent': worker is not None, 'workerType': type(worker).__name__,
                'workerState': {key: value for key in ('worker_id', '_running', '_stopping', '_stopped')
                    if isinstance(value := getattr(worker, key, None), (str, int, bool))},
                'observerError': observer.last_error_type, 'observerStopped': observer._stop.is_set(),
                'observerTaskDone': observer._task.done() if observer._task is not None else None}
            if self.transport == 'mcp':
                # Never include HTTP headers: the protocol fixture holds synthetic auth there.
                diagnostics['callbackTimings'] = self.callback_timings.snapshot(task['run_id'])
                diagnostics['mcp'] = {'calls': self.mcp.calls, 'requests': len(self.mcp.requests),
                    'closed': self.mcp.closed, 'serverTaskDone': self.mcp._task.done() if self.mcp._task else None}
            raise self.failureException(str(failure) + ': ' + json.dumps(diagnostics, default=str, sort_keys=True)) from failure
        finally:
            if watcher is not None:
                watcher.cancel()
                watcher.join()

    def request(self, *args, **kwargs):
        result = native.PersonalToolNativePostgresTests.request(self, *args, **kwargs)
        self.assertNotIn('synthetic-operation-token-', json.dumps(result))
        return result

    def setup_transport(self, transport, *, pause=False, retry_unknown=False):
        database = IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']).__enter__()
        self.addCleanup(database.__exit__, None, None, None)
        directory = TemporaryDirectory(prefix='reusable-operation-native-')
        self.addCleanup(directory.cleanup)
        self.marker = Path(directory.name) / 'business.jsonl'
        self.transport = transport
        if transport == 'mcp':
            from agent_factory.personal_mcp import _InvocationState
            self.callback_timings = CallbackTimings()
            if self.callback_timings.detailed:
                from mcp import ClientSession
                def observed(original, name):
                    async def invoke(session, *args, **kwargs):
                        self.callback_timings.record(name + '-enter')
                        try:
                            return await original(session, *args, **kwargs)
                        except BaseException as error:
                            self.callback_timings.record(name + '-error', exception=type(error).__name__)
                            raise
                        finally:
                            self.callback_timings.record(name + '-exit')
                    return invoke
                for name in ('initialize', 'list_tools', 'call_tool'):
                    self.enterContext(patch.object(ClientSession, name, observed(getattr(ClientSession, name), name)))
            self.enterContext(patch.object(_InvocationState, 'checked_callback',
                self.callback_timings.wrap(_InvocationState.checked_callback)))
        self.phases = {}
        self.pause = (threading.Event(), threading.Event()) if pause else None
        configuration = {'transport': transport, 'toolName': native.TOOL,
            'description': 'Synthetic public reusable operation', 'readOnly': True,
            'inputSchema': {'type': 'object', 'properties': {'value': {'type': 'string'}}, 'required': ['value']},
            'timeoutSeconds': 20, 'maxOutputBytes': 65536}
        if transport == 'cli':
            configuration.update(executable=sys.executable,
                arguments=['-I', str(Path(__file__).with_name('reusable_operation_cli_fixture.py')), str(self.marker)],
                credentialEnvironmentVariable='REUSABLE_FIXTURE_TOKEN')
            self.destination = sys.executable
        else:
            self.mcp = MCPProtocolServer()
            if self.callback_timings.detailed:
                original_http = self.mcp._authenticated
                async def observed_http(scope, receive, send):
                    self.callback_timings.record('mcp-http-enter', method=scope.get('method'))
                    async def observed_send(message):
                        if message['type'] == 'http.response.start':
                            self.callback_timings.record('mcp-http-response', status=message['status'])
                        await send(message)
                    try:
                        await original_http(scope, receive, observed_send)
                    finally:
                        self.callback_timings.record('mcp-http-exit')
                self.mcp._authenticated = observed_http
            self.mcp.tokens.update({'synthetic-operation-token-' + name: name for name in ('alice', 'bob', 'alice-second')})
            ready, stopped = Future(), threading.Event()
            errors = []
            async def serve():
                self.mcp_loop = asyncio.get_running_loop()
                async with self.mcp:
                    ready.set_result(None)
                    await asyncio.to_thread(stopped.wait)
            def run():
                try:
                    asyncio.run(serve())
                except BaseException as error:
                    errors.append(error)
                    if not ready.done():
                        ready.set_exception(error)
            thread = threading.Thread(target=run, daemon=True)
            thread.start()
            def close():
                stopped.set()
                thread.join(5)
                self.assertFalse(thread.is_alive(), 'Owned MCP fixture must stop')
                self.assertEqual(errors, [])
            self.addCleanup(close)
            ready.result(5)
            configuration.update(url=self.mcp.url, remoteToolName='echo')
            self.destination = self.mcp.url
        def model_factory(context):
            phases = self.phases.setdefault(context.run_context.run_id, [])
            def phase(name, **details):
                phases.append({'phase': name, 'monotonicSeconds': round(time.monotonic(), 6), **details})
            phase('model-created')
            model = OperationModel(retry_unknown=retry_unknown, pause=self.pause)
            model.phase = phase
            return model
        self.settings = Settings(db_url=database.url, workspace=Path(directory.name), max_workers=2,
            max_user_tasks=2, temporary_policy='member-self-service',
            runtime_adapters=[AdapterRegistration('model', native.MODEL, '1',
                model_factory, ),
                AdapterRegistration('environment', native.ENVIRONMENT, '1', lambda _: EnvironmentLimits())],
            credential_vault_factory=lambda engine: EncryptedCredentialVault(engine, b't' * 32,
                {'member-cli': DestinationPolicy(cli_destination), 'member-mcp': DestinationPolicy(mcp_url)}))
        self.client = None
        self.start()
        self.addCleanup(self.stop)
        if self.pause:
            self.addCleanup(self.pause[1].set)
        self.operation = self.request('POST', '/personal-tools/operations',
            {'configuration': configuration, 'requestId': 'public-operation'}, expected=201)
        listing = self.request('GET', '/personal-tools/operations', owner='bob')
        self.assertIn(self.operation, listing)
        self.publish()

    def publish(self):
        governance, applications = self.state['material_governance'], self.state['applications']
        materials = []
        for kind, adapter in (('prompt', None), ('model', native.MODEL), ('tool', None), ('environment', native.ENVIRONMENT)):
            definition = {'id': native.APPLICATION + '-' + kind, 'kind': kind, 'name': 'Reusable ' + kind,
                'content': native.TOOL if kind == 'tool' else 'Call the declared tool twice.',
                'license': 'MIT', 'permissions': [CAPABILITY] if kind == 'tool' else [],
                'compatibility': ['agno:3.1.0'], 'dependencies': [],
                'provenance': {'kind': 'original', 'notice': 'Synthetic operation fixture'}}
            if kind == 'tool':
                definition['runtimeBinding'] = {**self.operation['runtimeBinding'], 'config': {
                    **self.operation['runtimeBinding']['config'], 'connectionName': 'inventory'}}
            elif adapter:
                definition['runtimeBinding'] = {'adapterId': adapter, 'revision': '1', 'config': {}}
            material = governance.create_draft('alice', definition, kind + '-draft')
            governance.publish('alice', material['id'], material['version'], kind + '-publish')
            materials.append({key: material[key] for key in ('id', 'version', 'sha256')})
            if kind == 'tool':
                self.material_ref = materials[-1]
        application = applications.create_draft('alice', {'contractVersion': 2, 'id': native.APPLICATION,
            'name': 'Reusable operation fixture', 'description': 'Same published material, independent accounts',
            'defaultMode': 'lookup', 'modes': {'lookup': {'materialRefs': materials, 'capabilities': [CAPABILITY],
                'toolOrder': [native.TOOL], 'connectionRequirements': [{'name': 'inventory', 'kind': 'tool',
                    'requiredCapabilities': [CAPABILITY]}], 'budget': {'toolCalls': 4, 'maxDepth': 1,
                    'maxChildren': 1, 'operationSeconds': 30, 'outputBytes': 65536}}}}, 'application-draft')
        applications.publish('alice', application['id'], application['version'], 'application-publish')

    def account(self, owner, identity):
        credential = self.request('POST', '/personal-credentials', {'requestId': identity + '-key',
            'providerId': 'member-' + self.transport, 'destination': self.destination,
            'username': identity, 'password': 'synthetic-operation-token-' + identity}, owner=owner, expected=201)
        ref = self.operation['operationRef']
        account = self.request('POST', '/personal-tools/operations/' + ref['id'] + '/accounts',
            {'version': ref['version'], 'sha256': ref['sha256'], 'requestId': identity + '-account',
             'credentialRef': credential['credentialRef'], 'credentialRevision': credential['credentialRevision']},
            owner=owner, expected=201)
        self.assertEqual(account['operationRef'], ref)
        return account, self.bind(owner, account, identity)

    def bind(self, owner, account, suffix):
        return self.request('POST', '/user-connections', {'registrationRef': account['registrationRef'],
            'requestId': suffix + '-bind'}, owner=owner, expected=201)

    def submit(self, owner, connection, request_id):
        body = {'application': native.APPLICATION, 'mode': 'lookup', 'goal': 'Read two synthetic values.',
            'requestId': request_id, 'connectionRefs': {'inventory': connection['ref']}}
        return body, self.request('POST', '/application-interface/v1/starts', body, owner=owner, expected=202)

    def calls(self):
        if self.transport == 'mcp':
            return [owner for tool, owner in self.mcp.calls if tool == 'echo']
        return [json.loads(line)['owner'] for line in self.marker.read_text().splitlines()] if self.marker.exists() else []

    def assert_run(self, owner, connection, identity, request_id):
        body, started = self.submit(owner, connection, request_id)
        task = self.wait(started, owner)
        if self.transport == 'mcp':
            print('MCP_OPERATION_CALLBACK_EVIDENCE ' + json.dumps(self.callback_timings.snapshot(task['run_id']), sort_keys=True))
        plan = self.store.plan(task['plan_id'], owner)
        spec = plan['executionBindings']['tools'][0]
        self.assertEqual(spec['adapterId'], self.operation['runtimeBinding']['adapterId'])
        self.assertEqual(spec['config']['operationSha256'], self.operation['operationRef']['sha256'])
        self.assertIn(self.material_ref, plan['materialRefs'])
        self.assertEqual(plan['bindingManifest']['connections']['inventory']['ref'], connection['ref'])
        effects = self.store.effects(task['id'])
        self.assertEqual(len(effects), 2)
        for effect in effects:
            self.assertEqual(effect['status'], 'DONE')
            output = effect['result']['output']
            self.assertEqual((output['structuredContent'] if self.transport == 'mcp' else output)['owner'], identity)
        self.assertNotIn('synthetic-operation-token-', json.dumps([plan, effects, self.store.events(task['id'])]))
        self.assertEqual(self.request('POST', '/application-interface/v1/starts', body, owner=owner, expected=202)['job']['id'], task['id'])
        return task

    def matrix(self, transport):
        self.setup_transport(transport)
        alice, a = self.account('alice', 'alice')
        bob, b = self.account('bob', 'bob')
        second, a2 = self.account('alice', 'alice-second')
        self.assertEqual(len({row['registrationRef'] for row in (alice, bob, second)}), 3)
        self.assertEqual(len({row['revision'] for row in (alice, bob, second)}), 3)
        self.request('POST', '/personal-tools/' + alice['registrationRef'] + '/sharing',
            {'visibility': 'team', 'requestId': 'share-alice'})
        shared = self.bind('bob', alice, 'bob-shared')
        tasks = []
        for owner, connection, identity, request in [('alice', a, 'alice', 'alice-native-run'),
                ('bob', b, 'bob', 'bob-native-run'), ('alice', a2, 'alice-second', 'second-run'),
                ('bob', shared, 'alice', 'shared-run')]:
            tasks.append((owner, request, self.assert_run(owner, connection, identity, request)))
        self.assertEqual(self.calls(), ['alice'] * 2 + ['bob'] * 2 + ['alice-second'] * 2 + ['alice'] * 2)
        self.stop()
        self.start()
        for owner, request, task in tasks:
            receipt = self.request('GET', '/application-interface/v1/starts/' + request, owner=owner)
            self.assertEqual((receipt['taskId'], receipt['runId']), (task['id'], task['run_id']))
            self.assertFalse(receipt['automaticReplay'])
        self.assertEqual(len(self.calls()), 8)
        handles = [self.store.connections.resolve(owner, connection['ref'], 'tool')
            for owner, connection in [('alice', a), ('bob', b), ('alice', a2), ('bob', shared)]]
        restored = self.store.personal_tools.adapters[self.operation['runtimeBinding']['adapterId']]
        self.assertTrue(all(handle.adapter is restored for handle in handles))
        self.assertEqual((handles[-1].owner, handles[-1].requesting_actor), ('alice', 'bob'))
        self.request('POST', '/personal-tools/' + alice['registrationRef'] + '/revoke', {'requestId': 'revoke-alice'})
        self.assert_run('bob', b, 'bob', 'bob-after-restart')
        self.assertEqual(self.calls()[-2:], ['bob', 'bob'])
        ref = self.operation['operationRef']
        before = list(self.calls())
        self.request('POST', '/personal-tools/operations/' + ref['id'] + '/accounts',
            {'version': ref['version'], 'sha256': '0' * 64, 'requestId': 'wrong-hash'}, owner='bob', expected=409)
        self.assertEqual(self.calls(), before)

    def test_cli_same_material_independent_accounts_and_restart(self):
        self.matrix('cli')

    def test_mcp_same_material_independent_accounts_and_restart(self):
        self.matrix('mcp')

    def test_shared_withdrawal_between_native_calls_prevents_second_dispatch(self):
        self.setup_transport('mcp', pause=True)
        alice, _ = self.account('alice', 'alice')
        self.request('POST', '/personal-tools/' + alice['registrationRef'] + '/sharing',
            {'visibility': 'team', 'requestId': 'share-original-account'})
        shared = self.bind('bob', alice, 'shared')
        _, started = self.submit('bob', shared, 'withdraw-run')
        self.assertTrue(self.pause[0].wait(15), 'Native model did not reach second-call boundary')
        self.assertEqual(self.calls(), ['alice'])
        retained = self.store.connections.resolve('bob', shared['ref'], 'tool', task_id=started['job']['id'])
        self.request('POST', '/personal-tools/' + alice['registrationRef'] + '/sharing',
            {'visibility': 'personal', 'requestId': 'withdraw'})
        with self.assertRaises(HTTPException):
            retained.check_authorized()
        self.pause[1].set()
        self.wait(started, 'bob', expected={'failed', 'cancelled'})
        self.assertEqual(self.calls(), ['alice'])

    def test_material_withdrawal_between_native_calls_prevents_second_dispatch(self):
        self.setup_transport('cli', pause=True)
        _, connection = self.account('bob', 'bob')
        _, started = self.submit('bob', connection, 'material-withdraw-run')
        self.assertTrue(self.pause[0].wait(15), 'Native model did not reach second-call boundary')
        task = self.store.task(started['job']['id'], 'bob')
        original_plan = self.store.plan(task['plan_id'], 'bob')
        original_effects = self.store.effects(task['id'])
        self.assertEqual(self.calls(), ['bob'])
        self.assertEqual(len(original_effects), 1)
        self.assertEqual(original_effects[0]['status'], 'DONE')
        material = self.material_ref
        self.request('POST', '/material-governance/versions/' + material['id'] + '/' + str(material['version']) + '/withdraw',
            {'requestId': 'withdraw-original-material', 'reason': 'Synthetic withdrawal at native tool boundary'})
        self.pause[1].set()
        self.wait(started, 'bob', expected={'failed', 'cancelled'})
        self.assertEqual(self.calls(), ['bob'], 'Withdrawn material must not permit another CLI subprocess')
        self.assertEqual(self.store.plan(task['plan_id'], 'bob'), original_plan)
        effects = self.store.effects(task['id'])
        self.assertIn(original_effects[0], effects, 'First native receipt remains inspectable after withdrawal')
        self.assertFalse(any(effect['status'] == 'DONE' and effect['effect_key'] != original_effects[0]['effect_key']
                             for effect in effects))

    def test_cli_lost_ack_retains_original_unknown_after_service_restart(self):
        self.setup_transport('cli', retry_unknown=True)
        _, connection = self.account('alice', 'alice')
        service = self.store.personal_tools
        adapter_id = self.operation['runtimeBinding']['adapterId']
        service.ensure_registered(adapter_id)
        adapter = service.adapters[adapter_id]
        invoke = adapter.invoke
        async def lose_ack(invocation):
            result = await invoke(invocation)
            if invocation.arguments['value'] == 'stock-2':
                raise ToolInvocationError('SYNTHETIC_ACK_LOST')
            return result
        adapter.invoke = lose_ack
        body, started = self.submit('alice', connection, 'lost-ack-run')
        task = self.wait(started, 'alice', expected={'completed', 'cancelled'})
        effects = self.store.effects(task['id'])
        self.assertEqual({item['status'] for item in effects}, {'DONE', 'UNKNOWN'})
        self.assertEqual(len(effects), 2)
        self.assertEqual(self.calls(), ['alice', 'alice'])
        self.stop()
        self.start()
        self.assertEqual(self.request('POST', '/application-interface/v1/starts', body, expected=202)['job']['id'], task['id'])
        receipt = self.request('GET', '/application-interface/v1/starts/lost-ack-run')
        self.assertEqual((receipt['taskId'], receipt['runId']), (task['id'], task['run_id']))
        self.assertFalse(receipt['automaticReplay'])
        self.assertEqual(self.store.effects(task['id']), effects)
        self.assertFalse(self.store.task(task['id'])['terminal'])
        self.assertEqual(self.calls(), ['alice', 'alice'])


if __name__ == '__main__':
    unittest.main()
