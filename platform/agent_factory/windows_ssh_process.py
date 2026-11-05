"""Owned Windows process used by system SSH and personal CLI execution."""
import ctypes
from ctypes import wintypes as wt
import math
import os
import subprocess
import sys
import threading
from typing import Callable, cast


class _StartupInfo(ctypes.Structure):
    _fields_ = [('cb', wt.DWORD), ('lpReserved', wt.LPWSTR), ('lpDesktop', wt.LPWSTR),
        ('lpTitle', wt.LPWSTR), ('dwX', wt.DWORD), ('dwY', wt.DWORD),
        ('dwXSize', wt.DWORD), ('dwYSize', wt.DWORD), ('dwXCountChars', wt.DWORD),
        ('dwYCountChars', wt.DWORD), ('dwFillAttribute', wt.DWORD), ('dwFlags', wt.DWORD),
        ('wShowWindow', wt.WORD), ('cbReserved2', wt.WORD), ('lpReserved2', ctypes.POINTER(ctypes.c_byte)),
        ('hStdInput', wt.HANDLE), ('hStdOutput', wt.HANDLE), ('hStdError', wt.HANDLE)]


class _StartupInfoEx(ctypes.Structure):
    _fields_ = [('StartupInfo', _StartupInfo), ('lpAttributeList', wt.LPVOID)]


class _ProcessInfo(ctypes.Structure):
    _fields_ = [('hProcess', wt.HANDLE), ('hThread', wt.HANDLE), ('dwProcessId', wt.DWORD), ('dwThreadId', wt.DWORD)]


def _kernel() -> ctypes.CDLL:
    if sys.platform != 'win32':
        raise OSError('WINDOWS_SSH_PROCESS_REQUIRES_WINDOWS')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [wt.LPVOID, wt.LPCWSTR]
    kernel.CreateJobObjectW.restype = wt.HANDLE
    kernel.InitializeProcThreadAttributeList.argtypes = [wt.LPVOID, wt.DWORD, wt.DWORD, ctypes.POINTER(ctypes.c_size_t)]
    kernel.InitializeProcThreadAttributeList.restype = wt.BOOL
    kernel.UpdateProcThreadAttribute.argtypes = [wt.LPVOID, wt.DWORD, ctypes.c_size_t, wt.LPVOID,
                                               ctypes.c_size_t, wt.LPVOID, ctypes.POINTER(ctypes.c_size_t)]
    kernel.UpdateProcThreadAttribute.restype = wt.BOOL
    kernel.DeleteProcThreadAttributeList.argtypes = [wt.LPVOID]
    kernel.DeleteProcThreadAttributeList.restype = None
    kernel.CreateProcessW.argtypes = [wt.LPCWSTR, wt.LPWSTR, wt.LPVOID, wt.LPVOID, wt.BOOL, wt.DWORD,
                                    wt.LPVOID, wt.LPCWSTR, ctypes.POINTER(_StartupInfoEx), ctypes.POINTER(_ProcessInfo)]
    kernel.CreateProcessW.restype = wt.BOOL
    return kernel


def _os_handle(fd: int) -> int:
    if sys.platform == 'win32':
        import msvcrt
        return msvcrt.get_osfhandle(fd)
    raise OSError('WINDOWS_SSH_PROCESS_REQUIRES_WINDOWS')


def _binary_flag() -> int:
    if sys.platform == 'win32':
        return os.O_BINARY
    raise OSError('WINDOWS_SSH_PROCESS_REQUIRES_WINDOWS')


def _error() -> OSError:
    if sys.platform == 'win32':
        return ctypes.WinError(ctypes.get_last_error())
    return OSError('WINDOWS_SSH_PROCESS_REQUIRES_WINDOWS')


class WindowsProcessCreateError(OSError):
    """Creation failed before resume, and the suspended process was reaped."""


