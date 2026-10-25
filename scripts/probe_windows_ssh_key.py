"""Synthetic Windows key-loader experiment; never used by the product runtime."""
import ctypes
from ctypes import wintypes as w
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid


class WindowsFiles:
    def __init__(self):
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.advapi = ctypes.WinDLL('advapi32', use_last_error=True)
        self.bind(self.kernel, 'GetCurrentProcess', [], w.HANDLE)
        self.bind(self.kernel, 'CloseHandle', [w.HANDLE], w.BOOL)
        self.bind(self.kernel, 'LocalFree', [w.HLOCAL], w.HLOCAL)
        self.bind(self.advapi, 'OpenProcessToken', [w.HANDLE, w.DWORD, ctypes.POINTER(w.HANDLE)], w.BOOL)
        self.bind(self.advapi, 'GetTokenInformation', [w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD, ctypes.POINTER(w.DWORD)], w.BOOL)
        self.bind(self.advapi, 'ConvertSidToStringSidW', [w.LPVOID, ctypes.POINTER(w.LPWSTR)], w.BOOL)
        self.bind(self.advapi, 'ConvertStringSecurityDescriptorToSecurityDescriptorW', [w.LPCWSTR, w.DWORD, ctypes.POINTER(w.LPVOID), w.LPVOID], w.BOOL)
        self.bind(self.advapi, 'GetSecurityInfo', [w.HANDLE, ctypes.c_int, w.DWORD, w.LPVOID, w.LPVOID, w.LPVOID, w.LPVOID, ctypes.POINTER(w.LPVOID)], w.DWORD)
        self.bind(self.advapi, 'GetNamedSecurityInfoW', [w.LPCWSTR, ctypes.c_int, w.DWORD, w.LPVOID, w.LPVOID, w.LPVOID, w.LPVOID, ctypes.POINTER(w.LPVOID)], w.DWORD)
        self.bind(self.advapi, 'ConvertSecurityDescriptorToStringSecurityDescriptorW', [w.LPVOID, w.DWORD, w.DWORD, ctypes.POINTER(w.LPWSTR), w.LPVOID], w.BOOL)
        self.bind(self.kernel, 'CreateDirectoryW', [w.LPCWSTR, w.LPVOID], w.BOOL)
        self.bind(self.kernel, 'GetFileAttributesW', [w.LPCWSTR], w.DWORD)
        self.bind(self.kernel, 'CreateFileW', [w.LPCWSTR, w.DWORD, w.DWORD, w.LPVOID, w.DWORD, w.DWORD, w.HANDLE], w.HANDLE)
        self.bind(self.kernel, 'WriteFile', [w.HANDLE, w.LPCVOID, w.DWORD, ctypes.POINTER(w.DWORD), w.LPVOID], w.BOOL)
        self.bind(self.kernel, 'FlushFileBuffers', [w.HANDLE], w.BOOL)
        self.bind(self.kernel, 'GetHandleInformation', [w.HANDLE, ctypes.POINTER(w.DWORD)], w.BOOL)
        token = w.HANDLE()
        self.check(self.advapi.OpenProcessToken(self.kernel.GetCurrentProcess(), 8, ctypes.byref(token)))
        try:
            size = w.DWORD()
            self.advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
            data = ctypes.create_string_buffer(size.value)
            self.check(self.advapi.GetTokenInformation(token, 1, data, size, ctypes.byref(size)))
            sid = ctypes.cast(data, ctypes.POINTER(w.LPVOID))[0]
            text = w.LPWSTR()
            self.check(self.advapi.ConvertSidToStringSidW(sid, ctypes.byref(text)))
            try:
                self.sddl = f'O:{text.value}D:P(A;;FA;;;{text.value})'
            finally:
                self.kernel.LocalFree(ctypes.cast(text, w.HLOCAL))
        finally:
            self.kernel.CloseHandle(token)
        attrs = self.attributes()
        try:
            self.expected_sddl = self.descriptor_text(attrs.descriptor)
        finally:
            self.kernel.LocalFree(attrs.descriptor)

    @staticmethod
    def bind(library, name, arguments, result):
        fn = getattr(library, name)
        fn.argtypes, fn.restype = arguments, result

    @staticmethod
    def check(ok):
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())

    def attributes(self):
        class Attributes(ctypes.Structure):
            _fields_ = [('length', w.DWORD), ('descriptor', w.LPVOID), ('inherit', w.BOOL)]
        descriptor = w.LPVOID()
        self.check(self.advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(self.sddl, 1, ctypes.byref(descriptor), None))
        return Attributes(ctypes.sizeof(Attributes), descriptor, False)

    def descriptor_text(self, descriptor):
        text = w.LPWSTR()
        self.check(self.advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW(descriptor, 1, 5, ctypes.byref(text), None))
        try:
            return text.value
        finally:
            self.kernel.LocalFree(ctypes.cast(text, w.HLOCAL))

    def verify(self, path, handle=None):
        attrs = self.kernel.GetFileAttributesW(str(path))
        if attrs == 0xFFFFFFFF or attrs & 0x400:
            raise RuntimeError('PATH_ATTRIBUTES_REJECTED')
        descriptor = w.LPVOID()
        if handle is None:
            code = self.advapi.GetNamedSecurityInfoW(str(path), 1, 5, None, None, None, None, ctypes.byref(descriptor))
        else:
            code = self.advapi.GetSecurityInfo(handle, 1, 5, None, None, None, None, ctypes.byref(descriptor))
        if code:
            raise ctypes.WinError(code)
        try:
            if self.descriptor_text(descriptor) != self.expected_sddl:
                raise RuntimeError('OWNER_DACL_MISMATCH')
        finally:
            self.kernel.LocalFree(descriptor)

    def directory(self, path):
        attrs = self.attributes()
        try:
            self.check(self.kernel.CreateDirectoryW(str(path), ctypes.byref(attrs)))
        finally:
            self.kernel.LocalFree(attrs.descriptor)
        self.verify(path)

    def key(self, path, payload):
        attrs = self.attributes()
        try:
            # CREATE_NEW; read/write/delete access; share read/write/delete;
            # DELETE_ON_CLOSE and non-inheritable SECURITY_ATTRIBUTES.
            handle = self.kernel.CreateFileW(str(path), 0xC0010000, 7, ctypes.byref(attrs), 1, 0x04000000, None)
            creation_error = ctypes.get_last_error()
        finally:
            self.kernel.LocalFree(attrs.descriptor)
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(creation_error)
        try:
            self.verify(path, handle)
            flags = w.DWORD()
            self.check(self.kernel.GetHandleInformation(handle, ctypes.byref(flags)))
            if flags.value & 1:
                raise RuntimeError('HANDLE_INHERITABLE')
            written = w.DWORD()
            self.check(self.kernel.WriteFile(handle, payload, len(payload), ctypes.byref(written), None))
            if written.value != len(payload):
                raise RuntimeError('SHORT_WRITE')
            self.check(self.kernel.FlushFileBuffers(handle))
            return handle
        except BaseException:
            self.kernel.CloseHandle(handle)
            raise


