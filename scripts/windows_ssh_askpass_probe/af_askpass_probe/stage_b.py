"""Real system SSH authentication against an owned foreground loopback fixture."""
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import subprocess
import sys
import sysconfig
import tempfile
import time
import uuid

from . import safe_error


def diagnostic_flags(client_log, remote_error, output_empty):
    def bounded(path):
        if not path.is_file():
            return b'', False
        with path.open('rb') as stream:
            data = stream.read(16385)
        return data[:16384], len(data) > 16384
    log, log_truncated = bounded(client_log)
    error, error_truncated = bounded(remote_error)
    lowered = error.lower()
    return {'authenticatedPublickey': b'Authenticated to ' in log and b'using "publickey"' in log,
            'stdoutEmpty': output_empty, 'stderrPresent': bool(error),
            'shellSyntaxError': b'syntax' in lowered,
            'commandNotFound': b'not recognized' in lowered or b'not found' in lowered,
            'accessDenied': b'access is denied' in lowered or b'permission denied' in lowered,
            'channelRequestFailed': b'request failed on channel' in log.lower(),
            'clientLogTruncated': log_truncated, 'stderrTruncated': error_truncated}


def case(root, mode, system, experiment_deadline):
    from cryptography.hazmat.primitives import serialization as s
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from . import windows as w
    stage = 'CREATE_FIXTURE'
    server_job = client_job = pipe = None
    password = bytearray()
    ready = False
    releases = 0
    folder = root / mode
    result = {}
    try:
        w.directory(folder)
        host = Ed25519PrivateKey.generate()
        client = Ed25519PrivateKey.generate()
        def public(key):
            return key.public_key().public_bytes(s.Encoding.OpenSSH, s.PublicFormat.OpenSSH)
        password = bytearray(secrets.token_hex(32).encode('ascii'))
        key_path = folder / 'encrypted-key'
        # Match sshconnect2's byte-limited prompt exactly; this fixture uses ASCII paths.
        if not str(key_path).isascii():
            raise w.Reject('FIXTURE_PATH_NOT_ASCII')
        w.write_private(key_path, client.private_bytes(s.Encoding.PEM, s.PrivateFormat.OpenSSH,
                                                       s.BestAvailableEncryption(bytes(password))))
        w.write_private(Path(str(key_path) + '.pub'), public(client) + b'\n')
        host_path = folder / 'host-key'
        w.write_private(host_path, host.private_bytes(s.Encoding.PEM, s.PrivateFormat.OpenSSH, s.NoEncryption()))
        authorized = folder / 'authorized_keys'
        w.write_private(authorized, public(client) + b'\n')
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1', 0))
            port = reservation.getsockname()[1]
        username = w.win32api.GetUserName()
        if not re.fullmatch(r'[A-Za-z0-9_.-]+', username):
            raise w.Reject('FIXTURE_ACCOUNT_FORMAT')
        nonce = secrets.token_hex(16)
        config = folder / 'sshd_config'
        config_text = '\n'.join([
            f'Port {port}', 'ListenAddress 127.0.0.1',
            f'PidFile "{(folder / "sshd.pid").as_posix()}"', f'AllowUsers {username.lower()}',
            f'HostKey "{host_path.as_posix()}"', f'AuthorizedKeysFile "{authorized.as_posix()}"',
            'StrictModes yes', 'PubkeyAuthentication yes', 'AuthenticationMethods publickey',
            'PasswordAuthentication no', 'KbdInteractiveAuthentication no', 'PermitEmptyPasswords no',
            'AllowTcpForwarding no', 'AllowAgentForwarding no', 'X11Forwarding no',
            'PermitTunnel no', 'PermitUserRC no', 'LogLevel ERROR',
            f'ForceCommand echo {nonce}',
        ]) + '\n'
        w.write_private(config, config_text.encode('ascii'))
        env = {name: os.environ[name] for name in ('SystemRoot', 'WINDIR', 'ProgramData', 'TEMP', 'TMP') if name in os.environ}
        env['PATH'] = str(system)
        stage = 'VALIDATE_SERVER_CONFIG'
        validated = subprocess.run([str(system / 'sshd.exe'), '-t', '-f', str(config)],
                                   env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   timeout=max(0.01, min(5, experiment_deadline - time.monotonic())))
        if validated.returncode:
            result = {'fixtureComplete': False, 'accepted': False, 'status': 'INCOMPLETE',
                      'stage': stage, 'serverExitCode': validated.returncode, 'releases': 0}
            return result
        stage = 'START_FOREGROUND_SERVER'
        server_job = w.OwnedJob()
        server, _, _ = server_job.spawn([str(system / 'sshd.exe'), '-D', '-e', '-f', str(config)], env,
                                         folder / 'server-output')
        end = min(time.monotonic() + 5, experiment_deadline)
        while time.monotonic() < end and w.alive(server):
            try:
                with socket.create_connection(('127.0.0.1', port), timeout=0.1):
                    ready = True
                    break
            except OSError:
                time.sleep(0.05)
        if not ready:
            raise w.Reject('SERVER_NOT_READY')
        stage = 'CREATE_CLIENT'
        pinned = public(Ed25519PrivateKey.generate()) if mode == 'wrong-pin' else public(host)
        known = folder / 'known_hosts'
        w.write_private(known, f'[127.0.0.1]:{port} '.encode() + pinned + b'\n')
        helper = Path(sysconfig.get_path('scripts')) / 'af-windows-ssh-askpass-helper.exe'
        if not helper.is_file():
            raise w.Reject('INSTALLED_HELPER_MISSING')
        pipe_name = r'\\.\pipe\af-askpass-' + uuid.uuid4().hex
        pipe = w.server_pipe(pipe_name)
        env.update({'SSH_ASKPASS': str(helper), 'SSH_ASKPASS_REQUIRE': 'force',
                    'AF_PROBE_PIPE': pipe_name, 'AF_PROBE_CONTROLLER': str(os.getpid()),
                    'AF_PROBE_MODE': mode, 'AF_PROBE_KEY': str(key_path), 'AF_PROBE_PHASE': 'ssh'})
        log = folder / 'client-log'
        args = [str(system / 'ssh.exe'), '-F', 'none', '-E', str(log), '-i', str(key_path), '-p', str(port)]
        options = ['StrictHostKeyChecking=yes', f'UserKnownHostsFile={known}', 'GlobalKnownHostsFile=none',
                   'IdentitiesOnly=yes', 'IdentityAgent=none', 'AddKeysToAgent=no', 'BatchMode=no',
                   'PreferredAuthentications=publickey', 'PasswordAuthentication=no',
                   'KbdInteractiveAuthentication=no', 'NumberOfPasswordPrompts=1', 'ConnectTimeout=5',
                   'ProxyCommand=none', 'ProxyJump=none', 'ForwardAgent=no', 'ClearAllForwardings=yes',
                   'ControlMaster=no', 'ControlPath=none', 'PermitLocalCommand=no', 'LogLevel=VERBOSE']
        for option in options:
            args.extend(['-o', option])
        args.extend(['-l', username, '127.0.0.1', 'ignored-by-force-command'])
        client_job = w.OwnedJob()
        output = folder / 'command-output'
        remote_error = folder / 'remote-error'
        proc, thread, pid = client_job.spawn(args, env, output, suspended=True, error_output=remote_error)
        deadline = min(time.monotonic() + 10, experiment_deadline)
        w.win32process.ResumeThread(thread)
        shape = None
        repeat_denied = False
        if mode != 'wrong-pin':
            stage = 'AUTHENTICATE_HELPER'
            w.connect(pipe, deadline)
            shape, _ = w.check_client(pipe, proc, pid, helper, w.image(w.win32api.GetCurrentProcess()), sys.executable)
            if w.transfer(pipe, deadline, size=16) != b'READY':
                raise w.Reject('HELPER_NOT_READY')
            w.transfer(pipe, deadline, payload=bytes(password))
            releases = 1
            if w.transfer(pipe, deadline, size=16) != b'RECEIVED':
                raise w.Reject('RECEIPT_MISSING')
            if mode == 'repeat':
                if w.transfer(pipe, deadline, size=16) != b'AGAIN':
                    raise w.Reject('SECOND_REQUEST_MISSING')
                w.transfer(pipe, deadline, payload=b'N')
                repeat_denied = True
            pipe.Close()
            pipe = None
        stage = 'CLIENT_EXIT'
        if w.win32event.WaitForSingleObject(proc, max(0, int((deadline - time.monotonic()) * 1000))) != w.win32con.WAIT_OBJECT_0:
            raise TimeoutError('CLIENT_EXIT')
        exit_code = w.win32process.GetExitCodeProcess(proc)
        with output.open('rb') as stream:
            actual_output = stream.read(1024)
            matched = actual_output.strip() == nonce.encode()
        host_rejected = False
        if mode == 'wrong-pin' and log.is_file():
            with log.open('rb') as stream:
                diagnostic = stream.read(16385)
            host_rejected = len(diagnostic) <= 16384 and b'Host key verification failed.' in diagnostic
        accepted = (exit_code != 0 and not matched and releases == 0 and host_rejected
                    if mode == 'wrong-pin' else exit_code == 0 and matched and releases == 1)
        if mode == 'repeat':
            accepted = accepted and repeat_denied
        result = {'fixtureComplete': True, 'accepted': accepted, 'status': 'PASS' if accepted else 'FAIL',
                  'stage': stage, 'clientExitCode': exit_code, 'nonceMatched': matched, 'releases': releases,
                  'hostPinRejected': host_rejected, 'repeatDenied': repeat_denied, 'shape': shape,
                  'diagnostics': diagnostic_flags(log, remote_error, not actual_output)}
    except Exception as exc:
        result = {**safe_error(stage, exc), 'fixtureComplete': ready, 'accepted': False,
                  'status': 'FAIL' if ready else 'INCOMPLETE', 'releases': releases}
        helper_status = folder / 'helper-status.json'
        if helper_status.is_file():
            result['helper'] = json.loads(helper_status.read_text(encoding='utf-8'))
        if isinstance(exc, w.Reject) and exc.checks is not None:
            result['identityChecks'] = exc.checks
    finally:
        password[:] = b'\0' * len(password)
        if pipe is not None:
            pipe.Close()
        try:
            if client_job is not None:
                client_job.close()
        finally:
            if server_job is not None:
                server_job.close()
        result['ownedJobsStopped'] = True
    return result