class WindowsSSHProcess:
    """Construct suspended and job-assigned; resume only after caller authority checks."""
    def __init__(self, args: list[str], env: dict[str, str], *, cwd: str | None = None,
                 capture_stderr: bool = False):
        kernel = _kernel()
        import pywintypes
        import win32api
        import win32con
        import win32event
        import win32job
        import win32process
        handle_from_raw = cast("Callable[[int], pywintypes.HANDLEType]", pywintypes.HANDLE)
        self._api, self._con, self._event = win32api, win32con, win32event
        self._jobs, self._processes = win32job, win32process
        self._lock = threading.RLock()
        self._job = self._process = self._thread = None
        self._assigned = self._closed = self._resumed = False
        self.stdin = self.stdout = self.stderr = None
        self.pid = None
        self.returncode = None
        child_handles = []
        try:
            raw_job = kernel.CreateJobObjectW(None, None)
            if not raw_job:
                raise _error()
            self._job = handle_from_raw(raw_job)
            win32api.SetHandleInformation(int(self._job), win32con.HANDLE_FLAG_INHERIT, 0)
            limits = win32job.QueryInformationJobObject(int(self._job), win32job.JobObjectExtendedLimitInformation)
            limits['BasicLimitInformation']['LimitFlags'] = win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            win32job.SetInformationJobObject(int(self._job), win32job.JobObjectExtendedLimitInformation, limits)

            def child_end(fd):
                try:
                    current = win32api.GetCurrentProcess()
                    handle = win32api.DuplicateHandle(current, _os_handle(fd), current,
                        0, True, win32con.DUPLICATE_SAME_ACCESS)
                    child_handles.append(handle)
                    return int(handle)
                finally:
                    os.close(fd)

            input_read, input_write = os.pipe()
            self.stdin = os.fdopen(input_write, 'wb', buffering=0)
            child_input = child_end(input_read)
            output_read, output_write = os.pipe()
            self.stdout = os.fdopen(output_read, 'rb', buffering=0)
            child_output = child_end(output_write)
            if capture_stderr:
                error_read, error_write = os.pipe()
                self.stderr = os.fdopen(error_read, 'rb', buffering=0)
                child_error = child_end(error_write)
            else:
                child_error = child_end(os.open(os.devnull, os.O_WRONLY | _binary_flag()))
            size = ctypes.c_size_t()
            kernel.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
            attributes = ctypes.create_string_buffer(size.value)
            if not kernel.InitializeProcThreadAttributeList(attributes, 1, 0, ctypes.byref(size)):
                raise _error()
            try:
                handles = (wt.HANDLE * 3)(child_input, child_output, child_error)
                if not kernel.UpdateProcThreadAttribute(attributes, 0, 0x00020002, handles,
                                                       ctypes.sizeof(handles), None, None):
                    raise _error()
                startup = _StartupInfoEx()
                startup.StartupInfo.cb = ctypes.sizeof(startup)
                startup.StartupInfo.dwFlags = win32con.STARTF_USESTDHANDLES
                startup.StartupInfo.hStdInput = child_input
                startup.StartupInfo.hStdOutput = child_output
                startup.StartupInfo.hStdError = child_error
                startup.lpAttributeList = ctypes.cast(attributes, wt.LPVOID)
                command = ctypes.create_unicode_buffer(subprocess.list2cmdline(args))
                environment = ctypes.create_unicode_buffer('\0'.join(f'{key}={value}' for key, value in
                    sorted(env.items(), key=lambda pair: pair[0].upper())) + '\0\0')
                info = _ProcessInfo()
                flags = (win32con.CREATE_SUSPENDED | win32con.CREATE_NO_WINDOW |
                         win32con.CREATE_UNICODE_ENVIRONMENT | 0x00080000)
                if not kernel.CreateProcessW(args[0], command, None, None, True, flags,
                                             environment, cwd, ctypes.byref(startup), ctypes.byref(info)):
                    raise _error()
                self._process = handle_from_raw(info.hProcess)
                self._thread = handle_from_raw(info.hThread)
                self.pid = info.dwProcessId
                win32job.AssignProcessToJobObject(int(self._job), int(self._process))
                self._assigned = True
            finally:
                kernel.DeleteProcThreadAttributeList(attributes)
        except BaseException as error:
            self.close()
            if isinstance(error, Exception):
                # A caller may release an undispatched effect only after this
                # cleanup returned. A cleanup failure retains its own error.
                raise WindowsProcessCreateError('WINDOWS_PROCESS_CREATE_FAILED') from None
            raise
        finally:
            for handle in child_handles:
                handle.Close()

    @property
    def process_handle(self):
        """Borrowed original handle, valid only while this scope remains open."""
        with self._lock:
            if self._closed:
                raise ValueError('WINDOWS_SSH_PROCESS_CLOSED')
            assert self._process is not None
            return int(self._process)

    def resume(self):
        with self._lock:
            if self._closed or self._resumed:
                raise ValueError('WINDOWS_SSH_PROCESS_NOT_SUSPENDED')
            assert self._thread is not None
            self._processes.ResumeThread(self._thread)
            self._resumed = True
            self._thread.Close()
            self._thread = None

    def poll(self):
        with self._lock:
            if self._process is not None and self._event.WaitForSingleObject(self._process, 0) == self._con.WAIT_OBJECT_0:
                self.returncode = self._processes.GetExitCodeProcess(self._process)
            return self.returncode

    def wait(self, timeout):
        if timeout is None or not math.isfinite(timeout) or timeout < 0:
            raise ValueError('WINDOWS_SSH_WAIT_REQUIRES_FINITE_TIMEOUT')
        with self._lock:
            if self._closed:
                if self.returncode is None:
                    raise RuntimeError('WINDOWS_SSH_REAP_UNCONFIRMED')
                return self.returncode
            current = self._api.GetCurrentProcess()
            held = self._api.DuplicateHandle(current, self._process, current, 0, False, self._con.DUPLICATE_SAME_ACCESS)
        try:
            status = self._event.WaitForSingleObject(held, min(math.ceil(timeout * 1000), 0xFFFFFFFE))
            if status == self._con.WAIT_TIMEOUT:
                raise subprocess.TimeoutExpired('ssh', timeout)
            if status != self._con.WAIT_OBJECT_0:
                raise OSError('WINDOWS_SSH_WAIT_FAILED')
            self.returncode = self._processes.GetExitCodeProcess(held)
            return self.returncode
        finally:
            held.Close()

    def kill(self):
        with self._lock:
            if not self._closed and self._job is not None:
                self._jobs.TerminateJobObject(self._job, 1)

    def job_active_processes(self) -> int:
        """Observe the original Job while its owned handle is still open."""
        with self._lock:
            if self._closed or self._job is None:
                raise ValueError('WINDOWS_SSH_PROCESS_CLOSED')
            return self._jobs.QueryInformationJobObject(
                self._job, self._jobs.JobObjectBasicAccountingInformation)['ActiveProcesses']

    def close(self):
        with self._lock:
            if self._closed:
                return
            try:
                if self._process is not None and not self._assigned:
                    self._api.TerminateProcess(self._process, 1)
                if self._job is not None:
                    self._job.Close()
                    self._job = None
                if self._process is not None:
                    self.wait(timeout=5)
            finally:
                self._closed = True
                for pipe in (self.stdin, self.stdout, self.stderr):
                    if pipe is not None:
                        pipe.close()
                for handle in (self._thread, self._process):
                    if handle is not None:
                        handle.Close()
                self._thread = self._process = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
