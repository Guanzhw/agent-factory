"""Top-level candidate execute over real native PostgreSQL and synthetic children.

Baseline authentication, preparation and scientific/environment adaptation are
explicit mocks. Controllers, admission, process custody, checkpoint import,
independent evaluator verification, journal and final artifacts are real.
"""
from contextlib import ExitStack, nullcontext
from dataclasses import asdict
import importlib
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Any
import unittest
from unittest.mock import Mock, patch

from agent_factory.research_evaluation_service import ResearchEvaluationService
from agent_factory.research_manifest import manifest_fingerprint
from agent_factory.research_runtime_profile import publish_research_application
from agent_factory.store import digest
import test_research_local_postgres as fixture  # pyright: ignore[reportMissingImports]


@unittest.skipUnless(sys.platform == 'linux' and os.getenv('FACTORY_TEST_DATABASE_URL'),
                     'Requires disposable PostgreSQL and Linux guardian')
class CandidateExecutePostgresTests(unittest.TestCase):
    work: Any
    manifest: Any
    limits: Any
    store: Any
    auth: Any
    runtime: Any
    checkpoints: Any
    evaluation_contract: Any
    training_contract: Any
    app: Any
    state: Any
    provider: Any
    portal: Any
    observer: Any
    evaluator: Any
    setUp = fixture.ResearchLocalPostgresTests.setUp
    cleanup = fixture.ResearchLocalPostgresTests.cleanup
    request = fixture.ResearchLocalPostgresTests.request
    post = fixture.ResearchLocalPostgresTests.post
    task = fixture.ResearchLocalPostgresTests.task
    detail = fixture.ResearchLocalPostgresTests.detail
    until = fixture.ResearchLocalPostgresTests.until

    def test_execute_runs_one_training_and_evaluation_and_writes_real_receipts(self):
        scripts = str(Path(__file__).resolve().parents[2] / 'scripts')
        with patch.object(sys, 'path', [scripts, *sys.path]):
            runner = importlib.import_module('run_research_candidate')
            recovery = importlib.import_module('research_candidate_recovery')
            assembly = importlib.import_module('research_candidate_assembly')
            baseline_auth = importlib.import_module('research_candidate_baseline')
            snapshots = importlib.import_module('research_candidate_reopen')
        workspace = self.work.parent / 'candidate-execute'; workspace.mkdir(mode=0o700)
        variant = self.manifest['baselineSourceManifestSha256']
        baseline_variant = 'e' * 64
        identity = {'configSha256': 'a' * 64, 'candidateSha256': 'b' * 64, 'baselineManifestSha256': manifest_fingerprint(self.manifest)}
        observation = {'schema': 1, 'status': 'completed', 'comparisonIdentitySha256': manifest_fingerprint(self.manifest),
                       'variantSha256': baseline_variant, 'valBpb': 5.0}
        config = {'workspace': str(workspace), 'requestId': 'synthetic-candidate-execute',
            'databaseUrlFile': '/synthetic/database', 'upstreamRoot': '/synthetic/upstream',
            'inputRoot': '/synthetic/input', 'tokenizerBasename': 'tokenizer.json',
            'projectRoot': '/synthetic/project', 'venvRoot': '/synthetic/venv',
            'interpreterTarget': '/synthetic/python', 'interpreterSha256': 'd' * 64,
            'approvedInterpreterRoots': ['/synthetic'], 'receiverNamespaceSha256': 'a' * 64,
            'deviceUuid': 'GPU-12345678', 'nvidiaSmi': {'executable': '/synthetic/nvidia-smi', 'sha256': 'd' * 64},
            'limits': asdict(self.limits), 'microbatch': 1,
            'shards': [{'id': 'train', 'basename': 'train.parquet'}, {'id': 'val', 'basename': 'val.parquet'}],
            'validationIds': ['val']}
        inputs = {'identity': identity, 'baselineConfig': config, 'candidateBytes': b'synthetic changed source',
                  'manifestSha256': manifest_fingerprint(self.manifest), 'observation': observation}
        captured = {'comparisonManifest': self.manifest, 'manifestSha256': inputs['manifestSha256'], 'operatorInputs': {}}
        calls, publication_calls, saved_snapshots = [], [], []
        service = ResearchEvaluationService(self.store, self.auth, self.runtime.resources,
            {digest(self.manifest['evaluator']): 'evaluator'}, checkpoint_reader=self.checkpoints.identity)
        self.store.research_evaluation = service
        outer = self

        class Pending:
            def __getitem__(self, key):
                outer.assertEqual(key, 'evaluationContract')
                return outer.evaluation_contract

        base_bundle = {'app': self.app, 'state': self.state, 'settings': self.store.settings,
            'providerStore': self.provider.store, 'preparation': Mock(), 'checkpoints': self.checkpoints, 'pending': Pending()}

        def candidate_assembly(**kwargs):
            stage = 'evaluation' if kwargs['training'] else 'training'
            calls.append(stage)
            outer.assertEqual(kwargs['candidate_files']['train.py'], inputs['candidateBytes'])
            outer.assertEqual(kwargs['captured_inputs'], captured)
            expected = 'evaluate.py' if stage == 'evaluation' else 'train_candidate.py'
            outer.assertEqual(Path(kwargs['launch_spec'].argv[1]).name, expected)
            if stage == 'evaluation':
                outer.training_contract = kwargs['training']
                outer.assertEqual(kwargs['training']['variantSha256'], variant)
                outer.assertIs(kwargs['training_store'], outer.checkpoints)
            return base_bundle

        def publish(state, **kwargs):
            stage = kwargs['target_ref']
            publication_calls.append(stage)
            outer.assertEqual(kwargs['variant_sha256'], variant)
            outer.assertEqual(kwargs['adapter_suffix'], '-candidate-' + stage)
            # Explicit synthetic adapter boundary: registered fixture target names.
            return publish_research_application(state, target_ref='local' if stage == 'training' else 'evaluator',
                comparison_manifest=kwargs['comparison_manifest'], author='manager', reviewer='bob',
                adapter_suffix='' if stage == 'training' else '-evaluator')

        def request_client(bundle, client):
            return lambda method, path, body, owner: outer.request(method, path.removeprefix('/api/factory'), body, owner=owner)

        def preparation(bundle, client, request_id, progress, journal):
            progress.record('preparation', {'phase': 'IMPORTED', 'cleanupConfirmed': True,
                **{key: 'synthetic-preparation-' + key for key in
                   ('taskId', 'planId', 'nativeRunId', 'leaseId', 'providerJobId', 'artifactId')}})
            return 'synthetic-preparation-task', 'synthetic-preparation-artifact', {}

        def snapshot(**kwargs):
            saved_snapshots.append(kwargs['stage'])
            return {'schema': 1, 'stage': kwargs['stage'], 'syntheticEnvironmentBoundary': True}

        class ReleasingProgress(runner.Progress):
            def record(self, stage, value):
                super().record(stage, value)
                if stage == 'training' and value.get('phase') == 'PROCESS_SUBMITTED':
                    (outer.work / 'release').touch()

        with ExitStack() as patches:
            def mock(obj, name, **kw):
                return patches.enter_context(patch.object(obj, name, **kw))
            mock(runner, 'load_inputs', return_value=inputs)
            mock(runner, 'runtime_identity', return_value=None)
            mock(runner, 'read_private', return_value=b'synthetic original source')
            mock(runner, 'environment_pins', return_value=())
            mock(runner, 'preparation_phase', side_effect=preparation)
            mock(runner, 'request_client', side_effect=request_client)
            mock(baseline_auth, 'authorize_baseline', return_value=observation)
            mock(assembly, 'research_application', side_effect=candidate_assembly)
            mock(snapshots, 'make_snapshot', side_effect=snapshot)
            mock(importlib.import_module('fastapi.testclient'), 'TestClient', side_effect=lambda app: nullcontext(SimpleNamespace(portal=self.portal)))
            control = importlib.import_module('bootstrap_research_control')
            mock(control, 'read_database_url', return_value=self.store.settings.db_url)
            mock(control, 'ensure_task_development_reviewer', return_value='manager')
            mock(importlib.import_module('agent_factory.research_bootstrap_assembly'), 'prepare_application', return_value=base_bundle)
            mock(importlib.import_module('agent_factory.research_local_driver'), 'derive_local_identities',
                 return_value={'identities': {'candidate': {'sha256': variant}, 'baseline': {'sha256': baseline_variant}}})
            mock(importlib.import_module('agent_factory.research_profile'), 'verify_upstream_source', return_value={})
            mock(importlib.import_module('agent_factory.research_bootstrap_inventory'), 'build_inventory',
                 return_value={'inventoryBytes': b'{}', 'kernelBytes': b'{}', 'captureKwargs': {'bounds_profile': None}})
            mock(importlib.import_module('agent_factory.research_bootstrap_inputs'), 'capture_bootstrap_inputs', return_value=captured)
            mock(importlib.import_module('agent_factory.research_interpreter'), 'capture_interpreter_contract', return_value='synthetic-contract')
            mock(importlib.import_module('agent_factory.process_enforcement'), 'UvResearchProcessSpec',
                 side_effect=lambda executable, sha, argv, **kw: SimpleNamespace(argv=argv, **kw))
            mock(importlib.import_module('agent_factory.research_runtime_profile'), 'publish_research_application', side_effect=publish)
            with recovery.CandidateJournal(workspace / 'candidate-journal.json', identity=identity, total_seconds=120) as journal:
                result = runner.execute(config, workspace, ReleasingProgress(workspace, journal), journal)
                state = journal.snapshot()
        self.assertEqual(calls, ['training', 'evaluation'])
        self.assertEqual(publication_calls, calls)
        self.assertEqual(saved_snapshots, calls)
        self.assertTrue(all(state['stages'][name]['result']['cleanupConfirmed'] for name in ('preparation', *calls)))
        self.assertEqual(len(self.store.sql('SELECT id FROM af_tasks')), 2)
        self.assertEqual(len(self.store.sql('SELECT id FROM af_process_allocations')), 2)
        self.assertEqual(sum(row['operation'] == 'launch' for row in self.observer.calls), 1)
        self.assertEqual(sum(row['operation'] == 'launch' for row in self.evaluator._observer.calls), 1)
        self.assertEqual(result['assessment']['recommendation'], 'recommend_keep')
        self.assertTrue(result['evaluation']['imported']['trainingSyntheticFixture'])
        self.assertTrue(result['evaluation']['imported']['evaluatorSyntheticFixture'])
        for stage in calls:
            saved = json.loads((workspace / (stage + '-receipt.json')).read_text())
            self.assertEqual(saved, result[stage])
            self.assertEqual(saved['progress']['phase'], 'COMPLETED')
            self.assertEqual(self.store.native_db.get_job(saved['progress']['nativeRunId'], strict=True)['status'], 'completed')
        self.assertEqual(json.loads((workspace / 'assessment.json').read_text()), result['assessment'])
