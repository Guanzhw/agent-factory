# pyright: reportMissingImports=false
"""Real PG/native three-stage custody with explicit synthetic science boundaries.

Mock seams ONLY: build_training_bundle supplies self-authored stdlib programs;
ResearchEnvironmentObserver supplies controlled observations; GPU observations are
MockDeviceObserver; SOURCE_SHA256 uv.lock is temporarily pinned to a synthetic
lock before constructing its canonical source profile; the ORX runtime makes
fixed synthetic tool decisions. Real
ScientificPhaseAssembler, _LocalDriver, providers, preparation/checkpoint stores,
child authorization and independent result verification are never mocked.
No Torch/GPU/ORX/model service, scientific validation, or upstream training runs.
"""
import asyncio
from contextlib import ExitStack
from dataclasses import replace
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
import stat
import tempfile
import traceback
import time
from typing import Any
import unittest
from unittest.mock import patch
from uuid import uuid4

from agent_factory.autoresearch import ResearchPreset
from agent_factory.autoresearch_children import AutoResearchChildren
from agent_factory.config import Settings
from agent_factory.gpu_custody import GpuBinding
from agent_factory.process_enforcement import BoundedProcessAdapter, ProcessLimits, ProcessSpec, ResearchProcessLimits
from agent_factory import process_runtime_profile
from agent_factory import research_local_driver
from agent_factory.research_checkpoint_store import ResearchCheckpointStore
from agent_factory.research_local_provider import ResearchLocalProvider
from agent_factory.research_manifest import SOURCE_SHA256, manifest_fingerprint
from agent_factory.research_preparation_driver import PreparationDriver
from agent_factory.research_preparation_provider import PreparationProvider
from agent_factory.research_preparation_store import ResearchPreparationStore
from agent_factory.research_staging import InputPin, RootIdentity, pin_bytes
from agent_factory.resources import ComputePool, RemoteTarget
from agent_factory.store import Store
from pg_fixture import IsolatedPostgres
from test_autoresearch_postgres import bootstrap
import test_go_product_postgres as http_fixture
import test_process_runtime_postgres as process_fixture
from test_research_local_driver import FixtureObserver
from test_research_local_postgres import MockDeviceObserver, synthetic_uv_launch
from test_research_manifest import example_manifest
from test_research_preparation_harness import tokenizer


def identity(path):
    info = path.stat()
    return {'device': info.st_dev, 'inode': info.st_ino}


def artifact(raw):
    return {'sha256': hashlib.sha256(raw).hexdigest(), 'sizeBytes': len(raw)}


def generated_bundle():
    platform = str(Path(__file__).resolve().parents[1])
    prefix = f"import sys,json,hashlib\nsys.path.insert(0,{platform!r})\np=json.load(open(sys.argv[sys.argv.index('--config')+1]))\n"
    train = prefix + """from agent_factory.research_checkpoint import write_checkpoint
x=p['outputCheckpoint']
write_checkpoint(x['root'],x['basename'],{'weight':{'dtype':'F32','shape':[1],'data_offsets':[0,4]}},[b'\\0\\0\\x80?'],root_identity=x['rootIdentity'],binding=p['binding'],max_bytes=p['comparisonManifest']['artifactLimits']['checkpointBytes'],before_effect=lambda:None)
print('controlled stdlib checkpoint; no training')
"""
    evaluate = prefix + """from agent_factory.research_checkpoint import open_verified_checkpoint
x=p['checkpoint']
with open_verified_checkpoint(x['root'],x['basename'],x['rootIdentity'],x['binding'],x['sizeBytes']) as reader:
 assert reader.identity=={'sha256':x['sha256'],'sizeBytes':x['sizeBytes']}
 h=hashlib.sha256()
 while chunk:=reader.read_chunk(): h.update(chunk)
 assert h.hexdigest()==x['sha256']
contract=json.dumps(p['evaluationContract'],sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()
print(json.dumps({'schema':1,'evaluationContractSha256':hashlib.sha256(contract).hexdigest(),'status':'completed','metric':{'id':'val_bpb','value':4.0}}))
"""
    files = {'train_baseline.py': b'# controlled unused baseline\n', 'train_candidate.py': train.encode(),
        'evaluate.py': evaluate.encode(), 'trusted_architecture.py': b'# no architecture execution\n',
        'trusted_data.py': b'# no dataset execution\n'}
    return {'generatedFiles': files, 'receipt': {'approvedMicrobatch': 1,
        'candidateSource': {'baselineManifestSha256': '1'*64, 'candidateManifestSha256': '2'*64},
        'generatedSha256': {key: hashlib.sha256(value).hexdigest() for key, value in files.items()},
        'evidenceKind': 'controlled-stdlib-source-generation-fixture'}}


