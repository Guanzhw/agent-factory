"""External candidate CLI control tests; synthetic inputs and no database/GPU."""
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import hashlib
import importlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import test_research_baseline_runner as baseline_fixture
from test_research_manifest import example_manifest
from agent_factory.research_manifest import manifest_fingerprint

SCRIPTS = Path(__file__).parents[2] / 'scripts'
with patch.object(sys, 'path', [str(SCRIPTS), *sys.path]):
    runner = importlib.import_module('run_research_candidate')


@unittest.skipUnless(sys.platform == 'linux', 'Private journal and filesystem require Linux')
class CandidateRunnerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='synthetic-candidate-cli-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.addCleanup(patch.stopall)
        patch.object(sys, 'path', [str(SCRIPTS), *sys.path]).start()
        self.baseline = baseline_fixture.config(self.root)
        self.baseline['workspace'] = str(self.root / 'original-workspace')
        self.manifest = example_manifest()
        self.observation = {'schema': 1, 'status': 'completed',
            'comparisonIdentitySha256': manifest_fingerprint(self.manifest),
            'variantSha256': self.manifest['baselineSourceManifestSha256'], 'valBpb': 1.3}
        self.config = {'schema': 1, 'baselineConfigFile': str(self.root / 'original-config.json'),
            'baselineEvaluationReceiptFile': str(self.root / 'original-evaluation.json'),
            'baselineRunConfigFile': str(self.root / 'original-run-config.json'),
            'candidateTrainFile': str(self.root / 'candidate.py'),
            'candidateSha256': hashlib.sha256(b'# synthetic candidate\n').hexdigest(),
            'workspace': str(self.root / 'candidate-workspace'), 'requestId': 'candidate-attempt',
            'totalSeconds': 1800, 'ackCandidate': True}
        for field, body in (('baselineConfigFile', self.baseline),
                            ('baselineEvaluationReceiptFile', {'imported': {'observation': self.observation}}),
                            ('baselineRunConfigFile', {'comparisonManifest': self.manifest})):
            runner.write_private(Path(self.config[field]), runner.canonical(body))
        path = Path(self.config['candidateTrainFile']); path.write_bytes(b'# synthetic candidate\n'); path.chmod(0o644)
        self.path = self.root / 'candidate-config.json'
        runner.write_private(self.path, runner.canonical(self.config))

    def call(self, run):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = runner.main(['--config', str(self.path)], run=run)
        return code, out.getvalue(), err.getvalue()

    def test_closed_schema_rejects_new_limits_missing_ack_duplicate_and_boolean_budget(self):
        bad = [dict(self.config, limits=self.baseline['limits']), dict(self.config, ackCandidate=False),
               dict(self.config, totalSeconds=True), dict(self.config, totalSeconds=86401),
               dict(self.config, workspace='relative'), dict(self.config, candidateSha256='not-a-hash')]
        for value in bad:
            with self.subTest(value=value), self.assertRaises(ValueError):
                runner.config_from_bytes(runner.canonical(value))
        with self.assertRaises(ValueError):
            runner.config_from_bytes(b'{"schema":1,"schema":1}')

    def test_retained_manifest_observation_and_candidate_bytes_must_match(self):
        inputs = runner.load_inputs(self.config)
        self.assertEqual(inputs['baselineConfig'], self.baseline)
        self.assertEqual(inputs['observation'], self.observation)
        self.assertEqual(set(inputs['identity']), {'configSha256', 'candidateSha256', 'baselineManifestSha256'})
        Path(self.config['candidateTrainFile']).write_bytes(b'# replaced synthetic candidate\n')
        with self.assertRaises(ValueError):
            runner.load_inputs(self.config)

    def test_unmatched_or_incomplete_baseline_denied(self):
        path = Path(self.config['baselineEvaluationReceiptFile'])
        for change in ({'comparisonIdentitySha256': '0' * 64}, {'variantSha256': '0' * 64},
                       {'status': 'failed', 'valBpb': None}):
            value = {'imported': {'observation': {**self.observation, **change}}}
            path.write_bytes(runner.canonical(value))
            with self.subTest(change=change), self.assertRaises(ValueError):
                runner.load_inputs(self.config)

    def test_original_workspace_or_request_reuse_denied(self):
        for field in ('workspace', 'requestId'):
            value = deepcopy(self.config); value[field] = self.baseline[field]
            with self.assertRaises(ValueError):
                runner.load_inputs(value)

    def test_fresh_mock_execution_holds_lock_and_keeps_limits(self):
        def execute(config, workspace, progress, journal):
            from research_candidate_recovery import CandidateJournal
            self.assertEqual(runner.load_inputs(config)['baselineConfig']['limits'], self.baseline['limits'])
            self.assertEqual(workspace.stat().st_mode & 0o777, 0o700)
            with self.assertRaises(BlockingIOError), CandidateJournal(workspace / 'candidate-journal.json',
                    identity=journal.snapshot()['identity'], total_seconds=config['totalSeconds']):
                self.fail('Concurrent invocation acquired lock')
        self.assertEqual(self.call(execute), (0, 'RESEARCH_CANDIDATE_COMPLETED_PRIVATE_EVIDENCE\n', ''))
        journal = json.loads((Path(self.config['workspace']) / 'candidate-journal.json').read_bytes())
        self.assertEqual(journal['totalSeconds'], 1800)

    def test_existing_workspace_is_readonly_and_never_runs(self):
        workspace = Path(self.config['workspace']); workspace.mkdir(mode=0o700)
        marker = workspace / 'original'; marker.write_bytes(b'unchanged')
        before = marker.stat().st_mtime_ns
        run = Mock()
        self.assertEqual(self.call(run), (0, 'RESEARCH_CANDIDATE_EXISTING_INSPECT_ONLY\n', ''))
        run.assert_not_called()
        self.assertEqual(marker.stat().st_mtime_ns, before)
        self.assertEqual(list(workspace.iterdir()), [marker])

    def test_failure_is_redacted_never_retried_and_keeps_journal(self):
        run = Mock(side_effect=RuntimeError('synthetic private path and credential'))
        self.assertEqual(self.call(run), (2, '', 'RESEARCH_CANDIDATE_STOPPED\n'))
        run.assert_called_once()
        workspace = Path(self.config['workspace'])
        records = sorted(workspace.glob('progress-*.json'))
        self.assertEqual(json.loads(records[-1].read_bytes())['progress'],
                         {'phase': 'STOPPED', 'cleanupConfirmed': False})
        self.assertTrue((workspace / 'candidate-journal.json').is_file())

    def test_stage_timeout_uses_remaining_invocation_budget(self):
        self.assertEqual(runner.stage_timeout(Mock(remaining=Mock(return_value=45.9)), 600), 45)
        self.assertEqual(runner.stage_timeout(Mock(remaining=Mock(return_value=1000)), 600), 720)
        for value in (0, .5, float('nan'), True):
            with self.assertRaises(ValueError):
                runner.stage_timeout(Mock(remaining=Mock(return_value=value)), 600)

    def test_preparation_lost_ack_resolves_original_and_cleans_after_budget_expires(self):
        from research_candidate_recovery import CandidateJournal
        from agent_factory import process_runtime_profile, research_bootstrap_controller
        bootstrap = importlib.import_module('bootstrap_research_control')
        workspace = Path(self.config['workspace']); workspace.mkdir(mode=0o700)
        store = Mock()
        store.task.return_value = {'id': 'original-task', 'owner_id': 'alice', 'plan_id': 'original-plan'}
        expired = False
        calls = []
        def remaining():
            if expired:
                raise TimeoutError('synthetic deadline')
            return 120
        def request(method, path, body, *, owner):
            nonlocal expired
            calls.append((method, path))
            if path.endswith('/proposals'): return {'id': 'proposal'}
            if path.endswith('/accept'): return {'id': 'original-plan'}
            if path.endswith('/plan-reviews'): return {'id': 'review'}
            if path.endswith('/decision'): return {}
            if path.endswith('/instances'):
                expired = True
                raise TimeoutError('synthetic lost acknowledgement')
            if '/requests/' in path:
                return {'taskId': 'original-task', 'planId': 'original-plan',
                        'requestId': 'candidate-attempt:prep:instance'}
            if path.endswith('/cancel'): return {}
            raise AssertionError(path)
        with CandidateJournal(workspace / 'journal.json', identity=runner.load_inputs(self.config)['identity'],
                              total_seconds=120) as journal:
            journal.begin_stage('preparation')
            progress = runner.Progress(workspace, journal)
            with patch.object(journal, 'remaining', side_effect=remaining), \
                 patch.object(bootstrap, 'ensure_task_development_reviewer', return_value='reviewer'), \
                 patch.object(process_runtime_profile, 'publish_process_application',
                    return_value={'id': 'app', 'version': 1, 'sha256': 'a' * 64}), \
                 patch.object(runner, 'request_client', return_value=request), \
                 patch.object(research_bootstrap_controller, 'cleanup_original',
                    return_value={'cleanupConfirmed': True}) as cleanup:
                with self.assertRaises(TimeoutError):
                    runner.preparation_phase({'state': {'store': store}}, Mock(),
                        'candidate-attempt', progress, journal)
            cleanup.assert_called_once()
            self.assertEqual(journal.snapshot()['stages']['preparation']['progress']['taskId'], 'original-task')
            self.assertIn(('POST', '/api/factory/jobs/original-task/cancel'), calls)

    def test_baseline_authority_failure_prevents_preparation_or_candidate_dispatch(self):
        import research_candidate_baseline as authority
        from agent_factory import research_bootstrap_assembly
        from research_candidate_recovery import CandidateJournal
        workspace = Path(self.config['workspace']); workspace.mkdir(mode=0o700)
        with CandidateJournal(workspace / 'journal.json', identity=runner.load_inputs(self.config)['identity'],
                              total_seconds=120) as journal, \
             patch.object(runner, 'runtime_identity'), \
             patch.object(authority, 'authorize_baseline', side_effect=ValueError('synthetic authority denied')), \
             patch.object(research_bootstrap_assembly, 'prepare_application') as prepare:
            with self.assertRaises(ValueError):
                runner.execute(self.config, workspace, runner.Progress(workspace, journal), journal,
                               database_url='postgresql+psycopg://synthetic@127.0.0.1:5432/unused')
            prepare.assert_not_called()
            self.assertTrue(all(not row['consumed'] for row in journal.snapshot()['stages'].values()))
