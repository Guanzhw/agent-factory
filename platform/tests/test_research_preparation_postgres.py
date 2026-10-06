# pyright: reportMissingImports=false
"""Actual native PG/guardian preparation, with synthetic safe JSON and no ML."""
import asyncio
import hashlib
import os
from pathlib import Path
import sys
import unittest
from tempfile import TemporaryDirectory
from typing import Any, cast
from pg_fixture import IsolatedPostgres
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from agent_factory.config import Settings
from agent_factory.main import create_app
from agent_factory.process_enforcement import ProcessSpec, ProcessLimits
from agent_factory.process_runtime_profile import process_settings, publish_process_application
from agent_factory.research_preparation_driver import PreparationDriver
from agent_factory.research_preparation_provider import PreparationProvider
from agent_factory.research_preparation_store import ResearchPreparationStore
from agent_factory.resources import ComputePool, RemoteTarget
from agent_factory.store import Store
import test_process_runtime_postgres as process_fixture
from test_research_preparation_harness import tokenizer


@unittest.skipUnless(sys.platform == 'linux' and os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires isolated PG/Linux')
class PreparationPostgresTests(unittest.TestCase):
    def setUp(self):
        self.database = IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']).__enter__()
        self.addCleanup(self.database.__exit__, None, None, None)
        temporary = TemporaryDirectory(prefix='native-preparation-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.target_ref = 'bounded-preparation-target'

    request = process_fixture.ProcessRuntimePostgresTests.request
    submit = process_fixture.ProcessRuntimePostgresTests.submit
    until = process_fixture.ProcessRuntimePostgresTests.until
    lease = process_fixture.ProcessRuntimePostgresTests.lease
    cleanup_processes = process_fixture.ProcessRuntimePostgresTests.cleanup_processes

    def start(self):
        self.bootstrap = Store(self.database.url, Settings(db_url=self.database.url, workspace=self.root))
        self.addCleanup(self.bootstrap.engine.dispose)
        staged = self.root / 'preparation'; staged.mkdir(mode=0o700)
        info = staged.stat()
        self.driver = PreparationDriver(root=staged, root_identity={'device': info.st_dev, 'inode': info.st_ino},
            tokenizer_json=tokenizer(), reserve=lambda *a, **kw: self.preparation.reserve(*a, **kw), manifest_sha256='b'*64)
        executable = Path(sys.executable).resolve()
        self.spec = ProcessSpec(str(executable), hashlib.sha256(executable.read_bytes()).hexdigest(),
            ('-I', '-B', str(staged / 'prepare.py'), str(staged / 'run-config.json')))
        self.limits = ProcessLimits(wall_seconds=5)
        custody = self.root / 'process-custody'; custody.mkdir(mode=0o700)
        self.provider = PreparationProvider(self.bootstrap, custody, self.spec, self.limits, driver=self.driver)
        pool = ComputePool('prep-pool', 1, 128, 1, max_leases=1, max_owner_leases=1)
        target = RemoteTarget('Synthetic tokenizer preparation', 'compute', frozenset({'alice', 'bob'}),
            provider=self.provider, synthetic_fixture=True, max_cpu=1, max_memory_mb=128,
            max_disk_mb=1, max_seconds=5, capacity_pool=pool)
        self.settings = process_settings(db_url=self.database.url, workspace=self.root,
            target_ref=self.target_ref, remote_targets={self.target_ref: target})
        self.app = create_app(self.settings); self.state = self.app.app.state.factory
        self.store, self.auth = self.state['store'], self.state['auth']
        self.addCleanup(self.store.engine.dispose); self.addCleanup(self.store.native_db.db_engine.dispose)
        self.preparation = ResearchPreparationStore(self.store, self.auth, self.state['resources'], self.store.storage,
            preparation_manifest_sha256='b'*64, source_sha256=self.driver.configuration_fingerprint)
        self.auth.directory.upsert('prep-reviewer', name='Synthetic preparation reviewer')
        self.auth.authorization.assign('prep-reviewer', 'factory-manager')
        self.application = publish_process_application(self.state, target_ref=self.target_ref, author='manager', reviewer='prep-reviewer')
        self.client = TestClient(cast(Any, self.app)).__enter__(); self.addCleanup(self.client.__exit__, None, None, None)
        self.addCleanup(self.cleanup_processes)

    def test_original_native_export_import_lost_ack_and_reopen(self):
        self.start()
        task, plan = self.submit()
        def complete():
            detail = self.request('GET', '/jobs/' + task['id'])
            return detail if detail['job']['status'] in {'completed', 'failed'} else None
        detail = self.until(complete, timeout=25)
        outputs = [p.read_text() for p in self.provider.root.glob('*/custody.output')]
        self.assertEqual(detail['job']['status'], 'completed', {'outputs': outputs,
            'leases': self.store.sql('SELECT body FROM af_leases'), 'events': self.store.events(task['id'])})
        lease = self.lease(task)
        self.assertIsNotNone(lease)
        self.assertEqual(lease['state'], 'RECLAIMED')
        self.assertEqual(lease['executionStatus'], 'COMPLETED')
        self.assertFalse(lease['capacityHeld'])
        self.assertEqual(lease['planId'], plan['id'])
        self.assertEqual(lease['nativeRunId'], self.store.task(task['id'])['run_id'])
        proof = self.provider.read_launch_proof(lease['id'], 'alice')
        self.assertFalse(proof['executionVerified'])
        original_write = self.store.artifact_write
        def lose_ack(*args, **kwargs):
            original_write(*args, **kwargs)
            raise RuntimeError('controlled lost import acknowledgement')
        with patch.object(self.store, 'artifact_write', side_effect=lose_ack), self.assertRaises(RuntimeError):
            self.preparation.import_completed('alice', lease['id'])
        artifact = self.preparation.import_completed('alice', lease['id'])
        pin = self.preparation.input_pin('alice', task['id'], artifact['id'])
        self.assertEqual(pin['binding']['providerJobId'], lease['providerJobId'])
        self.assertLess(pin['sizeBytes'], 65536)
        self.assertEqual(len([a for a in self.store.artifacts(task['id']) if a['name'] == artifact['name']]), 1)
        reopened = PreparationProvider(self.bootstrap, self.provider.root, self.spec, self.limits, driver=self.driver)
        self.assertEqual(reopened.read_launch_proof(lease['id'], 'alice'), proof)
        snapshot = asyncio.run(reopened.inspect(lease['id'], 'alice'))
        self.assertEqual(snapshot['providerJobId'], lease['providerJobId'])
        self.assertEqual(self.store.sql('SELECT COUNT(*) AS n FROM af_process_allocations')[0]['n'], 1)
        with self.assertRaises(HTTPException):
            self.preparation.input_pin('bob', task['id'], artifact['id'])

    def test_cancel_at_original_reservation_prevents_child_dispatch(self):
        self.start()
        reserve = self.driver.reserve
        def cancel_before_reserve(owner, lease_id, **kwargs):
            lease = self.store.sql('SELECT body FROM af_leases WHERE id=:id', id=lease_id)[0]['body']
            self.store.request_cancel(lease['localTaskId'])
            return reserve(owner, lease_id, **kwargs)
        replacement = patch.object(self.driver, 'reserve', cancel_before_reserve)
        replacement.start(); self.addCleanup(replacement.stop)
        task, _ = self.submit()
        lease = self.until(lambda: self.lease(task))
        self.until(lambda: asyncio.run(self.provider.inspect(lease['id'], 'alice'))['allStopped'], timeout=25)
        original = process_fixture.BoundedProcessAdapter(self.provider.root / lease['id'] / 'custody.sqlite')
        snapshot = original.inspect(owner_id='alice')
        self.assertIsNone(snapshot['child'])
        self.assertIsNone(snapshot['guardian'])
        self.assertTrue(snapshot['stoppedProof'])
        self.assertFalse((self.driver.root / 'seal.json').exists())
        self.assertEqual(self.store.sql('SELECT COUNT(*) AS n FROM af_process_allocations')[0]['n'], 1)
        with self.assertRaises(ValueError):
            self.preparation.import_completed('alice', lease['id'])
