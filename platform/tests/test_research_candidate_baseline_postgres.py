"""Real PG/native checkpoint verification after full service reconstruction.

The child programs and device observer are explicitly synthetic. This proves
existing service wiring, never a real GPU baseline or scientific observation.
"""
import importlib
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException
from agent_factory.research_bootstrap_controller import ResearchBootstrapController
from agent_factory.research_checkpoint_store import ResearchCheckpointStore
from agent_factory.research_evaluation_service import ResearchEvaluationService
from agent_factory.research_manifest import manifest_fingerprint
from agent_factory.research_runtime_profile import publish_research_application
from agent_factory.store import digest
import test_research_local_postgres as fixture


@unittest.skipUnless(sys.platform == 'linux' and os.getenv('FACTORY_TEST_DATABASE_URL'),
                     'Requires disposable PostgreSQL and Linux guardian')
class CandidateBaselinePostgresTests(unittest.TestCase):
    setUp = fixture.ResearchLocalPostgresTests.setUp
    cleanup = fixture.ResearchLocalPostgresTests.cleanup
    request = fixture.ResearchLocalPostgresTests.request
    post = fixture.ResearchLocalPostgresTests.post
    task = fixture.ResearchLocalPostgresTests.task
    detail = fixture.ResearchLocalPostgresTests.detail
    until = fixture.ResearchLocalPostgresTests.until
    settled = fixture.ResearchLocalPostgresTests.settled

    def controller(self):
        def request(method, path, body, *, owner):
            return self.request(method, path.removeprefix('/api/factory'), body, owner=owner)
        return ResearchBootstrapController(self.state, request, self.portal.call)

    def run_stage(self, imported, progress=lambda value: None):
        return self.controller().run(owner='alice', reviewer='manager',
            application_ref={key: self.application[key] for key in ('id', 'version', 'sha256')},
            goal='Synthetic original checkpoint verification after reopening', request_id=str(uuid4()),
            after_reclaimed=imported, timeout_seconds=45, on_progress=progress)

    def test_full_reopen_verifies_actual_checkpoint_and_rejects_synthetic_baseline(self):
        def training_import(owner, task, lease):
            artifact = self.checkpoints.import_completed(owner, lease['id'])
            metadata, identity = self.checkpoints.identity(task['id'], artifact['id'], 65536)
            return {**{key: metadata['provenance'][key] for key in
                ('ownerId', 'taskId', 'nativeRunId', 'planId', 'planFingerprint', 'leaseId', 'providerJobId', 'variantSha256')},
                'checkpoint': {'artifactId': artifact['id'], **identity}}
        def training_progress(value):
            if value['phase'] == 'PROCESS_SUBMITTED':
                (self.work / 'release').touch()
        training = self.run_stage(training_import, training_progress)
        self.training_contract = training['imported']
        self.application = publish_research_application(self.state, target_ref='evaluator',
            comparison_manifest=self.manifest, author='manager', reviewer='bob', adapter_suffix='-evaluator')
        original_service = ResearchEvaluationService(self.store, self.auth, self.runtime.resources,
            {digest(self.manifest['evaluator']): 'evaluator'}, checkpoint_reader=self.checkpoints.identity)
        evaluation = self.run_stage(lambda owner, task, lease:
            self.portal.call(original_service.verify, owner, self.evaluation_contract))
        self.assertTrue(training['progress']['cleanupConfirmed'])
        self.assertTrue(evaluation['progress']['cleanupConfirmed'])
        counts = tuple(len(self.store.sql('SELECT id FROM ' + table)) for table in
                       ('af_tasks', 'af_process_allocations'))
        scripts = str(Path(__file__).resolve().parents[2] / 'scripts')
        with patch.object(sys, 'path', [scripts, *sys.path]):
            reopen = importlib.import_module('research_candidate_state')
            baseline = importlib.import_module('research_candidate_baseline')
        with reopen.open_state(self.state['settings'], full_verification=True) as state:
            self.assertEqual(set(state['store'].execution_guards), set(self.store.execution_guards))
            checkpoints = ResearchCheckpointStore(state['store'], state['auth'], state['resources'],
                                                   state['store'].storage)
            service = ResearchEvaluationService(state['store'], state['auth'], state['resources'],
                {digest(self.manifest['evaluator']): 'evaluator'}, checkpoint_reader=checkpoints.identity)
            with patch.object(self.provider, 'read_completed_output', side_effect=AssertionError('NO_TRAINING_STDOUT')):
                verified = self.portal.call(service.verify, 'alice', self.evaluation_contract)
            self.assertEqual(verified, evaluation['imported'])
            self.assertTrue(verified['evaluatorCustodyVerified'])
            self.assertTrue(verified['launchInputsVerified'])
            self.assertTrue(verified['trainingSyntheticFixture'])
            self.assertTrue(verified['evaluatorSyntheticFixture'])
            # Exercise actual terminal/native/GPU checks first; the final gate
            # must still reject this fixture as a real retained baseline.
            baseline._terminal_custody(service, 'alice', self.evaluation_contract)
            async def gate():
                return await baseline.verify_retained_baseline(service=service, owner='alice',
                    contract=self.evaluation_contract, retained_receipt=evaluation,
                    expected_manifest_sha256=manifest_fingerprint(self.manifest))
            with self.assertRaisesRegex(ValueError, 'RESEARCH_RETAINED_BASELINE_UNVERIFIED'):
                self.portal.call(gate)
            # A fresh authorization lookup must preserve current revocation.
            state['auth'].authorization.unassign('alice', 'factory-user')
            with self.assertRaises(HTTPException) as denied:
                self.portal.call(service.verify, 'alice', self.evaluation_contract)
            self.assertEqual(denied.exception.status_code, 403)
            state['auth'].authorization.assign('alice', 'factory-user')
        self.assertEqual(tuple(len(self.store.sql('SELECT id FROM ' + table)) for table in
            ('af_tasks', 'af_process_allocations')), counts)
