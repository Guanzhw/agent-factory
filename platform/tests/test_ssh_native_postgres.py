"""Real PG/native queue and helper custody; substituted local SSH subprocess.

The transport still obtains a real disposable ssh-agent/vault lease and speaks
its bounded JSON protocol. The subprocess runs locally, so this is not sshd,
GPU, external-host verification or live-model acceptance.
"""
from contextlib import contextmanager
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

from agno.models.response import ModelResponse
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from agent_factory.credential_vault import EncryptedCredentialVault
from agent_factory.execution_bindings import AdapterRegistration, EnvironmentLimits
from agent_factory.main import create_app
from agent_factory.process_enforcement import ResearchProcessLimits, ResearchProcessSpec
from agent_factory.resources import ComputePool
from agent_factory.ssh_credentials import PROVIDER_ID, SSHCredentialPolicy
from agent_factory.ssh_operation_runtime import SSHTrainingProfile
from agent_factory.ssh_process_contract import LAUNCH_ADAPTER_ID, LAUNCH_TOOL, WAIT_ADAPTER_ID, WAIT_TOOL
from fixture_auth import initialize_members
from fixture_identity import access_token
from fixture_settings import Settings
from pg_fixture import IsolatedPostgres
from test_personal_tool_native_postgres import InventoryModel


class SSHSequenceModel(InventoryModel):
    def __init__(self, inputs, observed):
        super().__init__()
        self.inputs = dict(inputs)
        self.observed = observed

    def response(self, messages):
        results = [m for m in messages if m.role == 'tool']
        if any(m.tool_call_error for m in results):
            raise AssertionError('SSH_NATIVE_TOOL_REJECTED')
        waits = [m for m in results if m.tool_name == WAIT_TOOL]
        if waits:
            result = json.loads(waits[-1].content)['operations'][0]
            assert result['allStopped'] and result['executionStatus'] == 'COMPLETED'
            assert result['exitCode'] == 0
            output = result['output']
            assert output['utf8Valid'] and not output['truncated']
            actual = json.loads(output['text'])
            self.observed.append({'operationId': result['operationId'], 'actual': actual,
                                  'artifact': output['artifact']})
            return ModelResponse(role='assistant', content=json.dumps(actual))
        launches = [m for m in results if m.tool_name == LAUNCH_TOOL]
        if launches:
            value = ast.literal_eval(launches[-1].content)
            name, args, identifier = WAIT_TOOL, {'operationIds': [value['operationId']]}, 'original-ssh-wait'
        else:
            name, args, identifier = LAUNCH_TOOL, {'inputs': self.inputs}, 'original-ssh-launch'
        return ModelResponse(role='assistant', tool_calls=[{'id': identifier, 'type': 'function',
            'function': {'name': name, 'arguments': json.dumps(args)}}])


def training_profile(remote, started, release):
    executable = str(Path(sys.executable).resolve())
    program = ("from pathlib import Path; import json, sys, time; "
               "assert sys.argv[1] == '--experiment-json'; values=json.loads(sys.argv[2]); "
               f"p=Path({str(started)!r}); p.open('a').write(json.dumps(values)+'\\n'); "
               f"release=Path({str(release)!r}); "
               "exec('while not release.exists():\\n time.sleep(.05)'); "
               "print(json.dumps({'received': values, 'argv': sys.argv[1:]}), flush=True)")
    return SSHTrainingProfile(
        ResearchProcessSpec(executable, hashlib.sha256(Path(executable).read_bytes()).hexdigest(),
            ('-I', '-S', '-c', program), str(remote),
            tuple((key, '1') for key in ('HF_HUB_OFFLINE', 'HF_DATASETS_OFFLINE',
                'TRANSFORMERS_OFFLINE', 'PYTHONNOUSERSITE')),
            (remote.stat().st_dev, remote.stat().st_ino)),
        ResearchProcessLimits(cpu_seconds=2, address_space_mb=128, file_size_bytes=65536,
            wall_seconds=60, disk_bytes=1048576, output_bytes=65536),
        executable, ComputePool('native-fixture', 2, 512, 8, max_leases=1, max_owner_leases=1),
        input_schema={'type': 'object', 'properties': {
            'width': {'type': 'integer', 'minimum': 1, 'maximum': 8},
            'label': {'type': 'string', 'maxLength': 100}},
            'required': ['width', 'label'], 'additionalProperties': False},
        input_argument='--experiment-json')


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL') and sys.platform == 'linux',
                     'Requires isolated PostgreSQL and Linux process custody')
