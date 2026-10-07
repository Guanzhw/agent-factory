"""Stop-only CLI routing controls with synthetic original native identities."""
from contextlib import ExitStack
from copy import deepcopy
import importlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, Mock, patch

SCRIPTS = str(Path(__file__).resolve().parents[2] / 'scripts')
with patch.object(sys, 'path', [SCRIPTS, *sys.path]):
    subject = importlib.import_module('research_candidate_recover_command')


class CandidateRecoverCommandTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(sys, 'path', [SCRIPTS, *sys.path]))
        self.config = {'workspace': '/synthetic/candidate', 'requestId': 'candidate-attempt'}
        self.inputs = {'identity': {'configSha256': 'a' * 64, 'candidateSha256': 'b' * 64,
                                    'baselineManifestSha256': 'c' * 64},
                       'baselineConfig': {'databaseUrlFile': '/synthetic/private-dsn'}}
        self.row = {'consumed': True, 'progress': {}, 'result': None}
        self.body = {'identity': self.inputs['identity'], 'stages': {'training': self.row}}
        self.journal = Mock(fresh=False, snapshot=Mock(side_effect=lambda: deepcopy(self.body)))
        self.task = {'id': 'original-task', 'plan_id': 'original-plan', 'run_id': 'original-native',
            'request_id': 'candidate-attempt:training:instance', 'owner_id': 'alice', 'terminal': False}
        self.lease = {'id': 'original-lease', 'providerJobId': 'original-process',
            'connectionRef': 'training', 'state': 'RUNNING', 'capacityHeld': True}
        self.ticket = {}
        self.store = Mock(task_for_request=Mock(return_value=self.task), task=Mock(return_value=self.task))
        self.runtime = Mock(_original=Mock(return_value={'lease_id': 'original-lease'}),
                            _custody=Mock(side_effect=lambda _: (self.lease, object(), self.task, self.ticket)))
        self.resources = Mock(targets={})
        self.state = {'store': self.store, 'resources': self.resources, 'research_runtime': self.runtime,
                      'process_runtime': Mock(), 'lifecycle_observer': Mock()}
        baseline = importlib.import_module('run_research_baseline')
        bootstrap = importlib.import_module('bootstrap_research_control')
        reopen = importlib.import_module('research_candidate_reopen')
        state_module = importlib.import_module('research_candidate_state')
        recovery = importlib.import_module('research_candidate_recovery')
        native = importlib.import_module('research_candidate_native_stop')
        self.stack.enter_context(patch.object(bootstrap, 'read_database_url', return_value='postgresql://synthetic/unused'))
        self.stack.enter_context(patch.object(baseline, 'read_private', return_value=b'{"stage":"training"}'))
        self.write = self.stack.enter_context(patch.object(baseline, 'write_private'))
        self.rebuild = self.stack.enter_context(patch.object(reopen, 'reconstruct_research_target',
                                                            return_value={'target': object()}))
        opened = self.stack.enter_context(patch.object(state_module, 'open_state'))
        opened.return_value.__enter__.return_value = self.state
        self.original = self.stack.enter_context(patch.object(recovery, 'recover_original', new=AsyncMock(
            return_value={'leaseId': 'original-lease', 'cleanupConfirmed': True})))
        self.native = self.stack.enter_context(patch.object(native, 'cancel_native_original',
            new=AsyncMock(return_value={'nativeCleanupConfirmed': True, 'terminalStatus': 'canceled'})))

    def run_recovery(self):
        return subject.recover(self.config, self.inputs, self.journal)

    def test_lost_ack_uses_exact_request_binding_and_original_stop(self):
        report = self.run_recovery()
        self.store.task_for_request.assert_called_once_with('candidate-attempt:training:instance', 'alice')
        self.state['lifecycle_observer']._binding.assert_called_once_with(self.task)
        self.original.assert_awaited_once_with(self.state, self.runtime, 'alice', 'original-task', 5)
        self.native.assert_awaited_once()
        expected = self.native.await_args.args[2]
        self.assertEqual(expected['nativeRunId'], 'original-native')
        self.assertEqual(expected['planId'], 'original-plan')
        self.assertTrue(report['cleanupConfirmed'])
        self.assertEqual(report['stages']['training']['status'], 'STOPPED')
        self.assertFalse(report['trainingResumed'])
        self.assertEqual(report['newAttempts'], 0)
        self.store.observed.assert_called_once_with(self.task, 'canceled', True)
        self.runtime.submit.assert_not_called()

    def test_mismatched_original_ids_cannot_cancel(self):
        for field in ('taskId', 'planId', 'nativeRunId', 'leaseId', 'providerJobId'):
            with self.subTest(field=field):
                self.row['progress'] = {field: 'different-original'}
                report = self.run_recovery()
                self.assertFalse(report['cleanupConfirmed'])
                self.assertEqual(report['stages']['training']['status'], 'UNKNOWN')
        self.original.assert_not_awaited()
        self.native.assert_not_awaited()
        self.store.observed.assert_not_called()

    def test_completed_original_is_checked_without_cancel(self):
        self.row['result'] = {'status': 'COMPLETED', 'cleanupConfirmed': True}
        self.task['terminal'] = True
        self.lease.update(state='RECLAIMED', capacityHeld=False, stopEvidence={'allStopped': True},
                          executionStatus='COMPLETED', exitCode=0, gpuEvidence={'state': 'RELEASED'})
        self.ticket.update(status='completed', persistedRunStatus='completed')
        report = self.run_recovery()
        self.assertTrue(report['cleanupConfirmed'])
        self.assertEqual(report['stages']['training']['status'], 'COMPLETED')
        self.original.assert_not_awaited()
        self.native.assert_not_awaited()
        self.journal.finish_stage.assert_not_called()

    def test_completed_projection_cannot_replace_original_native_and_gpu_proof(self):
        self.row['result'] = {'status': 'COMPLETED', 'cleanupConfirmed': True}
        self.task['terminal'] = True
        self.lease.update(state='RECLAIMED', capacityHeld=False, stopEvidence={'allStopped': True},
                          executionStatus='COMPLETED', exitCode=0, gpuEvidence={'state': 'RELEASED'})
        for ticket in ({}, {'status': 'paused', 'persistedRunStatus': 'paused'},
                       {'status': 'completed'}, {'status': 'completed', 'persistedRunStatus': 'paused'}):
            self.ticket.clear(); self.ticket.update(ticket)
            with self.subTest(ticket=ticket):
                self.assertFalse(self.run_recovery()['cleanupConfirmed'])
        self.ticket.update(status='completed', persistedRunStatus='completed')
        self.lease['gpuEvidence'] = {'state': 'UNKNOWN'}
        self.assertFalse(self.run_recovery()['cleanupConfirmed'])
        self.original.assert_not_awaited()
        self.native.assert_not_awaited()

    def test_native_unknown_never_marks_original_terminal(self):
        self.native.return_value = {'nativeCleanupConfirmed': False}
        report = self.run_recovery()
        self.assertFalse(report['cleanupConfirmed'])
        self.assertEqual(report['stages']['training']['status'], 'UNKNOWN')
        self.store.observed.assert_not_called()

    def test_compute_unknown_never_marks_original_terminal(self):
        self.original.return_value = {'leaseId': 'original-lease', 'cleanupConfirmed': False}
        report = self.run_recovery()
        self.assertFalse(report['cleanupConfirmed'])
        self.assertEqual(report['stages']['training']['status'], 'UNKNOWN')
        self.store.observed.assert_not_called()

    def test_no_mapping_stops_exact_native_intent_but_compute_remains_unknown(self):
        self.runtime._original.return_value = None
        report = self.run_recovery()
        self.assertFalse(report['cleanupConfirmed'])
        self.original.assert_not_awaited()
        self.native.assert_awaited_once()
        self.store.request_cancel.assert_called_once_with('original-task')
        self.runtime.submit.assert_not_called()
        self.store.observed.assert_not_called()

    def test_unconsumed_stage_never_reconstructs_or_looks_up(self):
        self.row['consumed'] = False
        report = self.run_recovery()
        self.assertEqual(report['stages'], {})
        self.assertFalse(report['cleanupConfirmed'])
        self.rebuild.assert_not_called()
        self.store.task_for_request.assert_not_called()

    def test_private_report_redacts_exception_and_uses_new_receipt(self):
        self.rebuild.side_effect = ValueError('/synthetic/private/path synthetic-secret')
        report = self.run_recovery()
        path, raw = self.write.call_args.args
        self.assertTrue(path.name.startswith('recovery-') and path.suffix == '.json')
        self.assertEqual(json.loads(raw), report)
        self.assertNotIn('synthetic-secret', raw.decode())
        self.assertNotIn('/synthetic/private/path', raw.decode())
        self.assertFalse(report['cleanupConfirmed'])

    def test_fresh_or_identity_changed_journal_rejected_before_database(self):
        self.journal.fresh = True
        with self.assertRaises(ValueError):
            self.run_recovery()
        self.journal.fresh = False
        self.body['identity'] = {'configSha256': 'd' * 64}
        with self.assertRaises(ValueError):
            self.run_recovery()
        self.store.task_for_request.assert_not_called()
