# pyright: reportMissingImports=false
"""Real native pause/continuation; inert controlled driver, never GPU execution proof."""
import asyncio
import hashlib
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient

from agent_factory.config import Settings
from agent_factory.catalog import create_plan
from agent_factory.gpu_custody import GpuBinding
from agent_factory.main import create_app
from agent_factory.research_runtime import ResearchProcessRuntimeService
from agent_factory.research_runtime_profile import research_settings, publish_research_application
from agent_factory.resources import ComputePool, RemoteTarget
from agent_factory.store import Store
from pg_fixture import IsolatedPostgres
from research_driver_fixture import ControlledResearchDriver
from test_research_manifest import example_manifest


@unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires isolated native PostgreSQL')
class ResearchRuntimePostgresTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        database = self.stack.enter_context(IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']))
        root = Path(self.stack.enter_context(tempfile.TemporaryDirectory(prefix='research-runtime-')))
        bootstrap = Store(database.url, Settings(db_url=database.url, workspace=root))
        self.stack.callback(bootstrap.engine.dispose)
        self.gpu = GpuBinding('a' * 64, 'b' * 64)
        self.manifest = example_manifest()
        self.manifest['device']['identitySha256'] = self.gpu.identity_key
        limits = SimpleNamespace(wall_seconds=self.manifest['protocol']['totalWallSeconds'],
            address_space_mb=128, file_size_bytes=65536)
        self.driver = ControlledResearchDriver(bootstrap, self.gpu, limits)
        self.alias_driver = ControlledResearchDriver(bootstrap, self.gpu, limits, namespace='8' * 64)
        targets = {}
        for ref, provider in (('research-main', self.driver), ('research-alias', self.alias_driver)):
            targets[ref] = RemoteTarget('Controlled synthetic research driver', 'compute', frozenset({'alice', 'bob'}),
                provider=provider, synthetic_fixture=True, max_cpu=1, max_memory_mb=128, max_disk_mb=1,
                max_seconds=600, gpu_binding=self.gpu,
                capacity_pool=ComputePool(ref + '-pool', 1, 128, 1, max_leases=1, max_owner_leases=1))
        settings = research_settings(db_url=database.url, workspace=root, target_ref='research-main',
            remote_targets=targets, comparison_manifest=self.manifest)
        self.app = create_app(settings)
        self.state = self.app.app.state.factory
        self.store, self.auth = self.state['store'], self.state['auth']
        self.runtime = self.store.research_runtime
        self.requirements = {}
        self.stack.callback(self.store.engine.dispose)
        self.stack.callback(self.store.native_db.db_engine.dispose)
        self.auth.authorization.unassign('bob', 'factory-user')
        self.auth.authorization.assign('bob', 'factory-manager')
        self.application = publish_research_application(self.state, target_ref='research-main',
            comparison_manifest=self.manifest, author='manager', reviewer='bob')
        self.client = self.stack.enter_context(TestClient(self.app))  # pyright: ignore[reportArgumentType]
        assert self.client.portal is not None
        self.portal = self.client.portal
        self.stack.callback(self.cleanup)

    def cleanup(self):
        self.driver.unknown_stop = False
        self.driver.lose_release_ack = False
        for row in self.store.sql('SELECT id,owner_id FROM af_process_allocations'):
            asyncio.run(self.driver.cancel(row['id'], row['owner_id']))
            asyncio.run(self.driver.reclaim(row['id'], row['owner_id']))
        for row in self.store.sql('SELECT id,owner_id FROM af_tasks WHERE NOT terminal'):
            self.request('POST', '/jobs/' + row['id'] + '/cancel', {}, owner=row['owner_id'], allowed={200, 409})

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

    def test_paused_repeat_concurrent_submit_restarts_and_continues_same_native_run(self):
        task, detail = self.task()
        native = self.store.task(task['id'])['run_id']
        self.approve(task['id'], detail, allowed={409})
        async def concurrent():
            return await asyncio.gather(self.runtime.submit('alice', task['id']),
                self.runtime.submit('alice', task['id']), return_exceptions=True)
        results = self.portal.call(concurrent)
        leases = [result for result in results if isinstance(result, dict)]
        self.assertTrue(leases)
        self.assertTrue(all(isinstance(result, dict) or isinstance(result, HTTPException) and result.status_code == 409
            for result in results))
        lease = self.portal.call(self.runtime.submit, 'alice', task['id'])
        self.assertEqual({item['id'] for item in leases}, {lease['id']})
        self.assertEqual(self.driver.launches, 1)
        # A 61-second-old custody record with a future 600-second deadline still
        # belongs to the same paused native run; no wall-clock sleep or timeout widening.
        now = datetime.now(timezone.utc)
        self.runtime.resources._update('alice', lease['id'], lease['state'],
            {'createdAt': (now - timedelta(seconds=61)).isoformat(), 'deadlineAt': (now + timedelta(seconds=539)).isoformat()})
        self.store.sql('UPDATE ai.agno_jobs SET created_at=:created WHERE id=:id',
            created=int(time.time()) - 61, id=native)
        self.portal.call(self.store.lifecycle_observer.tick)
        self.assertLessEqual(self.store.native_db.get_job(native)['created_at'], int(time.time()) - 60)
        self.assertFalse(self.store.task(task['id'])['cancel_requested'])
        restarted = ResearchProcessRuntimeService(self.store, self.auth, self.runtime.resources)
        self.assertEqual(self.portal.call(restarted.submit, 'alice', task['id'])['id'], lease['id'])
        self.assertEqual(self.store.native_db.get_job(native)['status'], 'paused')
        self.driver.complete(lease['id'], 'alice', b'Synthetic process output, not a validation metric')
        self.driver.lose_release_ack = True
        settled = self.portal.call(restarted.inspect_task, 'alice', task['id'])
        self.assertEqual(settled['state'], 'RECLAIMED')
        self.assertEqual(settled['gpuEvidence']['state'], 'RELEASED')
        pin = self.requirements[task['id']]
        command = {'commandId': str(uuid4()), 'requirementId': pin['id'], 'version': pin['version'], 'approved': True}
        continuation = self.state['bridge'].continue_run
        async def lost_ack(*args, **kwargs):
            await continuation(*args, **kwargs)
            raise HTTPException(503, 'Synthetic committed native continuation acknowledgement loss')
        with patch.object(self.state['bridge'], 'continue_run', side_effect=lost_ack) as dispatch:
            response = self.request('POST', '/jobs/' + task['id'] + '/approve', command, allowed={200})
            self.assertTrue(response['commandReceipt']['decisionRecorded'])
            self.request('POST', '/jobs/' + task['id'] + '/approve', command, allowed={200})
            self.assertEqual(dispatch.await_count, 1)
        self.until(lambda: self.store.native_db.get_job(native), lambda value: value['status'] == 'completed')
        self.assertEqual(self.store.task(task['id'])['run_id'], native)
        self.assertEqual(self.driver.launches, 1)
        self.assertEqual(len(self.store.sql('SELECT * FROM af_process_runs')), 1)
        self.assertEqual(len(self.store.sql('SELECT * FROM ai.agno_jobs WHERE session_id=:id', id=task['id'])), 1)
        checkpoint_bytes = b'Synthetic original checkpoint bytes only'
        checkpoint = self.store.artifact_write(native, 'checkpoint.bin', checkpoint_bytes,
            media_type='application/octet-stream', metadata={'nativeRunId': native, 'leaseId': lease['id'],
                'variantSha256': self.manifest['baselineSourceManifestSha256'], 'syntheticFixture': True})
        body, identity = self.store.artifact_identity(task['id'], checkpoint['id'],
            self.manifest['artifactLimits']['checkpointBytes'])
        self.assertEqual(body['id'], checkpoint['id'])
        self.assertEqual(identity, {'sha256': hashlib.sha256(checkpoint_bytes).hexdigest(), 'sizeBytes': len(checkpoint_bytes)})
        self.store.sql('UPDATE af_artifacts SET content=:raw WHERE id=:id',
            raw=b'X' * len(checkpoint_bytes), id=checkpoint['id'])
        with self.assertRaises(HTTPException) as corrupt:
            self.store.artifact_identity(task['id'], checkpoint['id'], self.manifest['artifactLimits']['checkpointBytes'])
        self.assertEqual(corrupt.exception.status_code, 409)

    def test_disconnect_unknown_ack_retains_original_lease_and_never_relaunches(self):
        task, detail = self.task()
        self.driver.lose_allocate_ack = True
        lease = self.portal.call(self.runtime.submit, 'alice', task['id'])
        self.assertEqual(lease['state'], 'UNKNOWN')
        self.assertTrue(lease['capacityHeld'])
        self.approve(task['id'], detail, allowed={409})
        with patch.object(self.driver, 'inspect', side_effect=ConnectionError('Synthetic controlled disconnect')):
            with self.assertRaises(ConnectionError):
                self.portal.call(self.runtime.inspect_task, 'alice', task['id'])
            held = self.runtime.resources.inspect('alice', lease['id'])
            self.assertTrue(held['capacityHeld'])
            self.assertFalse((held.get('stopEvidence') or {}).get('allStopped', False))
        repeated = self.portal.call(self.runtime.submit, 'alice', task['id'])
        self.assertEqual(repeated['id'], lease['id'])
        recovered = self.portal.call(self.runtime.inspect_task, 'alice', task['id'])
        self.assertEqual(recovered['providerJobId'], 'controlled-' + lease['id'])
        self.assertEqual(self.driver.launches, 1)

    def test_wrong_owner_unpaused_and_changed_requirement_cannot_dispatch(self):
        task, detail = self.task()
        assert detail is not None
        with self.assertRaises(HTTPException) as foreign:
            self.portal.call(self.runtime.submit, 'bob', task['id'])
        self.assertEqual(foreign.exception.status_code, 404)
        original = self.store.lifecycle_observer._binding
        with patch.object(self.store.lifecycle_observer, '_binding',
                side_effect=lambda current: {**original(current), 'status': 'running', 'persistedRunStatus': 'running'}):
            with self.assertRaises(HTTPException):
                self.portal.call(self.runtime.submit, 'alice', task['id'])
        requirement = self.requirements[task['id']]
        self.request('POST', '/jobs/' + task['id'] + '/approve',
            {'requirementId': requirement['id'], 'version': '0' * 64, 'approved': True}, allowed={409})
        self.assertEqual(self.driver.launches, 0)
        self.assertEqual(self.store.sql('SELECT * FROM af_process_runs'), [])

    def test_cancel_unknown_stop_holds_gpu_until_original_positive_release(self):
        task, _ = self.task()
        lease = self.portal.call(self.runtime.submit, 'alice', task['id'])
        self.driver.unknown_stop = True
        self.request('POST', '/jobs/' + task['id'] + '/cancel', {})
        unknown = self.portal.call(self.runtime.inspect_task, 'alice', task['id'])
        self.assertEqual(unknown['state'], 'UNKNOWN')
        self.assertTrue(unknown['capacityHeld'])
        self.assertNotEqual(unknown['gpuEvidence']['state'], 'RELEASED')
        self.assertEqual(self.driver.launches, 1)
        self.driver.unknown_stop = False
        # Supply positive original-process proof explicitly, without runtime replay.
        self.portal.call(self.driver.cancel, lease['id'], 'alice')
        released = self.portal.call(self.runtime.inspect_task, 'alice', task['id'])
        self.assertEqual(released['id'], lease['id'])
        self.assertEqual(released['gpuEvidence']['state'], 'RELEASED')
        self.assertFalse(released['capacityHeld'])
        self.assertEqual(self.driver.launches, 1)

    def test_real_gpu_capacity_blocks_other_owner_and_alias_despite_separate_pools(self):
        task, _ = self.task()
        original = self.portal.call(self.runtime.submit, 'alice', task['id'])
        for owner, target in (('alice', 'research-alias'), ('bob', 'research-alias')):
            with self.subTest(owner=owner):
                plan = create_plan(self.store, owner, 'Isolated synthetic capacity probe', 'literature')
                review = self.post('/plan-reviews', {'planId': plan['id']}, owner=owner)
                self.post('/plan-reviews/' + review['id'] + '/decision', {'approved': True}, owner='manager')
                probe, _ = self.store.reserve_task(plan, str(uuid4()))
                run_id = str(uuid4())
                self.store.accept(probe['id'], run_id)
                try:
                    # Capacity-only boundary: explicit fake native guard, real
                    # owner/plan/task/GPU reservation SQL. Not a second native workflow.
                    with patch.object(self.runtime, 'validate_execution', return_value=None):
                        with self.assertRaises(HTTPException) as held:
                            self.runtime.resources._reserve(owner, target, probe['id'], str(uuid4()),
                                {'cpu': 1, 'memoryMb': 128, 'diskMb': 1, 'seconds': 600},
                                execution={'nativeRunId': run_id, 'effectKey': 'research-process-run-v1', 'requirement': {}})
                    self.assertEqual(held.exception.status_code, 429)
                    self.assertEqual(held.exception.detail, 'GPU_CAPACITY_HELD: original device custody is not released')
                finally:
                    self.store.sql('UPDATE af_tasks SET terminal=TRUE,cancel_requested=TRUE WHERE id=:id', id=probe['id'])
        self.assertEqual(len(self.store.sql('SELECT id FROM af_leases')), 1)
        self.assertEqual(self.driver.launches, 1)
        self.assertEqual(self.alias_driver.launches, 0)
        self.assertEqual(self.runtime.resources.inspect('alice', original['id'])['id'], original['id'])

    def test_before_dispatch_busy_holds_intent_until_explicit_never_dispatched_proof(self):
        task, _ = self.task()
        allocate = self.driver.allocate_bound
        def denied():
            raise HTTPException(409, 'Synthetic current dispatch boundary busy')
        async def busy(lease, *, before_effect):
            return await allocate(lease, before_effect=denied)
        with patch.object(self.driver, 'allocate_bound', busy):
            lease = self.portal.call(self.runtime.submit, 'alice', task['id'])
        self.assertEqual(lease['state'], 'UNKNOWN')
        self.assertTrue(lease['capacityHeld'])
        self.assertEqual(self.driver.launches, 0)
        self.assertEqual(self.portal.call(self.runtime.submit, 'alice', task['id'])['id'], lease['id'])
        self.portal.call(self.driver.cancel, lease['id'], 'alice')
        released = self.portal.call(self.runtime.inspect_task, 'alice', task['id'])
        self.assertEqual(released['gpuEvidence']['state'], 'RELEASED')
        self.assertEqual(released['gpuEvidence']['releaseProof']['kind'], 'never-dispatched')
        self.assertEqual(self.driver.launches, 0)

    def test_expiry_stops_original_without_success_or_new_dispatch(self):
        task, _ = self.task()
        lease = self.portal.call(self.runtime.submit, 'alice', task['id'])
        self.runtime.resources._update('alice', lease['id'], lease['state'],
            {'deadlineAt': (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()})
        released = self.portal.call(self.runtime.inspect_task, 'alice', task['id'])
        self.assertEqual(released['id'], lease['id'])
        self.assertEqual(released['cancellationReason'], 'LEASE_EXPIRED')
        self.assertEqual(released['executionStatus'], 'CANCELLED')
        self.assertEqual(released['gpuEvidence']['state'], 'RELEASED')
        self.approve(task['id'], self.detail(task['id']), allowed={409})
        self.assertEqual(self.driver.launches, 1)

    def test_current_role_revocation_stops_original_without_releasing_unknown_gpu(self):
        task, _ = self.task()
        lease = self.portal.call(self.runtime.submit, 'alice', task['id'])
        self.portal.call(self.store.lifecycle_observer.stop)
        self.driver.unknown_stop = True
        self.auth.authorization.unassign('alice', 'factory-user')
        try:
            held = self.portal.call(self.runtime.observe_lease, lease['id'])
            self.assertEqual(held['cancellationReason'], 'AUTHORITY_ENDED')
            self.assertEqual(held['state'], 'UNKNOWN')
            self.assertTrue(held['capacityHeld'])
            self.assertNotEqual(held['gpuEvidence']['state'], 'RELEASED')
            self.driver.unknown_stop = False
            self.portal.call(self.driver.cancel, lease['id'], 'alice')
            released = self.portal.call(self.runtime.observe_lease, lease['id'])
            self.assertEqual(released['gpuEvidence']['state'], 'RELEASED')
            self.assertEqual(released['providerJobId'], held['providerJobId'])
            self.assertEqual(self.driver.launches, 1)
        finally:
            self.auth.authorization.assign('alice', 'factory-user')

    def test_shared_maintenance_tick_routes_real_research_lease_and_controlled_ordinary_row(self):
        task, _ = self.task()
        lease = self.portal.call(self.runtime.submit, 'alice', task['id'])
        self.portal.call(self.store.lifecycle_observer.stop)
        ordinary = self.store.process_runtime
        ordinary._cursor = ""
        # Routing-only ordinary row and spy: no ordinary process is asserted here.
        ordinary_lease = str(uuid4())
        self.store.sql("INSERT INTO af_process_runs VALUES(:task,'bounded-process-run-v1','alice',:run,:lease,CAST('{}' AS JSONB))",
            task='routing-only-' + uuid4().hex, run=str(uuid4()), lease=ordinary_lease)
        try:
            with patch.object(ordinary, 'observe_lease', return_value={'state': 'UNKNOWN', 'capacityHeld': True}) as route, \
                 patch.object(self.runtime, 'observe_lease', wraps=self.runtime.observe_lease) as real:
                results = self.portal.call(ordinary.tick)
                assert route.await_args is not None
                self.assertEqual(route.await_args.args, (ordinary_lease,))
                self.assertIn((lease['id'],), [call.args for call in real.await_args_list])
                mapped = {row['leaseId']: row for row in results}
                self.assertEqual(mapped[lease['id']]['state'], 'RUNNING')
                self.assertTrue(mapped[ordinary_lease]['capacityHeld'])
            self.assertEqual(self.driver.launches, 1)
        finally:
            self.store.sql('DELETE FROM af_process_runs WHERE lease_id=:id', id=ordinary_lease)
