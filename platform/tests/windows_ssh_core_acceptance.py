"""Copied outside checkout: actual installed-core Windows SSH acceptance.

The Windows ForceCommand is a controlled protocol endpoint, not the Linux helper.
No probe package, repository fixture or application implementation is imported.
"""
import argparse
import asyncio
from contextlib import ExitStack
import importlib.metadata
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
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch


class Blocked(Exception):
    pass


def require(value, code):
    if not value:
        raise AssertionError(code)


def provenance(environment, checkout):
    import agent_factory
    from agent_factory import windows_ssh_askpass, windows_ssh_credentials
    paths = [Path(module.__file__).resolve() for module in
             (agent_factory, windows_ssh_askpass, windows_ssh_credentials)]
    helper = Path(sysconfig.get_path('scripts')) / 'agent-factory-ssh-askpass.exe'
    require(Path(sys.prefix).resolve() == environment, 'WRONG_ENVIRONMENT')
    require(not os.environ.get('PYTHONPATH'), 'PYTHONPATH_PRESENT')
    require(all(p.is_relative_to(environment) and not p.is_relative_to(checkout) for p in paths),
            'CORE_NOT_INSTALLED_IN_FRESH_ENVIRONMENT')
    require(helper.is_file() and helper.resolve().is_relative_to(environment), 'FIXED_HELPER_NOT_INSTALLED')
    return {'coreVersion': importlib.metadata.version('department-agent-factory-core'),
            'corePath': str(paths[0]), 'helperPath': str(helper), 'isolatedPython': bool(sys.flags.isolated)}


def endpoint_script():
    return '''import json,os,pathlib,re,sys,time
original=os.environ.get('SSH_ORIGINAL_COMMAND','')
if 'agent_factory.ssh_process_helper' not in original:
    found=re.search(r'"nonce": "([a-f0-9]+)"', original)
    if not found: raise SystemExit(3)
    print(json.dumps({'nonce':found.group(1),'ok':True,'code':'SSH_CONNECTION_READY','directoryExists':True}))
else:
    request=json.loads(sys.stdin.buffer.read())
    if request['action']=='capabilities':
        print(json.dumps({'fixtureNonce':sys.argv[1]}))
    elif request['action']=='submit':
        pathlib.Path(sys.argv[2]).write_text(json.dumps(request['binding']),encoding='utf-8')
        time.sleep(60)
    else: raise SystemExit(4)
'''


async def cancel_original(provider, lease, marker, tracked, manager):
    task = asyncio.create_task(provider.allocate_bound(lease, before_effect=lambda: None))
    try:
        deadline = time.monotonic() + 15
        while not marker.exists() and time.monotonic() < deadline and not task.done():
            await asyncio.sleep(.02)
        require(marker.exists() and not task.done(), 'REMOTE_REQUEST_NOT_WAITING')
        recorded = json.loads(marker.read_text(encoding='utf-8'))
        require(recorded['taskId'] == lease['localTaskId'] and recorded['runId'] == lease['nativeRunId'],
                'ORIGINAL_REQUEST_CHANGED')
        require(tracked and tracked[-1].poll() is None, 'CLIENT_NOT_RUNNING_BEFORE_CANCEL')
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError('CALLER_DID_NOT_CANCEL')
        require(tracked[-1].poll() is not None and not manager.active, 'RETURNED_BEFORE_PROCESS_CLEANUP')
        require(not any(t.name == 'factory-ssh-askpass' for t in threading.enumerate()), 'BROKER_STILL_RUNNING')
    finally:
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


