"""Real PostgreSQL/native queue/stdlib guardian candidate journal acceptance.

Device observations are explicit fixture mocks; no Torch, GPU or scientific
candidate is executed. Reuse fixture methods without importing a TestCase alias.
"""
import importlib.util
from dataclasses import replace
import os
from pathlib import Path
import sys
from typing import Any
import unittest
from unittest.mock import patch
from uuid import uuid4

from agent_factory.research_bootstrap_controller import ResearchBootstrapController, ResearchBootstrapError
import test_research_local_postgres as fixture  # pyright: ignore[reportMissingImports]


@unittest.skipUnless(sys.platform == 'linux' and os.getenv('FACTORY_TEST_DATABASE_URL'),
                     'Requires disposable PostgreSQL and Linux guardian')
class ResearchCandidatePostgresTests(unittest.TestCase):
    work: Any
    state: Any
    store: Any
    runtime: Any
    portal: Any
    application: Any
    checkpoints: Any
    observer: Any
    journal_path: Any
    recovery: Any
    journal_identity: Any
    app: Any

    cleanup = fixture.ResearchLocalPostgresTests.cleanup
    request = fixture.ResearchLocalPostgresTests.request
    post = fixture.ResearchLocalPostgresTests.post
    task = fixture.ResearchLocalPostgresTests.task
    detail = fixture.ResearchLocalPostgresTests.detail
    until = fixture.ResearchLocalPostgresTests.until

    def setUp(self):
        fixture.ResearchLocalPostgresTests.setUp(self)
        source = Path(__file__).resolve().parents[2] / 'scripts/research_candidate_recovery.py'
        spec = importlib.util.spec_from_file_location('candidate_pg_recovery', source)
        assert spec is not None and spec.loader is not None
        self.recovery = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.recovery)
        self.journal_path = self.work / 'candidate-journal.json'
        self.journal_identity = {'configSha256': 'a' * 64, 'candidateSha256': 'b' * 64,
                                 'baselineManifestSha256': 'c' * 64}

    def controller(self):
        def request(method, path, body, *, owner):
            return self.request(method, path.removeprefix('/api/factory'), body, owner=owner)
        return ResearchBootstrapController(self.state, request, self.portal.call)

    def run_once(self, journal, progress, imported):
        journal.begin_stage('training')
        return self.controller().run(owner='alice', reviewer='manager',
            application_ref={key: self.application[key] for key in ('id', 'version', 'sha256')},
            goal='Synthetic candidate journal acceptance; mocked device, no training',
            request_id=str(uuid4()), after_reclaimed=imported, timeout_seconds=45,
            on_progress=progress)

    def assert_original_released(self, progress):
        task = self.store.task(progress['taskId'], 'alice')
        self.assertEqual(task['run_id'], progress['nativeRunId'])
        self.assertEqual(task['plan_id'], progress['planId'])
        lease = self.runtime.resources.inspect('alice', progress['leaseId'])
        self.assertEqual(lease['providerJobId'], progress['providerJobId'])
        self.assertEqual(lease['nativeRunId'], progress['nativeRunId'])
        self.assertEqual(lease['state'], 'RECLAIMED')
        self.assertFalse(lease['capacityHeld'])
        self.assertTrue(lease['stopEvidence']['allStopped'])
        self.assertEqual(lease['gpuEvidence']['state'], 'RELEASED')
        self.assertTrue(lease['syntheticFixture'])
        self.assertEqual(len(self.store.sql('SELECT id FROM af_tasks')), 1)
        self.assertEqual(len(self.store.sql('SELECT id FROM af_process_allocations')), 1)
        self.assertEqual(sum(call['operation'] == 'launch' for call in self.observer.calls), 1)
        return lease

    def test_native_completion_records_original_ids_without_duplicate_allocation(self):
        with self.recovery.CandidateJournal(self.journal_path, identity=self.journal_identity,
                                            total_seconds=90) as journal:
            def progress(value):
                journal.record_progress('training', value)
                if value['phase'] == 'PROCESS_SUBMITTED':
                    (self.work / 'release').touch()

            def imported(owner, task, lease):
                artifact = self.checkpoints.import_completed(owner, lease['id'])
                _, identity = self.checkpoints.identity(task['id'], artifact['id'], 65536)
                return {'artifactId': artifact['id'], 'identity': identity}

            result = self.run_once(journal, progress, imported)
            self.assertEqual(result['progress']['phase'], 'COMPLETED')
            self.assertFalse(result['progress']['scientificConclusionVerified'])
            journal.finish_stage('training', {'status': 'COMPLETED', 'cleanupConfirmed': True})
            original = journal.snapshot()['stages']['training']['progress']
            deadline = journal.snapshot()['deadlineMonotonic']
        with self.recovery.CandidateJournal(self.journal_path, identity=self.journal_identity) as reopened:
            self.assertEqual(reopened.snapshot()['stages']['training']['progress'], original)
            self.assertEqual(reopened.snapshot()['deadlineMonotonic'], deadline)
            with self.assertRaises(ValueError):
                reopened.begin_stage('training')
        lease = self.assert_original_released(original)
        self.assertEqual(lease['executionStatus'], 'COMPLETED')
        self.assertEqual(self.store.native_db.get_job(original['nativeRunId'], strict=True)['status'], 'completed')

    def test_controller_interruption_uses_stop_only_recovery_without_submit_replay(self):
        cleanup = []
        with self.recovery.CandidateJournal(self.journal_path, identity=self.journal_identity,
                                            total_seconds=90) as journal:
            def progress(value):
                journal.record_progress('training', value)
                if value['phase'] == 'PROCESS_SUBMITTED':
                    with patch.object(self.runtime, 'submit', side_effect=AssertionError('NO_SUBMIT_REPLAY')):
                        cleanup.append(self.portal.call(self.recovery.recover_original,
                            self.state, self.runtime, 'alice', value['taskId'], 5))
                    raise KeyboardInterrupt('synthetic operator interruption')

            def never_import(*args):
                self.fail('Interrupted candidate cannot import evidence')

            with self.assertRaises(ResearchBootstrapError) as caught:
                self.run_once(journal, progress, never_import)
            final = caught.exception.progress
            self.assertTrue(final['cleanupConfirmed'])
            self.assertEqual(len(cleanup), 1)
            self.assertTrue(cleanup[0]['cleanupConfirmed'])
            self.assertEqual(cleanup[0]['leaseId'], final['leaseId'])
            journal.finish_stage('training', {'status': 'STOPPED', 'cleanupConfirmed': True})
        lease = self.assert_original_released(final)
        self.assertNotEqual(lease['executionStatus'], 'COMPLETED')
        self.assertFalse((self.work / 'release').exists())

    def test_reopened_journal_recovers_running_original_without_new_task_or_allocation(self):
        # A cooperative synthetic caller interruption closes only its journal.
        # The existing application lifespan and original child remain alive;
        # this is not a cold restart or SIGKILL durability claim.
        task, _ = self.task()
        original_task = self.store.task(task['id'], 'alice')
        with self.recovery.CandidateJournal(self.journal_path, identity=self.journal_identity,
                                            total_seconds=90) as journal:
            journal.begin_stage('training')
            lease = self.portal.call(self.runtime.submit, 'alice', task['id'])
            original = {'phase': 'PROCESS_SUBMITTED', 'requestId': str(uuid4()),
                'taskId': task['id'], 'planId': original_task['plan_id'],
                'nativeRunId': original_task['run_id'], 'leaseId': lease['id'],
                'providerJobId': lease['providerJobId'], 'cancelRequested': False,
                'cleanupConfirmed': False}
            journal.record_progress('training', original)
        self.assertNotEqual(lease['state'], 'RECLAIMED')
        with self.recovery.CandidateJournal(self.journal_path, identity=self.journal_identity) as reopened:
            saved = reopened.snapshot()['stages']['training']['progress']
            self.assertEqual(saved, original)
            with patch.object(self.runtime, 'submit', side_effect=AssertionError('NO_SUBMIT_REPLAY')):
                result = self.portal.call(self.recovery.recover_original,
                    self.state, self.runtime, 'alice', saved['taskId'], 5)
                again = self.portal.call(self.recovery.recover_original,
                    self.state, self.runtime, 'alice', saved['taskId'], 5)
            self.assertTrue(result['cleanupConfirmed'])
            self.assertEqual(result['leaseId'], saved['leaseId'])
            self.assertEqual(again, result)
            reopened.record_progress('training', {**saved, 'phase': 'STOPPED',
                'cancelRequested': True, 'cleanupConfirmed': True})
            reopened.finish_stage('training', {'status': 'STOPPED', 'cleanupConfirmed': True})
            with self.assertRaises(ValueError):
                reopened.begin_stage('evaluation')
        self.assert_original_released(original)
        self.assertFalse((self.work / 'release').exists())

    def test_unstarted_native_worker_cancels_original_after_process_release(self):
        task, _ = self.task()
        self.portal.call(self.store.lifecycle_observer.stop)
        self.portal.call(self.app.app.state.queue_worker.stop)
        lease = self.portal.call(self.runtime.submit, 'alice', task['id'])
        original_task = self.store.task(task['id'], 'alice')
        expected = {key: original_task[field] for key, field in (
            ('ownerId', 'owner_id'), ('taskId', 'id'), ('nativeRunId', 'run_id'),
            ('planId', 'plan_id'), ('requestId', 'request_id'))}
        original = {**expected, 'leaseId': lease['id'], 'providerJobId': lease['providerJobId']}
        cleanup = self.portal.call(self.recovery.recover_original,
            self.state, self.runtime, 'alice', task['id'], 5)
        self.assertTrue(cleanup['cleanupConfirmed'])
        self.assertEqual(self.store.native_db.get_job(expected['nativeRunId'], strict=True)['status'], 'paused')
        self.assertEqual(self.store.sql('SELECT state FROM af_disk_holds WHERE task_id=:id',
                                       id=task['id'])[0]['state'], 'HELD')

        def external(name):
            path = Path(__file__).resolve().parents[2] / 'scripts' / (name + '.py')
            spec = importlib.util.spec_from_file_location(name + '_pg', path)
            assert spec is not None and spec.loader is not None
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module

        state_helper = external('research_candidate_state')
        native_stop = external('research_candidate_native_stop')
        with patch('agno.os.job_queue.QueueWorker.start', side_effect=AssertionError('NO_WORKER_START')), \
                patch('agno.os.job_queue.QueueWorker._claim_burst', side_effect=AssertionError('NO_CLAIM')), \
                patch.object(self.runtime, 'submit', side_effect=AssertionError('NO_NEW_ALLOCATION')):
            with state_helper.open_state(replace(self.store.settings), full_verification=True) as reopened:
                with patch.object(reopened['research_runtime'], 'submit',
                                  side_effect=AssertionError('NO_NEW_ALLOCATION')):
                    stopped = self.portal.call(native_stop.cancel_native_original,
                        reopened, task['id'], expected)
                self.assertTrue(stopped['nativeCleanupConfirmed'])
                self.assertEqual(stopped['nativeStatus'], 'cancelled')
                self.assertEqual(stopped['persistedRunStatus'], 'cancelled')
                self.assertEqual(stopped['terminalStatus'], 'canceled')
                current = reopened['store'].task(task['id'], 'alice')
                reopened['store'].observed(current, stopped['terminalStatus'], True)
                self.assertTrue(reopened['store'].task(task['id'], 'alice')['terminal'])
                self.assertEqual(reopened['store'].sql('SELECT state FROM af_disk_holds WHERE task_id=:id',
                                                      id=task['id'])[0]['state'], 'RELEASED')
        self.assert_original_released(original)
        self.assertFalse((self.work / 'release').exists())

    def test_narrow_reconstructed_state_preserves_disabled_user_and_withdrawn_material(self):
        # Reconstructed service objects retain the original fixture providers;
        # no OS restart, new app lifespan, worker or target machine is claimed.
        task, _ = self.task()
        lease = self.portal.call(self.runtime.submit, 'alice', task['id'])
        original_task = self.store.task(task['id'], 'alice')
        original = {'taskId': task['id'], 'planId': original_task['plan_id'],
                    'nativeRunId': original_task['run_id'], 'leaseId': lease['id'],
                    'providerJobId': lease['providerJobId']}
        governance = self.store.material_governance
        governance.withdraw('manager', 'checksum-tool', 1, str(uuid4()), 'Synthetic retained withdrawal')
        self.state['auth'].directory.set_disabled('bob', True)
        source = Path(__file__).resolve().parents[2] / 'scripts/research_candidate_state.py'
        spec = importlib.util.spec_from_file_location('candidate_pg_existing_state', source)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        settings = replace(self.store.settings)
        with patch('agent_factory.store.Store.initialize', side_effect=AssertionError('NO_STORE_SEED')), \
                patch('agent_factory.auth.AuthService.initialize_demo', side_effect=AssertionError('NO_AUTH_SEED')), \
                patch('agent_factory.main.create_app', side_effect=AssertionError('NO_NEW_APP')):
            with module.open_state(settings) as reopened:
                self.assertIsNot(reopened['store'], self.store)
                self.assertTrue(reopened['auth'].directory.get('bob')['disabled'])
                self.assertEqual(governance.inspect_version('manager', 'checksum-tool', 1)['governance']['state'],
                                 'withdrawn')
                runtime = reopened['research_runtime']
                with patch.object(runtime, 'submit', side_effect=AssertionError('NO_SUBMIT_REPLAY')):
                    result = self.portal.call(self.recovery.recover_original,
                        reopened, runtime, 'alice', original['taskId'], 5)
                self.assertTrue(result['cleanupConfirmed'])
                self.assertEqual(result['leaseId'], original['leaseId'])
                self.assertTrue(reopened['auth'].directory.get('bob')['disabled'])
        self.assertEqual(governance.inspect_version('manager', 'checksum-tool', 1)['governance']['state'],
                         'withdrawn')
        self.assert_original_released(original)
        self.assertFalse((self.work / 'release').exists())
