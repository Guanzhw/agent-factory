"""Synthetic keys and independent in-memory custody, never a real user/server."""
import asyncio
import base64
from contextvars import ContextVar
from datetime import datetime, timezone
import io
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

import httpx

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import Column, Integer, JSON, MetaData, String, Table, create_engine, select
from sqlalchemy.pool import StaticPool

from agent_factory.connections import ConnectionService
from agent_factory.credential_vault import CredentialVaultError, EncryptedCredentialVault, credential_vault_router
from agent_factory.personal_remote_provider import RemoteConnectionError, origin
from agent_factory.ssh_identity import SSHServer
from agent_factory.personal_ssh import PersonalSSHServers, SSHAgents, SSHEnrollmentConfig, personal_ssh_router
from agent_factory.ssh_credentials import PROVIDER_ID, SSHCredentialPolicy, endpoint, ssh_destination
from test_personal_remote_connections import Auth
from pg_fixture import IsolatedPostgres


def fixture_key():
    key = Ed25519PrivateKey.generate()
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH,
        serialization.NoEncryption()).decode()


class PersonalSSHTests(unittest.TestCase):
    def setUp(self):
        self.engine = (create_engine(self.database.url) if hasattr(self, 'database') else
            create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool))
        self.addCleanup(self.engine.dispose)
        metadata = MetaData()
        Table('af_audit', metadata, Column('id', Integer, primary_key=True), Column('actor_id', String),
            Column('action', String), Column('target_id', String), Column('body', JSON), Column('created_at', String))
        metadata.create_all(self.engine)
        self.auth = Auth()
        self.policy = SSHCredentialPolicy()
        self.vault = EncryptedCredentialVault(self.engine, b'f' * 32, {PROVIDER_ID: self.policy, 'http-fixture': origin})
        shared = ContextVar('ssh-fixture-connection', default=None)
        self.vault.bind_read_context(shared)
        self.connections = ConnectionService(SimpleNamespace(engine=self.engine, _connection=shared), self.auth,
            clock=lambda: datetime(2026, 10, 11, tzinfo=timezone.utc))
        self.service = PersonalSSHServers(self.auth, self.connections, self.vault,
            SSHEnrollmentConfig(max_active_seconds=60))
        self.addCleanup(self.service.close)
        self.acquire = Mock(side_effect=lambda server, destination, guard: SimpleNamespace(validate=guard, check=guard))
        self.service.agents.acquire = self.acquire
        self.service.probe = Mock(return_value={'ok': True})
        host = Ed25519PrivateKey.generate().public_key().public_bytes(
            serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH).decode()
        self.input = {'name': '合成本人服务器', 'address': '127.0.0.1', 'port': 2222, 'username': 'fixture',
            'hostKey': host, 'allowedRoot': '/tmp/af-personal-fixture'}
        self.identity = self.service.identity(self.input)
        self.private = fixture_key()
        app = FastAPI(); self.app = app
        app.include_router(credential_vault_router(self.auth, self.vault))
        app.include_router(personal_ssh_router(self.auth, self.service))
        self.client = TestClient(app); self.headers = {'x-fixture-owner': 'alice'}
        self.root = '/api/factory/personal-ssh'

    def credential(self, owner='alice', request=None):
        return self.vault.create(owner=owner, provider_id=PROVIDER_ID, destination=self.identity['origin'],
            username='fixture', password=self.private, request_id=request)

    def registered(self):
        credential = self.credential()
        values = {**self.input, 'confirmedHostKey': True, 'credentialRef': credential['credentialRef'],
            'credentialRevision': credential['credentialRevision'], 'requestId': uuid4().hex}
        response = self.client.post(self.root, headers=self.headers, json=values)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json(), credential, values

    def command(self, server, action, request=None):
        request = request or uuid4().hex
        response = self.client.post(f"{self.root}/{server['reference']}/{action}", headers=self.headers,
            json={'requestId': request})
        return response, request

    def enabled(self):
        server, credential, values = self.registered()
        self.assertEqual(self.command(server, 'verify')[0].status_code, 200)
        response, _ = self.command(server, 'bind'); self.assertEqual(response.status_code, 200, response.text)
        return response.json(), credential, values

    def test_ssh_ciphertext_only_exact_owner_identity_and_original_command_recovery(self):
        captured = io.StringIO(); handler = logging.StreamHandler(captured)
        logger = logging.getLogger('sqlalchemy.engine'); before = logger.level
        logger.addHandler(handler); logger.setLevel(logging.INFO)
        try: credential = self.credential(request='key-original')
        finally: logger.removeHandler(handler); logger.setLevel(before)
        self.assertEqual(self.vault.recover(owner='alice', request_id='key-original'), credential)
        self.assertIsNone(self.vault.recover(owner='bob', request_id='key-original'))
        with self.engine.connect() as conn: rows = conn.execute(select(self.vault.credentials)).mappings().all()
        for sample in (repr(rows), captured.getvalue(), json.dumps(credential)):
            self.assertNotIn(self.private, sample)
            self.assertNotIn('BEGIN OPENSSH PRIVATE KEY', sample)
        scope = dict(owner='alice', reference=credential['credentialRef'], revision=credential['credentialRevision'],
            provider_id=PROVIDER_ID, destination=self.identity['origin'])
        self.assertEqual(serialization.load_ssh_private_key(base64.b64decode(self.vault.resolve(**scope).password), None).public_key().public_bytes(
            serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH),
            serialization.load_ssh_private_key(self.private.encode(), None).public_key().public_bytes(
                serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH))
        self.assertFalse(self.vault.authorize(**(scope | {'owner': 'bob'})))
        other_host = self.identity['origin'].replace('hostkey=', 'hostkey=0')
        self.assertFalse(self.vault.authorize(**(scope | {'destination': other_host})))
        self.assertEqual(self.acquire.call_count, 0)

    def test_dedicated_key_account_and_destination_policy_reject_without_secret_echo(self):
        payload = dict(providerId=PROVIDER_ID, destination=self.identity['origin'], username='wrong',
            password=self.private, requestId='invalid-account')
        for changes in ({}, {'username': 'fixture', 'password': 'synthetic-invalid-private-key'},
                        {'username': 'fixture', 'destination': 'https://runtime.example.com'}):
            response = self.client.post('/api/factory/personal-credentials', headers=self.headers,
                json=payload | changes)
            self.assertEqual(response.status_code, 400)
            self.assertNotIn(payload['password'], response.text)
        for values in (self.input | {'address': 'bad address'}, self.input | {'port': 0}, self.input | {'hostKey': self.private},
                       self.input | {'allowedRoot': '/tmp/../etc/private'}):
            response = self.client.post(self.root + '/identity', headers=self.headers, json=values)
            self.assertEqual(response.status_code, 422)
            self.assertNotIn(self.private, response.text)
        self.assertEqual(self.acquire.call_count, 0)

    def test_member_endpoint_accepts_dns_root_custom_port_and_long_directory(self):
        values = self.input | {'address': 'worker.internal', 'username': 'root', 'port': 2244,
            'allowedRoot': '/srv/' + 'project-' * 20}
        identity = self.service.identity(values)
        self.assertEqual(identity['address'], 'worker.internal')
        self.assertEqual(ssh_destination(identity['origin']), identity['origin'])
        self.assertEqual(identity['username'], 'root')
        ipv6 = self.service.identity(self.input | {'address': '::1'})
        self.assertIn('@[::1]:2222?', ipv6['origin'])
        self.assertEqual(self.acquire.call_count, 0)

    def test_pinned_ssh_uses_member_host_port_user_and_only_public_identity_files(self):
        from agent_factory.ssh_identity import pinned_ssh
        identity = self.service.identity(self.input | {'address': 'worker.internal', 'port': 2244, 'username': 'root'})
        server = self.service.profile('alice', 'fixture', 'v1', {**self.input, **identity,
            'credentialRef': 'fixture-key', 'credentialRevision': 'v1'})
        lease = SimpleNamespace(socket='/fixture/agent.sock', public_key=self.input['hostKey'])
        with TemporaryDirectory() as folder, patch('agent_factory.ssh_identity.subprocess.Popen') as launch:
            pinned_ssh(server, lease, Path(folder), 'printf fixture')
            command = launch.call_args.args[0]
            self.assertEqual(command[-6:], ['-l', 'root', '-p', '2244', 'worker.internal', 'printf fixture'])
            self.assertIn('StrictHostKeyChecking=yes', command)
            self.assertIn('HostKeyAlias=factory-pinned', command)
            self.assertIn('IdentityAgent=/fixture/agent.sock', command)
            self.assertEqual((Path(folder) / 'known_hosts').read_text().strip(), 'factory-pinned ' + server.host_key)
            self.assertEqual((Path(folder) / 'identity.pub').read_text().strip(), lease.public_key)
            self.assertFalse(any('PRIVATE KEY' in path.read_text() for path in Path(folder).iterdir()))

    @unittest.skipUnless(os.name == 'posix', 'generic remote shell fixture requires POSIX pipes')
    def test_generic_ssh_check_runs_without_research_package_python_or_docker(self):
        service = self.service
        service.package = None; service.probe_source = None
        server = service.profile('alice', 'fixture', 'v1', {**self.input,
            'credentialRef': 'fixture-key', 'credentialRevision': 'v1'})
        lease = SimpleNamespace(validate=lambda: None)
        def local_shell(server, lease, folder, command):
            self.assertNotIn('python', command); self.assertNotIn('docker', command)
            return subprocess.Popen(['/bin/sh', '-c', command], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        with patch('agent_factory.personal_ssh.pinned_ssh', side_effect=local_shell):
            result = PersonalSSHServers.probe(service, server, lease, 'inspect')
        self.assertEqual(result['code'], 'SSH_CONNECTION_READY')
        self.assertFalse(result['directoryExists'])

    def test_team_server_uses_owner_credential_and_withdrawal_invalidates_member_lease(self):
        server, _, _ = self.enabled()
        reference = server['reference']
        shared = self.client.post(f'{self.root}/{reference}/sharing', headers=self.headers,
            json={'visibility': 'team', 'requestId': 'share-with-team'})
        self.assertEqual(shared.status_code, 200, shared.text)
        bob = {'x-fixture-owner': 'bob'}
        visible = self.client.get(f'{self.root}/{reference}', headers=bob)
        self.assertEqual(visible.status_code, 200, visible.text)
        self.assertEqual(visible.json()['ownerId'], 'alice')
        self.assertFalse(visible.json()['isOwner'])
        self.assertNotIn('credentialRef', visible.json())
        self.assertNotIn('credentialRevision', visible.json())
        bound = self.client.post(f'{self.root}/{reference}/bind', headers=bob,
            json={'requestId': 'bob-binds-team-server'})
        self.assertEqual(bound.status_code, 200, bound.text)
        profile = self.service.server('bob', reference)
        self.assertEqual((profile.owner, profile.actor), ('alice', 'bob'))
        lease = self.service.lease(profile); lease.validate()
        self.assertEqual(self.acquire.call_args.args[0].owner, 'alice')
        self.assertFalse(bound.json()['executionEnabled'])
        execute = self.client.post(f'{self.root}/{reference}/bind-execution', headers=bob,
            json={'requestId': 'bob-explicit-execution'})
        self.assertEqual(execute.status_code, 200)
        execution = self.service.server('bob', reference, required_capability='ssh:execute')
        execution_lease = self.service.lease(execution, required_capability='ssh:execute')
        execution_lease.validate()
        self.assertFalse(self.service.inspect('alice', reference)['executionEnabled'])
        for action in ('verify', 'revoke'):
            response = self.client.post(f'{self.root}/{reference}/{action}', headers=bob,
                json={'requestId': 'bob-cannot-' + action})
            self.assertEqual(response.status_code, 404)
        response = self.client.post(f'{self.root}/{reference}/sharing', headers=self.headers,
            json={'visibility': 'personal', 'requestId': 'withdraw-team-server'})
        self.assertEqual(response.status_code, 200, response.text)
        with self.assertRaises(HTTPException): lease.validate()
        with self.assertRaises(HTTPException): execution_lease.validate()
        self.assertEqual(self.client.get(self.root, headers=bob).json(), [])

    def test_parser_supported_rsa_ecdsa_ed25519_keys_roundtrip_in_encrypted_vault(self):
        for key in (rsa.generate_private_key(public_exponent=65537, key_size=4096),
                ec.generate_private_key(ec.SECP256R1()), Ed25519PrivateKey.generate()):
            public = key.public_key().public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH).decode()
            private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH,
                serialization.NoEncryption()).decode()
            identity = self.service.identity(self.input | {'hostKey': public})
            credential = self.vault.create(owner='alice', provider_id=PROVIDER_ID,
                destination=identity['origin'], username='fixture', password=private)
            lease = self.vault.resolve(owner='alice', reference=credential['credentialRef'],
                revision=credential['credentialRevision'], provider_id=PROVIDER_ID, destination=identity['origin'])
            restored = serialization.load_ssh_private_key(base64.b64decode(lease.password), password=None)
            self.assertEqual(restored.public_key().public_bytes(serialization.Encoding.OpenSSH,
                serialization.PublicFormat.OpenSSH).decode(), public)
            with self.engine.connect() as conn:
                row = conn.execute(select(self.vault.credentials).where(
                    self.vault.credentials.c.reference == credential['credentialRef'])).mappings().one()
            self.assertNotIn(private, repr(dict(row)))
            self.assertNotIn('PRIVATE KEY', repr(dict(row)))

    def test_username_is_preserved_as_one_ssh_argument_and_encoded_in_credential_destination(self):
        from agent_factory.ssh_identity import pinned_ssh
        values = self.input | {'username': 'member+lab@example'}
        identity = self.service.identity(values)
        self.assertIn('member%2Blab%40example@', identity['origin'])
        self.assertEqual(ssh_destination(identity['origin']), identity['origin'])
        server = self.service.profile('alice', 'fixture', 'v1', values | identity | {
            'credentialRef': 'fixture-key', 'credentialRevision': 'v1'})
        with TemporaryDirectory() as folder, patch('agent_factory.ssh_identity.subprocess.Popen') as launch:
            pinned_ssh(server, SimpleNamespace(public_key=values['hostKey'], socket='/fixture/agent.sock'),
                Path(folder), 'printf fixture')
            self.assertEqual(launch.call_args.args[0][-6:],
                ['-l', 'member+lab@example', '-p', '2222', '127.0.0.1', 'printf fixture'])

    def test_host_confirmation_is_required_before_registration_or_network(self):
        credential = self.credential()
        payload = {**self.input, 'credentialRef': credential['credentialRef'],
            'credentialRevision': credential['credentialRevision'], 'requestId': 'confirm-required'}
        for changes in ({}, {'confirmedHostKey': False}, {'confirmedHostKey': 'true'}):
            response = self.client.post(self.root, headers=self.headers, json=payload | changes)
            self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(self.service.list('alice'), [])
        self.assertEqual(self.acquire.call_count, 0); self.service.probe.assert_not_called()

    def test_registration_and_read_recovery_do_not_probe_or_install(self):
        server, _, values = self.registered()
        self.assertFalse(server['enabled']); self.assertEqual(server['status'], 'configured')
        response = self.client.get(f"{self.root}/requests/{values['requestId']}?action=configure", headers=self.headers)
        self.assertEqual(response.status_code, 200); self.assertEqual(response.json()['server']['reference'], server['reference'])
        self.assertEqual(self.client.get(self.root, headers=self.headers).status_code, 200)
        self.assertEqual(self.acquire.call_count, 0); self.service.probe.assert_not_called()

    def test_cross_owner_read_key_binding_verify_enable_and_revoke_are_denied(self):
        server, credential, values = self.registered(); bob = {'x-fixture-owner': 'bob'}
        self.assertEqual(self.client.get(self.root, headers=bob).json(), [])
        for action in ('verify', 'bind', 'bind-execution', 'revoke'):
            response = self.client.post(f"{self.root}/{server['reference']}/{action}", headers=bob, json={'requestId': uuid4().hex})
            self.assertEqual(response.status_code, 404)
        self.assertEqual(self.client.get(f"{self.root}/{server['reference']}", headers=bob).status_code, 404)
        self.assertEqual(self.client.post(self.root, headers=bob, json=values | {'requestId': 'bob-ref'}).status_code, 403)
        self.assertFalse(self.vault.authorize(owner='bob', reference=credential['credentialRef'],
            revision=credential['credentialRevision'], provider_id=PROVIDER_ID, destination=self.identity['origin']))
        self.service.probe.assert_not_called()

    def test_verify_is_read_only_and_separate_enable_is_required(self):
        server, _, _ = self.registered()
        response, request = self.command(server, 'verify'); self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()['enabled']); self.assertEqual(response.json()['status'], 'verified')
        self.assertEqual(self.service.probe.call_args.args[2], 'inspect')
        with self.assertRaises(HTTPException): self.service.server('alice', server['reference'])
        recover = self.client.get(f'{self.root}/requests/{request}?action=verify', headers=self.headers)
        self.assertEqual(recover.status_code, 200); self.assertEqual(self.service.probe.call_count, 1)
        response, request = self.command(server, 'bind'); self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['enabled'])
        self.assertEqual(self.client.get(f'{self.root}/requests/{request}?action=bind', headers=self.headers).status_code, 200)
        self.assertEqual(self.service.probe.call_count, 1)
        binding = self.connections.request_result('alice', request)['connection']
        self.connections.revoke('alice', binding['ref'], 'original-connection-revoke')
        wrong = self.client.get(f'{self.root}/requests/original-connection-revoke?action=bind', headers=self.headers)
        self.assertEqual(wrong.status_code, 409)

    def test_execution_requires_explicit_binding_and_recovers_original_scope(self):
        server, _, _ = self.enabled()
        self.assertTrue(server['enabled']); self.assertFalse(server['executionEnabled'])
        with self.assertRaises(HTTPException):
            self.service.server('alice', server['reference'], required_capability='ssh:execute')
        probes = self.service.probe.call_count
        response, request = self.command(server, 'bind-execution')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['executionEnabled'])
        self.assertEqual(self.command(server, 'bind-execution', request)[0].json(), response.json())
        recovered = self.client.get(f'{self.root}/requests/{request}?action=bind-execution', headers=self.headers)
        self.assertEqual(recovered.status_code, 200)
        self.assertEqual(self.client.get(f'{self.root}/requests/{request}?action=bind', headers=self.headers).status_code, 409)
        self.assertEqual(self.command(server, 'bind', request)[0].status_code, 409)
        self.assertEqual(self.service.probe.call_count, probes)
        profile = self.service.server('alice', server['reference'], required_capability='ssh:execute')
        lease = self.service.lease(profile, required_capability='ssh:execute'); lease.validate()
        binding = self.connections.request_result('alice', request)['connection']
        self.connections.revoke('alice', binding['ref'], 'revoke-execution')
        with self.assertRaises(HTTPException): lease.validate()
        self.assertTrue(self.service.inspect('alice', server['reference'])['enabled'])
        self.assertFalse(self.service.inspect('alice', server['reference'])['executionEnabled'])

    def test_prepare_receipt_and_probe_cannot_authorize_execution(self):
        server, _, _ = self.enabled()
        _, request = self.command(server, 'bind')
        self.assertEqual(self.client.get(f'{self.root}/requests/{request}?action=bind-execution', headers=self.headers).status_code, 409)
        profile = self.service.server('alice', server['reference'])
        with self.assertRaises(HTTPException):
            self.service.lease(profile, require_binding=False, required_capability='ssh:execute')

    def test_generic_omitted_capabilities_do_not_enable_execution(self):
        server, _, _ = self.enabled()
        original = self.connections.bind('alice', server['reference'], 'generic-prepare-only')
        self.assertEqual(original['capabilities'], ['ssh:prepare'])
        self.assertFalse(self.service.inspect('alice', server['reference'])['executionEnabled'])
        explicit = self.connections.bind('alice', server['reference'], 'generic-execute-explicit',
            capabilities=['ssh:prepare', 'ssh:execute'])
        self.assertEqual(set(explicit['capabilities']), {'ssh:prepare', 'ssh:execute'})
        self.assertTrue(self.service.inspect('alice', server['reference'])['executionEnabled'])
        replay = self.connections.bind('alice', server['reference'], 'generic-prepare-only')
        self.assertEqual(replay['ref'], original['ref'])
        self.assertEqual(replay['capabilities'], ['ssh:prepare'])

    def test_authoritative_dependency_failure_is_actionable_and_can_recover_without_reprobe(self):
        server, _, _ = self.registered()
        self.service.probe.side_effect = RemoteConnectionError('SSH_PYTHON_MISSING')
        response, request = self.command(server, 'verify'); self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['detail']['code'], 'SSH_PYTHON_MISSING')
        current = self.client.get(f"{self.root}/{server['reference']}", headers=self.headers).json()
        self.assertEqual(current['diagnostic'], 'SSH_PYTHON_MISSING'); self.assertEqual(current['lastCheckRequestId'], request)
        self.assertFalse(current['enabled']); self.assertEqual(current['status'], 'failed')
        self.assertEqual(self.service.probe.call_count, 1)
        self.service.probe.side_effect = None
        response, _ = self.command(server, 'verify'); self.assertEqual(response.status_code, 200)
        self.assertEqual(self.service.probe.call_count, 2)

    def test_untrusted_transport_exception_never_becomes_a_diagnostic_or_secret_echo(self):
        server, _, _ = self.registered()
        self.service.probe.side_effect = ValueError(self.private)
        response, _ = self.command(server, 'verify'); self.assertEqual(response.status_code, 409)
        self.assertNotIn(self.private, response.text)
        self.assertIsNone(self.service.inspect('alice', server['reference'])['diagnostic'])

    def test_recheck_and_new_binding_keep_configuration_pin_and_original_directory(self):
        server, _, _ = self.enabled(); original = self.service.server('alice', server['reference'])
        response, _ = self.command(server, 'verify'); self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()['enabled'])
        self.assertEqual(self.command(server, 'bind')[0].status_code, 200)
        replacement = self.service.server('alice', server['reference'])
        self.assertEqual(original.pin(), replacement.pin())
        self.assertEqual(replacement.allowed_root, self.input['allowedRoot'])

    def test_credential_rotation_and_resource_revocation_invalidate_live_guards(self):
        server, credential, _ = self.enabled(); profile = self.service.server('alice', server['reference'])
        lease = self.service.lease(profile); lease.validate()
        self.vault.rotate(owner='alice', reference=credential['credentialRef'], revision=credential['credentialRevision'],
            username='fixture', password=fixture_key())
        with self.assertRaises(HTTPException): lease.validate()
        self.assertFalse(self.service.inspect('alice', server['reference'])['enabled'])
        server, _, _ = self.enabled(); lease = self.service.lease(self.service.server('alice', server['reference']))
        response, request = self.command(server, 'revoke'); self.assertEqual(response.status_code, 200)
        with self.assertRaises(HTTPException): lease.validate()
        self.assertEqual(self.client.get(f'{self.root}/requests/{request}?action=revoke', headers=self.headers).status_code, 200)

    def test_explicit_reconfiguration_revokes_previous_bound_profile_without_remote_effect(self):
        server, _, values = self.enabled(); original = self.service.server('alice', server['reference'])
        self.service.probe.reset_mock()
        response = self.client.post(f"{self.root}/{server['reference']}/configure", headers=self.headers,
            json=values | {'allowedRoot': '/tmp/af-new-private-root', 'requestId': 'new-directory'})
        self.assertEqual(response.status_code, 200, response.text); self.assertFalse(response.json()['enabled'])
        with self.assertRaises(HTTPException): self.service.server('alice', original.reference)
        self.service.probe.assert_not_called()

    def test_permission_removed_during_probe_cannot_create_verification_or_binding(self):
        server, _, _ = self.registered()
        self.service.probe.side_effect = lambda *args: setattr(self.auth, 'disabled', True)
        response, _ = self.command(server, 'verify'); self.assertEqual(response.status_code, 403)
        self.auth.disabled = False
        self.assertFalse(self.service.inspect('alice', server['reference'])['enabled'])

    def test_slow_ssh_check_keeps_other_gets_responsive_without_replay(self):
        server, _, _ = self.registered()
        entered, release = threading.Event(), threading.Event()
        def slow_probe(*args):
            entered.set()
            if not release.wait(timeout=2): raise RemoteConnectionError('SSH_CHECK_UNCONFIRMED')
        self.service.probe.side_effect = slow_probe
        async def observe():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app),
                    base_url='http://fixture', headers=self.headers) as client:
                pending = asyncio.create_task(client.post(f"{self.root}/{server['reference']}/verify",
                    json={'requestId': 'slow-original-check'}))
                try:
                    self.assertTrue(await asyncio.to_thread(entered.wait, 1))
                    self.assertFalse(pending.done(), 'SSH probe blocked the ASGI loop')
                    health = await asyncio.wait_for(client.get(self.root + '/capabilities'), timeout=.5)
                    self.assertEqual(health.status_code, 200)
                    self.assertTrue(health.json()['enabled'])
                finally:
                    release.set()
                response = await pending
                self.assertEqual(response.status_code, 200, response.text)
                self.service.probe.assert_called_once()
        asyncio.run(observe())

    def test_stale_agent_expiry_callback_cannot_close_replacement_agent(self):
        agents = object.__new__(SSHAgents); agents.lock = threading.RLock()
        old, new, timer, folder = Mock(), Mock(), Mock(), Mock()
        agents.live = {'key': {'process': new, 'timer': timer, 'folder': folder}}
        agents._close('key', old)
        new.terminate.assert_not_called(); timer.cancel.assert_not_called(); folder.cleanup.assert_not_called()
        self.assertIs(agents.live['key']['process'], new)

    @unittest.skipUnless(os.name == 'posix' and shutil.which('ssh-agent') and shutil.which('ssh-add'), 'local OpenSSH agent fixture requires POSIX')
    def test_actual_private_agent_reuse_uses_new_strong_guard_and_no_private_file(self):
        credential = self.credential(); agents = SSHAgents(self.vault, max_agents=2, seconds=60); self.addCleanup(agents.close)
        server = SSHServer('fixture', 'alice', 'v1', 'fixture', '127.0.0.1', 2222, 'fixture', self.input['hostKey'],
            self.input['allowedRoot'], credential['credentialRef'], credential['credentialRevision'])
        def no_sql_under_agent_lock():
            admitted = threading.Event()
            def take_lock():
                with agents.lock: admitted.set()
            worker = threading.Thread(target=take_lock, daemon=True); worker.start()
            worker.join(timeout=1)
            self.assertTrue(admitted.is_set(), 'SQL/authorization callback held the agent mutex')
        authorize, resolve = self.vault.authorize, self.vault.resolve
        def unlocked_authorize(**scope):
            no_sql_under_agent_lock(); return authorize(**scope)
        def unlocked_resolve(**scope):
            no_sql_under_agent_lock(); return resolve(**scope)
        self.vault.authorize = unlocked_authorize; self.vault.resolve = unlocked_resolve
        first = agents.acquire(server, self.identity['origin'], no_sql_under_agent_lock)
        allowed = [True]
        def guard():
            no_sql_under_agent_lock()
            if not allowed[0]: raise RemoteConnectionError('SSH_CONFIGURATION_CHANGED')
        second = agents.acquire(server, self.identity['origin'], guard)
        self.assertEqual(first.socket, second.socket); self.assertEqual(first.public_key, second.public_key)
        allowed[0] = False
        with self.assertRaises(RemoteConnectionError): second.validate()
        with self.assertRaises(RemoteConnectionError): agents.acquire(server, self.identity['origin'], guard)
        self.assertFalse(any(p.is_file() for p in agents.root.rglob('*')))

    def test_legacy_https_domain_is_unchanged_and_ssh_destination_is_canonical(self):
        self.assertEqual(ssh_destination(self.identity['origin']), self.identity['origin'])
        legacy = self.vault.create(owner='alice', provider_id='http-fixture', destination='https://RUNTIME.example.com:443/',
            username='fixture', password='synthetic-http-only')
        self.assertEqual(legacy['destination'], 'https://runtime.example.com')
        with self.assertRaises(CredentialVaultError):
            self.vault.create(owner='alice', provider_id='http-fixture', destination=self.identity['origin'],
                username='fixture', password='synthetic-http-only')
        other = Ed25519PrivateKey.generate().public_key().public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH).decode()
        self.assertNotEqual(endpoint('127.0.0.1', 2222, 'fixture', other)['origin'], self.identity['origin'])


@unittest.skipUnless(os.environ.get('FACTORY_TEST_DATABASE_URL'), 'independent PostgreSQL fixture required')
class PersonalSSHPostgresTests(PersonalSSHTests):
    def setUp(self):
        self.database = IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL'])
        self.database.__enter__()
        self.addCleanup(self.database.__exit__, None, None, None)
        super().setUp()
