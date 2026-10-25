"""Disabled-owner original cleanup only; no native process, PG or new effects."""
import asyncio
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException
from agent_factory_research.research_iteration_driver import IterationRoundProvider
import test_research_iteration_driver as fixtures


class RevocationDriverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.DriverTests.setUpClass()

    def setUp(self):
        self.fixture = fixtures.DriverTests('runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.driver, self.store = self.fixture.driver, self.fixture.store
        self.driver.auth.require_member.side_effect = HTTPException(403, 'disabled')
        self.driver.research.iterations._round_for_task = Mock(
            side_effect=lambda *args: deepcopy(self.fixture.round))
        self.driver.research.iterations.round_for_task.side_effect = HTTPException(403, 'disabled')
        self.driver.bridge.find_run = AsyncMock(side_effect=HTTPException(403, 'disabled'))
        self.driver.bridge.find_original_run = AsyncMock(return_value=None)

    def original(self):
        async def same_thread(fn, *args, **kwargs):
            return fn(*args, **kwargs)
        with patch('agent_factory_research.research_iteration_driver.asyncio.to_thread', same_thread):
            return asyncio.run(self.driver.observe_original('alice', self.fixture.round))

    def test_disabled_owner_observes_stop_without_promotion_or_execution(self):
        self.driver.verified_evaluation = Mock(side_effect=AssertionError('No promotion during cleanup'))
        result = self.original()
        self.assertEqual(result, {'taskId': 'task', 'runId': 'native', 'state': 'stopped', 'failed': True})
        self.driver.auth.require_member.assert_not_called()
        self.driver.research.iterations.round_for_task.assert_not_called()
        self.store.lifecycle_observer.observe_root.assert_awaited_once_with('task')
        self.driver.bridge.submit.assert_not_awaited()
        self.driver.commands.submit.assert_not_awaited()
        self.driver.verified_evaluation.assert_not_called()

    def test_public_observe_and_cancel_still_require_current_membership(self):
        for method in (self.driver.observe, self.driver.cancel):
            with self.assertRaises(HTTPException):
                asyncio.run(method('alice', self.fixture.round))
        self.store.lifecycle_observer.observe_root.assert_not_awaited()
        self.driver.commands.submit.assert_not_awaited()

    def test_internal_receipt_recovery_never_uses_public_finder_or_submit(self):
        self.fixture.task.update(run_id=None, terminal=False, admission='unknown')
        self.fixture.native = None
        self.driver.bridge.find_original_run.return_value = {'run_id': 'original-native'}
        self.store.accept.side_effect = lambda task, run: self.fixture.task.update(run_id=run)
        result = self.original()
        self.assertEqual(result['state'], 'unknown')
        self.assertEqual(result['runId'], 'original-native')
        self.driver.bridge.find_original_run.assert_awaited_once_with('task', 'alice')
        self.driver.bridge.find_run.assert_not_awaited()
        self.driver.bridge.submit.assert_not_awaited()

    def test_missing_original_receipt_stays_unknown(self):
        self.fixture.task.update(run_id=None, terminal=False, admission='unknown')
        self.assertEqual(self.original()['state'], 'unknown')
        self.store.accept.assert_not_called()
        self.driver.bridge.submit.assert_not_awaited()

    def test_no_run_stop_uses_historical_rejection_and_all_positive_proofs(self):
        self.fixture.task.update(run_id=None, admission='rejected', terminal=True)
        self.fixture.round.update(dispatchAttempted=True, dispatchRejected=True)
        self.fixture.effects = []
        self.assertEqual(self.original()['state'], 'stopped')
        self.fixture.round.pop('dispatchRejected')
        self.assertEqual(self.original()['state'], 'unknown')
        self.driver.research.iterations.round_for_task.assert_not_called()

    def test_active_unknown_or_retained_custody_does_not_become_stopped(self):
        self.fixture.native['status'] = 'running'
        self.assertEqual(self.original()['state'], 'unknown')
        self.fixture.native['status'] = 'completed'
        self.fixture.effects[0]['status'] = 'UNKNOWN'
        self.assertEqual(self.original()['state'], 'unknown')
        self.fixture.effects[0]['status'] = 'DONE'
        self.store.process_runtime = SimpleNamespace(task_held=Mock(return_value=True))
        self.assertEqual(self.original()['state'], 'unknown')

    def test_wrong_historical_owner_plan_or_round_is_rejected(self):
        for changed in ({'ownerId': 'bob'}, {'planSha256': 'f' * 64}, {'id': 'replacement-round'}):
            with self.subTest(changed=changed):
                self.driver.research.iterations._round_for_task.side_effect = None
                self.driver.research.iterations._round_for_task.return_value = self.fixture.round | changed
                with self.assertRaises(HTTPException):
                    self.original()
        self.driver.bridge.submit.assert_not_awaited()
        self.store.lifecycle_observer.observe_root.assert_not_awaited()

    def provider(self):
        return IterationRoundProvider(research=self.driver.research, driver=self.driver,
            binary=Path('/unused'), source_archive=Path('/unused'), git_binary=Path('/unused'), python_binary=Path('/unused'))

    def test_cleanup_adapter_uses_original_lookup_and_forwards_execution_denial(self):
        deny = Mock(side_effect=PermissionError('Cleanup forbids new work'))
        with patch('agent_factory_research.research_iteration_driver.IterationORXProvider') as selected:
            adapter = self.provider().create_experiment_adapter(owner_id='alice', task_id='task',
                cleanup_only=True, authorize=deny, scope=Path('/original'))
            selected.return_value.create_experiment_adapter.assert_called_once_with(
                owner_id='alice', task_id='task', cleanup_only=True, authorize=deny, scope=Path('/original'))
            self.assertIs(adapter, selected.return_value.create_experiment_adapter.return_value)
            self.assertEqual(selected.call_args.kwargs['recipe'], 'seed')
        self.driver.research.iterations.round_for_task.assert_not_called()
        deny.assert_not_called()

    def test_ordinary_provider_cannot_use_internal_lookup_to_bypass_revocation(self):
        with patch('agent_factory_research.research_iteration_driver.IterationORXProvider') as selected:
            with self.assertRaises(HTTPException):
                self.provider().create_experiment_adapter(owner_id='alice', task_id='task', cleanup_only=False)
            selected.assert_not_called()
        self.driver.research.iterations._round_for_task.assert_not_called()

    def test_promoted_cleanup_keeps_historical_previous_artifact_verification(self):
        verified = self.driver.verified_evaluation('alice', self.fixture.round)
        baseline = {**verified['sourcePin'], 'metricValue': 0.0,
            'evaluationArtifactId': verified['evaluation']['artifactId'],
            'evaluationSha256': verified['evaluation']['sha256']}
        successor = {**self.fixture.round, 'id': 'round2', 'ordinal': 2,
            'previousRoundId': 'round1', 'taskId': 'task2', 'baselineSource': baseline}
        original_task = self.store.task.side_effect
        self.store.task.side_effect = lambda task, *args: (
            {**self.fixture.task, 'id': 'task2'} if task == 'task2' else original_task(task, *args))
        lookup = self.driver.research.iterations._round_for_task
        lookup.side_effect = lambda owner, task: deepcopy(successor if task == 'task2' else self.fixture.round)
        with patch('agent_factory_research.research_iteration_driver.IterationORXProvider') as selected:
            self.provider().create_experiment_adapter(owner_id='alice', task_id='task2', cleanup_only=True)
            self.assertEqual(selected.call_args.kwargs['recipe'], 'promoted')
            self.assertEqual([call.args for call in lookup.call_args_list], [('alice', 'task2'), ('alice', 'task')])
            self.fixture.artifacts['evaluation'][0]['sha256'] = 'b' * 64
            with self.assertRaises(HTTPException):
                self.provider().create_experiment_adapter(owner_id='alice', task_id='task2', cleanup_only=True)
            self.assertEqual(selected.call_count, 1)
        self.driver.research.iterations.round_for_task.assert_not_called()

    def test_cleanup_adapter_rejects_changed_original_recipe_before_construction(self):
        self.driver.research.iterations._round_for_task.side_effect = None
        changed = deepcopy(self.fixture.round)
        changed['baselineSource']['datasetSha256'] = 'b' * 64
        self.driver.research.iterations._round_for_task.return_value = changed
        with patch('agent_factory_research.research_iteration_driver.IterationORXProvider') as selected:
            with self.assertRaises(HTTPException):
                self.provider().create_experiment_adapter(owner_id='alice', task_id='task', cleanup_only=True)
            selected.assert_not_called()
