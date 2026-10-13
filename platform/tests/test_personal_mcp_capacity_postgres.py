"""MCP pre-dispatch stop evidence through real PG/native task capacity."""

import asyncio
from concurrent.futures import Future
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from unittest.mock import patch

from agent_factory.config import Settings
from agent_factory.credential_vault import CredentialVaultError, EncryptedCredentialVault
from agent_factory.execution_bindings import AdapterRegistration, EnvironmentLimits
from agent_factory.personal_mcp import MCPToolAdapter
from agent_factory.personal_remote_provider import SecretLease, origin
from agent_factory.personal_tool_contract import ToolDescriptor
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
    wait = native_fixture.PersonalToolNativePostgresTests.wait

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
            read_only=True, timeout_seconds=5,
        )
        self.adapter = MCPToolAdapter(descriptor, url=self.mcp.url, remote_tool_name='echo',
                                      allow_loopback_http=True, teardown_timeout_seconds=1,
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
        self.addCleanup(self.stop)
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
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            current = self.store.task(task['id'], 'alice')
            if current['terminal']:
                return current
            time.sleep(0.03)
        self.fail('Known pre-dispatch failure must release native task capacity')

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
        next_run = self.request('POST', '/application-interface/v1/starts',
                                {**body, 'requestId': 'after-known-mcp-failure'}, expected=202)
        self.assertNotEqual(next_run['job']['id'], task['id'])
        self.wait(next_run, 'alice')
        self.assertEqual(self.mcp.calls, [('echo', 'alice'), ('echo', 'alice')])

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

    def test_uncertain_schema_failure_cleanup_keeps_capacity_and_never_redispatches(self):
        connection = self.configure('alice')
        self.schema_drift()
        self.mcp.delete_release.clear()
        self.mcp.delete_drip_interval = 0.01
        body, started = self.submit('alice', connection)
        task = self.wait(started, 'alice', expected={'completed', 'cancelled'})
        effects = self.store.effects(task['id'])
        self.assertEqual(len(effects), 1)
        self.assertEqual(effects[0]['status'], 'UNKNOWN')
        self.assertEqual(effects[0]['result'], {'outcome': 'failed', 'stopped': False})
        self.assertFalse(self.store.task(task['id'])['terminal'])
        self.assertGreaterEqual(self.mcp.delete_chunks, 2)
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
