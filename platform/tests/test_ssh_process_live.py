"""Opt-in loopback SSH/process mechanism; no model, remote account or GPU."""
import asyncio
import hashlib
import os
from pathlib import Path
import sys
import sysconfig
import time
import unittest
import venv

from cryptography.hazmat.primitives.asymmetric import ed25519

from agent_factory.process_enforcement import BoundedProcessAdapter, ProcessLimits, ProcessSpec
from agent_factory.resources import PersistentResourceService
from agent_factory.ssh_process_provider import EFFECT, SSHProcessProvider, SSHProcessTransport
import test_personal_ssh_live as ssh_fixtures


@unittest.skipUnless(os.name == 'posix' and ssh_fixtures.SSHD,
                     'set FACTORY_TEST_SSHD for isolated real SSH process acceptance')
class SSHProcessLiveTests(unittest.TestCase):
    setUp = ssh_fixtures.PersonalSSHLiveTests.setUp
    start_server = ssh_fixtures.PersonalSSHLiveTests.start_server
    register = ssh_fixtures.PersonalSSHLiveTests.register

    def test_original_helper_process_survives_ssh_exit_and_reopens_without_dispatch(self):
        values, private = self.start_server(ed25519.Ed25519PrivateKey.generate())
        reference, _ = self.register(values, private)
        self.connections.personal.verify('alice', reference, 'verify-process')
        self.connections.bind('alice', reference, 'enable-process', capabilities=['ssh:prepare', 'ssh:execute'])
        server = self.service.server('alice', reference, required_capability='ssh:execute')
        # Install only a temporary interpreter view of already installed dependencies/source.
        environment = self.root / 'helper-environment'
        venv.EnvBuilder(with_pip=False, symlinks=True).create(environment)
        packages = environment / 'lib' / f'python{sys.version_info.major}.{sys.version_info.minor}' / 'site-packages'
        (packages / 'fixture-source.pth').write_text(
            str(Path(__file__).resolve().parents[1]) + '\n' + sysconfig.get_path('purelib') + '\n')
        interpreter = str(environment / 'bin' / 'python')
        transport = SSHProcessTransport(server,
            lambda action: self.service.lease(server, required_capability='ssh:execute'), interpreter=interpreter)
        executable = Path(sys.executable).resolve()
        marker = self.root / 'one-training-dispatch'
        code = f"from pathlib import Path; p=Path({str(marker)!r}); p.write_text(p.read_text()+'x' if p.exists() else 'x'); print('original-result')"
        spec = ProcessSpec(str(executable), hashlib.sha256(executable.read_bytes()).hexdigest(), ('-I', '-c', code))
        provider = SSHProcessProvider(server, target_ref='selected', spec=spec, limits=ProcessLimits(wall_seconds=5),
            exchange=transport, read_lease=lambda owner, key: dict(lease))
        lease = {'id': 'original-lease', 'ownerId': 'alice', 'localTaskId': 'original-child',
            'nativeRunId': 'original-run', 'planId': 'original-plan', 'planHash': 'a' * 64,
            'requestId': 'original-request', 'fingerprint': 'b' * 64, 'targetFingerprint': 'c' * 64,
            'connectionRef': 'selected', 'providerNamespace': provider.capacity_namespace,
            'executionEffect': EFFECT, 'executionGuard': {'operationId': 'original-operation'},
            'limits': {'cpu': 1, 'memoryMb': 128, 'diskMb': 1, 'seconds': 35}}
        def stop_original():
            path = Path(server.allowed_root) / lease['id'] / 'custody.sqlite'
            if path.exists():
                # Same-host fixture cleanup uses only its original journal, even if SSH failed.
                original = BoundedProcessAdapter(path)
                original.cancel(owner_id='alice')
                self.assertTrue(original.wait(owner_id='alice')['stoppedProof'])
        self.addCleanup(stop_original)
        received = asyncio.run(provider.allocate_bound(lease, before_effect=lambda: None))
        lease.update(PersistentResourceService.process_snapshot(lease, received))
        original_job = lease['providerJobId']
        reopened = SSHProcessProvider(server, target_ref='selected', spec=spec, limits=provider.limits,
            exchange=SSHProcessTransport(server,
                lambda action: self.service.lease(server, required_capability='ssh:execute'), interpreter=interpreter),
            read_lease=lambda owner, key: dict(lease))
        deadline = time.monotonic() + 10
        while not received['allStopped'] and time.monotonic() < deadline:
            received = asyncio.run(reopened.inspect(lease['id'], 'alice'))
            lease.update(PersistentResourceService.process_snapshot(lease, received))
            if not received['allStopped']:
                time.sleep(.05)
        self.assertTrue(received['allStopped'], received)
        self.assertEqual(received['executionStatus'], 'COMPLETED')
        self.assertEqual(received['providerJobId'], original_job)
        self.assertEqual(reopened.read_completed_output(lease['id'], 'alice'), b'original-result\n')
        self.assertEqual(marker.read_text(), 'x')
        lease['releaseAck'] = 'unknown'
        released = asyncio.run(reopened.inspect(lease['id'], 'alice'))
        self.assertEqual(released['state'], 'RECLAIMED')
        self.assertEqual(marker.read_text(), 'x')
