"""Isolated synthetic experiment; not an application credential provider."""
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import time
import uuid


def save(root, name, value):
    pending = root / (name + '.pending')
    pending.write_text(json.dumps(value), encoding='utf-8')
    pending.replace(root / (name + '.json'))


def safe_error(stage, exc):
    return {'fixtureComplete': False, 'stage': stage, 'errorType': type(exc).__name__,
            'winerror': getattr(exc, 'winerror', None)}


def helper_main():
    # SSH captures stdout as the passphrase. Never print diagnostics here.
    folder = None
    stage = 'IMPORT_WINDOWS'
    try:
        key_path = os.environ['AF_PROBE_KEY']
        folder = Path(key_path).parent
        from . import windows as w
        stage = 'VERIFY_FIXTURE_DIRECTORY'
        w.verify(folder)
        stage = 'EXACT_PROMPT'
        if len(sys.argv) != 2 or sys.argv[1] != f'Enter passphrase for "{key_path}": ':
            save(folder, 'helper-status', {'stage': stage, 'errorCode': 'PROMPT_MISMATCH'})
            return 1
        if os.environ.get('SSH_ASKPASS_PROMPT') in ('confirm', 'none'):
            save(folder, 'helper-status', {'stage': stage, 'errorCode': 'NON_PASSPHRASE_PROMPT'})
            return 1
        mode = os.environ['AF_PROBE_MODE']
        stage = 'PIPE_OPEN'
        pipe = w.client_pipe(os.environ['AF_PROBE_PIPE'])
        controller = w.process(int(os.environ['AF_PROBE_CONTROLLER']))
        try:
            stage = 'PIPE_SERVER_IDENTITY'
            if w.pipe_pid(pipe, False) != int(os.environ['AF_PROBE_CONTROLLER']) or not w.alive(controller):
                save(folder, 'helper-status', {'stage': stage, 'errorCode': 'SERVER_IDENTITY_REJECTED'})
                return 1
            deadline = time.monotonic() + 6
            if mode == 'stalled':
                save(folder, 'helper-status', {'stage': 'CONTROLLED_STALL'})
                time.sleep(20)  # Actual connected helper must die with its job.
                return 1
            stage = 'PIPE_SECRET_READ'
            w.transfer(pipe, deadline, payload=b'READY')
            password = bytearray(w.transfer(pipe, deadline, size=64))
            try:
                if len(password) != 64:
                    save(folder, 'helper-status', {'stage': stage, 'errorCode': 'SECRET_LENGTH_REJECTED'})
                    return 1
                stage = 'PIPE_RECEIPT'
                save(folder, 'helper-status', {'stage': 'SECRET_RECEIVED'})
                w.transfer(pipe, deadline, payload=b'RECEIVED')
                if mode == 'forced':
                    # Parent kills the broker after this acknowledgement: a real
                    # helper already holds the secret and must die with its job.
                    w.transfer(pipe, time.monotonic() + 20, size=1)
                    return 1
                if mode == 'repeat':
                    stage = 'REPEATED_REQUEST'
                    w.transfer(pipe, deadline, payload=b'AGAIN')
                    if w.transfer(pipe, deadline, size=1) != b'N':
                        return 1
                stage = 'SSH_PRIVATE_STDOUT'
                sys.stdout.buffer.write(password + b'\n')
                sys.stdout.buffer.flush()
                return 0
            finally:
                password[:] = b'\0' * len(password)
        finally:
            pipe.Close()
            controller.Close()
    except Exception as exc:
        if folder is not None:
            try:
                save(folder, 'helper-status', safe_error(stage, exc))
            except Exception:
                pass  # No fallback stdout/stderr: OpenSSH treats stdout as secret.
        return 1


def foreign_client():
    from . import windows as w
    try:
        pipe = w.client_pipe(os.environ['AF_PROBE_PIPE'])
        try:
            data = w.transfer(pipe, time.monotonic() + 3, size=64)
            return 0 if not data else 2
        finally:
            pipe.Close()
    except Exception:
        # The parent also independently verifies zero releases to this process.
        return 0