class SSHNativePostgresTests(unittest.TestCase):
    def setUp(self):
        for name in ('ssh-agent', 'ssh-add'):
            if not shutil.which(name):
                self.skipTest(name + ' is unavailable')
        self.database = self.enterContext(IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']))
        self.folder = Path(self.enterContext(TemporaryDirectory(prefix='ssh-native-')))
        self.remote = self.folder / 'remote'
        self.remote.mkdir(mode=0o700)
        self.release = self.folder / 'release'
        self.started = self.folder / 'starts'
        self.model_inputs = {'width': 1, 'label': 'first'}
        self.model_results = []
        self.profile = training_profile(self.remote, self.started, self.release)
        self.settings = Settings(db_url=self.database.url, workspace=self.folder / 'factory', max_workers=1,
            ssh_training_profiles={'native-fixture': self.profile},
            runtime_adapters=[AdapterRegistration('model', 'ssh-native-model', '1',
                                                 lambda _: SSHSequenceModel(self.model_inputs, self.model_results)),
                AdapterRegistration('environment', 'ssh-native-environment', '1', lambda _: EnvironmentLimits())],
            credential_vault_factory=lambda engine: EncryptedCredentialVault(engine, b'n' * 32,
                {PROVIDER_ID: SSHCredentialPolicy()}))
        self.processes = []
        self.client = None
        self.enterContext(patch('agent_factory.ssh_process_provider.pinned_ssh', side_effect=self.local_helper))
        self.addCleanup(self.cleanup)
        self.start()
        self.configure()
        self.publish()

    @contextmanager
    def local_helper(self, server, lease, folder, command, *, deadline):
        lease.validate()
        self.assertTrue(command.endswith(' -I -B -m agent_factory.ssh_process_helper'))
        source = str(Path(__file__).resolve().parents[1])
        code = f"import sys; sys.path.insert(0, {source!r}); from agent_factory.ssh_process_helper import main; main()"
        process = subprocess.Popen([sys.executable, '-c', code], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL)
        self.processes.append(process)
        try:
            yield process
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
            process.stdin.close()
            process.stdout.close()

    def start(self):
        self.app = create_app(self.settings)
        self.state = self.app.app.state.factory
        self.store, self.auth = self.state['store'], self.state['auth']
        initialize_members(self.auth)
        self.client = TestClient(self.app, base_url='https://testserver').__enter__()

    def stop(self):
        if self.client is not None:
            self.client.__exit__(None, None, None)
            self.client = None
            self.store.dispose_root_locks()
            self.store.engine.dispose()
            self.store.native_db.db_engine.dispose()

    def cleanup(self):
        self.release.touch()
        self.stop()
        for process in self.processes:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)

    def request(self, method, path, body=None, expected=200):
        reply = self.client.request(method, '/api/factory' + path, json=body,
                                    headers={'Authorization': 'Bearer ' + access_token('alice')})
        self.assertEqual(reply.status_code, expected, reply.text)
        return reply.json()

    def configure(self):
        private = Ed25519PrivateKey.generate().private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.OpenSSH, serialization.NoEncryption()).decode()
        host = Ed25519PrivateKey.generate().public_key().public_bytes(serialization.Encoding.OpenSSH,
            serialization.PublicFormat.OpenSSH).decode()
        body = {'name': 'Synthetic local SSH bridge', 'address': '127.0.0.1', 'port': 2222,
                'username': 'fixture', 'hostKey': host, 'allowedRoot': str(self.remote)}
        service = self.store.personal_ssh
        identity = service.identity(body)
        credential = service.vault.create(owner='alice', provider_id=PROVIDER_ID, destination=identity['origin'],
            username='fixture', password=private, request_id='native-ssh-key')
        configured = self.request('POST', '/personal-ssh', {**body, **{k: credential[k]
            for k in ('credentialRef', 'credentialRevision')}, 'confirmedHostKey': True,
            'requestId': 'native-ssh-config'}, expected=201)
        reference = configured['reference']
        def probe(server, lease, action):
            lease.validate()
            return {'ok': True}
        with patch.object(service, 'probe', side_effect=probe):
            self.request('POST', '/personal-ssh/' + reference + '/verify', {'requestId': 'native-ssh-verify'})
        self.request('POST', '/personal-ssh/' + reference + '/bind', {'requestId': 'native-ssh-prepare'})
        self.request('POST', '/personal-ssh/' + reference + '/bind-execution', {'requestId': 'native-ssh-execute'})
        self.connection = self.store.connections.request_result('alice', 'native-ssh-execute')['connection']['ref']

    def publish(self):
        refs = []
        for suffix, kind, adapter, name in (
            ('prompt', 'prompt', None, 'Use the two declared SSH tools.'),
            ('model', 'model', 'ssh-native-model', 'Controlled model'),
            ('environment', 'environment', 'ssh-native-environment', 'Controlled environment'),
            ('launch', 'tool', LAUNCH_ADAPTER_ID, LAUNCH_TOOL),
            ('wait', 'tool', WAIT_ADAPTER_ID, WAIT_TOOL)):
            body = {'id': 'ssh-native-' + suffix, 'kind': kind, 'name': suffix, 'content': name,
                    'license': 'MIT', 'permissions': ['ssh:execute'] if kind == 'tool' else []}
            if adapter:
                config = ({'connectionName': 'compute', 'profileId': 'native-fixture',
                           'profileSha256': self.profile.fingerprint} if suffix == 'launch' else {})
                body['runtimeBinding'] = {'adapterId': adapter, 'revision': '1', 'config': config}
            material = self.state['material_governance'].create_draft('alice', body, suffix + '-draft')
            self.state['material_governance'].publish('alice', material['id'], material['version'], suffix + '-publish')
            refs.append({k: material[k] for k in ('id', 'version', 'sha256')})
        app = self.state['applications'].create_draft('alice', {'contractVersion': 2, 'id': 'ssh-native',
            'name': 'SSH native custody', 'description': 'Synthetic integration', 'defaultMode': 'train',
            'modes': {'train': {'materialRefs': refs, 'capabilities': ['ssh:execute'],
                'toolOrder': [LAUNCH_TOOL, WAIT_TOOL], 'connectionRequirements': [
                    {'name': 'compute', 'kind': 'environment', 'requiredCapabilities': ['ssh:execute']}],
                'budget': {'toolCalls': 4, 'maxDepth': 1, 'maxChildren': 1,
                           'operationSeconds': 120, 'outputBytes': 65536}}}}, 'app-draft')
        self.state['applications'].publish('alice', app['id'], app['version'], 'app-publish')

    def until(self, predicate, label):
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            value = predicate()
            if value:
                return value
            time.sleep(.05)
        self.fail('Timed out: ' + label)

    def test_original_native_wait_resumes_once_after_controller_restart(self):
        started = self.request('POST', '/application-interface/v1/starts',
            {'application': 'ssh-native', 'mode': 'train', 'goal': 'Run original controlled training',
             'requestId': 'original-training', 'connectionRefs': {'compute': self.connection}}, expected=202)
        task_id = started['job']['id']
        task = self.store.task(task_id, 'alice')
        run_id = task['run_id']
        self.until(lambda: self.started.exists(), 'helper training process start')
        self.until(lambda: (self.store.native_db.get_job(run_id) or {}).get('status') == 'paused', 'native external wait')
        operations = self.store.sql('SELECT id FROM af_external_operations WHERE task_id=:task', task=task_id)
        self.assertEqual(len(operations), 1)
        operation_id = operations[0]['id']
        leases = self.store.sql("SELECT id FROM af_leases WHERE body->>'localTaskId'=:task", task=task_id)
        self.assertEqual(len(leases), 1)
        self.stop()
        self.release.touch()
        self.start()
        self.until(lambda: (self.store.native_db.get_job(run_id) or {}).get('status') == 'completed', 'same native run completed')
        self.until(lambda: self.store.task(task_id, 'alice')['terminal'], 'original task finalization')
        self.assertEqual(self.store.task(task_id, 'alice')['run_id'], run_id)
        self.assertEqual([json.loads(line) for line in self.started.read_text().splitlines()], [self.model_inputs])
        self.assertEqual(self.model_results[0]['operationId'], operation_id)
        self.assertEqual(self.model_results[0]['actual']['received'], self.model_inputs)
        self.assertEqual(self.model_results[0]['artifact']['taskId'], task_id)
        self.assertTrue(self.store.workflow.read('alice', operation_id)['closed'])
        receipts = self.store.sql('SELECT command_id FROM af_control_commands WHERE task_ref=:task', task=task_id)
        self.assertEqual(len(receipts), 1)
        self.assertTrue(receipts[0]['command_id'].startswith('ssh-wait:'))
        for _ in range(2):
            self.client.portal.call(self.state['lifecycle_observer'].observe_root, task_id)
        self.assertEqual(self.store.sql('SELECT command_id FROM af_control_commands WHERE task_ref=:task', task=task_id), receipts)
        self.assertEqual([json.loads(line) for line in self.started.read_text().splitlines()], [self.model_inputs])

    def test_uncertain_continuation_receipt_is_not_redispatched_after_restart(self):
        """Lost acknowledgement at the boundary; delivery itself is not proven."""
        started = self.request('POST', '/application-interface/v1/starts',
            {'application': 'ssh-native', 'mode': 'train', 'goal': 'Keep the original uncertain continuation',
             'requestId': 'uncertain-continuation', 'connectionRefs': {'compute': self.connection}}, expected=202)
        task_id = started['job']['id']
        run_id = self.store.task(task_id, 'alice')['run_id']
        self.until(lambda: self.started.exists(), 'helper training process start')
        self.until(lambda: (self.store.native_db.get_job(run_id) or {}).get('status') == 'paused', 'native external wait')
        operations = self.store.sql('SELECT id FROM af_external_operations WHERE task_id=:task', task=task_id)
        self.assertEqual(len(operations), 1)
        attempts = []

        async def unavailable_ack(bridge, original_run, original_task, owner, requirements, **kwargs):
            attempts.append((original_run, original_task, owner, kwargs['command_proof']))
            raise ConnectionError('Synthetic continuation acknowledgement unavailable')

        bridge_type = type(self.state['factory_api'].commands.bridge)
        with patch.object(bridge_type, 'continue_run', new=unavailable_ack):
            self.release.touch()
            rows = self.until(lambda: self.store.sql(
                "SELECT command_id FROM af_control_commands WHERE task_ref=:task AND state='DISPATCHING'",
                task=task_id), 'original command dispatch boundary')
            self.assertEqual(len(rows), 1)
            command_id = rows[0]['command_id']
            self.until(lambda: len(attempts) == 1, 'one uncertain continuation attempt')
            receipt = self.client.portal.call(self.state['factory_api'].commands.recover,
                                              'alice', task_id, command_id)
            self.assertEqual(receipt['state'], 'UNKNOWN')
            self.assertFalse(receipt['decisionRecorded'])
            self.assertFalse(receipt['canDispatch'])
            self.assertEqual(attempts[0][:3], (run_id, task_id, 'alice'))
            self.assertEqual(attempts[0][3]['commandId'], command_id)
            self.assertTrue(self.store.workflow.read('alice', operations[0]['id'])['closed'])
            self.stop()
            self.start()
            for _ in range(2):
                self.client.portal.call(self.state['lifecycle_observer'].observe_root, task_id)
                recovered = self.client.portal.call(self.state['factory_api'].commands.recover,
                                                     'alice', task_id, command_id)
                self.assertEqual(recovered['state'], 'UNKNOWN')
                self.assertFalse(recovered['canDispatch'])
                for key in ('commandId', 'fingerprint', 'binding', 'requirementId', 'version'):
                    self.assertEqual(recovered[key], receipt[key])
            self.assertEqual(len(attempts), 1)
            self.assertEqual(self.store.native_db.get_job(run_id)['status'], 'paused')
            self.assertEqual(self.store.task(task_id, 'alice')['run_id'], run_id)
            self.assertFalse(self.store.task(task_id, 'alice')['terminal'])
            self.assertEqual(self.store.sql('SELECT id FROM af_external_operations WHERE task_id=:task',
                                            task=task_id), operations)
            self.assertEqual(self.store.sql('SELECT command_id FROM af_control_commands WHERE task_ref=:task',
                                            task=task_id), rows)
            self.assertEqual([json.loads(line) for line in self.started.read_text().splitlines()], [self.model_inputs])
            self.assertEqual(self.model_results, [])

    def test_accepted_continuation_with_lost_ack_recovers_without_second_send(self):
        started = self.request('POST', '/application-interface/v1/starts',
            {'application': 'ssh-native', 'mode': 'train', 'goal': 'Recover the accepted original continuation',
             'requestId': 'accepted-ack-lost', 'connectionRefs': {'compute': self.connection}}, expected=202)
        task_id = started['job']['id']
        run_id = self.store.task(task_id, 'alice')['run_id']
        self.until(lambda: self.started.exists(), 'original helper start')
        self.until(lambda: self.store.native_db.get_job(run_id)['status'] == 'paused', 'original native wait')
        operations = self.store.sql('SELECT id FROM af_external_operations WHERE task_id=:task', task=task_id)
        self.assertEqual(len(operations), 1)
        bridge_type = type(self.state['factory_api'].commands.bridge)
        original = bridge_type.continue_run
        sent, accepted = [], []

        async def lost_after_acceptance(bridge, original_run, original_task, owner, requirements, **kwargs):
            proof = dict(kwargs['command_proof'])
            sent.append((original_run, original_task, owner, proof))
            await original(bridge, original_run, original_task, owner, requirements, **kwargs)
            accepted.append(proof)
            raise ConnectionError('Synthetic reply lost after actual native continuation returned')

        with patch.object(bridge_type, 'continue_run', new=lost_after_acceptance):
            self.release.touch()
            self.until(lambda: accepted, 'actual native acceptance before injected reply loss')
            self.assertEqual(len(sent), 1)
            command_id = accepted[0]['commandId']
            self.assertEqual(sent[0][:3], (run_id, task_id, 'alice'))
            assert self.client is not None and self.client.portal is not None
            receipt = self.client.portal.call(self.state['factory_api'].commands.recover, 'alice', task_id, command_id)
            self.assertTrue(receipt['decisionRecorded'], receipt)
            self.assertFalse(receipt['canDispatch'])
            self.assertIn(receipt['state'], {'DECISION_RECORDED', 'EXECUTION_CONTINUING'})
            self.assertEqual(receipt['fingerprint'], accepted[0]['fingerprint'])
            self.stop()
            self.start()
            self.until(lambda: self.store.task(task_id, 'alice')['terminal'], 'same original task completed')
            assert self.client is not None and self.client.portal is not None
            for _ in range(2):
                self.client.portal.call(self.state['lifecycle_observer'].observe_root, task_id)
                recovered = self.client.portal.call(self.state['factory_api'].commands.recover, 'alice', task_id, command_id)
                self.assertTrue(recovered['decisionRecorded'])
                self.assertFalse(recovered['canDispatch'])
                for key in ('commandId', 'fingerprint', 'binding', 'requirementId', 'version'):
                    self.assertEqual(recovered[key], receipt[key])
            self.assertEqual(len(sent), 1)
            self.assertEqual(self.store.task(task_id, 'alice')['run_id'], run_id)
            self.assertEqual(self.store.sql('SELECT id FROM af_external_operations WHERE task_id=:task', task=task_id), operations)
            self.assertEqual([json.loads(line) for line in self.started.read_text().splitlines()], [self.model_inputs])
            self.assertEqual(len(self.model_results), 1)
            self.assertEqual(self.model_results[0]['operationId'], operations[0]['id'])
            self.assertEqual(self.model_results[0]['actual']['received'], self.model_inputs)

    def test_distinct_inputs_reach_real_helper_and_restart_retains_original(self):
        first_inputs = dict(self.model_inputs)
        first = self.request('POST', '/application-interface/v1/starts',
            {'application': 'ssh-native', 'mode': 'train', 'goal': 'First typed training',
             'requestId': 'typed-first', 'connectionRefs': {'compute': self.connection}}, expected=202)
        first_task = first['job']['id']
        first_run = self.store.task(first_task, 'alice')['run_id']
        self.until(lambda: self.started.exists(), 'first actual helper argv')
        self.until(lambda: self.store.native_db.get_job(first_run)['status'] == 'paused', 'first native wait')
        first_operation = self.store.sql('SELECT id FROM af_external_operations WHERE task_id=:task',
                                         task=first_task)[0]['id']
        retained = self.store.workflow._load('alice', first_operation)['inputs']
        self.assertEqual(retained['inputs'], first_inputs)
        self.model_inputs = {'width': 3, 'label': "quoted '; $(not-a-shell-command)"}
        second_inputs = dict(self.model_inputs)
        self.stop()
        self.release.touch()
        self.start()
        self.until(lambda: self.store.task(first_task, 'alice')['terminal'], 'first original completion')
        self.assertEqual(self.store.task(first_task, 'alice')['run_id'], first_run)
        self.assertEqual(self.store.workflow._load('alice', first_operation)['inputs'], retained)
        first_output = self.model_results[0]
        self.assertEqual(first_output['operationId'], first_operation)
        self.assertEqual(first_output['actual']['received'], first_inputs)
        second = self.request('POST', '/application-interface/v1/starts',
            {'application': 'ssh-native', 'mode': 'train', 'goal': 'Second typed training',
             'requestId': 'typed-second', 'connectionRefs': {'compute': self.connection}}, expected=202)
        second_task = second['job']['id']
        self.until(lambda: self.store.task(second_task, 'alice')['terminal'], 'second actual helper completion')
        second_run = self.store.task(second_task, 'alice')['run_id']
        second_operation = self.store.sql('SELECT id FROM af_external_operations WHERE task_id=:task',
                                          task=second_task)[0]['id']
        self.assertNotEqual(first_task, second_task)
        self.assertNotEqual(first_run, second_run)
        self.assertNotEqual(first_operation, second_operation)
        second_retained = self.store.workflow._load('alice', second_operation)['inputs']
        self.assertEqual(second_retained['inputs'], second_inputs)
        self.assertNotEqual(retained['targetRef'], second_retained['targetRef'])
        self.assertEqual(len(self.model_results), 2)
        for output, expected, task, operation in (
            (first_output, first_inputs, first_task, first_operation),
            (self.model_results[1], second_inputs, second_task, second_operation)):
            self.assertEqual(output['operationId'], operation)
            self.assertEqual(output['artifact']['taskId'], task)
            self.assertEqual(output['actual']['received'], expected)
            argv = output['actual']['argv']
            self.assertEqual(len(argv), 2)
            self.assertEqual(argv[0], '--experiment-json')
            self.assertEqual(json.loads(argv[1]), expected)
        self.assertEqual([json.loads(line) for line in self.started.read_text().splitlines()],
                         [first_inputs, second_inputs])
