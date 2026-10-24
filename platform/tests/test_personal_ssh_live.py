"""Loopback OpenSSH acceptance with synthetic keys, platform members and SQL data.

Set FACTORY_TEST_SSHD to an installed/extracted sshd executable on POSIX. The
fixture launches and reaps its own loopback daemon, using the current OS account
and a test-only AuthorizedKeysFile. It never reads ~/.ssh.
"""
from contextvars import ContextVar
from datetime import datetime, timezone
import getpass
import os
from pathlib import Path
import shlex
import shutil
import socket
import subprocess
from tempfile import TemporaryDirectory
import time
from types import SimpleNamespace
import unittest
from uuid import uuid4

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, rsa
from fastapi import HTTPException
from sqlalchemy import Column, Integer, JSON, MetaData, String, Table, create_engine
from sqlalchemy.pool import StaticPool

from agent_factory.connections import ConnectionService
from agent_factory.credential_vault import CredentialVaultError, EncryptedCredentialVault
from agent_factory.personal_remote_provider import RemoteConnectionError
from agent_factory.personal_ssh import PersonalSSHServers, SSHEnrollmentConfig
from agent_factory.ssh_credentials import PROVIDER_ID, SSHCredentialPolicy
from agent_factory.ssh_identity import pinned_ssh


SSHD = os.environ.get('FACTORY_TEST_SSHD')


class Members:
    def __init__(self): self.disabled = set()
    def require_member(self, actor):
        if actor not in {'alice', 'bob', 'account-admin'} or actor in self.disabled:
            raise HTTPException(403, 'MEMBER_UNAVAILABLE')


