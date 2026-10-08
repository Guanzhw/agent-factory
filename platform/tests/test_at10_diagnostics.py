"""Deterministic public-only AT10 timing and fixture polling contracts."""
import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from inference_tree_worker import TimingRecorder, OneShotAuthorityProfile


class TimingRecorderTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'timings.json'
        self.recorder = TimingRecorder(self.path)

    def test_aggregate_elapsed_and_max_without_recording_arguments(self):
        with patch('inference_tree_worker.time.monotonic', side_effect=[10., 10.25, 20., 20.75]):
            with self.recorder.measure('authority'):
                pass
            with self.recorder.measure('authority'):
                pass
        self.assertEqual(json.loads(self.path.read_text()), {
            'authority': {'count': 2, 'seconds': 1., 'maxSeconds': .75, 'cancelled': 0}})
        self.assertFalse(self.path.with_suffix('.tmp').exists())

    def test_cancellation_preserves_signal_and_records_bound_evidence(self):
        signal = asyncio.CancelledError('Synthetic reason must never enter diagnostics')
        with self.assertRaises(asyncio.CancelledError) as caught:
            with patch('inference_tree_worker.time.monotonic', side_effect=[10., 70.]):
                with self.recorder.measure('cli'):
                    raise signal
        self.assertIs(caught.exception, signal)
        self.assertEqual(json.loads(self.path.read_text()), {
            'cli': {'count': 1, 'seconds': 60., 'maxSeconds': 60., 'cancelled': 1}})

    def test_failure_type_and_content_do_not_enter_diagnostics(self):
        with self.assertRaisesRegex(ValueError, 'synthetic-sensitive-content'):
            with self.recorder.measure('authority:execution'):
                raise ValueError('synthetic-sensitive-content')
        self.assertNotIn('synthetic-sensitive-content', self.path.read_text())
        self.assertEqual(json.loads(self.path.read_text())['authority:execution']['count'], 1)

    def test_setup_and_selection_labels_record_total_and_max(self):
        for label in ('container-setup', 'experiment-setup', 'model-selection'):
            with self.subTest(label=label):
                with patch('inference_tree_worker.time.monotonic', side_effect=[10., 13., 20., 21.]):
                    with self.recorder.measure(label):
                        pass
                    with self.recorder.measure(label):
                        pass
                self.assertEqual(json.loads(self.path.read_text())[label],
                    {'count': 2, 'seconds': 4., 'maxSeconds': 3., 'cancelled': 0})

    def test_reject_dynamic_labels_before_creating_evidence(self):
        with self.assertRaisesRegex(ValueError, 'fixed and public'):
            with self.recorder.measure('cli:dynamic-argument'):
                self.fail('Invalid label entered measurement')
        self.assertFalse(self.path.exists())


class AuthorityProfileTests(unittest.TestCase):
    def test_one_shot_profile_exports_only_bounded_code_statistics(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'authority.profile.json'
            profile = OneShotAuthorityProfile(path)
            calls = []
            def synthetic_authority(argument):
                calls.append(argument)
                return 'synthetic-result'
            self.assertEqual(profile.call(synthetic_authority, 'never-export-this'), 'synthetic-result')
            first = path.read_bytes()
            self.assertEqual(profile.call(synthetic_authority, 'second-private-argument'), 'synthetic-result')
            self.assertEqual(path.read_bytes(), first, 'Only the first callback may be profiled')
            self.assertEqual(len(calls), 2, 'Profiling must not skip current-authority callbacks')
            raw = first.decode()
            self.assertNotIn('never-export-this', raw)
            self.assertNotIn('second-private-argument', raw)
            self.assertNotIn(str(Path(__file__).resolve().parent), raw)
            functions = json.loads(raw)['functions']
            self.assertLessEqual(len(functions), 20)
            self.assertTrue(any(row['function'] == 'synthetic_authority' for row in functions))
            for row in functions:
                self.assertEqual(set(row), {'file', 'function', 'calls', 'primitiveCalls', 'cumulativeSeconds'})
                self.assertEqual(row['file'], Path(row['file']).name)

    def test_profile_preserves_exception_without_exporting_its_text(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'authority.profile.json'
            profile = OneShotAuthorityProfile(path)
            failure = ValueError('never-export-this')
            def synthetic_denial():
                raise failure
            with self.assertRaises(ValueError) as raised:
                profile.call(synthetic_denial)
            self.assertIs(raised.exception, failure)
            self.assertNotIn('never-export-this', path.read_text())


class LifecycleEvidenceTests(unittest.TestCase):
    def test_allowlisted_snapshot_omits_payloads_and_error_text(self):
        from test_actual_inference_tree import lifecycle_evidence
        store = Mock()
        task = {'id': 'synthetic-task', 'owner_id': 'alice', 'run_id': 'synthetic-run', 'terminal': False,
                'body': {'secret': 'never-export-this'}, 'request_id': 'never-export-this'}
        store.sql.side_effect = [[task], [{'id': 'attempt', 'state': 'UNKNOWN', 'body': 'never-export-this'}]]
        store.events.return_value = [{'id': 1, 'type': 'tool_failed', 'message': 'never-export-this',
            'data': {'errorType': 'CancelledError', 'error': 'never-export-this', 'payload': {'secret': 'never-export-this'}}}]
        store.native_db.get_job.return_value = {'id': 'synthetic-run', 'status': 'cancelled',
            'last_error': 'Run exceeded timeout_seconds=60 never-export-this', 'payload': {'token': 'never-export-this'}}
        with patch('agent_factory.inference_wait.read', return_value={'state': 'WAITING', 'deadline': 'synthetic-time',
                'body': 'never-export-this', 'executionOwner': {'token': 'never-export-this'}}):
            result = lifecycle_evidence(store)
        self.assertNotIn('never-export-this', json.dumps(result))
        saved = result['tasks'][0]
        self.assertEqual(saved['nativeQueue'], {'id': 'synthetic-run', 'status': 'cancelled', 'errorKind': 'timeout'})
        self.assertEqual(saved['events'][0]['data'], {'errorType': 'CancelledError'})
        self.assertEqual(saved['usageAttempts'], [{'id': 'attempt', 'state': 'UNKNOWN'}])

    def test_read_failures_record_type_without_exception_text(self):
        from test_actual_inference_tree import lifecycle_evidence
        store = Mock()
        store.sql.side_effect = [[{'id': 'synthetic-task', 'run_id': 'synthetic-run'}], []]
        store.events.return_value = []
        store.native_db.get_job.side_effect = ValueError('never-export-this')
        with patch('agent_factory.inference_wait.read', side_effect=RuntimeError('never-export-this')):
            result = lifecycle_evidence(store)
        self.assertNotIn('never-export-this', json.dumps(result))
        self.assertEqual(result['tasks'][0]['nativeQueue'], {'errorType': 'ValueError'})
        self.assertEqual(result['tasks'][0]['inferenceWait'], {'errorType': 'RuntimeError'})


if __name__ == '__main__':
    unittest.main()
