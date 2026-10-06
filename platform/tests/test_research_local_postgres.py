# pyright: reportMissingImports=false
"""Real native queue and stdlib guardian; device observations are explicit mocks."""
import asyncio
from contextlib import ExitStack
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import create_engine
from fastapi import HTTPException
from fastapi.testclient import TestClient
from agent_factory.config import Settings
from agent_factory.gpu_custody import GpuBinding
from agent_factory.main import create_app
from agent_factory.process_enforcement import BoundedProcessAdapter, ResearchProcessLimits, ResearchProcessSpec
from agent_factory.research_checkpoint_store import ResearchCheckpointStore
from agent_factory.research_local_provider import ResearchLocalProvider
from agent_factory.research_manifest import manifest_fingerprint
from agent_factory.research_evaluation import evaluation_contract_fingerprint
from agent_factory.research_evaluation_service import ResearchEvaluationService
from agent_factory.research_runtime import ResearchProcessRuntimeService
from agent_factory.research_runtime_profile import research_settings, publish_research_application, registrations
from agent_factory.resources import ComputePool, RemoteTarget
from agent_factory.store import Store, digest
from pg_fixture import IsolatedPostgres
from test_research_manifest import example_manifest


class MockDeviceObserver:
    configuration_fingerprint = 'c' * 64
    def __init__(self):
        self.calls = []
    def __call__(self, request):
        self.calls.append(request)
        return {'schema': 1, 'requestFingerprint': digest(request),
            'status': 'AVAILABLE' if request['operation'] == 'launch' else 'RELEASED',
            'observationSha256': digest({'controlledDeviceFixture': True, 'request': request})}


