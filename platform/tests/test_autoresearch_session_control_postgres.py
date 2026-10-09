# pyright: reportMissingImports=false
"""Real single-worker native pause/child/continuation, inert ORX session.

The scientific pin resolver is a trusted fixture seam. This proves queue and
original-process custody, not full scientific assembly, inference or evaluation.
"""
import asyncio
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
from typing import Any
import unittest
from unittest.mock import AsyncMock
from uuid import uuid4

from agent_factory.autoresearch import ResearchPreset
from agent_factory.config import Settings
from agent_factory.process_enforcement import ProcessLimits, ProcessSpec
from agent_factory.process_provider import ProcessResourceProvider
from agent_factory.research_manifest import manifest_fingerprint
from agent_factory.resources import ComputePool, RemoteTarget
from agent_factory.store import Store
from pg_fixture import IsolatedPostgres
from test_autoresearch_postgres import bootstrap
import test_go_product_postgres as native_fixture
from test_research_manifest import example_manifest


@unittest.skipUnless(sys.platform == 'linux' and os.getenv('FACTORY_TEST_DATABASE_URL'),
                     'Requires disposable PostgreSQL and Linux native queue fixture')
class ExternalSessionPostgresTests(unittest.TestCase):
    state: dict[str, Any]
    store: Any
    client: Any
    open_application = native_fixture.GoProductPostgresTests.open_application
    login = native_fixture.GoProductPostgresTests.login
    post = native_fixture.GoProductPostgresTests.post

    def test_original_parent_pauses_frees_single_worker_and_resumes_after_child(self):
        database = IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']).__enter__()
        self.addCleanup(database.__exit__, None, None, None)
        directory = tempfile.TemporaryDirectory(prefix='external-session-native-')
        self.addCleanup(directory.cleanup)
        workspace = Path(directory.name)
        source_store = Store(database.url, Settings(db_url=database.url, workspace=workspace))
        self.addCleanup(source_store.engine.dispose)
        custody = workspace / 'process'; custody.mkdir(mode=0o700)
        executable = Path(sys.executable).resolve()
        spec = ProcessSpec(str(executable), hashlib.sha256(executable.read_bytes()).hexdigest(),
                           ('-I', '-c', "print('Controlled original child')"))
        provider = ProcessResourceProvider(source_store, custody, spec, ProcessLimits(wall_seconds=5))
        target = RemoteTarget('Controlled child', 'compute', frozenset({'alice'}), provider=provider,
            synthetic_fixture=True, max_cpu=1, max_memory_mb=128, max_disk_mb=1, max_seconds=20,
            capacity_pool=ComputePool('original-child-pool', 1, 128, 1, max_leases=1, max_owner_leases=1))
        evidence: dict[str, Any] = {}
        testcase = self

        class Runtime:
            async def run(self):
                evidence['runtimeCalls'] = evidence.get('runtimeCalls', 0) + 1
                ctx = evidence['ctx']; parent = testcase.store.task(ctx.run_context.session_id, 'alice')
                ticket = testcase.store.lifecycle_observer._binding(parent)
                testcase.assertEqual(ticket['status'], 'paused')
                testcase.assertEqual(ticket['persistedRunStatus'], 'paused')
                testcase.assertEqual(ticket['attempt'], 1)
                testcase.assertEqual(ticket['max_attempts'], 1)
                evidence['parentBeforeChild'] = dict(ticket)
                child = await testcase.store.delegation.create('alice', parent['id'],
                    'Verify a retained preparation reference', 'scientific-preparation', 'single-worker-child')
                evidence['child'] = child['childTask']
                end = time.monotonic() + 45
                while time.monotonic() < end:
                    current = testcase.store.task(child['childTask']['id'], 'alice')
                    native = testcase.store.lifecycle_observer._binding(current)
                    if native and native['status'] == native['persistedRunStatus'] == 'completed':
                        evidence['childCompleted'] = dict(native)
                        break
                    if native and native['status'] in {'failed', 'cancelled'}:
                        raise AssertionError('Controlled native child failed')
                    await asyncio.sleep(.05)
                testcase.assertIn('childCompleted', evidence)
                testcase.assertEqual(testcase.store.lifecycle_observer._binding(parent)['status'], 'paused')
                return {'evidenceMode': 'controlled-fixture', 'modelExecuted': False}

            async def stop(self): return True
            async def cancel(self): return None

        runtime = Runtime()
        def runtime_factory(ctx, _):
            evidence['ctx'] = ctx
            return runtime
        async def forbidden(*_): raise AssertionError('No scientific experiment requested')
        preset = ResearchPreset(id='original-external-session', name='Native queue fixture',
            default_goal='Verify the original controlled parent and child lifecycle', owner_id='alice',
            instructions='Controlled synthetic queue only', manifest={'schema': 1, 'evidenceMode': 'controlled-fixture'},
            limits={'totalSeconds': 120, 'experimentSeconds': 30, 'maxExperiments': 1, 'toolCalls': 32, 'outputBytes': 65536},
            runtime_factory=runtime_factory, context_reader=lambda: {}, candidate_validator=lambda _: {},
            experiment=forbidden, review_owner='manager', external_session=True)
        self.settings = bootstrap.settings(db_url=database.url, workspace=workspace, preset=preset)
        # Explicit legacy accounting fixture; all model/provider IO remains controlled.
        self.settings.fee_management_enabled = self.settings.platform_paid_models_enabled = True
        self.settings.remote_targets = {'original-preparation': target}
        self.assertEqual(self.settings.max_workers, 1)
        self.open_application()
        def cleanup():
            from agent_factory.process_enforcement import BoundedProcessAdapter
            for row in self.store.sql('SELECT id,owner_id FROM af_process_allocations'):
                asyncio.run(provider.cancel(row['id'], row['owner_id']))
                path = custody / row['id'] / 'custody.sqlite'
                if path.exists():
                    adapter = BoundedProcessAdapter(path)
                    self.assertTrue(adapter.wait(owner_id=row['owner_id'])['stoppedProof'])
        self.addCleanup(cleanup)
        auth = self.state['auth']
        auth.authorization.unassign('bob', 'factory-user'); auth.authorization.assign('bob', 'factory-manager')
        preset = bootstrap.publish_application(self.state, preset, author='manager', reviewer='bob')
        self.settings.autoresearch_presets[preset.id] = preset
        self.store.autoresearch.presets[preset.id] = preset
        manifest = example_manifest()
        pin = {'targetRef': 'original-preparation', 'comparisonManifest': manifest,
               'comparisonManifestSha256': manifest_fingerprint(manifest), 'variantSha256': 'b' * 64}
        def require_child(ctx, phase):
            self.assertEqual(phase, 'preparation')
            self.assertEqual(ctx.plan['delegation']['rootTaskId'], evidence['ctx'].run_context.session_id)
            self.assertEqual(ctx.run_context.user_id, 'alice')
            return pin
        self.store.autoresearch_children = SimpleNamespace(require_child=require_child,
            verify_preparation=AsyncMock(return_value={'originalSourceTask': 'synthetic-producer', 'scientificConclusionVerified': False}))
        self.login('alice')
        request = str(uuid4())
        result = self.post('/api/factory/autoresearch/runs', {'presetId': preset.id, 'requestId': request}, 202)
        end = time.monotonic() + 75
        while time.monotonic() < end:
            body = self.store.autoresearch.row('alice', result['id'])['body']
            if body['status'] in {'completed', 'failed', 'unknown'}: break
            time.sleep(.05)
        self.assertEqual(body['status'], 'completed', body)
        parent = self.store.task(result['id'], 'alice')
        native = self.store.lifecycle_observer._binding(parent)
        self.assertEqual(native['status'], 'completed')
        self.assertEqual(native['id'], evidence['parentBeforeChild']['id'])
        self.assertNotEqual(native['id'], evidence['childCompleted']['id'])
        # Native continuation requeues the same parent ticket once; this is
        # not a provider retry or a replacement task/run.
        for task, expected_attempt in ((parent, 2), (evidence['child'], 1)):
            job = self.store.native_db.get_job(task['run_id'], strict=True)
            self.assertEqual(job['attempt'], expected_attempt)
            self.assertEqual(job['max_attempts'], expected_attempt)
        self.assertEqual(evidence['runtimeCalls'], 1)
        commands = self.store.sql('SELECT * FROM af_control_commands WHERE root_task_id=:task', task=parent['id'])
        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0]['command_id'], 'ar-session:' + parent['run_id'])
        links = self.store.sql('SELECT * FROM af_delegation_links WHERE parent_id=:parent', parent=parent['id'])
        self.assertEqual(len(links), 1)
        allocations = self.store.sql('SELECT * FROM af_process_allocations')
        self.assertEqual(len(allocations), 0)  # preparation verification never exports/reseals
        repeat = self.post('/api/factory/autoresearch/runs', {'presetId': preset.id, 'requestId': request}, 202)
        self.assertEqual(repeat['id'], parent['id'])