def experiment():
    if sys.platform != 'win32':
        return {'stage': 'B', 'status': 'BLOCKED', 'experimentCompleted': False,
                'candidateAccepted': False, 'errorCode': 'WINDOWS_REQUIRED'}, 1
    from . import windows as w
    system = Path(os.environ['SystemRoot']) / 'System32' / 'OpenSSH'
    present = {name: (system / name).is_file() for name in ('ssh.exe', 'sshd.exe')}
    if not all(present.values()):
        return {'stage': 'B', 'status': 'BLOCKED', 'experimentCompleted': False,
                'candidateAccepted': False, 'errorCode': 'SYSTEM_BINARY_MISSING', 'executables': present}, 1
    version = subprocess.run([str(system / 'ssh.exe'), '-V'], capture_output=True, timeout=3)
    match = re.search(rb'OpenSSH_for_Windows_[0-9.p]+', version.stderr + version.stdout)
    root = Path(tempfile.gettempdir()) / ('af-ssh-auth-' + uuid.uuid4().hex)
    w.directory(root)
    cases = {}
    report = {}
    deadline = time.monotonic() + 45
    try:
        for mode in ('normal', 'wrong-pin', 'repeat'):
            cases[mode] = case(root, mode, system, deadline)
            if not cases[mode].get('accepted'):
                break
        accepted = len(cases) == 3 and all(item.get('accepted') for item in cases.values())
        complete = all(item.get('fixtureComplete') for item in cases.values())
        report = {'stage': 'B', 'status': 'PASS' if accepted else ('FAIL' if complete else 'INCOMPLETE'),
                'experimentCompleted': complete, 'candidateAccepted': accepted, 'executables': present,
                'windowsVersion': list(sys.getwindowsversion()[:3]),
                'sshVersion': match.group().decode() if match else 'UNRECOGNIZED', 'cases': cases}
        return report, 0 if accepted else (2 if complete else 1)
    finally:
        shutil.rmtree(root)
        report['ownedFilesRemoved'] = not root.exists()
