"""Real standalone CLI/database routing with disposable credentials and no GPU.

Original native training/evaluator evidence comes from explicit synthetic stdlib
fixtures. Authentication/preflight/CLI/files/DB are not mocked. A new scientific
launch intentionally fails its real interpreter identity gate before admission.
"""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from typing import Any
from uuid import uuid4

from agent_factory.research_bootstrap_controller import ResearchBootstrapController
from agent_factory.research_evaluation_service import ResearchEvaluationService
from agent_factory.research_runtime_profile import publish_research_application
from agent_factory.store import Store, digest
from agent_factory.storage_governance import StorageGovernance
from pg_fixture import IsolatedPostgres  # pyright: ignore[reportMissingImports]
import test_research_baseline_runner as config_fixture  # pyright: ignore[reportMissingImports]
import test_research_local_postgres as fixture  # pyright: ignore[reportMissingImports]


@unittest.skipUnless(sys.platform == 'linux' and os.getenv('FACTORY_TEST_DATABASE_URL'),
                     'Requires disposable PostgreSQL and Linux guardian')
class CandidateDatabaseAuthPostgresTests(unittest.TestCase):
    work: Any
    state: Any
    store: Any
    auth: Any
    runtime: Any
    portal: Any
    application: Any
    checkpoints: Any
    manifest: Any
    training_contract: Any
    evaluation_contract: Any
    stack: Any
    setUp = fixture.ResearchLocalPostgresTests.setUp
    cleanup = fixture.ResearchLocalPostgresTests.cleanup
    request = fixture.ResearchLocalPostgresTests.request
    post = fixture.ResearchLocalPostgresTests.post
    task = fixture.ResearchLocalPostgresTests.task
    detail = fixture.ResearchLocalPostgresTests.detail
    until = fixture.ResearchLocalPostgresTests.until

    def run_stage(self, imported, progress=lambda value: None):
        def request(method, path, body, *, owner):
            return self.request(method, path.removeprefix('/api/factory'), body, owner=owner)
        return ResearchBootstrapController(self.state, request, self.portal.call).run(
            owner='alice', reviewer='manager', application_ref={k: self.application[k] for k in ('id', 'version', 'sha256')},
            goal='Synthetic native evidence for ephemeral database routing', request_id=str(uuid4()),
            after_reclaimed=imported, timeout_seconds=45, on_progress=progress)

    def test_standalone_route_preflight_rotate_execute_recover_and_wrong_database(self):
        def imported(owner, task, lease):
            artifact = self.checkpoints.import_completed(owner, lease['id'])
            metadata, identity = self.checkpoints.identity(task['id'], artifact['id'], 65536)
            return {**{k: metadata['provenance'][k] for k in
                ('ownerId', 'taskId', 'nativeRunId', 'planId', 'planFingerprint', 'leaseId', 'providerJobId', 'variantSha256')},
                'checkpoint': {'artifactId': artifact['id'], **identity}}
        def released(value):
            if value['phase'] == 'PROCESS_SUBMITTED':
                (self.work / 'release').touch()
        training = self.run_stage(imported, released)
        self.training_contract = training['imported']
        self.application = publish_research_application(self.state, target_ref='evaluator',
            comparison_manifest=self.manifest, author='manager', reviewer='bob', adapter_suffix='-evaluator')
        service = ResearchEvaluationService(self.store, self.auth, self.runtime.resources,
            {digest(self.manifest['evaluator']): 'evaluator'}, checkpoint_reader=self.checkpoints.identity)
        evaluation = self.run_stage(lambda owner, task, lease:
            self.portal.call(service.verify, owner, self.evaluation_contract))
        root = self.work.parent / 'ephemeral-auth-test'; root.mkdir(mode=0o700)
        script = Path(__file__).resolve().parents[2] / 'scripts/run_research_candidate.py'

        def write(name, body):
            path = root / name
            raw = body if type(body) is bytes else json.dumps(body, sort_keys=True).encode()
            with path.open('xb') as stream:
                stream.write(raw)
            path.chmod(0o600)
            return path

        original = config_fixture.config(root)
        original['workspace'] = str(self.work.parent)
        original['databaseUrlFile'] = str(root / 'expired-original-auth')
        retained = {
            'baselineConfigFile': write('original-config.json', original),
            'baselineEvaluationReceiptFile': write('original-evaluation.json', evaluation),
            'baselineRunConfigFile': write('original-run-config.json', {'comparisonManifest': self.manifest}),
        }
        candidate_raw = b'# explicitly synthetic candidate; never executed\n'
        candidate = write('candidate.py', candidate_raw)
        config = {'schema': 1, **{k: str(v) for k, v in retained.items()},
            'candidateTrainFile': str(candidate), 'candidateSha256': hashlib.sha256(candidate_raw).hexdigest(),
            'workspace': str(root / 'candidate-workspace'), 'requestId': 'auth-route-candidate',
            'totalSeconds': 120, 'ackCandidate': True}
        config_path = write('candidate-config.json', config)
        before = {path: path.read_bytes() for path in (*retained.values(), candidate, config_path)}
        first = write('first-auth', self.store.settings.db_url.encode())
        counts = tuple(len(self.store.sql('SELECT id FROM ' + table)) for table in ('af_tasks', 'af_process_allocations'))

        def cli(mode, authfile, selected=config_path):
            args = [sys.executable, '-B', str(script), *mode, '--config', str(selected),
                    '--database-url-file', str(authfile)]
            result = subprocess.run(args, capture_output=True, text=True, timeout=45)
            self.assertNotIn(str(authfile), result.stdout + result.stderr)
            self.assertNotIn(self.store.settings.db_url, result.stdout + result.stderr)
            return result

        result = cli(['--database-preflight'], first)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('DATABASE_BOUND_NO_EXECUTION', result.stdout)
        self.assertFalse(Path(config['workspace']).exists())
        first.unlink()
        second = write('rotated-auth', self.store.settings.db_url.encode())
        result = cli(['--database-preflight'], second)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(Path(config['workspace']).exists())

        # Real CLI execute resolves the new route, then stops at its unchanged
        # scientific interpreter gate. It must not consume any stage or task.
        result = cli([], second)
        self.assertEqual(result.returncode, 2)
        self.assertIn('RESEARCH_CANDIDATE_STOPPED', result.stderr)
        workspace = Path(config['workspace'])
        journal_path = workspace / 'candidate-journal.json'
        journal_before = journal_path.read_bytes()
        journal = json.loads(journal_before)
        self.assertTrue(all(not row['consumed'] for row in journal['stages'].values()))
        # Establish an empty candidate storage namespace through the real
        # constructor so the stop-only path can reopen it. No stages executed.
        storage_store = Store(self.store.settings.db_url, replace(self.store.settings, workspace=workspace))
        try:
            StorageGovernance(storage_store, self.auth)
        finally:
            storage_store.engine.dispose()
        second.unlink()
        recovery_auth = write('recovery-auth', self.store.settings.db_url.encode())
        result = cli(['--recover'], recovery_auth)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn('ORIGINAL_CUSTODY_UNKNOWN', result.stdout)
        self.assertEqual(journal_path.read_bytes(), journal_before)
        receipts = list(workspace.glob('recovery-*.json'))
        self.assertTrue(receipts, 'Real recovery must reopen DB and persist its private no-stage report')
        for path in receipts:
            report = json.loads(path.read_bytes())
            self.assertFalse(report['cleanupConfirmed'])
            self.assertEqual(report['stages'], {})

        with IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']) as wrong_db:
            wrong = write('wrong-auth', wrong_db.url.encode())
            changed = {**config, 'workspace': str(root / 'wrong-route-workspace'), 'requestId': 'wrong-route-candidate'}
            wrong_config = write('wrong-route-config.json', changed)
            for mode in (['--database-preflight'], []):
                result = cli(mode, wrong, wrong_config)
                self.assertEqual(result.returncode, 2)
                self.assertFalse(Path(changed['workspace']).exists())
            prior_receipts = {path: path.read_bytes() for path in workspace.glob('recovery-*.json')}
            self.assertEqual(cli(['--recover'], wrong).returncode, 2)
            self.assertEqual({path: path.read_bytes() for path in workspace.glob('recovery-*.json')}, prior_receipts)

        altered = deepcopy(evaluation)
        altered['imported']['trainingExecution']['nativeRunId'] = 'substituted-native-id'
        substituted = write('substituted-receipt.json', altered)
        mismatched = write('mismatched-config.json', {**config, 'baselineEvaluationReceiptFile': str(substituted),
            'workspace': str(root / 'mismatched-workspace'), 'requestId': 'mismatched-candidate'})
        self.assertEqual(cli(['--database-preflight'], recovery_auth, mismatched).returncode, 2)
        self.assertFalse((root / 'mismatched-workspace').exists())
        self.assertEqual(tuple(len(self.store.sql('SELECT id FROM ' + table))
            for table in ('af_tasks', 'af_process_allocations')), counts)
        self.assertEqual(journal_path.read_bytes(), journal_before)
        for path, raw in before.items():
            self.assertEqual(path.read_bytes(), raw)
        for path in workspace.glob('*.json'):
            raw = path.read_bytes()
            self.assertNotIn(str(first).encode(), raw)
            self.assertNotIn(str(second).encode(), raw)
            self.assertNotIn(str(recovery_auth).encode(), raw)
            self.assertNotIn(self.store.settings.db_url.encode(), raw)