@unittest.skipUnless(os.name == 'posix' and SSHD, 'set FACTORY_TEST_SSHD for isolated real SSH acceptance')
class PersonalSSHLiveTests(unittest.TestCase):
    def setUp(self):
        for executable in ('ssh', 'ssh-agent', 'ssh-add'):
            self.assertIsNotNone(shutil.which(executable), executable)
        self.temp = TemporaryDirectory(prefix='af-ssh-live-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        self.addCleanup(self.engine.dispose)
        metadata = MetaData()
        Table('af_audit', metadata, Column('id', Integer, primary_key=True), Column('actor_id', String),
            Column('action', String), Column('target_id', String), Column('body', JSON), Column('created_at', String))
        metadata.create_all(self.engine)
        shared = ContextVar('live-ssh-metadata', default=None)
        self.auth = Members()
        self.vault = EncryptedCredentialVault(self.engine, b'l' * 32, {PROVIDER_ID: SSHCredentialPolicy()})
        self.vault.bind_read_context(shared)
        self.connections = ConnectionService(SimpleNamespace(engine=self.engine, _connection=shared), self.auth,
            clock=lambda: datetime.now(timezone.utc))
        self.service = PersonalSSHServers(self.auth, self.connections, self.vault, SSHEnrollmentConfig(max_active_seconds=60))
        self.addCleanup(self.service.close)
        self.operations = self.root / 'operations.log'

    def start_server(self, key):
        directory = self.root / uuid4().hex[:8]; directory.mkdir(mode=0o700)
        private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH,
            serialization.NoEncryption()).decode()
        public = key.public_key().public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH).decode()
        host = directory / 'host'; host.write_text(private); host.chmod(0o600)
        authorized = directory / 'authorized_keys'; authorized.write_text(public + '\n'); authorized.chmod(0o600)
        wrapper = directory / 'remote-shell'
        wrapper.write_text('#!/bin/sh\nPATH=/factory-no-tools\nexport PATH\n'
            'if command -v python3 >/dev/null 2>&1 || command -v docker >/dev/null 2>&1; then exit 97; fi\n'
            'printf "%s\\n" "python=absent docker=absent" >> ' + shlex.quote(str(self.operations)) + '\n'
            'exec /bin/sh -c "$SSH_ORIGINAL_COMMAND"\n')
        wrapper.chmod(0o700)
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1', 0)); port = reservation.getsockname()[1]
        username = getpass.getuser()
        configuration = directory / 'sshd_config'
        configuration.write_text(f'Port {port}\nListenAddress 127.0.0.1\nHostKey {host}\n'
            f'PidFile {directory / "sshd.pid"}\nAuthorizedKeysFile {authorized}\nAllowUsers {username}\n'
            'StrictModes no\nPasswordAuthentication no\nKbdInteractiveAuthentication no\nUsePAM no\n'
            'PermitRootLogin yes\nPrintMotd no\nLogLevel ERROR\n'
            f'ForceCommand /bin/sh {wrapper}\n')
        stderr = (directory / 'sshd.log').open('wb')
        self.addCleanup(stderr.close)
        process = subprocess.Popen([SSHD, '-D', '-e', '-f', str(configuration)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=stderr)
        def stop():
            if process.poll() is None:
                process.terminate()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
        self.addCleanup(stop)
        deadline = time.monotonic() + 5
        while True:
            if process.poll() is not None:
                self.fail('isolated sshd failed: ' + (directory / 'sshd.log').read_text())
            try:
                with socket.create_connection(('127.0.0.1', port), timeout=.2): break
            except OSError:
                if time.monotonic() > deadline: self.fail('isolated sshd did not listen')
                time.sleep(.02)
        return {'name': 'synthetic live SSH', 'address': '127.0.0.1', 'port': port, 'username': username,
            'hostKey': public, 'allowedRoot': str(directory)}, private

    def register(self, values, private):
        identity = self.service.identity(values)
        credential = self.vault.create(owner='alice', provider_id=PROVIDER_ID, destination=identity['origin'],
            username=values['username'], password=private)
        configured = self.connections.personal.configure('alice', PROVIDER_ID, values | {
            'confirmedHostKey': True, 'credentialRef': credential['credentialRef'],
            'credentialRevision': credential['credentialRevision']}, uuid4().hex)
        return configured['registrationRef'], credential

    def count_operations(self):
        return len(self.operations.read_text().splitlines()) if self.operations.exists() else 0

    def test_real_rsa_ecdsa_ed25519_onboarding_has_no_research_dependencies(self):
        for key in (rsa.generate_private_key(public_exponent=65537, key_size=2048),
                ec.generate_private_key(ec.SECP256R1()), ed25519.Ed25519PrivateKey.generate()):
            with self.subTest(key=type(key).__name__):
                values, private = self.start_server(key)
                reference, _ = self.register(values, private)
                before = self.count_operations()
                result = self.connections.personal.verify('alice', reference, uuid4().hex)
                self.assertEqual(result['status'], 'verified')
                self.assertIsNone(self.service.package)
                self.assertIsNone(self.service.probe_source)
                self.assertEqual(self.count_operations(), before + 1)
                self.assertFalse(any(p.is_file() for p in self.service.agents.root.rglob('*')))

    def test_real_shared_ssh_keeps_owner_credentials_and_stops_retained_member_lease(self):
        values, private = self.start_server(ed25519.Ed25519PrivateKey.generate())
        reference, credential = self.register(values, private)
        self.connections.personal.verify('alice', reference, uuid4().hex)
        self.connections.personal.share('alice', reference, 'team', uuid4().hex)
        self.connections.bind('bob', reference, uuid4().hex, capabilities=['ssh:prepare'])
        profile = self.service.server('bob', reference)
        self.assertEqual((profile.owner, profile.actor), ('alice', 'bob'))
        projection = self.service.inspect('bob', reference)
        self.assertNotIn('credentialRef', projection); self.assertNotIn('credentialRevision', projection)
        scope = dict(owner='bob', reference=credential['credentialRef'], revision=credential['credentialRevision'],
            provider_id=PROVIDER_ID, destination=self.service.identity(values)['origin'])
        with self.assertRaises(CredentialVaultError): self.vault.resolve(**scope)
        for actor in ('bob', 'account-admin'):
            with self.assertRaises(HTTPException): self.connections.personal.revoke(actor, reference, uuid4().hex)
        lease = self.service.lease(profile)
        before = self.count_operations()
        proof = self.service.probe(profile, lease, 'inspect')
        self.assertEqual(proof['code'], 'SSH_CONNECTION_READY')
        self.assertTrue(proof['directoryExists']); self.assertEqual(self.count_operations(), before + 1)
        for change in ('disable', 'withdraw', 'revoke-credential'):
            with self.subTest(change=change):
                if change == 'disable': self.auth.disabled.add('bob')
                elif change == 'withdraw': self.connections.personal.share('alice', reference, 'personal', uuid4().hex)
                else: self.vault.revoke(owner='alice', reference=credential['credentialRef'], revision=credential['credentialRevision'])
                before = self.count_operations()
                with self.assertRaises((HTTPException, RemoteConnectionError)):
                    self.service.probe(profile, lease, 'inspect')
                self.assertEqual(self.count_operations(), before)
                if change == 'disable': self.auth.disabled.remove('bob')
                elif change == 'withdraw': self.connections.personal.share('alice', reference, 'team', uuid4().hex)

    def test_wrong_host_identity_fails_before_remote_operation_and_app_prepare_is_explicit(self):
        values, private = self.start_server(ed25519.Ed25519PrivateKey.generate())
        wrong = ed25519.Ed25519PrivateKey.generate().public_key().public_bytes(
            serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH).decode()
        reference, _ = self.register(values | {'hostKey': wrong}, private)
        before = self.count_operations()
        with self.assertRaises(HTTPException): self.connections.personal.verify('alice', reference, uuid4().hex)
        self.assertEqual(self.count_operations(), before)
        reference, _ = self.register(values, private)
        self.connections.personal.verify('alice', reference, uuid4().hex)
        self.connections.bind('alice', reference, uuid4().hex, capabilities=['ssh:prepare'])
        profile = self.service.server('alice', reference)
        lease = self.service.lease(profile)
        with self.assertRaisesRegex(RemoteConnectionError, '^SSH_CHECK_UNCONFIRMED$'):
            self.service.probe(profile, lease, 'prepare')
        self.service.package = SimpleNamespace(root=self.root, _ssh=pinned_ssh)
        self.service.probe_source = 'raise AssertionError("Python must not be required for enrollment")'
        before = self.count_operations()
        with self.assertRaisesRegex(RemoteConnectionError, '^SSH_PYTHON_MISSING$'):
            self.service.probe(profile, lease, 'prepare')
        self.assertEqual(self.count_operations(), before + 1)
