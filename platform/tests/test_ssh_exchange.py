"""Actual local pipe/process tests, also intended for the real Windows runner."""
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from unittest.mock import patch

from agent_factory.ssh_exchange import exchange, SSHExchangeCancelled, SSHExchangeCleanupError


class SSHExchangeTests(unittest.TestCase):
    def process(self, program):
        process = subprocess.Popen([sys.executable, '-I', '-S', '-c', program],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
        def cleanup():
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
            process.stdin.close()
            process.stdout.close()
        self.addCleanup(cleanup)
        return process

    def assert_closed(self, process):
        self.assertIsNotNone(process.poll())
        self.assertTrue(process.stdin.closed)
        self.assertTrue(process.stdout.closed)

    def test_simultaneous_backpressure_and_exact_response_cap(self):
        before = set(threading.enumerate())
        process = self.process("import sys; sys.stdout.buffer.write(b'o'*131072); sys.stdout.buffer.flush(); data=sys.stdin.buffer.read(); sys.stdout.buffer.write(data)")
        payload = b'i' * 32768
        output = exchange(process, payload, deadline=time.monotonic() + 5, max_output=131072 + len(payload))
        self.assertEqual(output, b'o' * 131072 + payload)
        self.assert_closed(process)
        self.assertEqual(set(threading.enumerate()), before)

    def test_short_writes_preserve_every_byte(self):
        process = self.process('import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())')
        actual = os.write
        with patch('agent_factory.ssh_exchange.os.write', side_effect=lambda fd, data: actual(fd, data[:7])):
            result = exchange(process, b'abc' * 100, deadline=time.monotonic() + 5, max_output=300)
        self.assertEqual(result, b'abc' * 100)
        self.assert_closed(process)

    def test_stalled_input_or_output_and_process_alive_after_eof_are_bounded(self):
        for program, payload in (
            ('import time; time.sleep(10)', b'x' * 32768),
            ('import sys,time; sys.stdin.buffer.read(); time.sleep(10)', b'x'),
            ('import os,time; os.close(1); time.sleep(10)', b''),
        ):
            with self.subTest(program=program):
                process = self.process(program)
                start = time.monotonic()
                with self.assertRaises(TimeoutError):
                    exchange(process, payload, deadline=start + .3, max_output=32)
                self.assertLess(time.monotonic() - start, 2)
                self.assert_closed(process)

    def test_overflow_and_nonzero_exit_fail(self):
        for program, error in (("import sys; sys.stdin.buffer.read(); sys.stdout.buffer.write(b'x'*33)", ValueError),
                               ('import sys; sys.stdin.buffer.read(); sys.exit(7)', subprocess.CalledProcessError)):
            with self.subTest(program=program):
                process = self.process(program)
                with self.assertRaises(error):
                    exchange(process, b'', deadline=time.monotonic() + 5, max_output=32)
                self.assert_closed(process)

    def test_expired_deadline_and_invalid_input_still_reap(self):
        for payload, deadline, error in ((b'', time.monotonic() - 1, TimeoutError),
                                         (b'x' * 32769, time.monotonic() + 5, ValueError)):
            with self.subTest(error=error):
                process = self.process('import time; time.sleep(10)')
                with self.assertRaises(error):
                    exchange(process, payload, deadline=deadline, max_output=32)
                self.assert_closed(process)

    def test_pipe_configuration_failure_still_reaps(self):
        process = self.process('import time; time.sleep(10)')
        with patch('agent_factory.ssh_exchange.os.set_blocking', side_effect=OSError('fixture')):
            with self.assertRaises(OSError):
                exchange(process, b'', deadline=time.monotonic() + 5, max_output=32)
        self.assert_closed(process)

    def test_guard_rejection_or_cancellation_before_eof_does_not_complete_request(self):
        for cancel in (False, True):
            with self.subTest(cancel=cancel), TemporaryDirectory() as folder:
                marker = Path(folder) / 'completed'
                process = self.process(f'import sys,pathlib; sys.stdin.buffer.read(); pathlib.Path({str(marker)!r}).write_text("completed")')
                stopped, calls = threading.Event(), []
                def guard():
                    calls.append(True)
                    if len(calls) == 2:
                        if cancel:
                            stopped.set()
                        else:
                            raise PermissionError('revoked')
                with self.assertRaises(SSHExchangeCancelled if cancel else PermissionError):
                    exchange(process, b'x', deadline=time.monotonic() + 5, max_output=32,
                             before_write=guard, cancelled=stopped)
                self.assertFalse(marker.exists())
                self.assert_closed(process)

    def test_cancellation_while_waiting_for_output_reaps_without_io_thread(self):
        process = self.process('import sys,time; sys.stdin.buffer.read(); time.sleep(10)')
        stopped = threading.Event()
        timer = threading.Timer(.2, stopped.set)
        timer.start()
        try:
            with self.assertRaises(SSHExchangeCancelled):
                exchange(process, b'x', deadline=time.monotonic() + 5, max_output=32, cancelled=stopped)
        finally:
            timer.join(timeout=1)
        self.assertFalse(timer.is_alive())
        self.assert_closed(process)

    def test_unconfirmed_reap_is_explicit_and_never_waits_without_timeout(self):
        process = self.process('import time; time.sleep(10)')
        with patch.object(process, 'wait', side_effect=subprocess.TimeoutExpired('ssh', 5)) as wait:
            with self.assertRaises(SSHExchangeCleanupError):
                exchange(process, b'', deadline=time.monotonic() - 1, max_output=32)
            wait.assert_called_once_with(timeout=5)
        process.wait(timeout=5)
        self.assert_closed(process)

    def test_async_guard_is_rejected_without_awaiting(self):
        process = self.process('import sys; sys.stdin.buffer.read()')
        async def guard():
            self.fail('must not execute async guard')
        with self.assertRaisesRegex(TypeError, 'SYNC_GUARD'):
            exchange(process, b'x', deadline=time.monotonic() + 5, max_output=32, before_write=guard)
        self.assert_closed(process)

    def test_guard_that_crosses_deadline_cannot_write(self):
        process = self.process('import time; time.sleep(10)')
        with patch('agent_factory.ssh_exchange.os.write', wraps=os.write) as write:
            with self.assertRaises(TimeoutError):
                exchange(process, b'x', deadline=time.monotonic() + .05, max_output=32,
                         before_write=lambda: time.sleep(.1))
            write.assert_not_called()
        self.assert_closed(process)

    def test_inherited_output_does_not_extend_deadline(self):
        with TemporaryDirectory() as folder:
            pid = Path(folder) / 'grandchild.pid'
            process = self.process('import subprocess,sys,pathlib; child=subprocess.Popen([sys.executable,"-I","-S","-c","import time; time.sleep(.6)"]); '
                                   f'pathlib.Path({str(pid)!r}).write_text(str(child.pid))')
            start = time.monotonic()
            with self.assertRaises(TimeoutError):
                exchange(process, b'', deadline=start + .3, max_output=32)
            self.assertLess(time.monotonic() - start, .6)
            self.assert_closed(process)
            # The fixture descendant is deliberately short-lived; no product tree killer.
            time.sleep(.7)
