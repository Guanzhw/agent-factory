"""Declared personal tools through real PG/Agno/vault; no provider network IO."""
import asyncio
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
import unittest

from agno.models.base import Model
from agno.exceptions import RunCancelledException
from agno.models.response import ModelResponse
from agno.run import RunContext
from agno.tools.function import FunctionCall
from fastapi import HTTPException
from fastapi.testclient import TestClient

from agent_factory.config import Settings
from agent_factory.credential_vault import EncryptedCredentialVault
from agent_factory.execution_bindings import AdapterRegistration, EnvironmentLimits
from agent_factory.main import create_app
from agent_factory.personal_remote_provider import origin
from agent_factory.personal_tool_contract import ToolDescriptor, ToolInvocationError
from pg_fixture import IsolatedPostgres


APPLICATION = 'fixture-personal-inventory'
MODEL = 'fixture-personal-inventory-model'
ENVIRONMENT = 'fixture-personal-inventory-environment'
TOOL = 'personal_inventory_lookup'
CAPABILITY = 'inventory:read'


class InventoryModel(Model):
    """Deterministic native tool-loop driver, never a vendor compatibility claim."""
    def __init__(self, retry_unknown=False, pause=None):
        super().__init__(id=MODEL, name='Synthetic owner inventory driver', provider='controlled-fixture', retries=0)
        self.retry_unknown = retry_unknown
        self.pause = pause
        self.responses = 0

    def response(self, messages):
        self.responses += 1
        results = [message for message in messages if message.role == 'tool' and message.tool_name == TOOL]
        if not self.retry_unknown and any(message.tool_call_error for message in results):
            raise ValueError('FIXTURE_INVENTORY_TOOL_REJECTED')
        if self.responses == (4 if self.retry_unknown else 3):
            return ModelResponse(role='assistant', content='Two synthetic owner inventory results received.')
        turn = self.responses
        return ModelResponse(role='assistant', tool_calls=[{'id': 'native-inventory-' + str(turn),
            'type': 'function', 'function': {'name': TOOL, 'arguments': json.dumps({'item': 'stock-' + str(turn)})}}])

    def invoke(self, messages, **kwargs):
        return self.response(messages)

    async def ainvoke(self, messages, **kwargs):
        results = [message for message in messages if message.role == 'tool' and message.tool_name == TOOL]
        if self.pause is not None and len(results) == 1:
            entered, release = self.pause
            entered.set()
            if not await asyncio.to_thread(release.wait, 15):
                raise AssertionError('FIXTURE_NATIVE_MODEL_BARRIER_TIMEOUT')
        return self.response(messages)

    def invoke_stream(self, messages, **kwargs):
        yield self.response(messages)

    async def ainvoke_stream(self, messages, **kwargs):
        yield self.response(messages)

    def _parse_provider_response(self, response, **kwargs):
        return response

    def _parse_provider_response_delta(self, response):
        return response


