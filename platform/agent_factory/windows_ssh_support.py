"""Windows-only file and pipe primitives for the fixed SSH credential carrier."""
from collections.abc import Buffer
import ctypes
from ctypes import wintypes as wt
import os
import time
import sys
from typing import cast

import pywintypes
import win32api
import win32con
import win32event
import win32file
import win32pipe
import win32process
import win32security


class Reject(Exception):
    def __init__(self, code, checks=None):
        super().__init__(code)
        self.checks = checks


def sid(process=None):
    token = cast(pywintypes.HANDLEType, win32security.OpenProcessToken(
        process or win32api.GetCurrentProcess(), win32con.TOKEN_QUERY))
    try:
        return win32security.ConvertSidToStringSid(win32security.GetTokenInformation(int(token), win32security.TokenUser)[0])
    finally:
        token.Close()


def attributes():
    user = sid()
    descriptor = win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(
        f'O:{user}D:P(A;;FA;;;{user})', win32security.SDDL_REVISION_1)
    result = pywintypes.SECURITY_ATTRIBUTES()
    result.SECURITY_DESCRIPTOR = descriptor
    result.bInheritHandle = False
    return result


def verify(path, handle=None):
    if win32file.GetFileAttributes(str(path)) & win32con.FILE_ATTRIBUTE_REPARSE_POINT:
        raise Reject('REPARSE')
    flags = win32security.OWNER_SECURITY_INFORMATION | win32security.DACL_SECURITY_INFORMATION
    actual = (win32security.GetSecurityInfo(handle, win32security.SE_FILE_OBJECT, flags)
              if handle is not None else win32security.GetNamedSecurityInfo(str(path), win32security.SE_FILE_OBJECT, flags))
    expected = attributes().SECURITY_DESCRIPTOR
    render = win32security.ConvertSecurityDescriptorToStringSecurityDescriptor
    if render(actual, 1, flags) != render(expected, 1, flags):
        raise Reject('DACL')


def directory(path):
    win32file.CreateDirectory(str(path), attributes())
    verify(path)


def write_private(path, encrypted):
    handle = win32file.CreateFile(str(path), win32con.GENERIC_WRITE, 0, attributes(), win32con.CREATE_NEW, 0, None)
    try:
        verify(path, handle)
        win32file.WriteFile(handle.handle, encrypted)
        win32file.FlushFileBuffers(handle.handle)
    finally:
        handle.Close()


def alive(handle):
    return win32event.WaitForSingleObject(handle, 0) == win32con.WAIT_TIMEOUT


def process(pid):
    return cast(pywintypes.HANDLEType, win32api.OpenProcess(
        win32con.PROCESS_QUERY_INFORMATION | win32con.SYNCHRONIZE, False, pid))


def created(handle):
    return win32process.GetProcessTimes(handle)['CreationTime']


def image(handle) -> str:
    if sys.platform != 'win32':
        raise OSError('WINDOWS_SSH_REQUIRED')
    query = ctypes.WinDLL('kernel32', use_last_error=True).QueryFullProcessImageNameW
    query.argtypes, query.restype = [wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)], wt.BOOL
    length = wt.DWORD(32768)
    buffer = ctypes.create_unicode_buffer(length.value)
    if not query(int(handle), 0, buffer, ctypes.byref(length)):
        raise ctypes.WinError(ctypes.get_last_error())
    return os.path.normcase(os.path.realpath(buffer.value))


def parent_pid(handle) -> int:
    if sys.platform != 'win32':
        raise OSError('WINDOWS_SSH_REQUIRED')
    # The fixed two-hop check needs only this process's original parent PID.
    class Basic(ctypes.Structure):
        _fields_ = [('reserved', wt.LPVOID), ('peb', wt.LPVOID), ('reserved2', wt.LPVOID * 2),
                    ('pid', ctypes.c_size_t), ('parent', ctypes.c_size_t)]
    query = ctypes.WinDLL('ntdll').NtQueryInformationProcess
    query.argtypes = [wt.HANDLE, wt.ULONG, wt.LPVOID, wt.ULONG, wt.LPVOID]
    query.restype = wt.LONG
    data = Basic()
    if query(int(handle), 0, ctypes.byref(data), ctypes.sizeof(data), None) != 0:
        raise Reject('PROCESS_PARENT_QUERY')
    return data.parent


def pipe_pid(handle, client) -> int:
    if sys.platform != 'win32':
        raise OSError('WINDOWS_SSH_REQUIRED')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    fn = kernel.GetNamedPipeClientProcessId if client else kernel.GetNamedPipeServerProcessId
    fn.argtypes, fn.restype = [wt.HANDLE, ctypes.POINTER(wt.ULONG)], wt.BOOL
    pid = wt.ULONG()
    if not fn(int(handle), ctypes.byref(pid)):
        raise ctypes.WinError(ctypes.get_last_error())
    return pid.value


