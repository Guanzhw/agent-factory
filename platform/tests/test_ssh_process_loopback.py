"""Real CPU-only SSH custody through a transparent non-22 TCP entrance.

Requires Linux, OpenSSH server/client/agent and uv with cached build dependencies.
The helper is installed from this checkout's core wheel, then invoked with -I;
the disposable venv reuses the test runner's dependency site-packages only.
No account, system SSH configuration or persistent credential is created.
Run serially: PYTHONPATH=platform python -m unittest discover -s platform/tests
-p test_ssh_process_loopback.py -v. Only the test runner uses PYTHONPATH;
the SSH helper always uses its installed wheel. This is not GPU acceptance,
lost-ACK injection, controller-service restart or production sshd acceptance.
"""
import base64
from dataclasses import replace
import hashlib
import os
from pathlib import Path
import select
import shutil
import socket
import stat
import subprocess
import sys
from tempfile import TemporaryDirectory
import threading
import time
import unittest

from agent_factory.ssh_identity import SSHAgentLease, SSHServer
from agent_factory.ssh_process_contract import PROTOCOL
from agent_factory.ssh_process_provider import SSHProcessTransport


def command(args, **kwargs):
    result = subprocess.run(args, capture_output=True, text=True, timeout=60, **kwargs)
    if result.returncode:
        raise RuntimeError(f'{args[0]} failed ({result.returncode}): {result.stderr}')
    return result


class TCPRelay:
    def __init__(self, destination):
        self.destination = destination
        self.listener = socket.socket()
        self.listener.bind(('127.0.0.1', 0))
        self.listener.listen()
        self.listener.settimeout(.1)
        self.port = self.listener.getsockname()[1]
        self.stop = threading.Event()
        self.workers = []
        self.thread = threading.Thread(target=self.accept)
        self.thread.start()

    def accept(self):
        while not self.stop.is_set():
            try:
                client, _ = self.listener.accept()
            except socket.timeout:
                continue
            worker = threading.Thread(target=self.forward, args=(client,))
            self.workers.append(worker)
            worker.start()

    def forward(self, client):
        with client, socket.create_connection(self.destination, timeout=5) as remote:
            peers = {client: remote, remote: client}
            while not self.stop.is_set():
                readable, _, _ = select.select(list(peers), [], [], .1)
                for source in readable:
                    chunk = source.recv(65536)
                    if not chunk:
                        return
                    peers[source].sendall(chunk)

    def close(self):
        self.stop.set()
        self.thread.join(timeout=6)
        self.listener.close()
        for worker in self.workers:
            worker.join(timeout=6)
        if self.thread.is_alive() or any(worker.is_alive() for worker in self.workers):
            raise RuntimeError('SSH fixture relay did not stop')