class SyntheticAuthenticatedTool:
    """Only the real owner vault authenticates this bounded in-memory fixture."""
    descriptor = ToolDescriptor(adapter_id='fixture-personal-inventory-tool', revision='1', tool_name=TOOL,
        description='Read a synthetic owner inventory item.', transport='cli',
        input_schema={'type': 'object', 'properties': {'item': {'type': 'string', 'maxLength': 30}},
            'required': ['item'], 'additionalProperties': False},
        credential_provider_id='fixture-inventory', credential_destination='https://inventory.example.com',
        capabilities=(CAPABILITY,), permission=CAPABILITY, read_only=True)

    def __init__(self):
        self.calls = []
        self.uncertain_item = None
        self.failed_unstopped_item = None

    async def invoke(self, invocation):
        invocation.check_authorized()
        lease = invocation.resolve_credential()
        if (lease.username != invocation.owner_id
                or lease.password != 'synthetic-inventory-secret-' + invocation.owner_id):
            raise AssertionError('FIXTURE_OWNER_CREDENTIAL_MISMATCH')
        self.calls.append({'owner': invocation.owner_id, 'runId': invocation.run_context.run_id,
            'callId': invocation.call_id, 'connectionRef': invocation.connection_ref,
            'credentialMatchedOwner': True})
        if invocation.arguments['item'] == self.uncertain_item:
            raise ToolInvocationError('FIXTURE_ACKNOWLEDGEMENT_UNKNOWN')
        if invocation.arguments['item'] == self.failed_unstopped_item:
            raise ToolInvocationError('FIXTURE_BUSINESS_FAILED', outcome='failed', stopped=False)
        invocation.check_authorized()
        return {'owner': invocation.owner_id, 'item': invocation.arguments['item'], 'available': 7,
            'evidenceKind': 'synthetic'}


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires disposable loopback PostgreSQL/native queue')
class PersonalToolNativePostgresTests(unittest.TestCase):
    def setUp(self):
        database = IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']).__enter__()
        self.addCleanup(database.__exit__, None, None, None)
        directory = TemporaryDirectory(prefix='personal-tool-native-')
        self.addCleanup(directory.cleanup)
        self.adapter = SyntheticAuthenticatedTool()
        self.retry_unknown = self._testMethodName in {
            'test_native_unknown_stops_new_call_id_and_preserves_restart_custody',
            'test_failed_business_without_stop_proof_keeps_capacity_and_result_after_restart'}
        self.pause = ((threading.Event(), threading.Event()) if self._testMethodName ==
            'test_fresh_services_replay_done_then_revocation_denies_next_native_call' else None)
        self.settings = Settings(db_url=database.url, workspace=Path(directory.name), max_workers=2, max_user_tasks=1,
            temporary_policy='member-self-service', personal_tool_adapters=(self.adapter,),
            runtime_adapters=[AdapterRegistration('model', MODEL, '1', lambda _: InventoryModel(self.retry_unknown, self.pause), demo_only=True),
                AdapterRegistration('environment', ENVIRONMENT, '1', lambda _: EnvironmentLimits())],
            credential_vault_factory=lambda engine: EncryptedCredentialVault(engine, b't' * 32,
                {self.adapter.descriptor.credential_provider_id: origin}))
        self.client = None
        self.start()
        self.addCleanup(self.stop)
        if self.pause:
            self.addCleanup(self.pause[1].set)
        self.publish()

    def start(self):
        self.app = create_app(self.settings)
        self.state = self.app.app.state.factory
        self.store, self.auth = self.state['store'], self.state['auth']
        self.addCleanup(self.store.engine.dispose)
        self.addCleanup(self.store.native_db.db_engine.dispose)
        self.client = TestClient(self.app).__enter__()

    def stop(self):
        if self.client is not None:
            self.client.__exit__(None, None, None)
            self.client = None

    def request(self, method, path, body=None, *, owner='alice', expected=200):
        response = self.client.request(method, '/api/factory' + path, json=body,
            headers={'Authorization': 'Bearer ' + self.auth._issue_native_token(owner),
                'X-Factory-Expected-Owner': owner})
        self.assertEqual(response.status_code, expected, response.text)
        self.assertNotIn('synthetic-inventory-secret-', response.text)
        return response.json()

    def publish(self):
        # The same member publication path as ordinary declarative applications.
        governance, applications = self.state['material_governance'], self.state['applications']
        materials = []
        for kind, adapter_id in (('prompt', None), ('model', MODEL),
                ('tool', self.adapter.descriptor.adapter_id), ('environment', ENVIRONMENT)):
            definition = {'id': APPLICATION + '-' + kind, 'kind': kind, 'name': 'Synthetic inventory ' + kind,
                'content': TOOL if kind == 'tool' else 'Use the declared personal inventory tool twice.',
                'license': 'MIT', 'permissions': [CAPABILITY] if kind == 'tool' else [],
                'compatibility': ['agno:3.1.0'], 'dependencies': [],
                'provenance': {'kind': 'original', 'notice': 'Synthetic offline owner inventory fixture.'}}
            if adapter_id:
                definition['runtimeBinding'] = {'adapterId': adapter_id, 'revision': '1',
                    'config': {'connectionName': 'inventory'} if kind == 'tool' else {}}
            material = governance.create_draft('alice', definition, kind + '-draft')
            governance.publish('alice', material['id'], material['version'], kind + '-publish')
            materials.append({key: material[key] for key in ('id', 'version', 'sha256')})
        application = applications.create_draft('alice', {'contractVersion': 2, 'id': APPLICATION,
            'name': 'Synthetic owner inventory', 'description': 'Declared personal tool native fixture.',
            'defaultMode': 'lookup', 'modes': {'lookup': {'materialRefs': materials,
                'capabilities': [CAPABILITY], 'toolOrder': [TOOL],
                'connectionRequirements': [{'name': 'inventory', 'kind': 'tool',
                    'requiredCapabilities': [CAPABILITY]}],
                'budget': {'toolCalls': 4, 'maxDepth': 1, 'maxChildren': 1,
                    'operationSeconds': 8, 'outputBytes': 65536}}}}, 'application-draft')
        applications.publish('alice', application['id'], application['version'], 'application-publish')

    def configure(self, owner):
        descriptor = self.adapter.descriptor
        credential = self.request('POST', '/personal-credentials', {'requestId': 'inventory-key',
            'providerId': descriptor.credential_provider_id, 'destination': descriptor.credential_destination,
            'username': owner, 'password': 'synthetic-inventory-secret-' + owner}, owner=owner, expected=201)
        registered = self.request('POST', '/personal-tools', {'requestId': 'inventory-tool',
            'adapterId': descriptor.adapter_id, 'credentialRef': credential['credentialRef'],
            'credentialRevision': credential['credentialRevision']}, owner=owner, expected=201)
        connection = self.request('POST', '/user-connections', {'registrationRef': registered['registrationRef'],
            'requestId': 'inventory-bind'}, owner=owner, expected=201)
        return connection

    def submit(self, owner, connection):
        body = {'application': APPLICATION, 'mode': 'lookup', 'goal': 'Read two synthetic inventory items.',
            'requestId': 'inventory-native-run', 'connectionRefs': {'inventory': connection['ref']}}
        started = self.request('POST', '/application-interface/v1/starts', body, owner=owner, expected=202)
        return body, started

    def wait(self, started, owner, *, expected='completed'):
        task_id = started['job']['id']
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            task = self.store.task(task_id, owner)
            native = self.store.native_db.get_job(task['run_id']) or {}
            if native.get('status') in {'completed', 'failed', 'cancelled'}:
                self.assertIn(native['status'], {expected} if isinstance(expected, str) else expected, native)
                return task
            time.sleep(.03)
        self.fail('Synthetic native inventory run did not reach a terminal queue state')

    def retained_call(self, task, *, call_id='native-inventory-1', item='stock-1'):
        plan = self.store.plan(task['plan_id'], task['owner_id'])
        context = RunContext(run_id=task['run_id'], session_id=task['id'], user_id=task['owner_id'],
            session_state={'factory_envelope': {'plan_ref': plan['id'], 'user_id': task['owner_id'],
                'task_id': task['id'], 'request_id': task['request_id']}})
        function = self.store.execution_bindings.tools_for(plan, context)[0]
        function._run_context = context
        return FunctionCall(function=function, call_id=call_id, arguments={'item': item})

    def test_application_native_owner_tools_and_restart_receipts_without_approval(self):
        connections = {owner: self.configure(owner) for owner in ('alice', 'bob')}
        submissions = {owner: self.submit(owner, connections[owner]) for owner in connections}
        tasks = {owner: self.wait(started, owner) for owner, (_, started) in submissions.items()}
        self.assertEqual(len(self.adapter.calls), 4)
        for owner, task in tasks.items():
            calls = [call for call in self.adapter.calls if call['owner'] == owner]
            self.assertEqual({call['callId'] for call in calls}, {'native-inventory-1', 'native-inventory-2'})
            self.assertTrue(all(call['credentialMatchedOwner'] and call['runId'] == task['run_id']
                and call['connectionRef'] == connections[owner]['ref'] for call in calls))
            plan = self.store.plan(task['plan_id'], owner)
            self.assertEqual(plan['executionBindings']['tools'][0]['adapterId'], self.adapter.descriptor.adapter_id)
            self.assertEqual(plan['bindingManifest']['connections']['inventory']['ref'], connections[owner]['ref'])
            self.assertEqual(self.store.plan_policy.require_execution(owner, plan)['source'], 'member-self-service')
            effects = self.store.effects(task['id'])
            self.assertEqual(len(effects), 2)
            self.assertTrue(all(effect['status'] == 'DONE' for effect in effects))
            self.assertEqual({effect['result']['output']['owner'] for effect in effects}, {owner})
            self.assertNotIn('synthetic-inventory-secret-', json.dumps([plan, effects, self.store.events(task['id'])]))
            self.assertEqual(self.request('POST', '/application-interface/v1/starts', submissions[owner][0],
                owner=owner, expected=202)['job']['id'], task['id'])
        self.assertEqual(self.store.sql('SELECT COUNT(*) AS n FROM af_plan_review_decisions')[0]['n'], 0)
        self.assertEqual(len(self.adapter.calls), 4)

        self.stop()
        self.start()
        for owner, task in tasks.items():
            receipt = self.request('GET', '/application-interface/v1/starts/inventory-native-run', owner=owner)
            self.assertEqual((receipt['taskId'], receipt['runId']), (task['id'], task['run_id']))
            self.assertFalse(receipt['createsExecution'])
            self.assertFalse(receipt['automaticReplay'])
            with self.assertRaisesRegex(HTTPException, 'CONNECTION_TASK_ENDED'):
                self.retained_call(task)
        self.assertEqual(len(self.adapter.calls), 4)
        self.assertNotIn('synthetic-inventory-secret-', str(self.store.sql('SELECT * FROM af_encrypted_credentials')))

    def test_native_unknown_stops_new_call_id_and_preserves_restart_custody(self):
        connection = self.configure('alice')
        self.adapter.uncertain_item = 'stock-2'
        body, started = self.submit('alice', connection)
        # Observer cleanup may also cancel the queue ticket after native stop;
        # neither queue outcome establishes completion of the UNKNOWN effect.
        task = self.wait(started, 'alice', expected={'completed', 'cancelled'})
        # This model explicitly asks for stock-3 with a new native call ID if
        # Agno feeds it an ordinary error. UNKNOWN must stop that continuation.
        self.assertEqual([call['callId'] for call in self.adapter.calls],
            ['native-inventory-1', 'native-inventory-2'])
        native_run = self.store.native_db.get_run(task['run_id'])
        self.assertIsNotNone(native_run)
        self.assertIsNotNone(native_run.tools, 'Original native stop evidence must be persisted')
        stopped_call = next(tool for tool in native_run.tools if tool.tool_call_id == 'native-inventory-2')
        self.assertTrue(stopped_call.stop_after_tool_call, 'Native stop proof must not depend on observer polling')
        effects = self.store.effects(task['id'])
        self.assertEqual(len(effects), 2)
        self.assertEqual({effect['status'] for effect in effects}, {'DONE', 'UNKNOWN'})
        unknown = next(effect for effect in effects if effect['status'] == 'UNKNOWN')
        self.assertIsNone(unknown['result'])
        self.request('POST', '/application-interface/v1/starts', body, expected=202)
        self.assertFalse(self.store.task(task['id'])['terminal'], 'UNKNOWN must retain original task custody')
        self.stop()
        self.start()
        receipt = self.request('GET', '/application-interface/v1/starts/inventory-native-run')
        self.assertEqual((receipt['taskId'], receipt['runId']), (task['id'], task['run_id']))
        self.assertFalse(receipt['automaticReplay'])
        self.assertFalse(self.store.task(task['id'])['terminal'])
        self.assertTrue(self.store.task(task['id'])['cancel_requested'])
        with self.assertRaises(RunCancelledException):
            self.retained_call(task)
        self.assertEqual(len(self.adapter.calls), 2)
        self.assertEqual(self.store.effects(task['id']), effects)

    def test_fresh_services_replay_done_then_revocation_denies_next_native_call(self):
        connection = self.configure('alice')
        _, started = self.submit('alice', connection)
        entered, release = self.pause
        self.assertTrue(entered.wait(10), 'Native model must reach the second-call boundary')
        task = self.store.task(started['job']['id'], 'alice')
        self.assertFalse(task['terminal'])
        self.assertEqual([call['callId'] for call in self.adapter.calls], ['native-inventory-1'])
        effects = self.store.effects(task['id'])
        # New service objects read the same immutable PG plan and effect while
        # the original native worker remains paused. No old handle is reused.
        reopened = create_app(self.settings)
        self.state = reopened.app.state.factory
        self.store, self.auth = self.state['store'], self.state['auth']
        self.addCleanup(self.store.engine.dispose)
        self.addCleanup(self.store.native_db.db_engine.dispose)
        known = self.retained_call(task)
        self.assertEqual(asyncio.run(known.aexecute()).status, 'success')
        self.assertEqual(known.result, {'owner': 'alice', 'item': 'stock-1', 'available': 7, 'evidenceKind': 'synthetic'})
        self.assertEqual(len(self.adapter.calls), 1)
        self.assertEqual(self.store.effects(task['id']), effects)

        next_call = self.retained_call(task, call_id='native-inventory-2', item='stock-2')
        self.request('POST', '/user-connections/' + connection['ref'] + '/revoke',
            {'requestId': 'inventory-revoke'})
        denied = asyncio.run(next_call.aexecute())
        self.assertEqual(denied.status, 'failure')
        self.assertIn('CONNECTION_REVOKED', denied.error)
        try:
            deadline = time.monotonic() + 5
            while not self.store.task(task['id'])['cancel_requested'] and time.monotonic() < deadline:
                time.sleep(.03)
            self.assertTrue(self.store.task(task['id'])['cancel_requested'])
        finally:
            release.set()
        self.wait(started, 'alice', expected='cancelled')
        self.assertEqual(len(self.adapter.calls), 1, 'Revocation must not select a fallback for the next native call')
        self.assertEqual(self.store.effects(task['id']), effects)

    def test_failed_business_without_stop_proof_keeps_capacity_and_result_after_restart(self):
        connection = self.configure('alice')
        self.adapter.failed_unstopped_item = 'stock-2'
        body, started = self.submit('alice', connection)
        task = self.wait(started, 'alice', expected={'completed', 'cancelled'})
        self.assertEqual([call['callId'] for call in self.adapter.calls],
            ['native-inventory-1', 'native-inventory-2'])
        effects = self.store.effects(task['id'])
        self.assertEqual(len(effects), 2)
        held = next(effect for effect in effects if effect['effect_key'].endswith(':native-inventory-2'))
        self.assertEqual(held['status'], 'UNKNOWN')
        self.assertEqual(held['result'], {'outcome': 'failed', 'stopped': False})
        native = self.store.native_db.get_run(task['run_id'])
        self.assertIsNotNone(native)
        self.assertIsNotNone(native.tools)
        stopped = next(tool for tool in native.tools if tool.tool_call_id == 'native-inventory-2')
        self.assertTrue(stopped.stop_after_tool_call)
        self.assertEqual(stopped.result, 'PERSONAL_TOOL_FAILED_CLEANUP_UNCONFIRMED')
        self.assertEqual(self.request('POST', '/application-interface/v1/starts', body, expected=202)['job']['id'], task['id'])
        self.assertFalse(self.store.task(task['id'])['terminal'])
        self.request('POST', '/application-interface/v1/starts',
            {**body, 'requestId': 'held-capacity-before-restart'}, expected=429)

        self.stop()
        self.start()
        receipt = self.request('GET', '/application-interface/v1/starts/inventory-native-run')
        self.assertEqual((receipt['taskId'], receipt['runId']), (task['id'], task['run_id']))
        self.assertFalse(receipt['automaticReplay'])
        self.assertFalse(self.store.task(task['id'])['terminal'])
        self.assertEqual(self.store.effects(task['id']), effects)
        self.request('POST', '/application-interface/v1/starts',
            {**body, 'requestId': 'held-capacity-after-restart'}, expected=429)
        with self.assertRaises(RunCancelledException):
            self.retained_call(task, call_id='native-inventory-2', item='stock-2')
        self.assertEqual(len(self.adapter.calls), 2, 'Known business failure with unconfirmed cleanup must never redispatch')
        self.assertEqual(self.store.effects(task['id']), effects)

if __name__ == '__main__':
    unittest.main()
