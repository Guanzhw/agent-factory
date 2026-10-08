"""External invocation durability and existing stop-only cleanup; no GPU or PG."""
import asyncio
import builtins
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts/research_candidate_recovery.py'
spec = importlib.util.spec_from_file_location('candidate_recovery', SCRIPT)
assert spec is not None and spec.loader is not None
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


class CandidateImportSafetyTests(unittest.TestCase):
    def test_absent_fcntl_allows_discovery_but_denies_journal_execution(self):
        original = builtins.__import__
        def without_fcntl(name, *args, **kwargs):
            if name == 'fcntl':
                raise ImportError('Synthetic unsupported platform')
            return original(name, *args, **kwargs)
        loaded = importlib.util.module_from_spec(spec)
        with patch.object(builtins, '__import__', side_effect=without_fcntl):
            spec.loader.exec_module(loaded)
        self.assertIsNone(loaded.fcntl)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                with loaded.CandidateJournal(Path(directory)/'candidate.json',
                        identity={key: 'a'*64 for key in loaded.IDENTITY}, total_seconds=1):
                    self.fail('Unsupported platform accepted a journal')
            self.assertEqual(list(Path(directory).iterdir()), [])


@unittest.skipUnless(sys.platform == 'linux', 'Linux monotonic boot identity and file locks')
class CandidateJournalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'candidate.json'
        self.identity = dict(zip(sorted(helper.IDENTITY), ['a' * 64, 'b' * 64, 'c' * 64], strict=True))

    def journal(self, **kwargs):
        return helper.CandidateJournal(self.path, identity=self.identity, **kwargs)

    def completed(self, journal, stage='training'):
        journal.record_progress(stage, {**dict(zip(helper.PROGRESS_IDS,
            ['request', 'task', 'plan', 'run', 'lease', 'job', 'artifact'], strict=True)),
            'phase': 'IMPORTED' if stage == 'preparation' else 'COMPLETED', 'cleanupConfirmed': True})
        journal.finish_stage(stage, {'status': 'COMPLETED', 'cleanupConfirmed': True})

    def test_durable_reopen_keeps_deadline_and_is_stop_only(self):
        with patch.object(helper.time, 'monotonic', return_value=100):
            with self.journal(total_seconds=10) as journal:
                journal.begin_stage('training')
                journal.record_progress('training', {'taskId': 'task', 'phase': 'TASK_ACCEPTED'})
                original = journal.snapshot()
                self.assertTrue(journal.fresh)
        with patch.object(helper.time, 'monotonic', return_value=103):
            with self.journal() as reopened:
                self.assertFalse(reopened.fresh)
                self.assertEqual(reopened.snapshot(), original)
                self.assertEqual(reopened.remaining(), 7)
                for stage in ('training', 'evaluation'):
                    with self.assertRaises(ValueError):
                        reopened.begin_stage(stage)
                reopened.record_progress('training', {'phase': 'STOPPED', 'cleanupConfirmed': False})
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.path.with_name('candidate.json.lock').stat().st_mode), 0o600)

    def test_each_stage_consumed_before_interruption_never_retried(self):
        with self.assertRaises(KeyboardInterrupt):
            with self.journal(total_seconds=60) as journal:
                journal.begin_stage('training')
                raise KeyboardInterrupt
        with self.journal() as journal:
            self.assertTrue(journal.snapshot()['stages']['training']['consumed'])
            with self.assertRaises(ValueError):
                journal.begin_stage('training')

    def test_completed_training_required_and_attempts_bounded(self):
        with self.journal(total_seconds=60) as journal:
            with self.assertRaises(ValueError):
                journal.begin_stage('evaluation')
            journal.begin_stage('preparation')
            journal.record_progress('preparation', {'phase': 'ACCEPTED', 'taskId': 'task', 'planId': 'plan'})
            self.completed(journal, 'preparation')
            journal.begin_stage('training')
            with self.assertRaises(ValueError):
                journal.begin_stage('training')
            with self.assertRaises(ValueError):
                journal.finish_stage('training', {'status': 'COMPLETED', 'cleanupConfirmed': True})
            self.completed(journal)
            journal.begin_stage('evaluation')
            with self.assertRaises(ValueError):
                journal.begin_stage('evaluation')

    def test_recovery_can_confirm_cleanup_without_rewriting_outcome(self):
        with self.journal(total_seconds=60) as journal:
            journal.begin_stage('training')
            journal.record_progress('training', {'phase': 'STOPPED'})
            journal.finish_stage('training', {'status': 'STOPPED', 'cleanupConfirmed': False})
        with self.journal() as journal:
            journal.finish_stage('training', {'status': 'STOPPED', 'cleanupConfirmed': True})
            with self.assertRaises(ValueError):
                journal.finish_stage('training', {'status': 'STOPPED', 'cleanupConfirmed': False})
            with self.assertRaises(ValueError):
                journal.finish_stage('training', {'status': 'COMPLETED', 'cleanupConfirmed': True})
            self.assertEqual(journal.snapshot()['stages']['training']['result']['status'], 'STOPPED')

    def test_changed_identity_budget_and_exclusive_lock_rejected(self):
        with self.journal(total_seconds=60):
            with self.assertRaises(BlockingIOError):
                with self.journal():
                    self.fail('Second writer acquired the lock')
        changed = {**self.identity, 'configSha256': 'd' * 64}
        with self.assertRaises(ValueError):
            with helper.CandidateJournal(self.path, identity=changed):
                pass
        with self.assertRaises(ValueError):
            with self.journal(total_seconds=61):
                pass

    def test_progress_ids_never_replace_and_arbitrary_fields_not_retained(self):
        with self.journal(total_seconds=60) as journal:
            journal.begin_stage('training')
            journal.record_progress('training', {'taskId': 'task', 'nativeRunId': 'run',
                'phase': 'TASK_ACCEPTED', 'arbitraryOutput': 'synthetic forbidden detail'})
            for key in ('taskId', 'nativeRunId'):
                with self.assertRaises(ValueError):
                    journal.record_progress('training', {key: 'replacement'})
            journal.record_progress('training', {'taskId': None, 'phase': 'STOPPED',
                                                  'cancelRequested': True, 'cleanupConfirmed': True})
            journal.record_progress('training', {'cancelRequested': False, 'cleanupConfirmed': False})
            row = journal.snapshot()['stages']['training']['progress']
            self.assertEqual(row['taskId'], 'task')
            self.assertTrue(row['cancelRequested'])
            self.assertTrue(row['cleanupConfirmed'])
            self.assertNotIn('arbitraryOutput', row)
            with self.assertRaises(ValueError):
                journal.record_progress('training', {'phase': 'STARTED'})
            with self.assertRaises(ValueError):
                journal.record_progress('training', {'phase': 'unbounded diagnostic text'})

    def test_expiry_and_boot_change_deny_newwork_but_allow_stop_record(self):
        with patch.object(helper.time, 'monotonic', return_value=100):
            with self.journal(total_seconds=2) as journal:
                journal.begin_stage('training')
                with patch.object(helper.time, 'monotonic', return_value=103):
                    with self.assertRaises(ValueError):
                        journal.remaining()
                    journal.record_progress('training', {'phase': 'STOPPED', 'cleanupConfirmed': False})
        with patch.object(helper, '_boot', return_value='0' * 36):
            with self.journal() as journal:
                with self.assertRaises(ValueError):
                    journal.remaining()
                journal.finish_stage('training', {'status': 'UNKNOWN', 'cleanupConfirmed': False})

    def test_missing_journal_cannot_reset_existing_lock_or_budget(self):
        with self.journal(total_seconds=60):
            pass
        self.path.unlink()
        with self.assertRaises(ValueError):
            with self.journal(total_seconds=60):
                self.fail('Deleted custody was recreated')

    def test_symlink_hardlink_and_public_file_are_rejected(self):
        with self.journal(total_seconds=60):
            pass
        original = self.path.read_bytes()
        other = self.path.with_name('other.json')
        other.write_bytes(original)
        other.chmod(0o600)
        self.path.unlink()
        self.path.symlink_to(other)
        with self.assertRaises(OSError):
            with self.journal():
                pass
        self.path.unlink()
        os.link(other, self.path)
        with self.assertRaises(ValueError):
            with self.journal():
                pass
        self.path.unlink()
        self.path.write_bytes(original)
        self.path.chmod(0o644)
        with self.assertRaises(ValueError):
            with self.journal():
                pass

    def test_external_replacement_or_lock_change_stops_writer(self):
        with self.journal(total_seconds=60) as journal:
            replacement = self.path.with_name('replace.json')
            replacement.write_bytes(self.path.read_bytes())
            replacement.chmod(0o600)
            replacement.replace(self.path)
            with self.assertRaises(ValueError):
                journal.begin_stage('training')
        with self.journal() as journal:
            lock = self.path.with_name('candidate.json.lock')
            lock.unlink()
            lock.touch(mode=0o600)
            with self.assertRaises(ValueError):
                journal.snapshot()

    def test_atomic_write_failure_does_not_consume_uncommitted_stage(self):
        with self.journal(total_seconds=60) as journal:
            with patch.object(helper.os, 'replace', side_effect=OSError('synthetic interruption before replace')):
                with self.assertRaises(OSError):
                    journal.begin_stage('training')
            self.assertFalse(journal.snapshot()['stages']['training']['consumed'])
            self.assertEqual(list(self.path.parent.glob('*.tmp')), [])
        with self.journal() as journal:
            with self.assertRaises(ValueError):
                journal.begin_stage('training')

    def test_corrupt_schema_and_duplicate_json_never_reinitialize(self):
        with self.journal(total_seconds=60):
            pass
        body = json.loads(self.path.read_bytes())
        body['deadlineMonotonic'] += 10
        self.path.write_text(json.dumps(body))
        with self.assertRaises(ValueError):
            with self.journal(total_seconds=60):
                pass
        self.path.write_text('{"schema":1,"schema":1}')
        with self.assertRaises(ValueError):
            with self.journal(total_seconds=60):
                pass


class OriginalRecoveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.task = {'id': 'task', 'owner_id': 'owner', 'run_id': 'run'}
        self.store = SimpleNamespace(task=Mock(return_value=self.task), request_cancel=Mock())
        self.state = {'store': self.store}
        self.lease = {'id': 'lease', 'ownerId': 'owner', 'localTaskId': 'task', 'nativeRunId': 'run',
            'state': 'RECLAIMED', 'capacityHeld': False, 'stopEvidence': {'allStopped': True},
            'gpuEvidence': {'state': 'RELEASED'}, 'cancelAck': 'unknown', 'releaseAck': 'unknown'}
        self.runtime = SimpleNamespace(_original=Mock(return_value={'task_id': 'task', 'owner_id': 'owner',
            'native_run_id': 'run', 'lease_id': 'lease'}), observe_lease=AsyncMock(return_value=self.lease),
            submit=Mock(side_effect=AssertionError('Recovery must never dispatch')))

    async def test_existing_original_cleanup_released_without_submit_or_ack_change(self):
        result = await helper.recover_original(self.state, self.runtime, 'owner', 'task', .1)
        self.assertEqual(result, {'cancelRequested': True, 'cleanupConfirmed': True, 'leaseId': 'lease'})
        self.store.request_cancel.assert_called_once_with('task')
        self.runtime.observe_lease.assert_awaited_once_with('lease')
        self.runtime.submit.assert_not_called()
        self.assertEqual(self.lease['cancelAck'], 'unknown')
        self.assertEqual(self.lease['releaseAck'], 'unknown')

    async def test_unknown_and_async_timeout_preserve_unconfirmed_original(self):
        self.lease.update(state='UNKNOWN', capacityHeld=True, stopEvidence={})
        result = await helper.recover_original(self.state, self.runtime, 'owner', 'task', .04)
        self.assertFalse(result['cleanupConfirmed'])
        self.assertEqual(result['leaseId'], 'lease')
        self.assertTrue(self.lease['capacityHeld'])
        async def blocked(*args):
            await asyncio.sleep(10)
        self.runtime.observe_lease.side_effect = blocked
        result = await helper.recover_original(self.state, self.runtime, 'owner', 'task', .02)
        self.assertFalse(result['cleanupConfirmed'])
        self.runtime.submit.assert_not_called()

    async def test_wrong_owner_or_mapping_never_dispatches_or_claims_cleanup(self):
        self.task['owner_id'] = 'other'
        result = await helper.recover_original(self.state, self.runtime, 'owner', 'task', .1)
        self.assertFalse(result['cleanupConfirmed'])
        self.store.request_cancel.assert_not_called()
        self.runtime.observe_lease.assert_not_awaited()
        self.task['owner_id'] = 'owner'
        self.runtime._original.return_value['native_run_id'] = 'other'
        result = await helper.recover_original(self.state, self.runtime, 'owner', 'task', .1)
        self.assertFalse(result['cleanupConfirmed'])
        self.runtime.observe_lease.assert_not_awaited()

    async def test_caller_cancellation_waits_for_original_cleanup_then_propagates(self):
        entered, finish = asyncio.Event(), asyncio.Event()
        async def observed(*args):
            entered.set()
            await finish.wait()
            return self.lease
        self.runtime.observe_lease.side_effect = observed
        task = asyncio.create_task(helper.recover_original(self.state, self.runtime, 'owner', 'task', .5))
        await entered.wait()
        task.cancel()
        await asyncio.sleep(.01)
        self.assertFalse(task.done())
        finish.set()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.runtime.observe_lease.assert_awaited_once_with('lease')
        self.runtime.submit.assert_not_called()

    async def test_repeated_cancellation_cannot_close_lifespan_before_cleanup(self):
        entered, finish = asyncio.Event(), asyncio.Event()
        async def observed(*args):
            entered.set()
            await finish.wait()
            return self.lease
        self.runtime.observe_lease.side_effect = observed
        task = asyncio.create_task(helper.recover_original(self.state, self.runtime, 'owner', 'task', .5))
        await entered.wait()
        for _ in range(3):
            task.cancel()
            await asyncio.sleep(.01)
            self.assertFalse(task.done())
        finish.set()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.runtime.observe_lease.assert_awaited_once_with('lease')
        self.runtime.submit.assert_not_called()

    async def test_invalid_cleanup_budget_never_touches_original(self):
        for budget in (0, -1, 6, float('nan'), True):
            with self.assertRaises(ValueError):
                await helper.recover_original(self.state, self.runtime, 'owner', 'task', budget)
        self.store.task.assert_not_called()