@unittest.skipUnless(sys.platform == 'linux' and os.getenv('FACTORY_TEST_DATABASE_URL'),
                     'Requires disposable PostgreSQL and Linux stdlib guardian')
class ScientificChildrenPostgresTests(unittest.TestCase):
    state: Any
    store: Any
    client: Any
    settings: Any
    auth: Any
    application: Any
    children: Any
    preparation: Any
    open_application = http_fixture.GoProductPostgresTests.open_application
    login = http_fixture.GoProductPostgresTests.login
    post = http_fixture.GoProductPostgresTests.post
    request = process_fixture.ProcessRuntimePostgresTests.request
    submit = process_fixture.ProcessRuntimePostgresTests.submit
    until = process_fixture.ProcessRuntimePostgresTests.until

    def test_original_preparation_verification_training_and_evaluation_share_paused_parent(self):
        stack = ExitStack(); self.addCleanup(stack.close)
        database = stack.enter_context(IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']))
        root = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix='scientific-children-')))
        scripts = str(Path(__file__).resolve().parents[2] / 'scripts')
        with patch.object(sys, 'path', [scripts, *sys.path]):
            assembly = importlib.import_module('autoresearch_scientific_assembly')
        bundle = generated_bundle()
        stack.enter_context(patch.object(research_local_driver, 'build_training_bundle', return_value=bundle))
        stack.enter_context(patch.object(assembly, 'build_training_bundle', return_value=bundle))
        stack.enter_context(patch.object(assembly, 'ResearchEnvironmentObserver', side_effect=lambda *a, **k: FixtureObserver()))
        original_driver_call = research_local_driver._LocalDriver.__call__
        def observed_driver_call(driver, record):
            try:
                return original_driver_call(driver, record)
            except BaseException as error:
                print('CONTROLLED_DRIVER_FAILURE ' + json.dumps({
                    'class': type(error).__name__, 'message': str(error)[:1000],
                    'traceback': traceback.format_exc(limit=32)[-18000:]}, default=str), flush=True)
                raise
        stack.enter_context(patch.object(research_local_driver._LocalDriver, '__call__', observed_driver_call))
        original_prep_allocate = PreparationProvider.allocate_bound
        async def observed_prep_allocate(provider, lease, *, before_effect):
            started = time.monotonic()
            def authority():
                try:
                    return before_effect()
                except BaseException as error:
                    print('CONTROLLED_PREP_AUTHORITY_FAILURE ' + json.dumps({
                        'elapsedSeconds': time.monotonic() - started,
                        'class': type(error).__name__, 'message': str(error)[:1000],
                        'createdAt': lease.get('createdAt'), 'deadlineAt': lease.get('deadlineAt')}, default=str), flush=True)
                    raise
            try:
                return await original_prep_allocate(provider, lease, before_effect=authority)
            finally:
                print('CONTROLLED_PREP_ALLOCATE_TIMING ' + json.dumps({
                    'elapsedSeconds': time.monotonic() - started,
                    'createdAt': lease.get('createdAt'), 'deadlineAt': lease.get('deadlineAt')}), flush=True)
        stack.enter_context(patch.object(PreparationProvider, 'allocate_bound', observed_prep_allocate))
        original_prep_call = PreparationDriver.__call__
        def observed_prep_call(driver, record):
            try:
                return original_prep_call(driver, record)
            except BaseException as error:
                print('CONTROLLED_PREP_DRIVER_FAILURE ' + json.dumps({
                    'class': type(error).__name__, 'message': str(error)[:1000],
                    'traceback': traceback.format_exc(limit=20)[-10000:]}, default=str), flush=True)
                raise
        stack.enter_context(patch.object(PreparationDriver, '__call__', observed_prep_call))
        original_allocate = ResearchLocalProvider.allocate_bound
        async def observed_allocate(provider, lease, *, before_effect):
            try:
                return await original_allocate(provider, lease, before_effect=before_effect)
            except BaseException as error:
                # Diagnostic observer only: execute the unchanged original method,
                # preserve its exception and let resource custody retain UNKNOWN.
                print('CONTROLLED_ALLOCATION_FAILURE ' + json.dumps({
                    'class': type(error).__name__, 'message': str(error)[:1000],
                    'traceback': traceback.format_exc(limit=16)[-12000:]}, default=str), flush=True)
                raise
        stack.enter_context(patch.object(ResearchLocalProvider, 'allocate_bound', observed_allocate))
        source_store = Store(database.url, Settings(db_url=database.url, workspace=root))
        self.addCleanup(source_store.engine.dispose)
        self.addCleanup(source_store.dispose_root_locks)
        prep_root = root / 'preparation'; prep_root.mkdir(mode=0o700)
        custody = root / 'prep-custody'; custody.mkdir(mode=0o700)
        driver = PreparationDriver(root=prep_root, root_identity=identity(prep_root), tokenizer_json=tokenizer(),
            reserve=lambda *a, **k: self.preparation.reserve(*a, **k), manifest_sha256='b'*64)
        executable = Path(sys.executable).resolve()
        spec = ProcessSpec(str(executable), hashlib.sha256(executable.read_bytes()).hexdigest(),
            ('-I', '-B', str(prep_root / 'prepare.py'), str(prep_root / 'run-config.json')))
        prep_provider = PreparationProvider(source_store, custody, spec, ProcessLimits(wall_seconds=5), driver=driver, preflight_seconds=15)
        # Assembler requires non-synthetic operator targets; this test's device
        # and source-generation seams remain explicitly labelled above/results.
        target = RemoteTarget('Controlled original preparation', 'compute', frozenset({'alice'}),
            provider=prep_provider, synthetic_fixture=False, max_cpu=1, max_memory_mb=128, max_disk_mb=4,
            max_seconds=20, capacity_pool=ComputePool('original-preparation', 1, 128, 4, 1, 1))
        evidence: dict[str, Any] = {}
        outer = self

        class Runtime:
            async def run(self):
                evidence['runtimeCalls'] = evidence.get('runtimeCalls', 0) + 1
                ctx = evidence['ctx']; service = outer.store.autoresearch
                task = outer.store.task(ctx.run_context.session_id, 'alice')
                ticket = outer.store.lifecycle_observer._binding(task)
                outer.assertEqual(ticket['status'], 'paused')
                outer.assertEqual(ticket['persistedRunStatus'], 'paused')
                evidence['parentTicket'] = ticket['id']
                await service.tool(ctx, 'research_context', {'_factoryCallId': 'fixed-context'})
                candidate = await service.tool(ctx, 'research_candidate', {'_factoryCallId': 'fixed-candidate',
                    'hypothesis': 'Controlled lifecycle only', 'trainPy': '# controlled changed source\n'})
                payload = {'_factoryCallId': 'fixed-experiment', 'candidateId': candidate['candidateId']}
                result = await service.tool(ctx, 'research_experiment', payload)
                # Reconstruct registries in this process from original durable
                # snapshots, not a process restart or permission to redispatch.
                journal = outer.children._read(ctx.run_context.run_id)
                def identities():
                    return {table: sorted(tuple(row[key] for key in keys)
                        for row in outer.store.sql('SELECT ' + ','.join(keys) + ' FROM ' + table))
                        for table, keys in (('af_tasks', ('id', 'run_id')),
                            ('af_process_allocations', ('id',)),
                            ('af_delegation_links', ('parent_id', 'request_id', 'child_id')))}
                before = identities()
                original_jobs = {phase: journal['phases'][phase]['receipt']['execution']['providerJobId']
                    for phase in ('training', 'evaluation')}
                resources = outer.state['resources']
                original_preparation_target = resources.targets['original-preparation']
                for phase in ('training', 'evaluation'):
                    ref = journal['phases'][phase]['config']['targetRef']
                    resources.targets.pop(ref)
                    outer.settings.remote_targets.pop(ref)
                outer.children.phase_config = make_assembler()
                outer.assertEqual(await outer.children.result_verifier(ctx, result), result)
                outer.assertEqual(identities(), before)
                outer.assertIs(resources.targets['original-preparation'], original_preparation_target)
                for phase in ('training', 'evaluation'):
                    entry = journal['phases'][phase]
                    lease = resources.inspect('alice', entry['receipt']['execution']['leaseId'])
                    outer.assertEqual(lease['providerJobId'], original_jobs[phase])
                    restored = resources.targets[entry['config']['targetRef']].provider
                    calls = []
                    with outer.assertRaisesRegex(ValueError, '^RESEARCH_RESTORED_DISPATCH_FORBIDDEN$'):
                        await restored.allocate_bound(lease, before_effect=lambda: calls.append(True))
                    outer.assertEqual(calls, [])
                outer.assertEqual(identities(), before)
                evidence['registryReconstructionVerified'] = True
                outer.assertEqual(await service.tool(ctx, 'research_experiment', payload), result)
                evidence['result'] = result
                await service.tool(ctx, 'research_result', {'_factoryCallId': 'fixed-result', 'candidateId': candidate['candidateId']})
                await service.tool(ctx, 'research_decision', {'_factoryCallId': 'fixed-decision',
                    'action': 'stop', 'reason': 'Synthetic lifecycle complete; no scientific conclusion'})
                return {'evidenceMode': 'controlled-fixture', 'modelExecuted': False}
            async def stop(self): return True
            async def cancel(self): return None

        def runtime_factory(ctx, _service):
            evidence['ctx'] = ctx
            return Runtime()
        async def experiment(ctx, candidate, call_id):
            try:
                return await self.children.experiment(ctx, candidate, call_id)
            except BaseException as error:
                evidence['failure'] = {'class': type(error).__name__, 'message': str(error)[:1000],
                    'custody': self.diagnostics()}
                print('CONTROLLED_SCIENTIFIC_FAILURE ' + json.dumps(evidence['failure'], default=str), flush=True)
                raise
        preset = ResearchPreset(id='three-phase-native-fixture', name='Three native phases fixture',
            owner_id='alice', default_goal='Verify original preparation and independent child custody',
            instructions='Controlled fixture decisions; not real science', manifest=example_manifest(),
            limits={'totalSeconds': 900, 'experimentSeconds': 600, 'maxExperiments': 1, 'toolCalls': 32, 'outputBytes': 65536},
            runtime_factory=runtime_factory, context_reader=lambda: {}, candidate_validator=lambda _: {'controlledFixture': True},
            experiment=experiment, review_owner='manager', external_session=True)
        self.settings = bootstrap.settings(db_url=database.url, workspace=root, preset=preset)
        prep_settings = process_runtime_profile.process_settings(db_url=database.url, workspace=root,
            target_ref='original-preparation', remote_targets={'original-preparation': target})
        self.settings.runtime_adapters.extend(prep_settings.runtime_adapters)
        self.settings.usage_pricing += prep_settings.usage_pricing
        self.settings.remote_targets = {'original-preparation': target}
        self.open_application()
        self.addCleanup(self.store.dispose_root_locks)
        self.auth = self.state['auth']
        self.auth.authorization.unassign('bob', 'factory-user'); self.auth.authorization.assign('bob', 'factory-manager')
        self.preparation = ResearchPreparationStore(self.store, self.auth, self.state['resources'], self.store.storage,
            preparation_manifest_sha256='b'*64, source_sha256=driver.configuration_fingerprint)
        self.application = process_runtime_profile.publish_process_application(self.state,
            target_ref='original-preparation', author='manager', reviewer='bob')
        providers = [prep_provider]
        def cleanup():
            for row in self.store.sql('SELECT id,owner_id FROM af_process_allocations'):
                for provider in providers:
                    path = provider.root / row['id'] / 'custody.sqlite'
                    if not path.exists(): continue
                    asyncio.run(provider.cancel(row['id'], row['owner_id']))
                    self.assertTrue(BoundedProcessAdapter(path).wait(owner_id=row['owner_id'])['stoppedProof'])
        self.addCleanup(cleanup)
        prep_task, _ = self.submit()
        def preparation_finished():
            task = self.store.task(prep_task['id'], 'alice')
            ticket = self.store.lifecycle_observer._binding(task)
            if ticket['status'] not in {'completed', 'failed', 'cancelled', 'canceled'}:
                return False
            if ticket['status'] != 'completed':
                diagnostic = self.diagnostics()
                original = self.store.process_runtime._original(prep_task['id'])
                if original is not None:
                    lease_id = original['lease_id']
                    try:
                        diagnostic['preparationCompletedOutput'] = prep_provider.read_completed_output(lease_id, 'alice').decode('utf-8', errors='replace')[:8000]
                    except Exception as error:
                        diagnostic['preparationCompletedOutputDenied'] = type(error).__name__
                    # Failed stdout is diagnostic only, never accepted artifact or
                    # success proof. Read only the original bounded fixture file.
                    output = prep_provider.root / lease_id / 'custody.output'
                    if output.exists():
                        fd = os.open(output, os.O_RDONLY | getattr(os, 'O_NOFOLLOW'))
                        try:
                            info = os.fstat(fd)
                            if stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size <= 65536:
                                diagnostic['preparationFailureOutput'] = os.read(fd, 8000).decode('utf-8', errors='replace')
                        finally:
                            os.close(fd)
                print('CONTROLLED_PREPARATION_FAILURE ' + json.dumps(diagnostic, default=str), flush=True)
                self.fail('Original preparation failed: ' + json.dumps(diagnostic, default=str))
            return True
        self.until(preparation_finished, timeout=30)
        original = self.store.process_runtime._original(prep_task['id'])
        prepared = self.preparation.import_completed('alice', original['lease_id'])
        token_pin = self.preparation.input_pin('alice', prep_task['id'], prepared['id'])
        manifest, inputs, environment = self.inputs(root, token_pin)
        gpu = GpuBinding('a'*64, 'b'*64)
        manifest['device']['identitySha256'] = gpu.identity_key
        limits = ResearchProcessLimits(cpu_seconds=5, address_space_mb=128, file_size_bytes=65536,
            disk_bytes=135168, output_bytes=4096, wall_seconds=manifest['protocol']['totalWallSeconds'])
        stages = {phase: self.stage(assembly, root, phase) for phase in ('training', 'evaluation')}
        checkpoints = ResearchCheckpointStore(self.store, self.auth, self.state['resources'], self.store.storage)
        def make_assembler():
            return assembly.ScientificPhaseAssembler(self.state, owner='alice', upstream_files={'train.py': b'original'},
            captured_inputs={'comparisonManifest': manifest, 'manifestSha256': manifest_fingerprint(manifest), 'operatorInputs': inputs},
            environment_pins=environment, stages=stages, limits=limits, gpu_binding=gpu,
            device_observer=MockDeviceObserver(), preparation=self.preparation, checkpoints=checkpoints,
            preparation_target_ref='original-preparation', preparation_reference={'taskId': prep_task['id'], 'artifactId': prepared['id']},
            microbatch=1)
        self.children = AutoResearchChildren(self.store, self.auth, self.store.autoresearch,
            phase_config=make_assembler(), preparation=self.preparation, checkpoints=checkpoints)
        self.store.autoresearch_children = self.children
        preset = replace(preset, manifest=manifest)
        preset = bootstrap.publish_application(self.state, preset, author='manager', reviewer='bob')
        self.settings.autoresearch_presets[preset.id] = preset; self.store.autoresearch.presets[preset.id] = preset
        self.login('alice')
        request_id = str(uuid4())
        result = self.post('/api/factory/autoresearch/runs', {'presetId': preset.id, 'requestId': request_id}, 202)
        def finished():
            row = self.store.autoresearch.row('alice', result['id'])['body']
            providers[:] = [t.provider for t in self.state['resources'].targets.values() if t.provider is not None]
            return row if row['status'] in {'completed', 'failed', 'unknown'} else None
        # Synthetic envelope covers the frozen 600-second protocol and custody
        # checks; production defaults and individual process limits are unchanged.
        body = self.until(finished, timeout=920)
        self.assertEqual(body['status'], 'completed', {'body': body, 'failure': evidence.get('failure'),
            'custody': self.diagnostics()})
        self.assertEqual(evidence['runtimeCalls'], 1)
        self.assertTrue(evidence['registryReconstructionVerified'])
        self.assertFalse(body['acceptance']['modelExecuted'])
        self.assertFalse(evidence['result']['scientificConclusionVerified'])
        parent = self.store.task(result['id'], 'alice')
        native = self.store.lifecycle_observer._binding(parent)
        self.assertEqual(native['status'], 'completed'); self.assertEqual(native['id'], evidence['parentTicket'])
        journal = self.children._read(parent['run_id'])
        self.assertEqual(journal['state'], 'DONE')
        links = self.store.sql('SELECT * FROM af_delegation_links WHERE parent_id=:parent', parent=parent['id'])
        self.assertEqual(len(links), 3)
        self.assertEqual(len(self.store.sql('SELECT id FROM af_tasks')), 5)  # original prep + parent + 3 children
        self.assertEqual(len(self.store.sql('SELECT id FROM af_process_allocations')), 3)  # original prep + train/evaluate
        for link in links:
            child = self.store.task(link['child_id'], 'alice')
            plan = self.store.plan(child['plan_id'], 'alice')
            self.assertEqual(plan['applicationRef'], preset.application_ref)
            self.assertEqual(plan['delegation'], {'parentTaskId': parent['id'], 'rootTaskId': parent['id'], 'depth': 1})
            self.assertEqual(self.store.lifecycle_observer._binding(child)['status'], 'completed')
        self.assertEqual(journal['phases']['preparation']['receipt']['execution']['taskId'], prep_task['id'])
        self.assertEqual(self.preparation.input_pin('alice', prep_task['id'], prepared['id']), token_pin)
        references = evidence['result']['originalReferences']
        self.assertNotEqual(references['training']['taskId'], references['evaluation']['taskId'])
        for phase in ('training', 'evaluation'):
            receipt = journal['phases'][phase]['receipt']['execution']
            lease = self.state['resources'].inspect('alice', receipt['leaseId'])
            self.assertEqual(lease['providerJobId'], receipt['providerJobId'])
            self.assertEqual(lease['state'], 'RECLAIMED'); self.assertFalse(lease['capacityHeld'])
            self.assertEqual(lease['gpuEvidence']['state'], 'RELEASED')
        repeat = self.post('/api/factory/autoresearch/runs', {'presetId': preset.id, 'requestId': request_id}, 202)
        self.assertEqual(repeat['id'], parent['id'])
        self.assertEqual(len(self.store.sql('SELECT id FROM af_tasks')), 5)

    def diagnostics(self):
        """Small synthetic failure evidence collected before isolated DB cleanup."""
        result: dict[str, Any] = {'tasks': [], 'phases': [], 'allocations': [], 'leases': []}
        for row in self.store.sql('SELECT id,owner_id,run_id,plan_id,terminal,cancel_requested FROM af_tasks'):
            task = self.store.task(row['id'], row['owner_id'])
            job = self.store.native_db.get_job(task['run_id'], strict=True) if task.get('run_id') else None
            entry = {**row, 'mode': self.store.plan(row['plan_id'], row['owner_id']).get('mode'),
                'job': {key: (job or {}).get(key) for key in ('status', 'attempt', 'max_attempts', 'error', 'error_message')}}
            try:
                native = self.store.lifecycle_observer._binding(task)
                entry['persistedRunStatus'] = (native or {}).get('persistedRunStatus')
            except Exception as error:
                entry['bindingError'] = type(error).__name__ + ':' + str(error)[:500]
            result['tasks'].append(entry)
        experiments = self.store.sql("SELECT to_regclass('af_autoresearch_experiments') AS table_name")[0]['table_name']
        for row in self.store.sql('SELECT body FROM af_autoresearch_experiments') if experiments else []:
            result['phases'].append({'state': row['body']['state'], 'phases': {
                key: {'state': phase['state'], 'child': phase.get('child'), 'hasReceipt': 'receipt' in phase,
                    'hasRuntimeSnapshot': 'runtimeSnapshot' in phase}
                for key, phase in row['body']['phases'].items()}})
        for row in self.store.sql('SELECT id,owner_id,body FROM af_process_allocations'):
            body = row['body']
            result['allocations'].append({'id': row['id'], 'ownerId': row['owner_id'],
                **{key: body.get(key) for key in ('state', 'released', 'cancelled', 'executionStatus',
                    'exitCode', 'preDispatchFailure', 'lastError', 'programVerification')},
                'processPin': {key: (body.get('processPin') or {}).get(key) for key in
                    ('id', 'specSha256', 'identitySha256')},
                'binding': {key: body.get('binding', {}).get(key) for key in
                    ('localTaskId', 'nativeRunId', 'planId', 'executionEffect')}})
        for row in self.store.sql('SELECT id,state,body FROM af_leases'):
            body = row['body']
            result['leases'].append({'id': row['id'], 'state': row['state'],
                **{key: body.get(key) for key in ('localTaskId', 'nativeRunId', 'providerJobId',
                    'capacityHeld', 'executionStatus', 'exitCode', 'preDispatchFailure', 'lastError',
                    'stopEvidence', 'gpuEvidence', 'createdAt', 'updatedAt', 'deadlineAt',
                    'cancellationReason', 'cancelRequested', 'cancelAck')}})
        return result

    def inputs(self, root, token_pin):
        folder = root / 'inputs'; folder.mkdir(mode=0o700)
        environment = []
        lock = b'controlled environment lock'
        patcher = patch.dict(SOURCE_SHA256, {'uv.lock': hashlib.sha256(lock).hexdigest()})
        patcher.start(); self.addCleanup(patcher.stop)
        manifest = example_manifest(); manifest['protocol']['seed'] = 42
        manifest['artifactLimits'].update(checkpointBytes=65536, logBytes=4096)
        for label, key, raw in (('environment-lockfile', 'lockfileSha256', lock),
                ('environment-inventory', 'installedInventory', b'controlled inventory'),
                ('environment-kernel', 'runtimeKernel', b'controlled kernel')):
            (folder / label).write_bytes(raw)
            environment.append(InputPin(label, 'environment', str(folder), RootIdentity(**identity(folder)), pin_bytes(label, raw)))
            manifest['environment'][key] = artifact(raw)['sha256'] if key == 'lockfileSha256' else artifact(raw)
        (folder / 'tokenizer.json').write_bytes(tokenizer())
        manifest['tokenizer'] = {'tokenizer': artifact(tokenizer()), 'tokenBytes': {k: token_pin[k] for k in ('sha256', 'sizeBytes')}}
        shards = []
        for name in ('train', 'validation'):
            raw = name.encode(); basename = name + '.bin'; (folder / basename).write_bytes(raw)
            shards.append({'id': name, 'basename': basename, **artifact(raw)})
        manifest['dataset']['shards'] = [{k: row[k] for k in ('id', 'sha256', 'sizeBytes')} for row in shards]
        manifest['dataset']['validationShardIds'] = ['validation']
        derived = research_local_driver.derive_local_identities({}, {}, microbatch=1)['identities']
        manifest['baselineSourceManifestSha256'] = derived['baseline']['sha256']
        for key, name in (('code', 'evaluatorCode'), ('configuration', 'evaluatorConfiguration')):
            manifest['evaluator'][key] = {k: derived[name][k] for k in ('sha256', 'sizeBytes')}
        config = {'inputRoot': str(folder), 'inputRootIdentity': identity(folder),
            'tokenizer': {'basename': 'tokenizer.json', **artifact(tokenizer())}, 'tokenBytes': token_pin,
            'dataset': {'shards': shards, 'validationShardIds': ['validation']}, 'outputCheckpoint': None}
        return manifest, config, tuple(environment)

    def stage(self, assembly, root, phase):
        area = root / ('uv-' + phase); area.mkdir(mode=0o700)
        scratch = area / 'scratch'; scratch.mkdir(mode=0o700)
        program = root / ('program-' + phase); program.mkdir(mode=0o700)
        cache = root / ('cache-' + phase); cache.mkdir(mode=0o700)
        custody = root / ('custody-' + phase); custody.mkdir(mode=0o700)
        environment = tuple((key, '1') for key in ('HF_HUB_OFFLINE', 'HF_DATASETS_OFFLINE', 'TRANSFORMERS_OFFLINE', 'PYTHONNOUSERSITE'))
        spec, _, _ = synthetic_uv_launch(area, scratch, '# unused fixture entry\n', environment)
        environment = (*environment, ('PYTHONPYCACHEPREFIX', str(program)),
            *((key, str(cache)) for key in ('HOME', 'TORCHINDUCTOR_CACHE_DIR', 'TRITON_CACHE_DIR', 'CUDA_CACHE_PATH', 'TMPDIR')))
        entry = 'evaluate.py' if phase == 'evaluation' else 'train_candidate.py'
        pin = RootIdentity(**identity(program))
        spec = replace(spec, argv=('-B', str(program / entry), '--config', str(program / 'run-config.json')),
            working_directory=str(program), working_directory_identity=(pin.device, pin.inode), environment=environment)
        return assembly.ScientificStage(spec, pin, cache, RootIdentity(**identity(cache)), custody)