class SyntheticProgramVerifier:
    def __init__(self, fixture, code):
        self.fixture = fixture
        self.code = code
        self.configuration_fingerprint = hashlib.sha256(code.encode()).hexdigest()
    def validate_spec(self, spec):
        if spec.argv != ('-I', '-c', self.code):
            raise ValueError('SYNTHETIC_SPEC_CHANGED')
    def __call__(self, record):
        f = self.fixture
        lease = record['binding']
        plan = f.store.plan(lease['planId'], lease['ownerId'])
        binding = {'ownerId': lease['ownerId'], 'taskId': lease['localTaskId'],
            'nativeRunId': lease['nativeRunId'], 'planId': lease['planId'], 'planFingerprint': plan['fingerprint'],
            'leaseId': lease['id'], 'providerJobId': record['processPin']['id'],
            'variantSha256': lease['executionGuard']['variantSha256'],
            'manifestSha256': lease['executionGuard']['manifestSha256']}
        destination = f.checkpoints.reserve(binding, disk_bytes=f.limits.disk_bytes)
        f.destination = destination
        payload = {'destination': destination, 'binding': binding, 'maximum': f.manifest['artifactLimits']['checkpointBytes']}
        fd = os.open(f.work / 'input.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(payload, stream)
        return {'schema': 1, 'descriptorSha256': digest(payload), 'sourceSha256': self.configuration_fingerprint,
            'manifestSha256': binding['manifestSha256'], 'variantSha256': binding['variantSha256'],
            'checkpoint': None, 'evaluationContractSha256': None}


class SyntheticEvaluatorVerifier:
    def __init__(self, fixture, code):
        self.fixture, self.code = fixture, code
        self.configuration_fingerprint = hashlib.sha256(code.encode()).hexdigest()
    def validate_spec(self, spec):
        if spec.argv != ('-I', '-c', self.code):
            raise ValueError('SYNTHETIC_EVALUATOR_SPEC_CHANGED')
    def __call__(self, record):
        f = self.fixture
        binding = record['binding']; plan = f.store.plan(binding['planId'], 'alice')
        execution = {'ownerId': 'alice', 'taskId': binding['localTaskId'], 'nativeRunId': binding['nativeRunId'],
            'planId': binding['planId'], 'planFingerprint': plan['fingerprint'], 'leaseId': binding['id'],
            'providerJobId': record['processPin']['id']}
        contract = {'schema': 1, 'evidenceKind': 'offline_research_evaluation_contract',
            'comparisonManifest': f.manifest, 'training': f.training_contract, 'evaluatorExecution': execution}
        fingerprint = evaluation_contract_fingerprint(contract)
        f.evaluation_contract = contract
        metadata = json.loads(f.store.artifact(f.training_contract['taskId'], f.training_contract['checkpoint']['artifactId'])[1])
        payload = {'contractFingerprint': fingerprint, 'destination': f.destination, 'binding': metadata['binding'],
            'checkpoint': f.training_contract['checkpoint']}
        fd = os.open(f.eval_work / 'input.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(payload, stream)
        return {'schema': 1, 'descriptorSha256': digest(payload), 'sourceSha256': self.configuration_fingerprint,
            'manifestSha256': binding['executionGuard']['manifestSha256'],
            'variantSha256': binding['executionGuard']['variantSha256'],
            'checkpoint': f.training_contract['checkpoint'], 'evaluationContractSha256': fingerprint}


@unittest.skipUnless(sys.platform == 'linux' and os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires isolated PostgreSQL and Linux guardian')
class ResearchLocalPostgresTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        db = self.stack.enter_context(IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']))
        root = Path(self.stack.enter_context(tempfile.TemporaryDirectory(prefix='research-local-')))
        bootstrap = Store(db.url, Settings(db_url=db.url, workspace=root))
        self.stack.callback(bootstrap.engine.dispose)
        self.work = root / 'work'; self.work.mkdir(mode=0o700)
        self.eval_work = root / 'evaluator'; self.eval_work.mkdir(mode=0o700)
        eval_custody = root / 'eval-custody'; eval_custody.mkdir(mode=0o700)
        custody = root / 'custody'; custody.mkdir(mode=0o700)
        self.gpu = GpuBinding('a' * 64, 'b' * 64)
        self.manifest = example_manifest(); self.manifest['device']['identitySha256'] = self.gpu.identity_key
        self.manifest['artifactLimits'].update(checkpointBytes=65536, logBytes=4096)
        platform_root = str(Path(__file__).resolve().parents[1])
        code = f"""import sys,json,time
sys.path.insert(0,{platform_root!r})
from agent_factory.research_checkpoint import write_checkpoint
p=json.load(open('input.json')); d=p['destination']
while not __import__('os').path.exists('release'): time.sleep(.02)
write_checkpoint(d['root'],d['basename'],{{'weight':{{'dtype':'F32','shape':[1],'data_offsets':[0,4]}}}},[b'\\0\\0\\x80?'],root_identity=d['rootIdentity'],binding=p['binding'],max_bytes=p['maximum'],before_effect=lambda:None)
print('synthetic checkpoint only; no training')
"""
        eval_code = f"""import sys,json,hashlib
sys.path.insert(0,{platform_root!r})
from agent_factory.research_checkpoint import open_verified_checkpoint
p=json.load(open('input.json')); d=p['destination']; expected=p['checkpoint']
with open_verified_checkpoint(d['root'],d['basename'],d['rootIdentity'],p['binding'],expected['sizeBytes']) as reader:
 assert reader.identity=={{'sha256':expected['sha256'],'sizeBytes':expected['sizeBytes']}}
 h=hashlib.sha256()
 while chunk:=reader.read_chunk(): h.update(chunk)
 assert h.hexdigest()==expected['sha256']
print(json.dumps({{'schema':1,'evaluationContractSha256':p['contractFingerprint'],'status':'completed','metric':{{'id':'val_bpb','value':4.0}}}}))
"""
        self.manifest['evaluator']['code'] = {'sha256': hashlib.sha256(eval_code.encode()).hexdigest(), 'sizeBytes': len(eval_code.encode())}
        executable = Path(sys.executable).resolve(); info = self.work.stat()
        env = tuple((key, '1') for key in ('HF_HUB_OFFLINE', 'HF_DATASETS_OFFLINE', 'TRANSFORMERS_OFFLINE', 'PYTHONNOUSERSITE'))
        spec = ResearchProcessSpec(str(executable), hashlib.sha256(executable.read_bytes()).hexdigest(), ('-I', '-c', code),
            working_directory=str(self.work), environment=env, working_directory_identity=(info.st_dev, info.st_ino))
        self.limits = ResearchProcessLimits(cpu_seconds=5, address_space_mb=128, file_size_bytes=65536,
            disk_bytes=135168, output_bytes=4096, wall_seconds=self.manifest['protocol']['totalWallSeconds'])
        verifier = SyntheticProgramVerifier(self, code); self.observer = MockDeviceObserver()
        self.provider = ResearchLocalProvider(bootstrap, custody, spec, self.limits, gpu_binding=self.gpu,
            source_fingerprint=verifier.configuration_fingerprint, manifest_fingerprint=manifest_fingerprint(self.manifest),
            observer=self.observer, program_verifier=verifier)
        target = RemoteTarget('Synthetic stdlib guardian, mocked device', 'compute', frozenset({'alice'}),
            provider=self.provider, synthetic_fixture=True, max_cpu=1, max_memory_mb=128, max_disk_mb=1,
            max_seconds=600, gpu_binding=self.gpu, capacity_pool=ComputePool('local', 1, 128, 1, 1, 1))
        eval_info = self.eval_work.stat()
        eval_spec = replace(spec, argv=('-I', '-c', eval_code), working_directory=str(self.eval_work),
            working_directory_identity=(eval_info.st_dev, eval_info.st_ino))
        eval_verifier = SyntheticEvaluatorVerifier(self, eval_code)
        self.evaluator = ResearchLocalProvider(bootstrap, eval_custody, eval_spec, self.limits, gpu_binding=self.gpu,
            source_fingerprint=eval_verifier.configuration_fingerprint, manifest_fingerprint=manifest_fingerprint(self.manifest),
            observer=MockDeviceObserver(), program_verifier=eval_verifier)
        evaluator_target = replace(target, provider=self.evaluator)
        settings = research_settings(db_url=db.url, workspace=root, target_ref='local', remote_targets={'local': target, 'evaluator': evaluator_target}, comparison_manifest=self.manifest)
        evaluator_adapters = registrations(target_ref='evaluator', comparison_manifest=self.manifest, adapter_suffix='-evaluator')
        settings = replace(settings, runtime_adapters=[*settings.runtime_adapters, *evaluator_adapters],
            usage_pricing=(*settings.usage_pricing, replace(settings.usage_pricing[0], adapter_id=settings.usage_pricing[0].adapter_id + '-evaluator')))
        self.app = create_app(settings); self.state = self.app.app.state.factory
        self.store, self.auth = self.state['store'], self.state['auth']; self.runtime = self.store.research_runtime
        self.checkpoints = ResearchCheckpointStore(self.store, self.auth, self.runtime.resources, self.store.storage)
        self.requirements = {}
        self.destination = {}
        self.training_contract = {}
        self.evaluation_contract = {}
        self.stack.callback(self.store.dispose_root_locks)
        self.stack.callback(bootstrap.dispose_root_locks)
        self.stack.callback(self.store.engine.dispose); self.stack.callback(self.store.native_db.db_engine.dispose)
        self.auth.authorization.unassign('bob', 'factory-user'); self.auth.authorization.assign('bob', 'factory-manager')
        self.application = publish_research_application(self.state, target_ref='local', comparison_manifest=self.manifest, author='manager', reviewer='bob')
        self.client = self.stack.enter_context(TestClient(self.app))  # pyright: ignore[reportArgumentType]
        assert self.client.portal is not None
        self.portal = self.client.portal
        self.stack.callback(self.cleanup)

    def cleanup(self):
        self.auth.authorization.assign('alice', 'factory-user')
        for row in self.store.sql('SELECT id,owner_id FROM af_process_allocations'):
            lease = self.runtime.resources.inspect(row['owner_id'], row['id'])
            provider = self.evaluator if lease['connectionRef'] == 'evaluator' else self.provider
            asyncio.run(provider.cancel(row['id'], row['owner_id']))
            asyncio.run(provider.reclaim(row['id'], row['owner_id']))
        for row in self.store.sql('SELECT id,owner_id FROM af_tasks WHERE NOT terminal'):
            self.request('POST', '/jobs/' + row['id'] + '/cancel', {}, owner=row['owner_id'], allowed={200,409})

    def request(self, method, path, body=None, *, owner='alice', allowed=None):
        response = self.client.request(method, '/api/factory' + path, json=body,
            headers={'Authorization': 'Bearer ' + self.auth._issue_native_token(owner)})
        self.assertTrue(response.status_code in allowed if allowed else response.is_success, response.text)
        return response.json()

    def post(self, path, body=None, **kwargs):
        return self.request('POST', path, {'requestId': str(uuid4()), **(body or {})}, **kwargs)

    def task(self, *, wait=True):
        proposal = self.post('/compositions/proposals', {'goal': 'Controlled research original native execution',
            'mode': 'controlled-fixture', 'applicationRef': {key: self.application[key] for key in ('id', 'version', 'sha256')}})
        plan = self.post('/compositions/proposals/' + proposal['id'] + '/accept')
        review = self.post('/plan-reviews', {'planId': plan['id']})
        self.post('/plan-reviews/' + review['id'] + '/decision', {'approved': True}, owner='manager')
        task = self.post('/instances', {'planId': plan['id']})
        detail = self.until(lambda: self.detail(task['id']), lambda d: d['job']['status'] == 'waiting_approval') if wait else None
        if wait:
            self.assertEqual(self.store.native_db.get_job(self.store.task(task['id'])['run_id'])['status'], 'paused')
            self.requirements[task['id']] = self.runtime._paused(self.store.task(task['id']), self.manifest,
                self.manifest['baselineSourceManifestSha256'])
        return task, detail

    def detail(self, task):
        return self.request('GET', '/jobs/' + task)

    def until(self, probe, predicate, timeout=20):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            value = probe()
            if predicate(value):
                return value
            time.sleep(.04)
        self.fail('Controlled native research state did not settle')

    def approve(self, task, detail, *, allowed=None):
        requirement = self.requirements[task]
        return self.request('POST', '/jobs/' + task + '/approve',
            {'requirementId': requirement['id'], 'version': requirement['version'], 'approved': True}, allowed=allowed)

    def settled(self, task):
        return self.until(lambda: self.portal.call(self.runtime.inspect_task, 'alice', task),
            lambda lease: lease['state'] == 'RECLAIMED')

    def test_native_original_process_checkpoint_import_and_tamper(self):
        task, _ = self.task(); native = self.store.task(task['id'])['run_id']
        lease = self.portal.call(self.runtime.submit, 'alice', task['id'])
        self.assertEqual(self.portal.call(self.runtime.submit, 'alice', task['id'])['id'], lease['id'])
        (self.work / 'release').touch()
        settled = self.settled(task['id'])
        self.assertEqual(settled['executionStatus'], 'COMPLETED')
        self.assertEqual(settled['providerJobId'], lease['providerJobId'])
        self.assertEqual(settled['nativeRunId'], native)
        self.assertEqual(settled['gpuEvidence']['state'], 'RELEASED')
        self.portal.call(self.store.lifecycle_observer.stop)
        prior_engine = self.store.engine
        limited = create_engine(prior_engine.url, pool_size=1, max_overflow=0, pool_timeout=.2)
        self.store.engine = limited
        try:
            artifact = self.checkpoints.import_completed('alice', lease['id'])
            self.assertEqual(self.checkpoints.import_completed('alice', lease['id'])['id'], artifact['id'])
            metadata, identity = self.checkpoints.identity(task['id'], artifact['id'], 65536)
            original_binding = json.loads(self.store.artifact(task['id'], artifact['id'])[1])['binding']
            self.assertEqual(self.checkpoints.reserve(original_binding, disk_bytes=self.limits.disk_bytes), self.destination)
        finally:
            self.store.engine = prior_engine
            limited.dispose()
        self.assertEqual(metadata['provenance']['nativeRunId'], native)
        self.assertEqual(metadata['provenance']['providerJobId'], lease['providerJobId'])
        self.assertGreater(int(identity['sizeBytes']), 4)
        self.assertEqual(len(self.store.sql('SELECT id FROM af_process_allocations')), 1)
        with self.assertRaises((ValueError, HTTPException)):
            self.checkpoints.import_completed('bob', lease['id'])
        checkpoint = Path(self.destination['root']) / self.destination['basename']
        content = checkpoint.read_bytes(); checkpoint.write_bytes(content[:-1] + bytes([content[-1] ^ 1]))
        with self.assertRaises(ValueError):
            self.checkpoints.identity(task['id'], artifact['id'], 65536)
        self.assertTrue(all(call['gpuBinding'] == self.gpu.to_dict() for call in self.observer.calls))

    def test_lost_launch_ack_restart_recovers_only_original_process(self):
        task, _ = self.task()
        original_launch = BoundedProcessAdapter.launch
        def lose_ack(adapter, **kwargs):
            original_launch(adapter, **kwargs)
            raise ValueError('SYNTHETIC_ACK_LOSS')
        with patch.object(BoundedProcessAdapter, 'launch', lose_ack):
            lease = self.portal.call(self.runtime.submit, 'alice', task['id'])
        restarted = ResearchProcessRuntimeService(self.store, self.auth, self.runtime.resources)
        with patch.object(BoundedProcessAdapter, 'launch', side_effect=AssertionError('NO_REPLAY')):
            again = self.portal.call(restarted.submit, 'alice', task['id'])
            self.assertEqual(again['id'], lease['id'])
            (self.work / 'release').touch()
            settled = self.until(lambda: self.portal.call(restarted.inspect_task, 'alice', task['id']),
                lambda value: value['state'] == 'RECLAIMED')
        self.assertEqual(settled['providerJobId'], lease['providerJobId'])
        self.assertEqual(settled['executionStatus'], 'COMPLETED')
        self.assertEqual(len(self.store.sql('SELECT id FROM af_process_allocations')), 1)
        self.assertEqual(sum(call['operation'] == 'launch' for call in self.observer.calls), 1)

    def test_revocation_stops_original_without_checkpoint_import(self):
        task, _ = self.task()
        lease = self.portal.call(self.runtime.submit, 'alice', task['id'])
        self.portal.call(self.store.lifecycle_observer.stop)
        self.auth.authorization.unassign('alice', 'factory-user')
        settled = self.until(lambda: self.portal.call(self.runtime.observe_lease, lease['id']),
            lambda value: value['state'] == 'RECLAIMED')
        self.assertEqual(settled['providerJobId'], lease['providerJobId'])
        self.assertFalse(settled['capacityHeld'])
        self.assertEqual(settled['gpuEvidence']['state'], 'RELEASED')
        self.assertNotEqual(settled['executionStatus'], 'COMPLETED')
        self.assertEqual(self.store.artifacts(task['id']), [])
        self.assertEqual(len(self.store.sql('SELECT id FROM af_process_allocations')), 1)
    def test_distinct_evaluator_consumes_original_checkpoint_and_bound_contract(self):
        training, _ = self.task()
        train_lease = self.portal.call(self.runtime.submit, 'alice', training['id'])
        (self.work / 'release').touch(); self.settled(training['id'])
        artifact = self.checkpoints.import_completed('alice', train_lease['id'])
        metadata, identity = self.checkpoints.identity(training['id'], artifact['id'], 65536)
        self.training_contract = {key: metadata['provenance'][key] for key in
            ('ownerId', 'taskId', 'nativeRunId', 'planId', 'planFingerprint', 'leaseId', 'providerJobId', 'variantSha256')}
        self.training_contract['checkpoint'] = {'artifactId': artifact['id'], **identity}
        self.application = publish_research_application(self.state, target_ref='evaluator', comparison_manifest=self.manifest,
            author='manager', reviewer='bob', adapter_suffix='-evaluator')
        evaluation, _ = self.task()
        eval_lease = self.portal.call(self.runtime.submit, 'alice', evaluation['id'])
        settled = self.settled(evaluation['id'])
        self.assertEqual(settled['executionStatus'], 'COMPLETED')
        service = ResearchEvaluationService(self.store, self.auth, self.runtime.resources,
            {digest(self.manifest['evaluator']): 'evaluator'}, checkpoint_reader=self.checkpoints.identity)
        with patch.object(self.provider, 'read_completed_output', side_effect=AssertionError('TRAINING_STDOUT_IS_NOT_EVIDENCE')):
            receipt = self.portal.call(service.verify, 'alice', self.evaluation_contract)
        self.assertTrue(receipt['evaluatorCustodyVerified'])
        self.assertTrue(receipt['launchInputsVerified'])
        self.assertFalse(receipt['executionVerified'])
        self.assertFalse(receipt['scientificConclusionVerified'])
        self.assertEqual(receipt['observation']['valBpb'], 4.0)
        self.assertEqual(receipt['checkpoint']['sha256'], identity['sha256'])
        for key in ('id', 'providerJobId', 'nativeRunId', 'localTaskId'):
            self.assertNotEqual(train_lease[key], eval_lease[key])
        self.assertEqual(len(self.store.sql('SELECT id FROM af_process_allocations')), 2)
        wrong = json.loads(json.dumps(self.evaluation_contract))
        wrong['training']['checkpoint']['sha256'] = '0' * 64
        with self.assertRaises(ValueError):
            self.portal.call(service.verify, 'alice', wrong)
        wrong = json.loads(json.dumps(self.evaluation_contract))
        wrong['comparisonManifest']['protocol']['seed'] += 1
        with self.assertRaises(ValueError):
            self.portal.call(service.verify, 'alice', wrong)