def error_code(exc):
    # Do not serialize exception messages, stderr, paths, or cryptographic data.
    return {'type': type(exc).__name__, 'winerror': getattr(exc, 'winerror', None)}


def save_result(root, mode, result):
    pending = root / f'{mode}.pending'
    pending.write_text(json.dumps(result), encoding='utf-8')
    pending.replace(root / f'{mode}.json')


def keeper(root, mode, keygen, progress):
    progress['stage'] = 'IMPORT_CRYPTOGRAPHY'
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    progress['stage'] = 'INIT_SECURITY'
    api = WindowsFiles()
    progress['stage'] = 'VERIFY_ROOT'
    api.verify(root)
    folder = root / mode
    progress['stage'] = 'CREATE_PRIVATE_DIRECTORY'
    api.directory(folder)
    progress['stage'] = 'GENERATE_SYNTHETIC_KEY'
    key = Ed25519PrivateKey.generate()
    payload = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH, serialization.NoEncryption())
    public = key.public_key().public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH)
    progress['stage'] = 'CREATE_VERIFY_WRITE_KEY'
    handle = api.key(folder / 'key', payload)
    try:
        progress['stage'] = 'KEY_LOADER'
        loaded = subprocess.run([keygen, '-y', '-P', '', '-f', str(folder / 'key')], capture_output=True, timeout=8)
        readable = loaded.returncode == 0 and loaded.stdout.strip() == public
        sharing = any(marker in loaded.stderr.lower() for marker in (b'sharing violation', b'used by another process'))
        result = {'stage': 'LOADER_COMPLETE', 'fixtureComplete': True, 'readable': readable, 'loaderExitCode': loaded.returncode,
                  'errorCode': None if readable else ('SHARING_VIOLATION' if sharing else 'KEY_LOADER_REJECTED')}
        save_result(root, mode, result)
        if mode == 'forced':
            # Parent terminates this process after observing the safe result file.
            time.sleep(30)
    finally:
        api.kernel.CloseHandle(handle)


