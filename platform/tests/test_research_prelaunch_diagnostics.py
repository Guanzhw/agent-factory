"""Real PREPARED SQLite custody; no subprocess, GPU, model or installed-source execution."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from typing import cast
import unittest
from unittest.mock import Mock, patch

from sqlalchemy import create_engine, text

from agent_factory.gpu_custody import GpuBinding
from agent_factory.process_enforcement import BoundedProcessAdapter, ResearchProcessLimits, ResearchProcessSpec
from agent_factory.research_local_driver import ResearchDriverFailure
from agent_factory.research_local_provider import ResearchLocalProvider
from agent_factory.store import canonical
from agent_factory.resources import PersistentResourceService
import test_research_local_provider as fixtures  # pyright: ignore[reportMissingImports]
from pg_fixture import IsolatedPostgres  # pyright: ignore[reportMissingImports]


class FailedVerifier(fixtures.Verifier):
    def __init__(self, error):
        self.error, self.calls = error, 0

    def __call__(self, record):
        self.calls += 1
        raise self.error


class PhaseTests(unittest.TestCase):
    def test_only_exact_trusted_phase_is_preserved_and_messages_never_guessed(self):
        phases = ('binding-validation', 'runtime-config-validation', 'environment-verification',
                  'config-staging', 'staged-program-verification')
        class UntrustedSubclass(ResearchDriverFailure):
            pass
        cases: list[tuple[Exception, str]] = [(ResearchDriverFailure(phase), phase) for phase in phases]
        cases.extend([(ResearchDriverFailure('/private/input'), 'program-verification'),
                      (ValueError('environment-verification /private/token=value'), 'program-verification'),
                      (UntrustedSubclass('config-staging'), 'program-verification')])
        for error, expected in cases:
            provider, observer, record, snapshot = fixtures.fixture()
            provider._program_verifier = FailedVerifier(error)
            with self.subTest(phase=expected), self.assertRaises(type(error)) as raised:
                provider._before_launch(record, snapshot)
            self.assertIs(raised.exception, error)
            self.assertEqual(record['preDispatchFailure'], {'schema': 1, 'phase': expected,
                'code': 'RESEARCH_PRELAUNCH_VERIFICATION_FAILED', 'journalId': 'original',
                'identitySha256': '9' * 64, 'dispatchAttempted': False})
            self.assertEqual(observer.calls, [])
            self.assertNotIn('/private', json.dumps(record))

    def test_device_denial_is_labeled_only_at_device_boundary(self):
        provider, observer, record, snapshot = fixtures.fixture()
        observer.status = 'UNKNOWN'
        with patch.object(ResearchLocalProvider, 'configuration_fingerprint', 'a' * 64), self.assertRaises(ValueError):
            provider._before_launch(record, snapshot)
        self.assertEqual(record['preDispatchFailure']['phase'], 'device-verification')
        self.assertIn('programVerification', record)
        self.assertNotIn('gpuLaunchObservationSha256', record)


class DurableCase:
    postgres = False

    def setUp(self):
        case = cast(unittest.TestCase, self)
        folder = tempfile.TemporaryDirectory()
        case.addCleanup(folder.cleanup)
        self.base = Path(folder.name)
        self.root = self.base / 'custody'; self.root.mkdir(mode=0o700)
        self.program = self.base / 'program'; self.program.mkdir(mode=0o700)
        if self.postgres:
            database = IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']).__enter__()
            case.addCleanup(database.__exit__, None, None, None)
            url = database.url
        else:
            url = 'sqlite:///' + str(self.base / 'admission.sqlite')
        engine = create_engine(url)
        case.addCleanup(engine.dispose)
        body_type = 'JSONB' if self.postgres else 'TEXT'
        with engine.begin() as conn:
            conn.execute(text(f'CREATE TABLE af_leases(id TEXT PRIMARY KEY,owner_id TEXT,body {body_type})'))
            conn.execute(text(f'CREATE TABLE af_process_allocations(id TEXT PRIMARY KEY,owner_id TEXT,body {body_type})'))
            conn.execute(text(f'CREATE TABLE af_process_runs(task_id TEXT,effect_key TEXT,owner_id TEXT,native_run_id TEXT,lease_id TEXT UNIQUE,body {body_type},PRIMARY KEY(task_id,effect_key))'))
        self.store = SimpleNamespace(engine=engine)
        self.verifier = FailedVerifier(ResearchDriverFailure('environment-verification'))
        self.observer = fixtures.Observer()
        info = self.program.stat()
        self.spec = ResearchProcessSpec('/synthetic-never-executed/python', 'a' * 64,
            ('-B', str(self.program / 'entry.py')), str(self.program),
            tuple((key, '1') for key in ('HF_HUB_OFFLINE', 'HF_DATASETS_OFFLINE', 'TRANSFORMERS_OFFLINE', 'PYTHONNOUSERSITE')),
            (info.st_dev, info.st_ino))
        self.limits = ResearchProcessLimits(address_space_mb=128, file_size_bytes=65536,
            disk_bytes=1048576, wall_seconds=5, output_bytes=16384)
        self.provider = self.reopened()
        self.lease = {'id': 'lease1', 'ownerId': 'alice', 'localTaskId': 'task1', 'planId': 'plan1',
            'nativeRunId': 'run1', 'requestId': 'request1', 'connectionRef': 'research', 'poolId': 'pool1',
            'fingerprint': 'b' * 64, 'targetFingerprint': 'c' * 64, 'poolFingerprint': 'd' * 64,
            'planHash': 'e' * 64, 'providerNamespace': self.provider.capacity_namespace,
            'limits': {'cpu': 1, 'memoryMb': 128, 'diskMb': 1, 'seconds': 5},
            'executionEffect': 'research-process-run-v1',
            'executionGuard': {'manifestSha256': 'f' * 64, 'variantSha256': '7' * 64},
            'gpuBinding': self.provider.gpu_binding.to_dict()}
        body = {'taskId': 'task1', 'nativeRunId': 'run1', 'planId': 'plan1', 'ownerId': 'alice',
            'leaseId': 'lease1', 'targetRef': 'research', 'planHash': 'e' * 64,
            'requestId': 'request1', 'leaseFingerprint': 'b' * 64}
        parameter = 'CAST(:body AS JSONB)' if self.postgres else ':body'
        with engine.begin() as conn:
            conn.execute(text(f"INSERT INTO af_leases VALUES('lease1','alice',{parameter})"), {'body': canonical(self.lease)})
            conn.execute(text(f"INSERT INTO af_process_runs VALUES('task1','research-process-run-v1','alice','run1','lease1',{parameter})"), {'body': canonical(body)})

    def reopened(self):
        return ResearchLocalProvider(self.store, self.root, self.spec, self.limits,
            gpu_binding=GpuBinding('a' * 64, 'b' * 64), source_fingerprint='e' * 64,
            manifest_fingerprint='f' * 64, observer=self.observer, program_verifier=self.verifier)

    async def test_resource_snapshot_preserves_diagnostic_and_rejects_corruption(self):
        case = cast(unittest.TestCase, self)
        with patch('agent_factory.process_enforcement.subprocess.Popen', side_effect=AssertionError('NO PROCESS')) as popen:
            snapshot = await self.provider.allocate_bound(self.lease, before_effect=lambda: None)
            projected = PersistentResourceService.process_snapshot(self.lease, snapshot)
            diagnostic = snapshot['preDispatchFailure']
            case.assertEqual(projected['preDispatchFailure'], diagnostic)
            case.assertIsNot(projected['preDispatchFailure'], diagnostic)
            previous = {**self.lease, **deepcopy(projected)}
            case.assertEqual(PersistentResourceService.process_snapshot(previous, snapshot), projected)
            mutations = [None, [], {'schema': True}, {'phase': 'guessed-secret-path'},
                {'phase': []}, {'journalId': 'another-original-journal'},
                {'code': 'raw exception message'}, {'message': '/private/raw-token'},
                {'identitySha256': 'not-a-hash'}, {'dispatchAttempted': 0}]
            for change in mutations:
                corrupted = deepcopy(snapshot)
                corrupted['preDispatchFailure'] = (diagnostic | change) if isinstance(change, dict) else change
                with case.subTest(change=change), case.assertRaises(ValueError):
                    PersistentResourceService.process_snapshot(previous, corrupted)
            # Individually valid fields cannot replace already recorded custody.
            for change in ({'identitySha256': '0' * 64}, {'phase': 'config-staging'}):
                corrupted = deepcopy(snapshot)
                corrupted['preDispatchFailure'].update(change)
                with case.subTest(previous=change), case.assertRaises(ValueError):
                    PersistentResourceService.process_snapshot(previous, corrupted)
            omitted = deepcopy(snapshot)
            omitted.pop('preDispatchFailure')
            with case.assertRaises(ValueError):
                PersistentResourceService.process_snapshot(previous, omitted)
            # Listing is metadata only: exercise its owner query without a provider call.
            auth = SimpleNamespace(require=Mock())
            store = SimpleNamespace(sql=Mock(return_value=[{'id': previous['id'], 'body': canonical(previous)}]))
            manager = PersistentResourceService(store, auth, {})
            listing = manager.list_leases('alice')
            case.assertEqual(listing['leases'][0]['preDispatchFailure'], diagnostic)
            auth.require.assert_called_once_with('alice', 'run')
            case.assertEqual(store.sql.call_args.kwargs['owner'], 'alice')
            case.assertEqual(self.observer.calls, [])
            popen.assert_not_called()
            await self.provider.cancel('lease1', 'alice')
            await self.provider.reclaim('lease1', 'alice')

    async def test_failed_hook_is_durable_prepared_no_dispatch_then_normal_cancel_reclaim(self):
        case = cast(unittest.TestCase, self)
        with patch('agent_factory.process_enforcement.subprocess.Popen', side_effect=AssertionError('NO PROCESS')) as popen:
            failed = await self.provider.allocate_bound(self.lease, before_effect=lambda: None)
            case.assertTrue(failed['capacityHeld'])
            case.assertFalse(failed['released'])
            journal = self.root / 'lease1' / 'custody.sqlite'
            original = BoundedProcessAdapter(journal).inspect(owner_id='alice')
            case.assertEqual(original['state'], 'PREPARED')
            diagnostic = failed['preDispatchFailure']
            case.assertEqual(diagnostic['journalId'], original['id'])
            case.assertEqual(diagnostic['identitySha256'], original['identitySha256'])
            case.assertFalse(diagnostic['dispatchAttempted'])
            case.assertEqual(diagnostic['phase'], 'environment-verification')
            reopened = self.reopened()
            observed = await reopened.inspect('lease1', 'alice')
            case.assertEqual(observed['preDispatchFailure'], diagnostic)
            case.assertTrue(observed['capacityHeld'])
            replay = await reopened.allocate_bound(self.lease, before_effect=lambda: None)
            case.assertEqual(replay['preDispatchFailure'], diagnostic)
            case.assertEqual(self.verifier.calls, 1)
            cancelled = await reopened.cancel('lease1', 'alice')
            case.assertEqual(cancelled['stopEvidence'], {'allStopped': True, 'kind': 'never-dispatched'})
            case.assertTrue(cancelled['capacityHeld'])
            released = await reopened.reclaim('lease1', 'alice')
            case.assertFalse(released['capacityHeld'])
            case.assertEqual(released['preDispatchFailure'], diagnostic)
            case.assertEqual(self.observer.calls, [])
            popen.assert_not_called()


@unittest.skipUnless(sys.platform == 'linux', 'Real Linux PREPARED custody, no child process')
class SQLitePrelaunchTests(DurableCase, unittest.IsolatedAsyncioTestCase):
    pass


@unittest.skipUnless(sys.platform == 'linux' and os.getenv('FACTORY_TEST_DATABASE_URL'),
                     'Requires explicit serial disposable PostgreSQL lane')
class PostgresPrelaunchTests(DurableCase, unittest.IsolatedAsyncioTestCase):
    postgres = True


if __name__ == '__main__':
    unittest.main()
