"""Pure calibration: diagnostics preserve bounded, redacted observations only."""
import asyncio
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import native_timeout_diagnostics as diagnostics


class ReadOnlyStore:
    def sql(self, *args, **kwargs):
        raise AssertionError('Diagnostics must not acquire a database connection')


class NativeTimeoutDiagnosticsTests(unittest.TestCase):
    def app(self, worker=None):
        return SimpleNamespace(state=SimpleNamespace(queue_worker=worker))

    def test_whitelist_bounds_and_no_external_calls(self):
        secret = 'DO-NOT-EMIT-payload-headers-DSN'
        store = ReadOnlyStore()
        row = dict(id='task', run_id='r' * 300, terminal=False,
                   body=secret, payload=secret, headers=secret, exception=secret)
        worker = SimpleNamespace(worker_id='synthetic-worker', _task=None,
                                 _in_flight={str(index): None for index in range(100)})
        with patch('socket.create_connection', side_effect=AssertionError('network')), \
             patch('subprocess.Popen', side_effect=AssertionError('process')), \
             patch('http.client.HTTPConnection.connect', side_effect=AssertionError('HTTP forbidden')), \
             patch.object(store, 'sql', side_effect=AssertionError('SQL forbidden')) as sql:
            result = diagnostics.snapshot({'store': store}, self.app(worker),
                                          observed_task=row, observed_ticket=row)
        sql.assert_not_called()
        self.assertNotIn(secret, json.dumps(result))
        self.assertEqual(set(result['observedTask']), set(diagnostics.TASK_FIELDS))
        self.assertEqual(len(result['observedTask']['run_id']), diagnostics.MAX_TEXT)
        self.assertEqual(set(result['observedTicket']), set(diagnostics.TICKET_FIELDS))
        self.assertEqual(len(result['worker']['inFlight']), diagnostics.MAX_TASKS)
        self.assertTrue(result['worker']['inFlightTruncated'])
        self.assertFalse(result['freshDatabaseReads'])
        self.assertTrue(result['nonAtomic'])
        self.assertFalse(result['stopProof'])

    def test_real_suspended_coroutine_chain_is_read_without_cancel(self):
        async def exercise():
            gate = asyncio.Event()
            async def inner_wait():
                sensitive_local = 'DO-NOT-EMIT-coroutine-local'
                await gate.wait()
                return sensitive_local
            async def outer_wait():
                return await inner_wait()
            task = asyncio.create_task(outer_wait())
            try:
                await asyncio.sleep(0)
                worker = SimpleNamespace(worker_id='worker', _task=None,
                                         _in_flight={'original-run': task})
                result = diagnostics.snapshot({'store': ReadOnlyStore()}, self.app(worker))
                observed = result['worker']['inFlight'][0]
                names = [frame['function'] for frame in observed['task']['awaitChain']]
                self.assertIn('outer_wait', names)
                self.assertIn('inner_wait', names)
                self.assertEqual(observed['runId'], 'original-run')
                self.assertNotIn('DO-NOT-EMIT', json.dumps(result))
                self.assertFalse(task.done())
                self.assertFalse(task.cancelling())
                gate.set()
                await task
            finally:
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
        asyncio.run(exercise())

    def test_thread_and_frame_bounds_do_not_expose_locals_or_paths(self):
        code = SimpleNamespace(co_filename='/private/DO-NOT-EMIT/frame.py', co_name='bounded')
        frame = SimpleNamespace(f_code=code, f_lineno=12, f_locals={'secret': 'DO-NOT-EMIT'})
        frame.f_back = frame
        with patch.object(diagnostics.sys, '_current_frames',
                          return_value={index: frame for index in range(100)}):
            result = diagnostics.snapshot({'store': ReadOnlyStore()}, self.app())
        self.assertEqual(len(result['threads']), diagnostics.MAX_THREADS)
        self.assertTrue(result['threadsTruncated'])
        self.assertEqual(len(result['threads'][0]['frames']), diagnostics.MAX_FRAMES)
        self.assertTrue(result['threads'][0]['framesTruncated'])
        self.assertNotIn('DO-NOT-EMIT', json.dumps(result))

    def test_await_chain_cycles_are_bounded(self):
        cursor = SimpleNamespace(cr_frame=None)
        cursor.cr_await = cursor
        task = SimpleNamespace(get_coro=lambda: cursor, done=lambda: False, cancelled=lambda: False)
        observed = diagnostics._task(task)
        self.assertEqual(observed['awaitChain'], [])
        self.assertTrue(observed['awaitChainTruncated'])

    def test_diagnostic_errors_do_not_replace_original_assertion(self):
        class BrokenStore:
            def sql(self, statement):
                raise RuntimeError('DO-NOT-EMIT-connection-details')
        worker = SimpleNamespace(worker_id='worker')
        with patch.object(diagnostics.sys, '_current_frames', side_effect=ValueError('DO-NOT-EMIT')):
            result = diagnostics.snapshot({'store': BrokenStore()}, self.app(worker))
        self.assertIsNone(result['observedTask'])
        self.assertEqual(result['worker']['diagnosticErrorType'], 'AttributeError')
        self.assertEqual(result['threadsError']['diagnosticErrorType'], 'ValueError')
        self.assertNotIn('DO-NOT-EMIT', json.dumps(result))
        with self.assertRaisesRegex(AssertionError, 'original native timeout'):
            diagnostics.snapshot({'store': BrokenStore()}, self.app())
            raise AssertionError('original native timeout')


if __name__ == '__main__':
    unittest.main()