def experiment():
    if sys.platform != 'win32':
        return {'experimentCompleted': False, 'candidateAccepted': False, 'errorCode': 'WINDOWS_REQUIRED'}, 1
    api = WindowsFiles()
    system = Path(os.environ['SystemRoot']) / 'System32' / 'OpenSSH'
    ssh, keygen = system / 'ssh.exe', system / 'ssh-keygen.exe'
    if not ssh.is_file() or not keygen.is_file():
        return {'experimentCompleted': False, 'candidateAccepted': False, 'errorCode': 'SYSTEM_OPENSSH_MISSING'}, 1
    version = subprocess.run([str(ssh), '-V'], capture_output=True, timeout=5)
    match = re.search(rb'OpenSSH_for_Windows_[0-9.p]+', version.stderr + version.stdout)
    root = Path(tempfile.gettempdir()) / ('af-key-lifetime-' + uuid.uuid4().hex)
    api.directory(root)
    results = {}
    try:
        for mode in ('normal', 'forced'):
            process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--keeper', str(root), mode, str(keygen)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
            try:
                ready = root / f'{mode}.json'
                deadline = time.monotonic() + 15
                while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.05)
                if not ready.exists():
                    raise RuntimeError('KEEPER_NOT_READY')
                results[mode] = json.loads(ready.read_text(encoding='utf-8'))
                fixture_complete = results[mode].get('fixtureComplete') is True
                if mode == 'forced' and fixture_complete:
                    if process.poll() is not None:
                        raise RuntimeError('KEEPER_EXITED_BEFORE_TERMINATION')
                    process.kill()  # Popen.kill on Windows invokes TerminateProcess.
                    results[mode]['terminatedWhileKeeperAlive'] = True
                process.wait(timeout=3)
                if fixture_complete and mode == 'normal' and process.returncode != 0:
                    raise RuntimeError('NORMAL_KEEPER_FAILED')
                results[mode]['keyAbsentAfterExit'] = not (root / mode / 'key').exists()
                results[mode]['keeperExitCode'] = process.returncode
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=3)
        completed = all(item.get('fixtureComplete') is True for item in results.values())
        accepted = completed and all(item['readable'] and item['keyAbsentAfterExit'] for item in results.values())
        return {'experimentCompleted': completed, 'candidateAccepted': accepted,
                'windowsVersion': list(sys.getwindowsversion()[:3]),
                'sshVersion': match.group().decode('ascii') if match else 'UNRECOGNIZED',
                'cases': results}, (0 if accepted else 2) if completed else 1
    finally:
        # Only this invocation's synthetic fixture; never sweep user directories.
        shutil.rmtree(root)


def main():
    if len(sys.argv) == 5 and sys.argv[1] == '--keeper':
        progress = {'stage': 'KEEPER_START'}
        try:
            keeper(Path(sys.argv[2]), sys.argv[3], sys.argv[4], progress)
            return 0
        except Exception as exc:
            save_result(Path(sys.argv[2]), sys.argv[3], {**progress, 'fixtureComplete': False, 'error': error_code(exc)})
            return 1
    try:
        result, code = experiment()
    except Exception as exc:
        result, code = {'experimentCompleted': False, 'candidateAccepted': False, 'errorCode': 'PROBE_INCOMPLETE', 'error': error_code(exc)}, 1
    print(json.dumps(result, sort_keys=True))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
