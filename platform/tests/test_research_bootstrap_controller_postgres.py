"""Actual native/PG/stdlib-guardian controller acceptance, mocked device only.

Reuses setup functions without inheriting or importing another TestCase class into
this module's namespace. No Torch, GPU workload or scientific score is executed.
"""
import os
import sys
import unittest
from typing import Any
from uuid import uuid4

from agent_factory.research_bootstrap_controller import ResearchBootstrapController
import test_research_local_postgres as fixture


@unittest.skipUnless(sys.platform == 'linux' and os.getenv('FACTORY_TEST_DATABASE_URL'),
                     'Requires disposable PostgreSQL and Linux guardian')
class ResearchBootstrapControllerPostgresTests(unittest.TestCase):
    # Installed dynamically by the explicitly reused fixture setUp.
    work: Any
    checkpoints: Any
    state: Any
    portal: Any
    application: Any
    store: Any
    runtime: Any
    observer: Any

    setUp = fixture.ResearchLocalPostgresTests.setUp
    cleanup = fixture.ResearchLocalPostgresTests.cleanup
    request = fixture.ResearchLocalPostgresTests.request
    post = fixture.ResearchLocalPostgresTests.post

    def test_original_native_controller_import_and_same_run_continuation(self):
        events = []
        imports = []

        def request(method, path, body, *, owner):
            self.assertTrue(path.startswith('/api/factory/'))
            return self.request(method, path.removeprefix('/api/factory'), body, owner=owner)

        def progress(value):
            events.append(value)
            if value['phase'] == 'PROCESS_SUBMITTED':
                (self.work / 'release').touch()  # Own stdlib fixture proceeds; no provider/custody shortcut.

        def import_checkpoint(owner, task, lease):
            self.assertEqual(owner, 'alice')
            self.assertEqual(task['run_id'], lease['nativeRunId'])
            artifact = self.checkpoints.import_completed(owner, lease['id'])
            metadata, identity = self.checkpoints.identity(task['id'], artifact['id'], 65536)
            self.assertEqual(metadata['provenance']['providerJobId'], lease['providerJobId'])
            self.assertEqual(metadata['provenance']['nativeRunId'], task['run_id'])
            imports.append(artifact['id'])
            return {'artifactId': artifact['id'], 'identity': identity}

        controller = ResearchBootstrapController(self.state, request, self.portal.call)
        result = controller.run(owner='alice', reviewer='manager',
            application_ref={key: self.application[key] for key in ('id', 'version', 'sha256')},
            goal='Controlled stdlib checkpoint; mocked device, no training', request_id=str(uuid4()),
            after_reclaimed=import_checkpoint, timeout_seconds=45, on_progress=progress)
        final = result['progress']
        self.assertEqual(final['phase'], 'COMPLETED')
        self.assertTrue(final['cleanupConfirmed'])
        self.assertFalse(final['scientificConclusionVerified'])
        self.assertEqual(len(imports), 1)
        task = self.store.task(final['taskId'], 'alice')
        self.assertEqual(task['run_id'], final['nativeRunId'])
        self.assertEqual(task['plan_id'], final['planId'])
        self.assertEqual(self.store.native_db.get_job(task['run_id'], strict=True)['status'], 'completed')
        lease = self.runtime.resources.inspect('alice', final['leaseId'])
        self.assertEqual(lease['providerJobId'], final['providerJobId'])
        self.assertEqual(lease['nativeRunId'], final['nativeRunId'])
        self.assertEqual(lease['state'], 'RECLAIMED')
        self.assertEqual(lease['executionStatus'], 'COMPLETED')
        self.assertTrue(lease['stopEvidence']['allStopped'])
        self.assertFalse(lease['capacityHeld'])
        self.assertTrue(lease['syntheticFixture'])
        self.assertEqual(len(self.store.sql('SELECT id FROM af_process_allocations')), 1)
        self.assertEqual(sum(call['operation'] == 'launch' for call in self.observer.calls), 1)
        self.assertEqual([value['phase'] for value in events], ['STARTED', 'PLAN_APPROVED', 'TASK_ACCEPTED',
            'NATIVE_PAUSED', 'PROCESS_SUBMITTED', 'PROCESS_RECLAIMED', 'EVIDENCE_IMPORTED', 'COMPLETED'])
        self.assertEqual({value['taskId'] for value in events if value['taskId']}, {task['id']})

    def test_failure_after_dispatch_stops_original_guardian_before_lifespan_closes(self):
        from agent_factory.research_bootstrap_controller import ResearchBootstrapError
        def request(method, path, body, *, owner):
            return self.request(method, path.removeprefix('/api/factory'), body, owner=owner)
        def progress(value):
            if value['phase'] == 'PROCESS_SUBMITTED':
                raise RuntimeError('Controlled operator failure while original child awaits release')
        def never_import(*args):
            self.fail('Running or cancelled process cannot import a checkpoint')
        controller = ResearchBootstrapController(self.state, request, self.portal.call)
        with self.assertRaises(ResearchBootstrapError) as caught:
            controller.run(owner='alice', reviewer='manager',
                application_ref={key: self.application[key] for key in ('id', 'version', 'sha256')},
                goal='Controlled failure while original stdlib process is running', request_id=str(uuid4()),
                after_reclaimed=never_import, timeout_seconds=45, on_progress=progress)
        result = caught.exception.progress
        self.assertTrue(result['cancelRequested'])
        self.assertTrue(result['cleanupConfirmed'])
        lease = self.runtime.resources.inspect('alice', result['leaseId'])
        self.assertEqual(lease['state'], 'RECLAIMED')
        self.assertFalse(lease['capacityHeld'])
        self.assertTrue(lease['stopEvidence']['allStopped'])
        self.assertEqual(lease['providerJobId'], result['providerJobId'])
        self.assertEqual(lease['nativeRunId'], result['nativeRunId'])
        self.assertNotEqual(lease['executionStatus'], 'COMPLETED')
        self.assertFalse((self.work / 'release').exists())
        self.assertEqual(len(self.store.sql('SELECT id FROM af_process_allocations')), 1)
        self.assertEqual(sum(call['operation'] == 'launch' for call in self.observer.calls), 1)