def controller(root, mode):
    from . import windows as w
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    stage = 'START'
    job = pipe = None
    password = bytearray()
    try:
        w.verify(root)
        folder = root / mode
        w.directory(folder)
        stage = 'ENCRYPT_KEY'
        password = bytearray(secrets.token_hex(32).encode('ascii'))
        key = Ed25519PrivateKey.generate()
        ciphertext = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH,
                                       serialization.BestAvailableEncryption(bytes(password)))
        public = key.public_key().public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH)
        key_path = folder / 'encrypted-key'
        w.write_private(key_path, ciphertext)
        # Prove fixture bytes require a password before asking system OpenSSH.
        encrypted = False
        try:
            serialization.load_ssh_private_key(key_path.read_bytes(), password=None)
        except TypeError:
            encrypted = True
        if not encrypted:
            raise w.Reject('NOT_ENCRYPTED')
        stage = 'CREATE_PIPE_JOB'
        pipe_name = r'\\.\pipe\af-askpass-' + uuid.uuid4().hex
        pipe = w.server_pipe(pipe_name)
        job = w.OwnedJob()
        system = Path(os.environ['SystemRoot']) / 'System32' / 'OpenSSH'
        helper = Path(sysconfig.get_path('scripts')) / 'af-windows-ssh-askpass-helper.exe'
        if not helper.is_file():
            raise w.Reject('INSTALLED_HELPER_MISSING')
        env = {name: os.environ[name] for name in ('SystemRoot', 'WINDIR', 'ProgramData', 'TEMP', 'TMP') if name in os.environ}
        env.update({'PATH': str(system), 'SSH_ASKPASS': str(helper), 'SSH_ASKPASS_REQUIRE': 'force',
                    'AF_PROBE_PIPE': pipe_name, 'AF_PROBE_CONTROLLER': str(os.getpid()),
                    'AF_PROBE_MODE': mode, 'AF_PROBE_KEY': str(key_path)})
        output = folder / 'public-output'
        stage = 'SPAWN_SUSPENDED_ASSIGN'
        proc, thread, pid = job.spawn([str(system / 'ssh-keygen.exe'), '-y', '-f', str(key_path)], env, output, suspended=True)
        deadline = time.monotonic() + 6
        rejected = False
        if mode == 'foreign':
            stage = 'FOREIGN_CLIENT'
            foreign, _, _ = job.spawn([sys.executable, '-m', 'af_askpass_probe', '--foreign'], env, folder / 'foreign-output')
            w.connect(pipe, deadline)
            try:
                w.check_client(pipe, proc, pid, helper, w.image(w.win32api.GetCurrentProcess()))
            except w.Reject:
                rejected = True
            if not rejected:
                raise w.Reject('FOREIGN_ACCEPTED')
            w.win32pipe.DisconnectNamedPipe(pipe)
            if w.win32event.WaitForSingleObject(foreign, 2000) != w.win32con.WAIT_OBJECT_0:
                raise TimeoutError('FOREIGN_EXIT')
        w.win32process.ResumeThread(thread)
        stage = 'ACCEPT_HELPER'
        w.connect(pipe, deadline)
        shape, client_pid = w.check_client(pipe, proc, pid, helper, w.image(w.win32api.GetCurrentProcess()))
        try:
            if w.transfer(pipe, deadline, size=16) != b'READY':
                raise w.Reject('HELPER_NOT_READY')
        except TimeoutError:
            if mode != 'stalled':
                raise
            job.close()
            job = None
            save(root, mode, {'fixtureComplete': True, 'accepted': True, 'stage': 'STALLED_BOUNDED',
                              'shape': shape, 'releases': 0, 'encryptedOnly': encrypted, 'jobStopped': True})
            return
        stage = 'ONE_RELEASE'
        w.transfer(pipe, deadline, payload=bytes(password))
        if w.transfer(pipe, deadline, size=16) != b'RECEIVED':
            raise w.Reject('RECEIPT_MISSING')
        if mode == 'forced':
            save(root, 'forced-ready', {'fixtureComplete': True, 'stage': 'HELPER_HOLDS_SECRET',
                 'helperPid': client_pid, 'loaderPid': pid, 'shape': shape, 'encryptedOnly': encrypted, 'releases': 1})
            time.sleep(20)  # The outer harness must terminate this controller.
            raise TimeoutError('CONTROLLER_NOT_KILLED')
        repeat_denied = False
        if mode == 'repeat':
            if w.transfer(pipe, deadline, size=16) != b'AGAIN':
                raise w.Reject('SECOND_REQUEST_MISSING')
            w.transfer(pipe, deadline, payload=b'N')
            repeat_denied = True
        pipe.Close()
        pipe = None
        stage = 'LOADER_EXIT'
        if w.win32event.WaitForSingleObject(proc, max(0, int((deadline - time.monotonic()) * 1000))) != w.win32con.WAIT_OBJECT_0:
            raise TimeoutError('LOADER_EXIT')
        status = w.win32process.GetExitCodeProcess(proc)
        with output.open('rb') as stream:
            readable = status == 0 and stream.read(1024).strip() == public
        job.close()
        job = None
        key_path.unlink()
        save(root, mode, {'fixtureComplete': True, 'accepted': readable, 'stage': 'LOADER_COMPLETE',
             'readable': readable, 'loaderExitCode': status, 'shape': shape, 'releases': 1,
             'foreignDenied': rejected, 'repeatDenied': repeat_denied, 'encryptedOnly': encrypted,
             'keyAbsentAfterClose': not key_path.exists(), 'jobStopped': True})
    except Exception as exc:
        result = safe_error(stage, exc)
        helper_status = root / mode / 'helper-status.json'
        if helper_status.is_file():
            result['helper'] = json.loads(helper_status.read_text(encoding='utf-8'))
        save(root, mode, result)
    finally:
        password[:] = b'\0' * len(password)
        if pipe is not None:
            pipe.Close()
        if job is not None:
            job.close()


