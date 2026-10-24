"""Round-driver identity/artifact boundaries; no PG, native ORX or provider run."""
import asyncio
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import replace
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException
from agent_factory.store import digest
from agent_factory_research.services import ResearchServices
from agent_factory_research import orx_local
from agent_factory_research.research_iteration_recipe import IterationSeedORXAdapter
from agent_factory_research.research_iteration_driver import ActualORXRoundDriver, IterationRoundProvider, source_files, sha


class DriverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        recipe = IterationSeedORXAdapter._recipe
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, source in recipe.sources:
                (root / name).write_bytes((Path(orx_local.__file__).parent / 'orx_toy' / source).read_bytes())
            env = {**os.environ, 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull,
                'GIT_AUTHOR_NAME': 'Factory toy evaluator', 'GIT_AUTHOR_EMAIL': 'toy@example.invalid',
                'GIT_COMMITTER_NAME': 'Factory toy evaluator', 'GIT_COMMITTER_EMAIL': 'toy@example.invalid',
                'GIT_AUTHOR_DATE': '2000-01-01T00:00:00Z', 'GIT_COMMITTER_DATE': '2000-01-01T00:00:00Z'}
            def git(*args):
                return subprocess.check_output([shutil.which('git'), '-c', 'core.hooksPath=', '-c',
                    'commit.gpgSign=false', *args], cwd=root, env=env, timeout=5)
            git('init', '-q', '-b', 'main'); git('add', '--', *recipe.files())
            git('commit', '-q', '-m', 'Reviewed original deterministic toy evaluator')
            cls.archive = git('archive', '--format=tar', 'HEAD')

    def setUp(self):
        self.recipe = IterationSeedORXAdapter._recipe
        self.plan = {'id': 'plan', 'ownerId': 'alice', 'status': 'ready', 'applicationRef': {'id': 'app', 'version': 1}, 'mode': 'toy'}
        self.task = {'id': 'task', 'owner_id': 'alice', 'plan_id': 'plan', 'run_id': 'native',
                     'request_id': 'request', 'admission': 'accepted', 'terminal': True, 'cancel_requested': False}
        self.round = {'id': 'round1', 'activityId': 'activity', 'ownerId': 'alice', 'ordinal': 1,
            'previousRoundId': None, 'requestId': 'request', 'taskId': 'task', 'planId': 'plan',
            'planSha256': digest(self.plan), 'runId': None, 'dispatchAttempted': True,
            'roundSeconds': 30, 'deadline': 9999999999,
            'pins': {'applicationRef': self.plan['applicationRef'], 'mode': 'toy', 'connectionRefs': {'experiment': 'connection'}},
            'baselineSource': {'kind': 'reviewedSeed', 'sha256': orx_local.TOY_FILES['baseline.py'],
                'metricValue': 16.0, 'datasetSha256': orx_local.TOY_FILES['dataset.json'],
                'evaluatorSha256': orx_local.TOY_FILES['evaluator.py']}}
        provenance = {'recipeIdentity': self.recipe.identity, 'recipeSourceCommit': self.recipe.commit,
            'recipeArchiveSha256': sha(self.archive), 'sourceArchiveSha256': sha(self.archive),
            'fileSha256': self.recipe.files(), 'taskId': 'task', 'ownerSha256': sha(b'alice')}
        self.result = {'taskId': 'task', 'planId': 'plan', 'nativeRunId': 'native', 'effectFingerprint': 'a'*64,
            'projectId': 'project', 'experimentId': 'experiment', 'orxRunId': 'orx', 'status': 'done',
            'sourceVerified': True, 'scopeVerified': True, 'stopEvidence': {'allStopped': True},
            'sourceArtifactId': 'source', 'sourceArtifactSha256': sha(self.archive), 'provenance': provenance,
            'evaluation': {'status': 'done', 'metric': 'mean_squared_error', 'sampleCount': 7, 'taskId': 'task',
                'ownerSha256': sha(b'alice'), 'runId': 'orx', 'fileSha256': self.recipe.files(),
                'baseline': {'value': 16.0}, 'candidate': {'value': 0.0}, 'improvement': 16.0}}
        payload = json.dumps({'schema': 1, 'result': self.result}, sort_keys=True).encode()
        self.result.update(artifactId='evaluation', artifactSha256=sha(payload))
        def artifact(identifier, raw, kind):
            return {'id': identifier, 'sha256': sha(raw), 'provenance': {'evidenceKind': kind, 'taskId': 'task',
                'nativeRunId': 'native', 'effectFingerprint': 'a'*64, 'orxRunId': 'orx'}}, raw
        self.artifacts = {'source': artifact('source', self.archive, 'original_reviewed_toy_source'),
                          'evaluation': artifact('evaluation', payload, 'toy_local_evaluation')}
        self.effects = [{'effect_key': 'native:orx-experiment-launch-v1', 'status': 'DONE',
                         'result': self.result}]
        self.native = {'id': 'native', 'session_id': 'task', 'user_id': 'alice', 'status': 'completed'}
        self.store = SimpleNamespace(sql=Mock(return_value=[{'fingerprint': 'a' * 64}]), task=Mock(side_effect=lambda *args: deepcopy(self.task)),
            plan=Mock(side_effect=lambda *args: deepcopy(self.plan)), effects=Mock(side_effect=lambda *args: deepcopy(self.effects)),
            artifact=Mock(side_effect=lambda task, identifier: deepcopy(self.artifacts[identifier])),
            native_db=SimpleNamespace(get_job=Mock(side_effect=lambda *args: deepcopy(self.native))),
            application_runtime=None, require_plan_execution=Mock(), accept=Mock(), admission_unknown=Mock(),
            reserve_task=Mock(return_value=(self.task, True)), _connection=ContextVar('connection', default=object()),
            composition=SimpleNamespace(propose=Mock(return_value={'id': 'proposal'}), accept=Mock(return_value=self.plan)))
        self.store.lifecycle_observer = SimpleNamespace(
            _binding=Mock(side_effect=lambda task: deepcopy(self.native)), observe_root=AsyncMock())
        self.research = ResearchServices(self.store, installed=True)
        self.research.iterations = SimpleNamespace(round_for_task=Mock(side_effect=lambda *args: deepcopy(self.round)))
        self.driver = ActualORXRoundDriver(self.store, SimpleNamespace(require_member=Mock()),
                                          SimpleNamespace(submit=AsyncMock(return_value={'run_id': 'submitted'})),
                                          SimpleNamespace(submit=AsyncMock()), research=self.research)
        for name in ('inspect_owned_orx_experiment', 'inspect_orx_experiment'):
            patcher = patch('agent_factory_research.research_iteration_driver.' + name,
                            side_effect=lambda *args: deepcopy(self.result))
            patcher.start(); self.addCleanup(patcher.stop)

    def test_observation_verifies_archive_and_artifact_separate_hashes(self):
        observed = self.driver._observe('alice', self.round)
        self.assertEqual(observed['state'], 'stopped')
        self.assertEqual(observed['sourcePin']['sha256'], orx_local.TOY_FILES['candidate.py'])
        self.assertEqual(observed['sourcePin']['archiveSha256'], sha(self.archive))
        self.assertEqual(observed['evaluation']['baselineValue'], 16.0)
        self.driver.bridge.submit.assert_not_awaited()
        self.driver.commands.submit.assert_not_awaited()

    def test_real_store_effect_projection_without_fingerprint_is_verified(self):
        # Store.effects deliberately projects only these three columns.
        self.effects = [{key: effect[key] for key in ('effect_key', 'status', 'result')}
                        for effect in self.effects]
        self.store.sql = Mock(return_value=[{'fingerprint': 'a' * 64}])
        observed = self.driver._observe('alice', self.round)
        self.assertEqual(observed['state'], 'stopped')
        self.assertEqual(observed['evaluation']['candidateValue'], 0.0)
        self.store.sql.assert_called_once_with(
            'SELECT fingerprint FROM af_effects WHERE task_id=:task AND run_id=:run AND effect_key=:key',
            task='task', run='native', key='native:orx-experiment-launch-v1')

    def test_original_effect_fingerprint_missing_ambiguous_or_changed_is_rejected(self):
        for rows in ([], [{'fingerprint': 'b' * 64}], [{}, {}], [{}]):
            with self.subTest(rows=rows):
                self.store.sql.return_value = rows
                with self.assertRaises(HTTPException):
                    self.driver._observe('alice', self.round)
        self.driver.bridge.submit.assert_not_awaited()

    def test_unknown_and_human_approval_never_become_stopped(self):
        self.native['status'] = 'paused'
        self.assertEqual(self.driver._observe('alice', self.round)['approvalRequired'], True)
        self.native['status'] = 'completed'
        self.task['terminal'] = False
        self.assertEqual(self.driver._observe('alice', self.round)['state'], 'unknown')
        self.task['terminal'] = True; self.effects[0]['status'] = 'UNKNOWN'
        self.assertEqual(self.driver._observe('alice', self.round)['state'], 'unknown')
        self.effects[0]['status'] = 'DONE'; self.result['stopEvidence'] = {'allStopped': False}
        self.assertEqual(self.driver._observe('alice', self.round)['state'], 'unknown')
        self.driver.commands.submit.assert_not_awaited()

    def test_corrupt_artifact_and_native_identity_rejected(self):
        metadata, raw = self.artifacts['source']; self.artifacts['source'] = metadata, raw + b'changed'
        with self.assertRaises(HTTPException): self.driver._observe('alice', self.round)
        self.artifacts['source'] = metadata, raw
        self.native['user_id'] = 'bob'
        with self.assertRaises(HTTPException): self.driver._observe('alice', self.round)

    def test_terminal_ticket_with_retained_custody_is_not_stopped(self):
        self.store.process_runtime = SimpleNamespace(task_held=Mock(return_value=True))
        self.assertEqual(self.driver._observe('alice', self.round)['state'], 'unknown')
        with self.assertRaises(HTTPException): self.driver.verified_evaluation('alice', self.round)
        self.driver.bridge.submit.assert_not_awaited()

    def test_positive_rejection_before_dispatch_is_stopped_without_native_or_effects(self):
        self.task.update(run_id=None, admission='rejected', terminal=True)
        self.round['dispatchAttempted'] = False
        self.effects = []
        observed = self.driver._observe('alice', self.round)
        self.assertEqual(observed, {'taskId': 'task', 'runId': None, 'state': 'stopped', 'failed': True})
        self.store.lifecycle_observer._binding.assert_not_called()
        self.driver.bridge.submit.assert_not_awaited()

    def test_no_run_requires_every_positive_no_dispatch_fact(self):
        self.task.update(run_id=None, admission='rejected', terminal=True)
        self.round['dispatchAttempted'] = False
        self.effects = []
        for field, value in (('admission', 'unknown'), ('admission', 'reserved'), ('terminal', False)):
            with self.subTest(field=field, value=value):
                original = self.task[field]; self.task[field] = value
                self.assertEqual(self.driver._observe('alice', self.round)['state'], 'unknown')
                self.task[field] = original
        for fence in (True, None, 0):
            self.round['dispatchAttempted'] = fence
            self.assertEqual(self.driver._observe('alice', self.round)['state'], 'unknown')
        self.round['dispatchAttempted'] = False
        self.effects = [{'status': 'DONE'}]
        self.assertEqual(self.driver._observe('alice', self.round)['state'], 'unknown')
        self.effects = []
        self.store.process_runtime = SimpleNamespace(task_held=Mock(return_value=True))
        self.assertEqual(self.driver._observe('alice', self.round)['state'], 'unknown')

    def test_stale_pre_dispatch_snapshot_cannot_override_persisted_fence(self):
        self.task.update(run_id=None, admission='rejected', terminal=True)
        self.effects = []
        old_round = {**self.round, 'dispatchAttempted': False}
        self.assertTrue(self.round['dispatchAttempted'])
        self.native = None
        self.assertEqual(self.driver._observe('alice', old_round)['state'], 'unknown')

    def test_missing_native_after_dispatch_and_completed_run_without_stop_proof_stay_unknown(self):
        self.native = None
        self.assertEqual(self.driver._observe('alice', self.round)['state'], 'unknown')
        self.native = {'id': 'native', 'session_id': 'task', 'user_id': 'alice',
                       'status': 'running', 'persistedRunStatus': 'completed'}
        self.task['terminal'] = False
        self.assertEqual(self.driver._observe('alice', self.round)['state'], 'unknown')

    def test_verified_original_completed_run_overrides_stale_queue_status(self):
        self.native.update(status='paused', persistedRunStatus='completed')
        self.assertEqual(self.driver._observe('alice', self.round)['state'], 'stopped')
        self.store.lifecycle_observer._binding.side_effect = ValueError('native identity mismatch')
        with self.assertRaises(ValueError):
            self.driver._observe('alice', self.round)

    def test_missing_strict_observer_does_not_fall_back_to_queue_completion(self):
        self.store.lifecycle_observer = None
        self.assertEqual(self.driver._observe('alice', self.round)['state'], 'unknown')
        with self.assertRaises(HTTPException):
            self.driver.verified_evaluation('alice', self.round)
        self.store.native_db.get_job.assert_not_called()

    def test_observe_recovers_original_receipt_then_observes_without_submission(self):
        self.task.update(run_id=None, admission='unknown', terminal=False)
        self.native = None
        self.driver.bridge.find_run = AsyncMock(return_value={'run_id': 'recovered'})
        def accept(task_id, run_id):
            self.task.update(run_id=run_id, admission='accepted')
        self.store.accept.side_effect = accept
        async def synchronous_worker(fn, *args):
            return fn(*args)
        with patch('agent_factory_research.research_iteration_driver.asyncio.to_thread', synchronous_worker):
            observed = asyncio.run(self.driver.observe('alice', self.round))
        self.assertEqual(observed['runId'], 'recovered')
        self.assertEqual(observed['state'], 'unknown')
        self.driver.bridge.find_run.assert_awaited_once_with('task', 'alice')
        self.store.accept.assert_called_once_with('task', 'recovered')
        self.store.lifecycle_observer.observe_root.assert_awaited_once_with('task')
        self.driver.bridge.submit.assert_not_awaited()
        self.driver.commands.submit.assert_not_awaited()

    def test_tar_rejects_duplicate_traversal_and_links_without_extracting(self):
        for name, type in (('../baseline.py', tarfile.REGTYPE), ('baseline.py', tarfile.SYMTYPE)):
            stream = io.BytesIO()
            with tarfile.open(fileobj=stream, mode='w') as archive:
                member = tarfile.TarInfo(name); member.type = type; member.linkname = '/elsewhere'
                archive.addfile(member)
            raw = stream.getvalue()
            with self.assertRaises(HTTPException):
                source_files(raw, replace(self.recipe, archive_sha256=sha(raw)))

    def test_reserve_uses_original_pins_and_request_inside_transaction(self):
        activity = {'ownerId': 'alice', 'goal': 'fixed goal', 'pins': self.round['pins']}
        result = self.driver.reserve('alice', activity, self.round)
        self.assertEqual(result, {'taskId': 'task', 'planId': 'plan', 'planSha256': digest(self.plan)})
        self.store.composition.propose.assert_called_once_with('alice', 'fixed goal', mode='toy',
            application_ref=self.plan['applicationRef'], connection_refs={'experiment': 'connection'}, request_id='request:proposal')
        self.store.reserve_task.assert_called_once_with(self.plan, 'request')
        self.driver.bridge.submit.assert_not_awaited()

    def test_pre_submit_expiry_and_permission_rejection_return_no_dispatch_proof(self):
        self.task.update(run_id=None, terminal=False)
        with patch('agent_factory_research.research_iteration_driver.time.time',
                   return_value=self.round['deadline']):
            self.assertEqual(asyncio.run(self.driver.dispatch('alice', self.round)),
                             {'notSubmitted': True, 'reason': 'preflight_rejected'})
        self.store.require_plan_execution.side_effect = HTTPException(403, 'revoked')
        self.assertEqual(asyncio.run(self.driver.dispatch('alice', self.round)),
                         {'notSubmitted': True, 'reason': 'preflight_rejected'})
        self.driver.bridge.submit.assert_not_awaited()
        self.store.admission_unknown.assert_not_called()
        self.store.accept.assert_not_called()

    def test_bridge_http_error_never_becomes_pre_submit_proof(self):
        self.task.update(run_id=None, terminal=False)
        self.driver.bridge.submit.side_effect = HTTPException(503, 'uncertain acknowledgement')
        with self.assertRaises(HTTPException):
            asyncio.run(self.driver.dispatch('alice', self.round))
        self.driver.bridge.submit.assert_awaited_once()
        self.store.admission_unknown.assert_called_once_with('task')
        self.store.accept.assert_not_called()

    def test_fenced_rejection_requires_fresh_positive_persisted_proof(self):
        self.task.update(run_id=None, admission='rejected', terminal=True)
        self.effects = []
        snapshot = deepcopy(self.round)
        self.assertEqual(self.driver._observe('alice', snapshot)['state'], 'unknown')
        self.round['dispatchRejected'] = True
        self.assertEqual(self.driver._observe('alice', snapshot)['state'], 'stopped')
        self.task['terminal'] = False
        self.assertEqual(self.driver._observe('alice', snapshot)['state'], 'unknown')
        self.task['terminal'] = True
        self.effects = [{'status': 'DONE'}]
        self.assertEqual(self.driver._observe('alice', snapshot)['state'], 'unknown')
        self.effects = []
        self.store.workflow = SimpleNamespace(task_held=Mock(return_value=True))
        self.assertEqual(self.driver._observe('alice', snapshot)['state'], 'unknown')
        self.store.workflow = None
        for value in (False, None, 1):
            self.round['dispatchRejected'] = value
            self.assertEqual(self.driver._observe('alice', snapshot)['state'], 'unknown')
        self.driver.bridge.submit.assert_not_awaited()

    def test_lost_dispatch_ack_marks_original_unknown_without_retry_or_approval(self):
        self.task.update(run_id=None, terminal=False)
        self.driver.bridge.submit.side_effect = TimeoutError('lost ack')
        with self.assertRaises(TimeoutError): asyncio.run(self.driver.dispatch('alice', self.round))
        self.driver.bridge.submit.assert_awaited_once()
        self.store.admission_unknown.assert_called_once_with('task')
        self.store.accept.assert_not_called(); self.driver.commands.submit.assert_not_awaited()

    def test_cancel_uses_original_control_command(self):
        asyncio.run(self.driver.cancel('alice', self.round))
        call = self.driver.commands.submit.await_args
        self.assertEqual(call.args[:2], ('alice', 'task'))
        self.assertEqual(call.args[2].action, 'cancel')
        self.driver.bridge.submit.assert_not_awaited()

    def test_provider_checks_previous_artifacts_before_promoted_selection(self):
        verified = self.driver.verified_evaluation('alice', self.round)
        baseline = {**verified['sourcePin'], 'metricValue': 0.0,
            'evaluationArtifactId': verified['evaluation']['artifactId'], 'evaluationSha256': verified['evaluation']['sha256']}
        successor = {**self.round, 'id': 'round2', 'ordinal': 2, 'previousRoundId': 'round1',
                     'taskId': 'task2', 'baselineSource': baseline}
        self.research.iterations = SimpleNamespace(round_for_task=Mock(side_effect=lambda owner, task:
            deepcopy(successor if task == 'task2' else self.round)))
        original_bound = self.driver._bound
        self.driver._bound = lambda owner, r: (self.task, self.plan) if r['taskId'] == 'task2' else original_bound(owner, r)
        provider = IterationRoundProvider(research=self.research, driver=self.driver, binary=Path('/unused'),
            source_archive=Path('/unused'), git_binary=Path('/unused'), python_binary=Path('/unused'))
        with patch('agent_factory_research.research_iteration_driver.IterationORXProvider') as selected:
            provider.create_experiment_adapter(owner_id='alice', task_id='task2')
            self.assertEqual(selected.call_args.kwargs['recipe'], 'promoted')
            self.artifacts['evaluation'][0]['sha256'] = 'b'*64
            with self.assertRaises(HTTPException):
                provider.create_experiment_adapter(owner_id='alice', task_id='task2')
            self.assertEqual(selected.call_count, 1)
