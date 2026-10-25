"""Owned Windows system-SSH process; no credentials or remote execution policy."""
import ctypes
from ctypes import wintypes as wt
import math
import os
import subprocess
import sys
import threading


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


def _kernel():
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
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


class WindowsSSHProcess:
    """Construct suspended and job-assigned; resume only after caller authority checks."""
    def __init__(self, args, env):
        if sys.platform != 'win32':
            raise OSError('WINDOWS_SSH_PROCESS_REQUIRES_WINDOWS')
        import pywintypes
        import win32api
        import win32con
        import win32event
        import win32job
        import win32process
        import msvcrt
        self._api, self._con, self._event = win32api, win32con, win32event
        self._jobs, self._processes = win32job, win32process
        self._lock = threading.RLock()
        self._job = self._process = self._thread = None
        self._assigned = self._closed = self._resumed = False
        self.stdin = self.stdout = None
        self.pid = None
        self.returncode = None
        child_handles = []
        try:
            self._job = win32job.CreateJobObject(None, None)
            win32api.SetHandleInformation(self._job, win32con.HANDLE_FLAG_INHERIT, 0)
            limits = win32job.QueryInformationJobObject(self._job, win32job.JobObjectExtendedLimitInformation)
            limits['BasicLimitInformation']['LimitFlags'] = win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            win32job.SetInformationJobObject(self._job, win32job.JobObjectExtendedLimitInformation, limits)

            def child_end(fd):
                try:
                    current = win32api.GetCurrentProcess()
                    handle = win32api.DuplicateHandle(current, msvcrt.get_osfhandle(fd), current,
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
            child_error = child_end(os.open(os.devnull, os.O_WRONLY | os.O_BINARY))
            kernel = _kernel()
            size = ctypes.c_size_t()
            kernel.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
            attributes = ctypes.create_string_buffer(size.value)
            if not kernel.InitializeProcThreadAttributeList(attributes, 1, 0, ctypes.byref(size)):
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                handles = (wt.HANDLE * 3)(child_input, child_output, child_error)
                if not kernel.UpdateProcThreadAttribute(attributes, 0, 0x00020002, handles,
                                                       ctypes.sizeof(handles), None, None):
                    raise ctypes.WinError(ctypes.get_last_error())
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
                                             environment, None, ctypes.byref(startup), ctypes.byref(info)):
                    raise ctypes.WinError(ctypes.get_last_error())
                self._process = pywintypes.HANDLE(info.hProcess)
                self._thread = pywintypes.HANDLE(info.hThread)
                self.pid = info.dwProcessId
                win32job.AssignProcessToJobObject(self._job, self._process)
                self._assigned = True
            finally:
                kernel.DeleteProcThreadAttributeList(attributes)
        except BaseException:
            self.close()
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
            return int(self._process)

    def resume(self):
        with self._lock:
            if self._closed or self._resumed:
                raise ValueError('WINDOWS_SSH_PROCESS_NOT_SUSPENDED')
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
                for pipe in (self.stdin, self.stdout):
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