def exercise(root, report):
    from cryptography.hazmat.primitives import serialization as serial
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from sqlalchemy import create_engine
    from agent_factory import windows_ssh_support as w, windows_ssh_process as process_module
    from agent_factory.credential_vault import EncryptedCredentialVault
    from agent_factory.personal_remote_provider import RemoteConnectionError
    from agent_factory.personal_ssh import PersonalSSHServers
    from agent_factory.process_enforcement import ProcessLimits, ProcessSpec
    from agent_factory.ssh_credentials import PROVIDER_ID, SSHCredentialPolicy, endpoint
    from agent_factory.ssh_identity import SSHServer, pinned_ssh
    from agent_factory.ssh_process_contract import PROTOCOL
    from agent_factory.ssh_process_provider import SSHProcessProvider, SSHProcessTransport, EFFECT
    from agent_factory.windows_ssh_credentials import WindowsSSHCredentials

    system = Path(os.environ['SystemRoot']) / 'System32/OpenSSH'
    if not all((system / name).is_file() for name in ('ssh.exe', 'sshd.exe')):
        raise Blocked('SYSTEM_SSH_BINARIES_MISSING')
    username = w.win32api.GetUserName()
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', username):
        raise Blocked('FIXTURE_ACCOUNT_FORMAT_UNSUPPORTED')
    w.directory(root)
    host, client = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    def public(key):
        return key.public_key().public_bytes(serial.Encoding.OpenSSH, serial.PublicFormat.OpenSSH).decode()
    def private(key):
        return key.private_bytes(serial.Encoding.PEM, serial.PrivateFormat.OpenSSH, serial.NoEncryption())
    host_path, authorized = root / 'host-key', root / 'authorized_keys'
    w.write_private(host_path, private(host))
    w.write_private(authorized, (public(client) + '\n').encode())
    nonce = secrets.token_hex(16)
    marker, script = root / 'request-received.json', root / 'endpoint.py'
    w.write_private(script, endpoint_script().encode())
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        port = reservation.getsockname()[1]
    command = subprocess.list2cmdline([sys.executable, '-I', str(script), nonce, str(marker)])
    config = root / 'sshd_config'
    w.write_private(config, ('\n'.join([
        f'Port {port}', 'ListenAddress 127.0.0.1', f'AllowUsers {username.lower()}',
        f'HostKey "{host_path.as_posix()}"', f'AuthorizedKeysFile "{authorized.as_posix()}"',
        f'PidFile "{(root / "sshd.pid").as_posix()}"', 'StrictModes yes',
        'PubkeyAuthentication yes', 'AuthenticationMethods publickey', 'PasswordAuthentication no',
        'KbdInteractiveAuthentication no', 'PermitEmptyPasswords no', 'AllowTcpForwarding no',
        'AllowAgentForwarding no', 'X11Forwarding no', 'PermitTunnel no', 'PermitUserRC no',
        'LogLevel ERROR', 'ForceCommand ' + command]) + '\n').encode('utf-8'))
    env = {name: os.environ[name] for name in ('SystemRoot', 'WINDIR', 'ProgramData', 'TEMP', 'TMP') if name in os.environ}
    env['PATH'] = str(system)
    checked = subprocess.run([str(system / 'sshd.exe'), '-t', '-f', str(config)],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
    if checked.returncode:
        raise Blocked('FOREGROUND_SSHD_CONFIG_REJECTED')

    with ExitStack() as stack:
        server_process = stack.enter_context(process_module.WindowsSSHProcess(
            [str(system / 'sshd.exe'), '-D', '-e', '-f', str(config)], env))
        server_process.resume()
        end = time.monotonic() + 5
        ready = False
        while time.monotonic() < end and server_process.poll() is None:
            try:
                with socket.create_connection(('127.0.0.1', port), timeout=.1):
                    ready = True
                    break
            except OSError:
                time.sleep(.05)
        if not ready:
            raise Blocked('FOREGROUND_SSHD_NOT_READY')
        report['fixtureReady'] = True
        engine = create_engine('sqlite:///' + str(root / 'vault.sqlite'), connect_args={'check_same_thread': False})
        stack.callback(engine.dispose)
        vault = EncryptedCredentialVault(engine, secrets.token_bytes(32), {PROVIDER_ID: SSHCredentialPolicy()})
        manager = WindowsSSHCredentials(vault, max_agents=2, seconds=60)
        stack.callback(manager.close)
        manager_root = manager.root
        require(not str(manager_root).isascii(), 'UNICODE_CARRIER_PARENT_NOT_EXERCISED')
        require(manager.diagnostic() is None, 'INSTALLED_CLIENT_OR_HELPER_MISSING')
        report['unicodeCarrierParent'] = True
        tracked, handles = [], []
        releases = []
        original_process, original_transfer, original_client = process_module.WindowsSSHProcess, w.transfer, w.check_client
        def track_process(*args, **kwargs):
            process = original_process(*args, **kwargs)
            tracked.append(process)
            current = w.win32api.GetCurrentProcess()
            held = w.win32api.DuplicateHandle(current, process.process_handle, current, 0, False,
                                             w.win32con.DUPLICATE_SAME_ACCESS)
            handles.append(held)
            return process
        def transfer(*args, **kwargs):
            result = original_transfer(*args, **kwargs)
            if kwargs.get('payload') is not None:
                releases.append(True)
            return result
        def client_check(*args, **kwargs):
            result = original_client(*args, **kwargs)
            handles.append(w.win32api.OpenProcess(w.win32con.SYNCHRONIZE, False, result[1]))
            return result
        stack.enter_context(patch.object(process_module, 'WindowsSSHProcess', side_effect=track_process))
        stack.enter_context(patch.object(w, 'transfer', side_effect=transfer))
        stack.enter_context(patch.object(w, 'check_client', side_effect=client_check))
        stack.callback(lambda: [handle.Close() for handle in handles])

        def connection(pin):
            identity = endpoint('127.0.0.1', port, username, pin)
            value = vault.create(owner='alice', provider_id=PROVIDER_ID, destination=identity['origin'],
                username=username, password=private(client).decode())
            server = SSHServer('fixture', 'alice', 'v1', 'Installed core fixture', '127.0.0.1', port,
                username, pin, '/controlled-fixture', value['credentialRef'], value['credentialRevision'])
            lease = manager.acquire(server, identity['origin'], lambda: None)
            return server, lease, identity['origin']
        server, lease, destination = connection(public(host))
        service = SimpleNamespace(agents=SimpleNamespace(root=manager.root), package=None, probe_source=None)
        inspected = PersonalSSHServers.probe(service, server, lease, 'inspect')
        require(inspected['ok'] and inspected['directoryExists'], 'PROBE_PROTOCOL_MISMATCH')
        transport = SSHProcessTransport(server, lambda action: lease, interpreter='/controlled/python')
        reply = transport({'protocol': PROTOCOL, 'action': 'capabilities', 'root': server.allowed_root})
        require(reply == {'fixtureNonce': nonce}, 'TRANSPORT_NONCE_MISMATCH')
        require(len(releases) == 2, 'NORMAL_RELEASE_COUNT')
        require(all(p.poll() is not None for p in tracked), 'NORMAL_CLIENT_NOT_REAPED')
        report['cases']['twoConsumers'] = {'status': 'PASS', 'nonceMatched': True, 'successfulReleases': 2}

        wrong, wrong_lease, _ = connection(public(Ed25519PrivateKey.generate()))
        before = len(releases)
        clients_before = len(tracked)
        try:
            SSHProcessTransport(wrong, lambda action: wrong_lease, interpreter='/controlled/python')(
                {'protocol': PROTOCOL, 'action': 'capabilities', 'root': wrong.allowed_root})
        except (ValueError, RemoteConnectionError):
            pass
        else:
            raise AssertionError('WRONG_PIN_ACCEPTED')
        require(len(releases) == before, 'WRONG_PIN_RELEASED_SECRET')
        require(len(tracked) == clients_before + 1 and tracked[-1].poll() == 255,
                'WRONG_PIN_DID_NOT_REACH_REAL_SSH_FAILURE')
        report['cases']['wrongPin'] = {'status': 'PASS', 'successfulReleases': 0}

        provider = SSHProcessProvider(server, target_ref='fixture',
            spec=ProcessSpec('/bin/not-executed', 'a' * 64, (), path_style='posix'), limits=ProcessLimits(),
            exchange=transport, read_lease=lambda owner, key: None, archive_original=None)
        reservation = {'id': 'lease-1', 'ownerId': 'alice', 'localTaskId': 'task-1', 'nativeRunId': 'run-1',
            'planId': 'plan-1', 'planHash': 'b' * 64, 'requestId': 'request-1', 'targetFingerprint': 'c' * 64,
            'connectionRef': 'fixture', 'providerNamespace': provider.capacity_namespace,
            'executionEffect': EFFECT, 'executionGuard': {'operationId': 'operation-1'},
            'limits': {'cpu': 1, 'memoryMb': 128, 'diskMb': 1, 'seconds': 33}}
        before = len(tracked)
        asyncio.run(cancel_original(provider, reservation, marker, tracked, manager))
        require(len(tracked) == before + 1, 'CANCEL_CREATED_REPLACEMENT')
        report['cases']['cancelOriginal'] = {'status': 'PASS', 'originalClientCount': 1, 'receivedOriginalRequest': True}

        short = WindowsSSHCredentials(vault, max_agents=1, seconds=.1)
        stack.callback(short.close)
        expired = short.acquire(server, destination, lambda: None)
        time.sleep(max(0, expired.expires_at - time.monotonic()) + .01)
        before = len(tracked)
        with patch.object(vault, 'resolve', wraps=vault.resolve) as resolve:
            try:
                with pinned_ssh(server, expired, root, 'ignored', deadline=time.monotonic() + 5):
                    raise AssertionError('EXPIRED_LEASE_ENTERED')
            except RemoteConnectionError:
                pass
            resolve.assert_not_called()
        vault.revoke(owner='alice', reference=server.credential_ref, revision=server.credential_revision)
        with patch.object(vault, 'resolve', wraps=vault.resolve) as resolve:
            try:
                with pinned_ssh(server, lease, root, 'ignored', deadline=time.monotonic() + 5):
                    raise AssertionError('REVOKED_LEASE_ENTERED')
            except RemoteConnectionError:
                pass
            resolve.assert_not_called()
        require(len(tracked) == before, 'EXPIRY_OR_REVOCATION_SPAWNED')
        report['cases']['expiryAndRevocation'] = {'status': 'PASS', 'newClients': 0, 'credentialResolutions': 0}
        require(all(w.win32event.WaitForSingleObject(handle, 0) == w.win32con.WAIT_OBJECT_0 for handle in handles),
                'ORIGINAL_CLIENT_OR_HELPER_HANDLE_STILL_RUNNING')
        require(not manager.active and not any(t.name == 'factory-ssh-askpass' for t in threading.enumerate()),
                'OWNED_CARRIER_OR_BROKER_REMAINING')
        require(not any(manager_root.iterdir()), 'CARRIER_FILES_REMAINING')
        manager.close()
        short.close()
        require(not manager_root.exists() and not short.root.exists(), 'CARRIER_ROOT_NOT_REMOVED')
        report['ownedClientsAndHelpersStopped'] = True
    require(server_process.poll() is not None, 'FOREGROUND_SERVER_NOT_REAPED')
    report['ownedServerStopped'] = True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--environment', type=Path, required=True)
    parser.add_argument('--checkout', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = {'status': 'FAIL', 'scope': 'installed Windows core credential and pipe consumers',
              'fixtureReady': False, 'cases': {},
              'remoteEndpoint': 'controlled Windows ForceCommand, not Linux helper',
              'windowsToLinuxOriginalRecovery': 'BLOCKED: no authorized Linux endpoint supplied'}
    root = Path(os.environ['TEMP']) / ('owned-ssh-' + secrets.token_hex(6))
    try:
        if sys.platform != 'win32':
            raise Blocked('WINDOWS_REQUIRED')
        report['provenance'] = provenance(args.environment.resolve(), args.checkout.resolve())
        exercise(root, report)
        report['status'] = 'PASS'
    except Blocked as error:
        report.update(status='BLOCKED', reason=str(error))
    except Exception as error:
        report.update(status='FAIL', errorType=type(error).__name__)
        # Only fixture assertion identifiers are emitted; never exception text from providers.
        if isinstance(error, AssertionError) and re.fullmatch('[A-Z_]+', str(error)):
            report['assertion'] = str(error)
    finally:
        if root.exists():
            shutil.rmtree(root)
        report['ownedFixtureRemoved'] = not root.exists()
        args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
