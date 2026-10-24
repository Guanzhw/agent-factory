"""MCP pre-dispatch stop evidence through real PG/native task capacity."""

import asyncio
from concurrent.futures import Future
import json
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from unittest.mock import patch

from mcp import ClientSession

from agent_factory.config import Settings
from agent_factory.credential_vault import CredentialVaultError, EncryptedCredentialVault
from agent_factory.execution_bindings import AdapterRegistration, EnvironmentLimits
from agent_factory.personal_mcp import MCPToolAdapter
from agent_factory.personal_remote_provider import SecretLease, origin
from agent_factory.personal_tool_contract import ToolDescriptor, ToolInvocationError
from mcp_protocol_fixture import MCPProtocolServer
from pg_fixture import IsolatedPostgres
import test_personal_tool_native_postgres as native_fixture


class EchoModel(native_fixture.InventoryModel):
    """Use the existing deterministic native driver with standard MCP arguments."""

    def response(self, messages):
        result = super().response(messages)
        for call in result.tool_calls or []:
            arguments = json.loads(call['function']['arguments'])
            call['function']['arguments'] = json.dumps({'value': arguments['item']})
        return result


class ObservedMCPAdapter(MCPToolAdapter):
    """Keep fixed failure/cleanup facts for capacity assertion diagnostics."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.observations = {}

    def observation(self, invocation):
        key = (invocation.run_context.run_id, invocation.call_id)
        return self.observations.setdefault(key, {'runId': key[0], 'callId': key[1]})

    async def invoke(self, invocation):
        observation = self.observation(invocation)
        started = time.monotonic()
        try:
            result = await super().invoke(invocation)
            observation['outcome'] = 'completed'
            return result
        except ToolInvocationError as error:
            observation.update(code=error.code, outcome=error.outcome, stopped=error.stopped)
            raise
        finally:
            observation['elapsedSeconds'] = round(time.monotonic() - started, 3)
            state = observation.pop('state', None)
            if state is not None:
                # invoke has joined its SDK/monitor tasks. Keep diagnostic facts
                # and live completion Events, not callbacks retaining the old app.
                observation.update(dispatched=state.dispatched, authorizationRejected=state.authorization_rejected,
                    sdkClosed=state.sdk_closed, transportClosed=state.transport_closed,
                    callbacks=tuple(state.callbacks_finished))

    async def _run(self, state, arguments):
        observation = self.observation(state.invocation)
        observation['state'] = state
        try:
            return await super()._run(state, arguments)
        finally:
            if 'bodyEnded' in observation:
                observation['closeSeconds'] = round(time.monotonic() - observation['bodyEnded'], 3)

    async def _call(self, session, state, arguments):
        observation = self.observation(state.invocation)
        started = time.monotonic()
        try:
            return await super()._call(session, state, arguments)
        finally:
            observation['bodyEnded'] = time.monotonic()
            observation['bodySeconds'] = round(time.monotonic() - started, 3)

    def diagnostics(self):
        result = []
        for observation in self.observations.values():
            item = {key: value for key, value in observation.items() if key not in {'state', 'bodyEnded', 'callbacks'}}
            state = observation.get('state')
            callbacks = observation.get('callbacks', ())
            if state is not None:
                item.update(dispatched=state.dispatched, authorizationRejected=state.authorization_rejected,
                            sdkClosed=state.sdk_closed, transportClosed=state.transport_closed)
                callbacks = state.callbacks_finished
            if state is not None or 'callbacks' in observation:
                item.update(callbacksTotal=len(callbacks), callbacksDone=sum(event.is_set() for event in callbacks))
            result.append(item)
        return result


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires disposable loopback PostgreSQL/native queue')
class PersonalMCPCapacityPostgresTests(unittest.TestCase):
    # Reuse the established app/vault/publication API fixture without inheriting
    # its unrelated test cases or replacing any core admission implementation.
    start = native_fixture.PersonalToolNativePostgresTests.start
    stop = native_fixture.PersonalToolNativePostgresTests.stop
    request = native_fixture.PersonalToolNativePostgresTests.request
    publish = native_fixture.PersonalToolNativePostgresTests.publish
    configure = native_fixture.PersonalToolNativePostgresTests.configure
    submit = native_fixture.PersonalToolNativePostgresTests.submit
    def wait(self, started, owner, *, expected='completed'):
        try:
            return native_fixture.PersonalToolNativePostgresTests.wait(self, started, owner, expected=expected)
        except AssertionError as error:
            # Capture before teardown, only after the unchanged wait failed.
            # Frames contain locations only, never locals/credentials/messages.
            task = self.store.task(started['job']['id'], owner)
            native = self.store.native_db.get_job(task['run_id']) or {}
            stacks = []
            for frame in sys._current_frames().values():
                stack = []
                while frame is not None and len(stack) < 16:
                    stack.append({'file': Path(frame.f_code.co_filename).name,
                                  'function': frame.f_code.co_name, 'line': frame.f_lineno})
                    frame = frame.f_back
                stacks.append(stack)
            effects = [{'key': effect['effect_key'], 'status': effect['status'],
                        'result': {key: effect['result'][key] for key in ('outcome', 'stopped', 'cancelled')
                                   if key in effect['result']} if isinstance(effect.get('result'), dict) else None}
                       for effect in self.store.effects(task['id'])]
            diagnostic = {'taskId': task['id'], 'runId': task['run_id'], 'requestId': task['request_id'],
                'terminal': task['terminal'], 'cancelRequested': task['cancel_requested'],
                'native': {key: native.get(key) for key in ('status', 'attempts', 'worker_id', 'created_at', 'updated_at')},
                'effects': effects, 'adapter': self.adapter.diagnostics(), 'toolCallCount': len(self.mcp.calls),
                'observerError': self.store.lifecycle_observer.last_error_type, 'threads': stacks}
            raise self.failureException(str(error) + '\nMCP_NATIVE_FAILURE: ' +
                json.dumps(diagnostic, sort_keys=True, default=str)) from error

    def setUp(self):
        database = IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']).__enter__()
        self.addCleanup(database.__exit__, None, None, None)
        directory = TemporaryDirectory(prefix='personal-mcp-capacity-')
        self.addCleanup(directory.cleanup)
        self.mcp = MCPProtocolServer(stateless=False)
        self.mcp.tokens['synthetic-inventory-secret-alice'] = 'alice'
        ready = Future()
        self.server_stop = threading.Event()

        async def serve():
            self.server_loop = asyncio.get_running_loop()
            async with self.mcp:
                ready.set_result(None)
                await asyncio.to_thread(self.server_stop.wait)

        def run_server():
            try:
                asyncio.run(serve())
            except BaseException as error:
                if not ready.done():
                    ready.set_exception(error)
                else:
                    self.server_error = error

        self.server_error = None
        self.server_thread = threading.Thread(target=run_server, daemon=True)
        self.server_thread.start()
        self.addCleanup(self.stop_server)
        ready.result(timeout=5)
        descriptor = ToolDescriptor(
            adapter_id='fixture-personal-mcp-capacity', revision='1', tool_name=native_fixture.TOOL,
            description='Read synthetic owner inventory through local MCP.', transport='mcp',
            input_schema={'type': 'object', 'properties': {'value': {'type': 'string'}}, 'required': ['value']},
            credential_provider_id='fixture-inventory', credential_destination='https://inventory.example.com',
            capabilities=(native_fixture.CAPABILITY,), permission=native_fixture.CAPABILITY,
            # Real vault/permission callbacks can take over five seconds per call.
            # Timeout semantics have separate adapter tests; this checks capacity.
            read_only=True, timeout_seconds=20,
        )
        # Exercise the production close budget. Halving it here can turn a
        # healthy vault/permission lookup into UNKNOWN under database load.
        # Strict blocked-credential and streaming deadlines remain unit tests.
        self.adapter = ObservedMCPAdapter(descriptor, url=self.mcp.url, remote_tool_name='echo',
                                         authorization_interval=0.25)
        self.settings = Settings(
            db_url=database.url, workspace=Path(directory.name), max_workers=2, max_user_tasks=1,
            temporary_policy='member-self-service', personal_tool_adapters=(self.adapter,),
            runtime_adapters=[
                AdapterRegistration('model', native_fixture.MODEL, '1', lambda _: EchoModel(), demo_only=True),
                AdapterRegistration('environment', native_fixture.ENVIRONMENT, '1', lambda _: EnvironmentLimits()),
            ],
            credential_vault_factory=lambda engine: EncryptedCredentialVault(
                engine, b't' * 32, {descriptor.credential_provider_id: origin}),
        )
        self.client = None
        self.start()
        self.publish()

    def stop_server(self):
        self.server_stop.set()
        self.server_thread.join(timeout=5)
        self.assertFalse(self.server_thread.is_alive(), 'Local MCP fixture must stop')
        self.assertIsNone(self.server_error)

    def schema_drift(self):
        self.mcp.tool_schemas['echo'] = {
            'type': 'object', 'properties': {'value': {'type': 'integer'}}, 'required': ['value'],
        }

    def wait_terminal(self, task):
        started = time.monotonic()
        deadline = started + 5
        while time.monotonic() < deadline:
            current = self.store.task(task['id'], 'alice')
            if current['terminal']:
                return current
            time.sleep(0.03)
        # Read diagnostics only after the unchanged deadline; never tick the
        # observer, reconcile effects or expose tool outputs/credentials here.
        observer = self.state['lifecycle_observer']
        native = self.store.native_db.get_job(task['run_id']) or {}
        effects = []
        for effect in self.store.effects(task['id']):
            receipt = effect['result']
            effects.append({'status': effect['status'], 'result': {
                key: receipt[key] for key in ('outcome', 'stopped', 'cancelled') if key in receipt
            } if isinstance(receipt, dict) else None})
        diagnostics = {
            'elapsedSeconds': round(time.monotonic() - started, 3),
            'taskId': task['id'], 'runId': task['run_id'], 'requestId': task['request_id'],
            'terminal': current['terminal'], 'nativeStatus': native.get('status'), 'effects': effects,
            'adapter': self.adapter.diagnostics(), 'observerError': observer.last_error_type,
            'observerStopped': observer._stop.is_set(),
            'observerTaskDone': observer._task.done() if observer._task is not None else None,
            'observerGroups': observer.last_result.get('groups', []),
            'observerErrors': observer.last_result.get('errors', []),
        }
        self.fail('Native task capacity must be released: ' + json.dumps(diagnostics, sort_keys=True))

    def assert_original_receipt(self, body, task, effects, request_count):
        replay = self.request('POST', '/application-interface/v1/starts', body, expected=202)
        self.assertEqual(replay['job']['id'], task['id'])
        receipt = self.request('GET', '/application-interface/v1/starts/inventory-native-run')
        self.assertEqual((receipt['taskId'], receipt['runId']), (task['id'], task['run_id']))
        self.assertFalse(receipt['automaticReplay'])
        self.assertFalse(receipt['createsExecution'])
        self.assertEqual(self.store.effects(task['id']), effects)
        self.assertEqual(len(self.mcp.requests), request_count)
        self.assertEqual(self.mcp.calls, [])

    def prove_released(self, body, started):
        task = self.wait(started, 'alice', expected={'failed', 'completed', 'cancelled'})
        self.wait_terminal(task)
        effects = self.store.effects(task['id'])
        self.assertEqual(len(effects), 1)
        self.assertEqual(effects[0]['status'], 'DONE')
        self.assertEqual(effects[0]['result'], {'outcome': 'failed', 'stopped': True})
        request_count = len(self.mcp.requests)
        self.assert_original_receipt(body, task, effects, request_count)
        self.stop()
        self.start()
        self.assert_original_receipt(body, task, effects, request_count)
        self.mcp.tool_schemas.clear()
        self.mcp.delete_status = None
        self.mcp.delete_drip_interval = None
        self.server_loop.call_soon_threadsafe(self.mcp.delete_release.set)
        next_run = self.request('POST', '/application-interface/v1/starts',
                                {**body, 'requestId': 'after-known-mcp-failure'}, expected=202)
        self.assertNotEqual(next_run['job']['id'], task['id'])
        next_task = self.wait(next_run, 'alice')
        self.wait_terminal(next_task)
        self.assertEqual(self.mcp.calls, [('echo', 'alice'), ('echo', 'alice')])
        next_effects = self.store.effects(next_task['id'])
        self.assertEqual(len(next_effects), 2)
        self.assertTrue(all(effect['status'] == 'DONE' for effect in next_effects), next_effects)
        self.assertTrue(all(effect['result']['outcome'] == 'completed' for effect in next_effects), next_effects)

    def test_schema_failure_releases_capacity_and_keeps_original_receipt_after_restart(self):
        connection = self.configure('alice')
        self.schema_drift()
        body, started = self.submit('alice', connection)
        self.prove_released(body, started)

    def test_credential_resolution_failure_releases_capacity_without_mcp_io(self):
        connection = self.configure('alice')
        with patch.object(self.state['credential_vault'], 'resolve', side_effect=CredentialVaultError()):
            body, started = self.submit('alice', connection)
            task = self.wait(started, 'alice', expected={'failed', 'completed', 'cancelled'})
            self.wait_terminal(task)
        self.assertEqual(self.mcp.requests, [])
        self.prove_released(body, started)

    def test_http_authentication_rejection_releases_capacity_without_tool_dispatch(self):
        connection = self.configure('alice')
        with patch.object(self.state['credential_vault'], 'resolve',
                          return_value=SecretLease('alice', 'synthetic-mcp-wrong-token')):
            body, started = self.submit('alice', connection)
            task = self.wait(started, 'alice', expected={'failed', 'completed', 'cancelled'})
            self.wait_terminal(task)
        self.assertEqual(len(self.mcp.requests), 1)
        self.assertIsNone(self.mcp.requests[0].owner)
        self.assertEqual(self.mcp.calls, [])
        self.prove_released(body, started)

    def test_delete_not_supported_releases_predispatch_failure_capacity(self):
        connection = self.configure('alice')
        self.schema_drift()
        self.mcp.delete_status = 405
        body, started = self.submit('alice', connection)
        self.wait(started, 'alice', expected={'failed', 'completed', 'cancelled'})
        self.assertTrue(self.mcp.delete_started.is_set())
        self.assertTrue(any(request.method == 'DELETE' for request in self.mcp.requests))
        self.prove_released(body, started)

    def test_slow_delete_releases_predispatch_failure_after_local_cleanup(self):
        connection = self.configure('alice')
        self.schema_drift()
        self.mcp.delete_release.clear()
        self.mcp.delete_drip_interval = 0.01
        body, started = self.submit('alice', connection)
        self.prove_released(body, started)
        self.assertGreaterEqual(self.mcp.delete_chunks, 2)

    def test_sdk_exit_failure_keeps_capacity_and_never_redispatches(self):
        exit_failed = threading.Event()

        class BrokenExitSession(ClientSession):
            async def __aexit__(self, *args):
                await super().__aexit__(*args)
                exit_failed.set()
                raise RuntimeError('SYNTHETIC_SDK_EXIT_FAILED')

        connection = self.configure('alice')
        self.schema_drift()
        with patch('agent_factory.personal_mcp.ClientSession', BrokenExitSession):
            body, started = self.submit('alice', connection)
            task = self.wait(started, 'alice', expected={'completed', 'cancelled'})
        self.assertTrue(exit_failed.is_set())
        effects = self.store.effects(task['id'])
        self.assertEqual(len(effects), 1)
        self.assertEqual(effects[0]['status'], 'UNKNOWN')
        self.assertIsNone(effects[0]['result'])
        self.assertFalse(self.store.task(task['id'])['terminal'])
        request_count = len(self.mcp.requests)
        self.assert_original_receipt(body, task, effects, request_count)
        self.request('POST', '/application-interface/v1/starts',
                     {**body, 'requestId': 'held-before-restart'}, expected=429)
        self.stop()
        self.start()
        self.assert_original_receipt(body, task, effects, request_count)
        self.assertFalse(self.store.task(task['id'])['terminal'])
        self.request('POST', '/application-interface/v1/starts',
                     {**body, 'requestId': 'held-after-restart'}, expected=429)