def experiment():
    if sys.platform != 'win32':
        return {'stage': 'A', 'experimentCompleted': False, 'candidateAccepted': False, 'errorCode': 'WINDOWS_REQUIRED'}, 1
    from . import windows as w
    from cryptography.hazmat.primitives import serialization
    ssh = Path(os.environ['SystemRoot']) / 'System32' / 'OpenSSH' / 'ssh.exe'
    version = subprocess.run([str(ssh), '-V'], capture_output=True, timeout=3)
    match = re.search(rb'OpenSSH_for_Windows_[0-9.p]+', version.stderr + version.stdout)
    root = Path(tempfile.gettempdir()) / ('af-askpass-' + uuid.uuid4().hex)
    w.directory(root)
    cases = {}
    try:
        for mode in ('normal', 'foreign', 'repeat', 'stalled', 'forced'):
            proc = subprocess.Popen([sys.executable, '-m', 'af_askpass_probe', '--controller', str(root), mode],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            held = []
            try:
                if mode == 'forced':
                    ready = root / 'forced-ready.json'
                    end = time.monotonic() + 9
                    while not ready.exists() and proc.poll() is None and time.monotonic() < end:
                        time.sleep(0.05)
                    if not ready.exists():
                        failure = root / 'forced.json'
                        cases[mode] = json.loads(failure.read_text()) if failure.exists() else {'fixtureComplete': False, 'stage': 'NO_SECRET_HOLDER'}
                        break
                    result = json.loads(ready.read_text())
                    held = [w.process(result['helperPid']), w.process(result['loaderPid'])]
                    if not all(w.alive(handle) for handle in held):
                        raise w.Reject('SECRET_HOLDER_ALREADY_EXITED')
                    proc.kill()
                    proc.wait(timeout=3)
                    stopped = all(w.win32event.WaitForSingleObject(handle, 3000) == w.win32con.WAIT_OBJECT_0 for handle in held)
                    key_path = root / mode / 'encrypted-key'
                    residue = key_path.exists()
                    encrypted = False
                    if residue:
                        try:
                            serialization.load_ssh_private_key(key_path.read_bytes(), password=None)
                        except TypeError:
                            encrypted = True
                    cases[mode] = {**result, 'accepted': stopped and residue and encrypted,
                                   'jobStopped': stopped, 'encryptedResidue': residue and encrypted,
                                   'controllerTerminated': True}
                else:
                    proc.wait(timeout=10)
                    result_path = root / f'{mode}.json'
                    cases[mode] = json.loads(result_path.read_text()) if result_path.exists() else {'fixtureComplete': False, 'stage': 'NO_CONTROLLER_RESULT'}
                if not cases[mode].get('accepted'):
                    break  # Preserve the first failure; do not blindly repeat.
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait(timeout=3)
                for handle in held:
                    handle.Close()
        complete = len(cases) == 5 and all(case.get('fixtureComplete') for case in cases.values())
        accepted = complete and all(case.get('accepted') for case in cases.values())
        # A measured normal-loader rejection is a completed rejected candidate;
        # unexecuted follow-up cases remain absent, not reported as passed.
        rejected = any(case.get('fixtureComplete') and case.get('accepted') is False for case in cases.values())
        return {'stage': 'A', 'experimentCompleted': complete or rejected, 'candidateAccepted': accepted,
                'windowsVersion': list(sys.getwindowsversion()[:3]), 'sshVersion': match.group().decode() if match else 'UNRECOGNIZED',
                'cases': cases}, 0 if accepted else (2 if rejected else 1)
    finally:
        shutil.rmtree(root)


def main():
    try:
        if len(sys.argv) == 4 and sys.argv[1] == '--controller':
            controller(Path(sys.argv[2]), sys.argv[3])
            return 0
        if sys.argv[1:] == ['--foreign']:
            return foreign_client()
        result, code = experiment()
    except Exception as exc:
        result, code = {**safe_error('HARNESS', exc), 'stage': 'A', 'experimentCompleted': False, 'candidateAccepted': False}, 1
    print(json.dumps(result, sort_keys=True))
    return code
