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
from agent_factory.windows_ssh_process import WindowsProcessCreateError, WindowsSSHProcess


@unittest.skipUnless(sys.platform == 'win32', 'Requires actual Windows process, Job and handle-list APIs')
class WindowsSSHProcessTests(unittest.TestCase):
    def process(self, program, *args, cwd=None, capture_stderr=False):
        return WindowsSSHProcess([sys.executable, '-I', '-S', '-c', program, *args], dict(os.environ),
                                 cwd=cwd, capture_stderr=capture_stderr)

    def test_stderr_capture_is_optional_and_job_observation_uses_original_handle(self):
        import win32job
        for capture in (False, True):
            with self.subTest(capture=capture):
                with self.process('import os; os.write(1,b"out"); os.write(2,b"err")',
                                  capture_stderr=capture) as process:
                    job = process._job
                    self.assertEqual(process.job_active_processes(), 1)
                    self.assertEqual(win32job.QueryInformationJobObject(
                        job, win32job.JobObjectBasicAccountingInformation)['ActiveProcesses'], 1)
                    process.resume()
                    process.stdin.close()
                    self.assertEqual(process.stdout.read(), b'out')
                    if capture:
                        self.assertEqual(process.stderr.read(), b'err')
                    else:
                        self.assertIsNone(process.stderr)
                    process.wait(timeout=5)
                    self.assertEqual(process.job_active_processes(), 0)
                    self.assertIs(process._job, job)
                if capture:
                    self.assertTrue(process.stderr.closed)
                with self.assertRaisesRegex(ValueError, 'CLOSED'):
                    process.job_active_processes()

    def test_original_job_remains_observable_after_parent_exit_and_repeated_kill(self):
        import win32job
        program = ('import subprocess,sys; subprocess.Popen([sys.executable,"-I","-S","-c",'
                   '"import time;time.sleep(60)"]); print("parent exited",flush=True)')
        with self.process(program, capture_stderr=True) as process:
            job = process._job
            process.resume()
            process.wait(timeout=5)
            self.assertEqual(process.poll(), 0)
            self.assertGreater(process.job_active_processes(), 0)
            process.kill()
            process.kill()
            deadline = time.monotonic() + 5
            while process.job_active_processes() and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertIs(process._job, job)
            self.assertEqual(win32job.QueryInformationJobObject(
                job, win32job.JobObjectBasicAccountingInformation)['ActiveProcesses'], 0)
            self.assertEqual(process.stdout.read().strip(), b'parent exited')
            self.assertEqual(process.stderr.read(), b'')

    def test_captured_stderr_is_closed_after_rejected_creation(self):
        streams = []
        original = os.fdopen
        def record(*args, **kwargs):
            stream = original(*args, **kwargs)
            streams.append(stream)
            return stream
        with patch.object(os, 'fdopen', record):
            with self.assertRaises(WindowsProcessCreateError):
                WindowsSSHProcess([str(Path(sys.executable).parent / 'missing-cli-fixture.exe')],
                                  dict(os.environ), capture_stderr=True)
        self.assertEqual(len(streams), 3)
        self.assertTrue(all(stream.closed for stream in streams))

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
                with self.assertRaisesRegex(WindowsProcessCreateError, 'WINDOWS_PROCESS_CREATE_FAILED'):
                    self.process('import time; time.sleep(60)')
            self.assertEqual(len(held), 1)
            self.assertEqual(win32event.WaitForSingleObject(held[0], 0), win32con.WAIT_OBJECT_0)
        finally:
            for handle in held:
                handle.Close()

    def test_spawn_failure_does_not_leak_parent_handles(self):
        import win32api
        import msvcrt
        import ctypes
        from ctypes import wintypes as wt
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.GetProcessHandleCount.argtypes = [wt.HANDLE, ctypes.POINTER(wt.DWORD)]
        kernel.GetProcessHandleCount.restype = wt.BOOL
        kernel.GetHandleInformation.argtypes = [wt.HANDLE, ctypes.POINTER(wt.DWORD)]
        kernel.GetHandleInformation.restype = wt.BOOL
        current = win32api.GetCurrentProcess()
        def handle_count():
            count = wt.DWORD()
            if not kernel.GetProcessHandleCount(int(current), ctypes.byref(count)):
                raise ctypes.WinError(ctypes.get_last_error())
            return count.value
        from agent_factory import windows_ssh_process as owned
        stages, completed, inventory = [], [], []
        acquired = {'job': [], 'parent': [], 'child': []}
        original_fdopen, original_duplicate = os.fdopen, win32api.DuplicateHandle
        def tracked_fdopen(*args, **kwargs):
            stream = original_fdopen(*args, **kwargs)
            acquired['parent'].append((msvcrt.get_osfhandle(stream.fileno()), stream))
            return stream
        def tracked_duplicate(*args):
            handle = original_duplicate(*args)
            acquired['child'].append(int(handle))
            return handle
        original_error, original_close = owned._error, WindowsSSHProcess.close
        def record(stage):
            saved_error = ctypes.get_last_error()
            try:
                stages.append([stage, handle_count()])
            finally:
                ctypes.set_last_error(saved_error)
        def measured_error():
            record('error.before')
            error = original_error()
            record('error.after')
            return error
        def measured_close(process):
            record('close.before')
            try:
                return original_close(process)
            finally:
                record('close.after')
        original_kernel = owned._kernel
        def measured_kernel():
            native = original_kernel()
            create = native.CreateProcessW
            create_job = native.CreateJobObjectW
            def tracked_job(*args):
                handle = create_job(*args)
                if handle:
                    acquired['job'].append(handle)
                return handle
            native.CreateJobObjectW = tracked_job
            def measured_create(*args):
                record('CreateProcessW.before')
                result = create(*args)
                record('CreateProcessW.after')
                return result
            native.CreateProcessW = measured_create
            return native
        before = handle_count()
        with (patch.object(owned, '_error', measured_error),
              patch.object(owned, '_kernel', measured_kernel),
              patch.object(WindowsSSHProcess, 'close', measured_close),
              patch.object(os, 'fdopen', tracked_fdopen),
              patch.object(win32api, 'DuplicateHandle', tracked_duplicate)):
            for index in range(3):
                for values in acquired.values():
                    values.clear()
                record(f'spawn.{index}.before')
                with self.assertRaises(OSError):
                    WindowsSSHProcess([str(Path(sys.executable).parent / 'missing-ssh-fixture.exe')], dict(os.environ))
                record(f'spawn.{index}.after')
                completed.append(handle_count())
                self.assertEqual({kind: len(values) for kind, values in acquired.items()},
                                 {'job': 1, 'parent': 2, 'child': 3})
                handles = acquired['job'] + acquired['child'] + [raw for raw, _ in acquired['parent']]
                for raw in handles:
                    flags = wt.DWORD()
                    ctypes.set_last_error(0)
                    valid = kernel.GetHandleInformation(raw, ctypes.byref(flags))
                    error = ctypes.get_last_error()
                    self.assertFalse(valid, f'attempt {index}: owned handle {raw} remains open')
                    self.assertEqual(error, 6, f'attempt {index}: expected ERROR_INVALID_HANDLE')
                self.assertTrue(all(stream.closed for _, stream in acquired['parent']))
                inventory.append({'attempt': index, 'closedOwnedHandles': len(handles)})
        after = handle_count()
        control_program = """
import ctypes, json
from ctypes import wintypes as w
kernel = ctypes.WinDLL('kernel32', use_last_error=True)
kernel.GetCurrentProcess.argtypes = []
kernel.GetCurrentProcess.restype = w.HANDLE
kernel.GetProcessHandleCount.argtypes = [w.HANDLE, ctypes.POINTER(w.DWORD)]
kernel.GetProcessHandleCount.restype = w.BOOL
current = kernel.GetCurrentProcess()
def count():
    value = w.DWORD()
    if not kernel.GetProcessHandleCount(current, ctypes.byref(value)):
        raise RuntimeError('control count failed')
    return value.value
counts = [count()]
for _ in range(3):
    ctypes.WinError(2)
    counts.append(count())
print(json.dumps({'winErrorOnly': counts}))
"""
        control = subprocess.run([sys.executable, '-I', '-S', '-c', control_program],
                                 capture_output=True, text=True, timeout=10, check=True)
        native_program = control_program[:control_program.index('counts = [count()]')] + """
import os, sys
class Startup(ctypes.Structure):
    _fields_ = [('cb', w.DWORD), ('lpReserved', w.LPWSTR), ('lpDesktop', w.LPWSTR),
        ('lpTitle', w.LPWSTR), ('dwX', w.DWORD), ('dwY', w.DWORD),
        ('dwXSize', w.DWORD), ('dwYSize', w.DWORD), ('dwXCountChars', w.DWORD),
        ('dwYCountChars', w.DWORD), ('dwFillAttribute', w.DWORD), ('dwFlags', w.DWORD),
        ('wShowWindow', w.WORD), ('cbReserved2', w.WORD), ('lpReserved2', ctypes.POINTER(ctypes.c_byte)),
        ('hStdInput', w.HANDLE), ('hStdOutput', w.HANDLE), ('hStdError', w.HANDLE)]
class Process(ctypes.Structure):
    _fields_ = [('hProcess', w.HANDLE), ('hThread', w.HANDLE), ('pid', w.DWORD), ('tid', w.DWORD)]
kernel.CreateProcessW.argtypes = [w.LPCWSTR, w.LPWSTR, w.LPVOID, w.LPVOID, w.BOOL, w.DWORD,
                                w.LPVOID, w.LPCWSTR, ctypes.POINTER(Startup), ctypes.POINTER(Process)]
kernel.CreateProcessW.restype = w.BOOL
kernel.TerminateProcess.argtypes = [w.HANDLE, w.UINT]
kernel.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
kernel.CloseHandle.argtypes = [w.HANDLE]
missing = os.path.join(os.path.dirname(sys.executable), 'missing-ssh-fixture.exe')
assert not os.path.exists(missing)
counts, errors = [count()], []
for _ in range(3):
    startup, process = Startup(), Process()
    startup.cb = ctypes.sizeof(startup)
    command = ctypes.create_unicode_buffer('"' + missing + '"')
    created = kernel.CreateProcessW(missing, command, None, None, False, 0x08000004,
                                   None, None, ctypes.byref(startup), ctypes.byref(process))
    error = ctypes.get_last_error()
    if created:
        kernel.TerminateProcess(process.hProcess, 1)
        kernel.WaitForSingleObject(process.hProcess, 5000)
        kernel.CloseHandle(process.hThread)
        kernel.CloseHandle(process.hProcess)
        raise AssertionError('missing executable unexpectedly started')
    assert error == 2, error
    errors.append(error)
    counts.append(count())
print(json.dumps({'nativeMissingExecutable': counts, 'errors': errors}))
"""
        native_control = subprocess.run([sys.executable, '-I', '-S', '-c', native_program],
                                        capture_output=True, text=True, timeout=10, check=True)
        evidence = {'coldCounts': [before, after], 'stages': stages, 'owned': inventory,
                    'control': json.loads(control.stdout), 'nativeControl': json.loads(native_control.stdout)}
        print('FAILED_SPAWN_OWNERSHIP ' + json.dumps(evidence))
        self.assertEqual(completed, [completed[0]] * 3, json.dumps(evidence))

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