@unittest.skipUnless(sys.platform == 'linux', 'OpenSSH custody requires Linux')
class SSHProcessLoopbackTests(unittest.TestCase):
    def setUp(self):
        import pwd

        if os.getuid() == 0:
            self.skipTest('fixture must use an existing nonroot account')
        for executable in ('ssh', 'sshd', 'ssh-keygen', 'ssh-agent', 'ssh-add', 'uv'):
            if not shutil.which(executable):
                self.skipTest(f'loopback prerequisite unavailable: {executable}')
        self.root = Path(self.enterContext(TemporaryDirectory(prefix='af-ssh-loopback-')))
        self.runs = self.root / 'runs'
        self.runs.mkdir(mode=0o700)
        self.processes = []
        self.addCleanup(self.stop_processes)
        checkout = Path(__file__).resolve().parents[1]
        wheels = self.root / 'wheels'
        build_env = {**os.environ, 'UV_CACHE_DIR': str(self.root / 'uv-cache')}
        command(['uv', 'build', '--offline', '--no-build-isolation', '--python', sys.executable,
                 '--wheel', '--out-dir', str(wheels), str(checkout)], env=build_env)
        environment = self.root / 'venv'
        command(['uv', 'venv', '--offline', '--python', sys.executable, str(environment)], env=build_env)
        self.python = str(environment / 'bin/python')
        command(['uv', 'pip', 'install', '--offline', '--no-deps', '--python', self.python,
                 str(next(wheels.glob('*.whl')))], env=build_env)
        site = next((environment / 'lib').glob('python*/site-packages'))
        dependencies = [p for p in sys.path if p.endswith('/site-packages')]
        (site / 'fixture-dependencies.pth').write_text('\n'.join(dependencies) + '\n')
        loaded = command([self.python, '-I', '-c',
                          'import agent_factory.ssh_process_helper; import agent_factory; print(agent_factory.__file__)']).stdout.strip()
        self.assertTrue(Path(loaded).is_relative_to(environment), loaded)
        for name in ('host', 'client', 'wrong'):
            command(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(self.root / name)])
            self.assertEqual(stat.S_IMODE((self.root / name).stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.root.stat().st_mode), 0o700)
        self.agent_socket = self.root / 'agent.sock'
        self.start(['ssh-agent', '-D', '-a', str(self.agent_socket)])
        self.until(lambda: self.agent_socket.exists(), 'agent socket')
        command(['ssh-add', str(self.root / 'client')],
                env={**os.environ, 'SSH_AUTH_SOCK': str(self.agent_socket)})
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1', 0))
            backend_port = reservation.getsockname()[1]
        config = self.root / 'sshd_config'
        config.write_text(f'''ListenAddress 127.0.0.1
Port {backend_port}
HostKey {self.root / 'host'}
PidFile {self.root / 'sshd.pid'}
AuthorizedKeysFile {self.root / 'client.pub'}
PasswordAuthentication no
KbdInteractiveAuthentication no
UsePAM no
LogLevel ERROR
# The disposable authorized-key directory is private; its /tmp ancestor is not.
StrictModes no
AllowUsers {pwd.getpwuid(os.getuid()).pw_name}
''')
        self.start([shutil.which('sshd'), '-D', '-e', '-f', str(config)])

        def listening():
            try:
                with socket.create_connection(('127.0.0.1', backend_port), timeout=.1):
                    return True
            except OSError:
                return False

        self.until(listening, 'sshd listener')
        relay = TCPRelay(('127.0.0.1', backend_port))
        self.addCleanup(relay.close)
        self.assertNotEqual(relay.port, 22)
        self.server = SSHServer('fixture', 'alice', '1', 'loopback', '127.0.0.1', relay.port,
            pwd.getpwuid(os.getuid()).pw_name, self.public_key('host'), str(self.runs), 'key', '1')
        self.lease = SSHAgentLease(str(self.agent_socket), self.public_key('client'), lambda: None)
        self.transport = self.transport_for(self.server)

    def public_key(self, name):
        return ' '.join((self.root / f'{name}.pub').read_text().split()[:2])

    def tearDown(self):
        path = self.root / 'process-1.log'
        if path.exists() and path.stat().st_size:
            print('fixture sshd: ' + path.read_text(), file=sys.stderr)

    def start(self, args):
        log = self.enterContext((self.root / f'process-{len(self.processes)}.log').open('wb'))
        process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=log, stderr=log)
        self.processes.append(process)

    def stop_processes(self):
        for process in reversed(self.processes):
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    def until(self, predicate, label):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            for index, process in enumerate(self.processes):
                if process.poll() is not None:
                    self.fail(f'fixture process exited: {(self.root / f"process-{index}.log").read_text()}')
            result = predicate()
            if result:
                return result
            time.sleep(.05)
        self.fail(f'timed out waiting for {label}')

    def transport_for(self, server):
        return SSHProcessTransport(server, lambda _action: self.lease, interpreter=self.python)

    def request(self, name, program):
        executable = str(Path(sys.executable).resolve())
        return {'protocol': PROTOCOL, 'action': 'submit', 'root': str(self.runs),
            'binding': {'leaseId': name, 'operationId': name, 'ownerId': 'alice',
                'taskId': 'task', 'runId': 'run', 'planId': 'plan', 'requestId': name,
                'planHash': 'a' * 64, 'targetFingerprint': self.server.pin()},
            'spec': {'executable': executable, 'sha256': hashlib.sha256(Path(executable).read_bytes()).hexdigest(),
                     'argv': ['-I', '-S', '-c', program]},
            'limits': {'cpu_seconds': 1, 'address_space_mb': 128,
                       'file_size_bytes': 65536, 'wall_seconds': 5.0}}

    def test_pinned_forwarded_helper_original_identity_output_and_cancel(self):
        wrong = self.transport_for(replace(self.server, host_key=self.public_key('wrong')))
        value = self.request('complete', "print('synthetic-result', flush=True)")
        with self.assertRaises(ValueError):
            wrong(value)
        self.assertEqual(list(self.runs.iterdir()), [])
        capabilities = self.transport({'protocol': PROTOCOL, 'action': 'capabilities'})
        self.assertTrue(capabilities['processCustody'])
        self.assertFalse(capabilities['gpuAllocation'])
        first = self.transport(value)['observation']
        recovered = self.transport_for(self.server)

        def terminal():
            result = recovered({**value, 'action': 'inspect'})['observation']
            return result if result['stoppedProof'] else None

        stopped = self.until(terminal, 'original completion')
        self.assertEqual(stopped['state'], 'COMPLETED')
        duplicate = recovered(value)['observation']
        self.assertEqual((first['id'], stopped['id']), (duplicate['id'], duplicate['id']))
        self.assertEqual(stopped['child'], duplicate['child'])
        output = recovered({**value, 'action': 'output'})['output']
        raw = base64.b64decode(output['base64'])
        self.assertEqual(raw, b'synthetic-result\n')
        self.assertEqual(output['sha256'], hashlib.sha256(raw).hexdigest())
        self.assertEqual(len(list(self.runs.iterdir())), 1)
        long = self.request('cancel', 'import time; print("started", flush=True); time.sleep(30)')
        original = self.transport(long)['observation']
        try:
            cancelled = recovered({**long, 'action': 'cancel'})['observation']
            self.assertEqual(cancelled['id'], original['id'])
            self.assertTrue(cancelled['cancelRequested'])

            def cancellation_stopped():
                result = recovered({**long, 'action': 'inspect'})['observation']
                self.assertEqual(result['id'], original['id'])
                return result if result['stoppedProof'] else None

            cancelled = self.until(cancellation_stopped, 'original cancellation stop proof')
            self.assertEqual(cancelled['state'], 'CANCELLED')
        finally:
            recovered({**long, 'action': 'cancel'})
