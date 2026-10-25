"""Actual Windows process/handle tests; Linux collection is explicitly skipped."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch
import threading
import time
import unittest

from agent_factory.ssh_exchange import exchange, SSHExchangeCancelled
from agent_factory.windows_ssh_process import WindowsSSHProcess


@unittest.skipUnless(sys.platform == 'win32', 'Requires actual Windows process, Job and handle-list APIs')
class WindowsSSHProcessTests(unittest.TestCase):
    def process(self, program, *args, cwd=None):
        return WindowsSSHProcess([sys.executable, '-I', '-S', '-c', program, *args], dict(os.environ), cwd=cwd)

    def test_suspended_until_resume_then_exact_pipe_roundtrip(self):
        with TemporaryDirectory() as folder:
            marker = Path(folder) / 'ran'
            with self.process('import sys,pathlib; pathlib.Path(sys.argv[1]).write_text("ran"); '
                              'sys.stdout.buffer.write(sys.stdin.buffer.read())', str(marker)) as process:
                self.assertFalse(marker.exists())
                self.assertIsNone(process.poll())
                with self.assertRaises(subprocess.TimeoutExpired):
                    process.wait(timeout=.02)
                self.assertFalse(marker.exists())
                process.resume()
                self.assertEqual(exchange(process, b'controlled input', deadline=time.monotonic() + 5,
                                          max_output=1024), b'controlled input')
                self.assertEqual(process.poll(), 0)
                with self.assertRaisesRegex(ValueError, 'NOT_SUSPENDED'):
                    process.resume()
            self.assertTrue(marker.exists())
            self.assertTrue(process.stdin.closed)
            self.assertTrue(process.stdout.closed)
            process.close()

    def test_unrelated_inheritable_handle_never_reaches_child(self):
        import ctypes
        from ctypes import wintypes as wt
        import win32api
        import win32con
        import win32event
        import pywintypes
        attributes = pywintypes.SECURITY_ATTRIBUTES()
        attributes.bInheritHandle = True
        sentinel = win32event.CreateEvent(attributes, True, False, None)
        try:
            self.assertTrue(win32api.GetHandleInformation(sentinel) & win32con.HANDLE_FLAG_INHERIT)
            program = ('import ctypes,json,sys; from ctypes import wintypes as w; '
                       'k=ctypes.WinDLL("kernel32",use_last_error=True); '
                       'k.SetEvent.argtypes=[w.HANDLE]; k.SetEvent.restype=w.BOOL; '
                       'ok=bool(k.SetEvent(int(sys.argv[1]))); '
                       'print(json.dumps({"canaryInherited":ok}))')
            with self.process(program, str(int(sentinel))) as process:
                kernel = ctypes.WinDLL('kernel32', use_last_error=True)
                kernel.GetHandleInformation.argtypes = [wt.HANDLE, ctypes.POINTER(wt.DWORD)]
                kernel.GetHandleInformation.restype = wt.BOOL
                import msvcrt
                for pipe in (process.stdin, process.stdout):
                    flags = wt.DWORD()
                    self.assertTrue(kernel.GetHandleInformation(msvcrt.get_osfhandle(pipe.fileno()), ctypes.byref(flags)))
                    self.assertEqual(flags.value & win32con.HANDLE_FLAG_INHERIT, 0)
                process.resume()
                result = exchange(process, b'', deadline=time.monotonic() + 5, max_output=1024)
                self.assertFalse(json.loads(result)['canaryInherited'])
            self.assertEqual(win32event.WaitForSingleObject(sentinel, 0), win32con.WAIT_TIMEOUT)
        finally:
            sentinel.Close()

    def test_concurrent_scopes_do_not_cross_stdio(self):
        start = threading.Barrier(2)
        def run(payload):
            start.wait(timeout=5)
            with self.process('import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())') as process:
                process.resume()
                return exchange(process, payload, deadline=time.monotonic() + 5, max_output=32768)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(run, b'a' * 32768)
            second = pool.submit(run, b'b' * 32768)
            self.assertEqual(first.result(timeout=10), b'a' * 32768)
            self.assertEqual(second.result(timeout=10), b'b' * 32768)

    def test_cancelled_exchange_reaps_before_scope_close(self):
        stopped = threading.Event()
        with self.process('import sys,time; sys.stdin.buffer.read(); time.sleep(60)') as process:
            process.resume()
            timer = threading.Timer(.2, stopped.set)
            timer.start()
            try:
                with self.assertRaises(SSHExchangeCancelled):
                    exchange(process, b'x', deadline=time.monotonic() + 5, max_output=1024, cancelled=stopped)
            finally:
                timer.join(timeout=1)
            self.assertIsNotNone(process.poll())
            self.assertTrue(process.stdin.closed)
            self.assertTrue(process.stdout.closed)

    def test_exception_before_exchange_reaps_suspended_or_resumed_child(self):
        import win32api
        import win32con
        import win32event
        for resume in (False, True):
            with self.subTest(resume=resume):
                observed = None
                try:
                    with self.assertRaisesRegex(RuntimeError, 'before exchange'):
                        with self.process('import time; time.sleep(60)') as process:
                            observed = win32api.OpenProcess(win32con.SYNCHRONIZE, False, process.pid)
                            if resume:
                                process.resume()
                            raise RuntimeError('before exchange')
                    self.assertEqual(win32event.WaitForSingleObject(observed, 0), win32con.WAIT_OBJECT_0)
                    self.assertTrue(process.stdin.closed)
                    self.assertTrue(process.stdout.closed)
                    with self.assertRaisesRegex(ValueError, 'CLOSED'):
                        _ = process.process_handle
                finally:
                    if observed is not None:
                        observed.Close()

    def test_scope_close_stops_owned_descendant(self):
        import win32api
        import win32con
        import win32event
        with TemporaryDirectory() as folder:
            pid_file = Path(folder) / 'child.pid'
            child_handle = None
            try:
                with self.process('import subprocess,sys,pathlib,time; '
                    'child=subprocess.Popen([sys.executable,"-I","-S","-c","import time; time.sleep(60)"]); '
                    'pathlib.Path(sys.argv[1]).write_text(str(child.pid)); time.sleep(60)', str(pid_file)) as process:
                    process.resume()
                    deadline = time.monotonic() + 5
                    while not pid_file.exists() and time.monotonic() < deadline:
                        time.sleep(.01)
                    self.assertTrue(pid_file.exists())
                    child_handle = win32api.OpenProcess(win32con.SYNCHRONIZE, False, int(pid_file.read_text()))
                self.assertEqual(win32event.WaitForSingleObject(child_handle, 5000), win32con.WAIT_OBJECT_0)
            finally:
                if child_handle is not None:
                    child_handle.Close()

    def test_assignment_failure_reaps_child_without_resuming(self):
        import win32api
        import win32con
        import win32event
        held = []
        def reject(job, process):
            current = win32api.GetCurrentProcess()
            held.append(win32api.DuplicateHandle(current, process, current, 0, False, win32con.DUPLICATE_SAME_ACCESS))
            raise RuntimeError('controlled job assignment failure')
        try:
            with patch('win32job.AssignProcessToJobObject', side_effect=reject):
                with self.assertRaisesRegex(RuntimeError, 'controlled job assignment failure'):
                    self.process('import time; time.sleep(60)')
            self.assertEqual(len(held), 1)
            self.assertEqual(win32event.WaitForSingleObject(held[0], 0), win32con.WAIT_OBJECT_0)
        finally:
            for handle in held:
                handle.Close()

    def test_spawn_failure_does_not_leak_parent_handles(self):
        import win32api
        import ctypes
        from ctypes import wintypes as wt
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.GetProcessHandleCount.argtypes = [wt.HANDLE, ctypes.POINTER(wt.DWORD)]
        kernel.GetProcessHandleCount.restype = wt.BOOL
        current = win32api.GetCurrentProcess()
        def handle_count():
            count = wt.DWORD()
            if not kernel.GetProcessHandleCount(int(current), ctypes.byref(count)):
                raise ctypes.WinError(ctypes.get_last_error())
            return count.value
        before = handle_count()
        for _ in range(3):
            with self.assertRaises(OSError):
                WindowsSSHProcess([str(Path(sys.executable).parent / 'missing-ssh-fixture.exe')], dict(os.environ))
        self.assertEqual(handle_count(), before)

    def test_unicode_long_child_cwd_reads_relative_identity_without_parent_chdir(self):
        original_cwd = os.getcwd()
        with TemporaryDirectory() as temporary:
            folder = Path(temporary) / ('研究目录-' + 'long-path-' * 12)
            folder.mkdir()
            self.assertGreater(len(str(folder).encode('utf-8')), 100)
            (folder / 'identity').write_text('controlled identity', encoding='utf-8')
            program = ('import json,os,pathlib; '
                       'print(json.dumps({"cwd":os.getcwd(),'
                       '"identity":pathlib.Path("identity").read_text(encoding="utf-8")}))')
            with self.process(program, cwd=str(folder)) as process:
                process.resume()
                result = json.loads(exchange(process, b'', deadline=time.monotonic() + 5, max_output=4096))
                self.assertEqual(Path(result['cwd']).resolve(), folder.resolve())
                self.assertEqual(result['identity'], 'controlled identity')
            self.assertEqual(os.getcwd(), original_cwd)

    def test_wait_requires_explicit_finite_bound(self):
        with self.process('import time; time.sleep(60)') as process:
            for timeout in (None, float('inf'), -1):
                with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                    process.wait(timeout=timeout)