def check_client(pipe, root, root_pid, helper_path, python_path, venv_path):
    client = process(pipe_pid(pipe, True))
    handles = [client]
    try:
        if sid(client) != sid() or not alive(root) or not alive(client):
            raise Reject('CLIENT_OWNER_OR_LIFETIME')
        expected_helper = os.path.normcase(os.path.realpath(helper_path))
        expected_python = os.path.normcase(os.path.realpath(python_path))
        expected_venv = os.path.normcase(os.path.realpath(venv_path))
        if image(client) == expected_helper:
            launcher = client
            shape = 'direct'
        elif image(client) == expected_python:
            launcher = process(parent_pid(client))
            handles.append(launcher)
            checks = {'parentIsHelper': image(launcher) == expected_helper,
                      'parentIsVenvPython': image(launcher) == expected_venv,
                      'parentAlive': alive(launcher),
                      'parentBeforeClient': created(launcher) <= created(client)}
            if not checks['parentAlive'] or not checks['parentBeforeClient']:
                raise Reject('LAUNCHER_IDENTITY', checks)
            if checks['parentIsHelper']:
                shape = 'launcher-python'
            elif checks['parentIsVenvPython'] and expected_venv != expected_python:
                redirector = launcher
                launcher = process(parent_pid(redirector))
                handles.append(launcher)
                checks.update({'redirectorParentIsHelper': image(launcher) == expected_helper,
                               'redirectorParentAlive': alive(launcher),
                               'redirectorParentBeforeChild': created(launcher) <= created(redirector)})
                if not all(checks[key] for key in ('redirectorParentIsHelper', 'redirectorParentAlive',
                                                  'redirectorParentBeforeChild')):
                    raise Reject('LAUNCHER_IDENTITY', checks)
                shape = 'launcher-venv-python'
            else:
                raise Reject('LAUNCHER_IDENTITY', checks)
        else:
            raise Reject('CLIENT_IMAGE')
        if parent_pid(launcher) != root_pid or created(root) > created(launcher):
            raise Reject('ROOT_IDENTITY')
        return shape, pipe_pid(pipe, True)
    finally:
        for handle in handles:
            handle.Close()


def connect(pipe, deadline, cancelled=None):
    if time.monotonic() >= deadline or (cancelled is not None and cancelled.is_set()):
        raise TimeoutError('PIPE_DEADLINE')
    overlapped = pywintypes.OVERLAPPED()
    event = cast(pywintypes.HANDLEType, win32event.CreateEvent(None, True, False, None))
    overlapped.hEvent = int(event)
    try:
        try:
            win32pipe.ConnectNamedPipe(pipe, overlapped)
        except pywintypes.error as exc:
            if exc.winerror == 535:  # Already connected.
                return
            if exc.winerror != 997:
                raise
        wait_io(pipe, overlapped, deadline, cancelled)
    finally:
        event.Close()


def wait_io(pipe, overlapped, deadline, cancelled):
    while time.monotonic() < deadline and not (cancelled is not None and cancelled.is_set()):
        milliseconds = max(0, min(50, int((deadline - time.monotonic()) * 1000)))
        if win32event.WaitForSingleObject(overlapped.hEvent, milliseconds) == win32con.WAIT_OBJECT_0:
            return win32file.GetOverlappedResult(pipe, overlapped, False)
    win32file.CancelIo(pipe)
    if win32event.WaitForSingleObject(overlapped.hEvent, 3000) != win32con.WAIT_OBJECT_0:
        raise TimeoutError('PIPE_CANCEL_INCOMPLETE')
    raise TimeoutError('PIPE_DEADLINE')


def transfer(pipe, deadline, payload=None, size=64, cancelled=None):
    if time.monotonic() >= deadline or (cancelled is not None and cancelled.is_set()):
        raise TimeoutError('PIPE_DEADLINE')
    overlapped = pywintypes.OVERLAPPED()
    event = cast(pywintypes.HANDLEType, win32event.CreateEvent(None, True, False, None))
    overlapped.hEvent = int(event)
    try:
        if payload is None:
            buffer = win32file.AllocateReadBuffer(size)
            win32file.ReadFile(pipe, buffer, overlapped)
        else:
            win32file.WriteFile(pipe, payload, overlapped)
        count = wait_io(pipe, overlapped, deadline, cancelled)
        if payload is not None:
            return payload[:count]
        return bytes(memoryview(cast(Buffer, buffer))[:count])
    finally:
        event.Close()


def server_pipe(name):
    return cast(pywintypes.HANDLEType, win32pipe.CreateNamedPipe(name,
        win32pipe.PIPE_ACCESS_DUPLEX | win32con.FILE_FLAG_OVERLAPPED | 0x00080000,
        win32pipe.PIPE_TYPE_MESSAGE | win32pipe.PIPE_READMODE_MESSAGE | 8,  # PIPE_REJECT_REMOTE_CLIENTS
        1, 128, 128, 0, attributes()))


def client_pipe(name):
    return win32file.CreateFile(name, win32con.GENERIC_READ | win32con.GENERIC_WRITE, 0,
                               None, win32con.OPEN_EXISTING, win32con.FILE_FLAG_OVERLAPPED, None)

