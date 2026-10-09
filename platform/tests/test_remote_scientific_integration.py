# pyright: reportMissingImports=false
"""Three real PostgreSQL/native apps, controlled ASGI transport and stdlib science.

Original preparation stays in a separate baseline DB/root; the receiver control
plane has no allocatable original-preparation target.

Explicit seams: fixed synthetic ORX decisions; self-authored stdlib generated
programs; synthetic uv.lock identity; fixture environment/device observations.
Original preparation/process/checkpoint/evaluation, native delegation, handoff,
receiver scope, evidence validators, approvals and usage/debit journals are real.
No GPU, upstream training, live model, TLS or scientific acceptance is claimed.
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
import tempfile
import traceback
from types import SimpleNamespace
from typing import Any
import unittest
from unittest.mock import patch
from uuid import uuid4

import httpx
from fastapi.testclient import TestClient

from agent_factory.autoresearch import ResearchPreset
from agent_factory.autoresearch_remote_children import AutoResearchRemoteChildren
from agent_factory.config import Settings
from agent_factory.gpu_custody import GpuBinding
from agent_factory.main import create_app
from agent_factory.process_enforcement import BoundedProcessAdapter, ProcessLimits, ProcessSpec, ResearchProcessLimits
from agent_factory import process_runtime_profile
from agent_factory.research_checkpoint_store import ResearchCheckpointStore
from agent_factory.research_local_driver import derive_local_identities
from agent_factory import research_local_driver
from agent_factory.research_manifest import manifest_fingerprint
from agent_factory.research_preparation_driver import PreparationDriver
from agent_factory.research_preparation_provider import PreparationProvider
from agent_factory.research_preparation_store import ResearchPreparationStore
from agent_factory.remote_handoff import HandoffTarget, TrustedOrigin, PreparedHandoffService
from agent_factory.remote_authority import AuthorityScientificCustody, ScientificCustodyReply
from agent_factory.remote_scientific_origin import RemoteScientificOrigin
from agent_factory.remote_scientific_receiver import RemoteScientificProject, RemoteScientificReceiver
from agent_factory.resources import ComputePool, RemoteTarget
from agent_factory.store import Store
from pg_fixture import IsolatedPostgres
import test_autoresearch_scientific_children_postgres as local
import test_autoresearch_operator_bindings as operator_fixture
import test_process_runtime_postgres as process_fixture


class Actor(unittest.TestCase):
    """Reuse request helpers only; importing this class adds no test cases."""
    settings: Any
    state: Any
    store: Any
    auth: Any
    client: Any
    application: Any
    request = process_fixture.ProcessRuntimePostgresTests.request
    submit = process_fixture.ProcessRuntimePostgresTests.submit
    until = process_fixture.ProcessRuntimePostgresTests.until
    inputs = local.ScientificChildrenPostgresTests.inputs
    stage = local.ScientificChildrenPostgresTests.stage


class ReviewedTransport(httpx.AsyncBaseTransport):
    """Real receiver preparation then explicit independent manager approval.

    Repeats the same prepared request only after review; normal responses are
    never mocked. Optional lost drive ACK is injected after its real acceptance.
    """
    def __init__(self, app, state):
        self.inner = httpx.ASGITransport(app=app); self.state = state
        self.reviews = []; self.lose_drive = False; self.lost = False; self.errors = []; self.drive_posts = []
    async def handle_async_request(self, request):
        try:
            return await self._request(request)
        except BaseException:
            self.errors.append(traceback.format_exc(limit=-30)[-16000:])
            self.errors[:] = self.errors[-3:]
            raise
    async def _request(self, request):
        if request.method == 'POST' and request.url.path.endswith('/scientific-drive'):
            self.drive_posts.append(request.url.path)
        response = await self.inner.handle_async_request(request)
        await response.aread()
        if request.method == 'POST' and request.url.path.endswith('/prepare') and response.status_code < 300:
            body = response.json()
            if body.get('receiverReviewRequired'):
                policy = self.state['plan_policy']
                review = policy.request_review('alice', body['remotePlanId'], 'review:' + body['id'])
                policy.decide('manager', review['id'], True, 'approve:' + body['id'])
                self.reviews.append(review['id'])
                response = await self.inner.handle_async_request(request)
                await response.aread()
        if self.lose_drive and not self.lost and request.method == 'POST' and request.url.path.endswith('/scientific-drive') and response.status_code < 300:
            self.lost = True
            raise httpx.ReadTimeout('Controlled accepted-drive acknowledgment loss', request=request)
        # Inspection above consumes the ASGI response. The real handoff client
        # deliberately uses aiter_raw(), so return an unconsumed byte stream.
        return httpx.Response(response.status_code, headers=response.headers,
            stream=httpx.ByteStream(response.content), request=request,
            extensions=response.extensions)


@unittest.skipUnless(sys.platform == 'linux' and os.getenv('FACTORY_TEST_DATABASE_URL'),
                     'Requires isolated PostgreSQL and Linux stdlib guardian')
class RemoteScientificIntegrationTests(unittest.TestCase):
    def _app(self, settings, stack):
        app = create_app(settings); state = app.app.state.factory
        stack.callback(state['store'].engine.dispose)
        stack.callback(state['store'].native_db.db_engine.dispose)
        stack.callback(state['store'].dispose_root_locks)
        client = stack.enter_context(TestClient(app))
        state['auth'].authorization.unassign('bob', 'factory-user')
        state['auth'].authorization.assign('bob', 'factory-manager')
        actor = Actor(); actor.settings, actor.state, actor.store = settings, state, state['store']
        actor.auth, actor.client = state['auth'], client
        stack.callback(actor.doCleanups)
        return app, state, actor

    def test_three_remote_native_phases_original_receipts_and_shared_budget(self):
        with ExitStack() as stack:
            origin_db = stack.enter_context(IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']))
            receiver_db = stack.enter_context(IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']))
            baseline_db = stack.enter_context(IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']))
            root = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix='remote-science-')))
            receiver_root = root / 'receiver'; receiver_root.mkdir(mode=0o700)
            origin_root = root / 'origin'; origin_root.mkdir(mode=0o700)
            baseline_root = root / 'baseline'; baseline_root.mkdir(mode=0o700)
            assembly = importlib.import_module('autoresearch_scientific_assembly')
            operator = importlib.import_module('autoresearch_operator_bindings')
            bundle = local.generated_bundle()
            stack.enter_context(patch.object(research_local_driver, 'build_training_bundle', return_value=bundle))
            stack.enter_context(patch.object(assembly, 'build_training_bundle', return_value=bundle))
            stack.enter_context(patch.object(assembly, 'ResearchEnvironmentObserver', side_effect=lambda *a, **k: local.FixtureObserver()))
            source_store = Store(baseline_db.url, Settings(db_url=baseline_db.url, workspace=baseline_root))
            stack.callback(source_store.engine.dispose); stack.callback(source_store.dispose_root_locks)
            program = baseline_root / 'original-preparation'; program.mkdir(mode=0o700)
            custody = baseline_root / 'original-preparation-custody'; custody.mkdir(mode=0o700)
            holder = {}
            driver = PreparationDriver(root=program, root_identity=local.identity(program), tokenizer_json=local.tokenizer(),
                manifest_sha256='b'*64, reserve=lambda *a, **k: holder['preparation'].reserve(*a, **k))
            binary = Path(sys.executable).resolve()
            spec = ProcessSpec(str(binary), hashlib.sha256(binary.read_bytes()).hexdigest(),
                ('-I', '-B', str(program/'prepare.py'), str(program/'run-config.json')))
            provider = PreparationProvider(source_store, custody, spec, ProcessLimits(wall_seconds=5),
                driver=driver, preflight_seconds=15)
            target = RemoteTarget('Original synthetic tokenizer producer', 'compute', frozenset({'alice'}),
                provider=provider, synthetic_fixture=False, max_cpu=1, max_memory_mb=128, max_disk_mb=4,
                max_seconds=20, capacity_pool=ComputePool('original-preparation', 1, 128, 4, 1, 1))
            receiver_config = operator_fixture.config('receiver'); receiver_config['workspace'] = str(receiver_root)
            receiver_config['publication'] = {'author': 'manager', 'reviewer': 'bob'}
            receiver_settings = operator.describe_settings(receiver_config, receiver_db.url)
            # Controlled accounting compatibility; no real model/service calls.
            receiver_settings.fee_management_enabled = receiver_settings.platform_paid_models_enabled = True
            prep_settings = process_runtime_profile.process_settings(db_url=baseline_db.url, workspace=baseline_root,
                target_ref='original-preparation', remote_targets={'original-preparation': target})
            _, baseline, producer = self._app(prep_settings, stack)
            preparation = ResearchPreparationStore(baseline['store'], baseline['auth'], baseline['resources'], baseline['store'].storage,
                preparation_manifest_sha256='b'*64, source_sha256=driver.configuration_fingerprint)
            holder['preparation'] = preparation
            producer.application = process_runtime_profile.publish_process_application(baseline,
                target_ref='original-preparation', author='manager', reviewer='bob')
            original_task, _ = producer.submit()
            producer.until(lambda: baseline['store'].lifecycle_observer._binding(
                baseline['store'].task(original_task['id'], 'alice'))['status'] == 'completed', timeout=40)
            original = baseline['store'].process_runtime._original(original_task['id'])
            artifact = preparation.import_completed('alice', original['lease_id'])
            token = preparation.input_pin('alice', original_task['id'], artifact['id'])
            remote_app, remote, receiver = self._app(receiver_settings, stack)
            self.assertNotIn('original-preparation', remote['resources'].targets)
            self.assertNotIn('original-preparation', receiver_settings.remote_targets)
            manifest, inputs, environment = receiver.inputs(receiver_root, token)
            gpu = GpuBinding('a'*64, 'b'*64); manifest['device']['identitySha256'] = gpu.identity_key
            stages = {phase: receiver.stage(assembly, receiver_root, phase) for phase in ('training','evaluation')}
            limits = ResearchProcessLimits(cpu_seconds=5, address_space_mb=128, file_size_bytes=65536,
                disk_bytes=135168, output_bytes=4096, wall_seconds=manifest['protocol']['totalWallSeconds'])
            checkpoints = ResearchCheckpointStore(remote['store'], remote['auth'], remote['resources'], remote['store'].storage)
            def fresh_assembler():
                return assembly.ScientificPhaseAssembler(remote, owner='alice', upstream_files={'train.py': b'original'},
                captured_inputs={'comparisonManifest': manifest, 'manifestSha256': manifest_fingerprint(manifest), 'operatorInputs': inputs},
                environment_pins=environment, stages=stages, limits=limits, gpu_binding=gpu,
                device_observer=local.MockDeviceObserver(), preparation=preparation, checkpoints=checkpoints,
                preparation_state=baseline, preparation_target_ref='original-preparation', preparation_reference={'taskId': original_task['id'], 'artifactId': artifact['id']}, microbatch=1)
            assembler = fresh_assembler()
            receiver_config['project']['manifest'] = manifest
            publication = operator.prepare_publication(SimpleNamespace(operator_config=receiver_config,
                state=SimpleNamespace(factory=remote)), receiver_config['publication'])
            evidence = {}; origin_config = operator_fixture.config('controller')
            origin_config.update(workspace=str(origin_root), publication={'author':'manager','reviewer':'bob'})
            origin_config['project']['manifest'] = manifest
            origin_config['project']['applicationSnapshot'] = publication['applicationSnapshot']
            transport = ReviewedTransport(remote_app, remote)
            transport.lose_drive = True
            handoff_target = HandoffTarget('receiver', 'origin', 'http://receiver.fixture', {'alice':'alice'},
                lambda owner: {'Authorization': 'Bearer ' + remote['auth']._issue_native_token(owner)},
                transport=transport, configuration_revision='reviewed-v1')
            outer = self
            class Runtime:
                async def run(self):
                    try:
                        return await self._run()
                    except BaseException:
                        evidence['runtimeTraceback'] = traceback.format_exc(limit=-30)[-16000:]
                        raise
                async def _run(self):
                    ctx, service = evidence['ctx'], evidence['service']
                    await service.tool(ctx, 'research_context', {'_factoryCallId':'context'})
                    candidate = await service.tool(ctx, 'research_candidate', {'_factoryCallId':'candidate',
                        'hypothesis':'Synthetic remote lifecycle only', 'trainPy':'# controlled changed source\n'})
                    payload = {'_factoryCallId':'experiment','candidateId':candidate['candidateId']}
                    result = await service.tool(ctx, 'research_experiment', payload)
                    outer.assertEqual(await service.tool(ctx, 'research_experiment', payload), result)
                    evidence['result'] = result
                    assessed = await service.tool(ctx, 'research_result',
                        {'_factoryCallId': 'result', 'candidateId': candidate['candidateId']})
                    outer.assertEqual(assessed, result)
                    await service.tool(ctx, 'research_decision', {'_factoryCallId':'decision','action':'stop',
                        'reason':'Controlled lifecycle only, no scientific acceptance'})
                    return {'modelExecuted':False, 'evidenceMode':'controlled-fixture'}
                async def stop(self): return True
                async def cancel(self): return None
            def runtime(ctx, service):
                evidence.update(ctx=ctx, service=service); return Runtime()
            async def experiment(ctx, candidate, call_id):
                return await holder['children'].experiment(ctx, candidate, call_id)
            project_id = origin_config['project']['id']
            preset = ResearchPreset(project_id, 'Controlled remote science', 'Verify original remote scientific phases',
                'alice', 'Read reviewed context', manifest, origin_config['project']['limits'],
                runtime_factory=runtime, context_reader=lambda: {}, candidate_validator=lambda _: {'controlledFixture':True},
                experiment=experiment, external_session=True, review_owner='manager')
            origin_settings = operator.describe_settings(origin_config, origin_db.url)
            origin_settings.fee_management_enabled = origin_settings.platform_paid_models_enabled = True
            origin_settings.autoresearch_presets = {project_id:preset}
            origin_settings.handoff_targets = {'receiver':handoff_target}
            variant = derive_local_identities({}, {}, microbatch=1)['identities']['candidate']['sha256']
            def origin_factory(store, auth, resources, client, receiver, commands):
                return RemoteScientificOrigin(store, auth, handoff_client=client,
                    project_validator=lambda *args: variant)
            def children_factory(store, auth, service, resources):
                result = AutoResearchRemoteChildren(store, auth, service, target_ref='receiver',
                    project_id=project_id, project_pin='b'*64, manifest=manifest)
                holder['children'] = result; return result
            origin_settings.remote_scientific_factory = origin_factory
            origin_settings.autoresearch_children_factory = children_factory
            origin_app, origin, actor = self._app(origin_settings, stack)
            origin_ref = operator.prepare_publication(SimpleNamespace(operator_config=origin_config,
                state=SimpleNamespace(factory=origin)), origin_config['publication'])
            self.assertEqual(origin_ref['applicationRef'], publication['applicationRef'],
                'Independently approved imported catalogue preserves the exact source identity')
            self.assertEqual(origin_ref['applicationSnapshot'], publication['applicationSnapshot'])
            # Same-process trusted authority callbacks stand in only for network;
            # original handoff checks and shared scientific debit remain real.
            client = origin['handoff_client']
            class Authority:
                def __call__(self, *args): return client.authority_callback(*args)
                def check_scientific_custody(self, owner, task_id, manifest_hash, *,
                                             receiver_task_id, native_run_id, phase_scope_sha256, lease_id):
                    request = AuthorityScientificCustody.model_validate({'schema': 1,
                        'originRef': 'origin', 'targetRef': 'receiver', 'originOwner': owner,
                        'originTaskId': task_id, 'manifestSha256': manifest_hash, 'tool': None,
                        'receiverIdentity': 'alice', 'targetRevision': handoff_target.configuration_revision,
                        'targetFingerprint': handoff_target.fingerprint, 'receiverTaskId': receiver_task_id,
                        'nativeRunId': native_run_id, 'phaseScopeSha256': phase_scope_sha256, 'leaseId': lease_id})
                    proof = origin['store'].remote_scientific.authorize_completed_custody(request.model_dump())
                    return ScientificCustodyReply(**request.model_dump(), outcome='custody-readable', **proof).model_dump()
                def consume_scientific_tool(self, owner, task_id, manifest_hash, tool, **kw):
                    return origin['store'].remote_scientific.consume_remote_tool({'schema':1,
                        'originRef':'origin','targetRef':'receiver','originOwner':owner,'originTaskId':task_id,
                        'manifestSha256':manifest_hash,'tool':tool,'receiverIdentity':'alice',
                        'targetRevision':handoff_target.configuration_revision,'targetFingerprint':handoff_target.fingerprint,
                        'callId':kw['call_id'],'receiverTaskId':kw['receiver_task_id'],'nativeRunId':kw['native_run_id'],
                        'phaseScopeSha256':kw['phase_scope_sha256']})
            trusted = TrustedOrigin('origin', {'alice':'alice'}, Authority(),
                tools=frozenset({'research_preparation_verify','research_process_run'}),
                capabilities=frozenset({'research:read','compute:local'}),
                budget={'toolCalls':32,'maxDepth':1,'maxChildren':3,'experimentSeconds':600,'outputBytes':65536},
                configuration_revision='reviewed-v1',tool_contract='autoresearch-session-v1')
            remote_receiver = PreparedHandoffService(remote['store'], remote['auth'], remote['bridge'], {'origin':trusted})
            remote_receiver.install_guard(); remote['store'].handoff_receiver = remote_receiver
            remote_app.app.include_router(remote_receiver.router)
            project = RemoteScientificProject('alice','b'*64,assembler,preparation,checkpoints,manifest,
                lambda: (_ for _ in ()).throw(AssertionError('baseline not called by fixture')))
            service = RemoteScientificReceiver(remote['store'],remote['auth'],{project_id:project},remote['store'].autoresearch.commands)
            self.assertIs(remote['store'].remote_scientific_receiver,service)
            original_drive_phase = service.drive_phase
            async def observed_drive_phase(*args, **kwargs):
                try:
                    return await original_drive_phase(*args, **kwargs)
                except BaseException:
                    evidence.setdefault('receiverDriveTracebacks', []).append(
                        traceback.format_exc(limit=-30)[-16000:])
                    evidence['receiverDriveTracebacks'][:] = evidence['receiverDriveTracebacks'][-3:]
                    raise
            stack.enter_context(patch.object(service, 'drive_phase', side_effect=observed_drive_phase))
            def stop_original_processes():
                for row in remote['store'].sql('SELECT id,owner_id FROM af_process_allocations'):
                    for registered in remote['resources'].targets.values():
                        owned = registered.provider
                        if owned is None or not hasattr(owned, 'root'): continue
                        journal = owned.root / row['id'] / 'custody.sqlite'
                        if not journal.exists(): continue
                        asyncio.run(owned.cancel(row['id'], row['owner_id']))
                        self.assertTrue(BoundedProcessAdapter(journal).wait(owner_id=row['owner_id'])['stoppedProof'])
            stack.callback(stop_original_processes)
            request_id = str(uuid4())
            parent = actor.request('POST','/autoresearch/runs',{'presetId':project_id,'requestId':request_id})
            def terminal_or_receiver_failure():
                row = origin['store'].autoresearch.row('alice', parent['id'])['body']
                failed = remote['store'].sql("SELECT receipt_id,phase FROM af_remote_scientific_phases "
                    "WHERE body->'driveRequest'->>'status'='UNKNOWN' LIMIT 1")
                if failed:
                    evidence['receiverDriveUnknown'] = failed[0]
                    return row
                return row if row['status'] in {'completed', 'failed', 'unknown'} else None
            final = actor.until(terminal_or_receiver_failure, timeout=920)
            if final['status'] != 'completed' or evidence.get('receiverDriveUnknown'):

                diagnostics = {'runtimeTraceback': evidence.get('runtimeTraceback'),
                    'transportTracebacks': transport.errors,
                    'receiverDriveTracebacks': evidence.get('receiverDriveTracebacks', []),
                    'receiverDriveUnknown': evidence.get('receiverDriveUnknown'), 'actualParentStatus': final['status']}
                for side, state in (('origin', origin), ('receiver', remote), ('baseline', baseline)):
                    for table in ('af_events', 'af_tasks', 'af_delegation_links',
                                  'af_remote_scientific_origins', 'af_remote_scientific_phases',
                                  'af_remote_scientific_drive_intents', 'af_leases'):
                        if not state['store'].sql('SELECT to_regclass(:name) AS present', name=table)[0]['present']:
                            continue
                        rows = state['store'].sql('SELECT * FROM ' + table + ' LIMIT 12')
                        diagnostics[side + ':' + table] = json.dumps(rows, default=str)[:12000]
                print('CONTROLLED_REMOTE_DIAGNOSTICS ' + json.dumps(diagnostics, default=str), flush=True)
            self.assertFalse(evidence.get('receiverDriveUnknown'),
                'Original receiver drive became UNKNOWN; parent status was ' + final['status'])
            self.assertEqual(final['status'],'completed',final)
            self.assertFalse(final['acceptance']['modelExecuted']); self.assertFalse(evidence['result']['scientificConclusionVerified'])
            self.assertTrue(final['acceptance']['independentResult'])
            self.assertTrue(final['acceptance']['nextDecision'])
            self.assertEqual(len(transport.reviews),3)
            self.assertEqual(len(origin['store'].sql('SELECT * FROM af_delegation_links')),3)
            self.assertEqual(len(origin['store'].sql('SELECT * FROM af_remote_scientific_calls')),3)
            self.assertEqual(len(remote['store'].sql('SELECT * FROM af_remote_scientific_phases')),3)
            self.assertEqual(len(remote['store'].sql('SELECT * FROM af_process_allocations')),2)
            self.assertEqual(len(baseline['store'].sql('SELECT * FROM af_process_allocations')),1)
            self.assertEqual(preparation.input_pin('alice', original_task['id'], artifact['id']), token)
            self.assertEqual(baseline['store'].process_runtime._original(original_task['id']), original)
            for row in origin['store'].sql('SELECT id,run_id FROM af_tasks WHERE id<>:parent',parent=parent['id']):
                self.assertIsNone(row['run_id'], 'Origin projections must never fabricate native tickets')
            replay = actor.request('POST','/autoresearch/runs',{'presetId':project_id,'requestId':request_id})
            self.assertEqual(replay['id'],parent['id'])
            foreign = actor.client.get('/api/factory/autoresearch/runs/'+parent['id'],
                headers={'Authorization':'Bearer '+origin['auth']._issue_native_token('bob')})
            self.assertEqual(foreign.status_code,404)

            self.assertTrue(transport.lost, 'A real accepted drive response must be dropped once')
            self.assertEqual(len(transport.drive_posts), 3)
            self.assertNotIn('original-preparation', remote['resources'].targets)
            self.assertEqual(len(set(transport.drive_posts)), 3, 'No original drive POST may be replayed')
            # Reconstruct the service/assembler over the same durable receiver DB.
            # This is custody reconstruction, not a whole-process restart claim.
            links = origin['store'].sql('SELECT child_id FROM af_delegation_links ORDER BY child_id')
            allocations = remote['store'].sql('SELECT id,owner_id FROM af_process_allocations ORDER BY id')
            debits = origin['store'].sql('SELECT * FROM af_remote_scientific_calls ORDER BY child_id')
            async def original_custody():
                return [await origin['store'].remote_scientific.origin_phase('alice', row['child_id']) for row in links]
            before = actor.client.portal.call(original_custody)
            actor.client.portal.call(service.close)
            reconstructed = RemoteScientificReceiver(remote['store'], remote['auth'],
                {project_id: replace(project, assembler=fresh_assembler())}, remote['store'].autoresearch.commands)
            after = actor.client.portal.call(original_custody)
            for old, current in zip(before, after, strict=True):
                self.assertEqual(current['scope'], old['scope'])
                self.assertEqual(current['receipt']['scientificEvidence'], old['receipt']['scientificEvidence'])
                self.assertTrue(current['allStopped'])
                for key in ('id', 'remoteTaskId', 'remotePlanId', 'remoteRunId'):
                    self.assertEqual(current['receipt'][key], old['receipt'][key])
            # Completed-original cleanup only; no claim of in-flight cancellation.
            async def completed_cleanup():
                for row in links:
                    await origin['store'].remote_scientific.cancel_original('alice', row['child_id'])
                    observed = await origin['store'].remote_scientific.cleanup_phase('alice', row['child_id'])
                    self.assertTrue(observed['allStopped'])
                await reconstructed.close()
            actor.client.portal.call(completed_cleanup)
            self.assertEqual(remote['store'].sql('SELECT id,owner_id FROM af_process_allocations ORDER BY id'), allocations)
            self.assertEqual(origin['store'].sql('SELECT * FROM af_remote_scientific_calls ORDER BY child_id'), debits)
            self.assertEqual(len(transport.drive_posts), 3)
            self.assertNotIn('original-preparation', remote['resources'].targets)
