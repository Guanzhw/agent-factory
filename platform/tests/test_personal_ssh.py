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
from tempfile import TemporaryDirectory
import threading
from types import SimpleNamespace
from typing import cast
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

import httpx

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import Column, Integer, JSON, MetaData, String, Table, create_engine, select
from sqlalchemy.pool import StaticPool

from agent_factory.connections import ConnectionService
from agent_factory.credential_vault import CredentialVaultError, EncryptedCredentialVault, credential_vault_router
from agent_factory.personal_remote_provider import RemoteConnectionError, origin
from agent_factory.personal_ssh import PersonalSSHServers, SSHAgents, SSHEnrollmentConfig, personal_ssh_router
from agent_factory.platform_openresearch import PlatformOpenResearchConfig
from agent_factory.runtime_packages.openresearch_v1 import ssh_prerequisites
from agent_factory.ssh_credentials import PROVIDER_ID, SSHCredentialPolicy, endpoint, ssh_destination
from agent_factory.ssh_openresearch import SSHServer
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
        self.policy = SSHCredentialPolicy(lambda ip, port: ip == '127.0.0.1' and port == 2222)
        self.vault = EncryptedCredentialVault(self.engine, b'f' * 32, {PROVIDER_ID: self.policy, 'http-fixture': origin})
        shared = ContextVar('ssh-fixture-connection', default=None)
        self.vault.bind_read_context(shared)
        self.connections = ConnectionService(SimpleNamespace(engine=self.engine, _connection=shared), self.auth,
            clock=lambda: datetime(2026, 10, 11, tzinfo=timezone.utc))
        runtime = cast(PlatformOpenResearchConfig, SimpleNamespace(max_active_seconds=60))
        self.service = PersonalSSHServers(self.auth, self.connections, self.vault,
            SSHEnrollmentConfig(runtime, lambda ip, port: ip == '127.0.0.1' and port == 2222))
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
        for values in (self.input | {'username': 'root'}, self.input | {'address': 'runtime.example.com'},
                       self.input | {'port': 22}, self.input | {'hostKey': self.private},
                       self.input | {'allowedRoot': '/tmp/../etc/private'}):
            response = self.client.post(self.root + '/identity', headers=self.headers, json=values)
            self.assertEqual(response.status_code, 422)
            self.assertNotIn(self.private, response.text)
        self.assertEqual(self.acquire.call_count, 0)

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
        for action in ('verify', 'bind', 'revoke'):
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
        original_policy = self.service.config
        self.service.config = SSHEnrollmentConfig(original_policy.runtime, lambda ip, port: False)
        with self.assertRaises(HTTPException): lease.validate()
        self.assertFalse(self.service.inspect('alice', server['reference'])['enabled'])
        self.service.config = original_policy
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


@unittest.skipUnless(os.name == 'posix', 'owner directory fixture requires POSIX')
class SSHPrerequisiteTests(unittest.TestCase):
    def test_inspect_never_creates_root_and_prepare_creates_only_private_child(self):
        with TemporaryDirectory() as parent:
            root = Path(parent) / 'private'
            body = {'root': str(root), 'action': 'inspect', 'nonce': 'fixture'}
            with patch.object(ssh_prerequisites.sys, 'platform', 'linux'), patch.object(ssh_prerequisites.os, 'uname', return_value=SimpleNamespace(machine='x86_64')), patch.object(ssh_prerequisites.os, 'getuid', return_value=os.getuid()), patch.object(ssh_prerequisites.shutil, 'which', return_value='/fixture/docker'), patch.object(ssh_prerequisites.subprocess, 'run', return_value=SimpleNamespace(returncode=0)):
                result = ssh_prerequisites.run(body); self.assertTrue(result['ok']); self.assertFalse(root.exists())
                result = ssh_prerequisites.run(body | {'action': 'prepare'}); self.assertTrue(result['ok'])
                self.assertEqual(root.stat().st_mode & 0o777, 0o700)
                self.assertEqual(list(Path(parent).iterdir()), [root])

    def test_missing_dependencies_foreign_and_linked_directories_are_distinct_failures(self):
        with TemporaryDirectory() as parent:
            root = Path(parent) / 'private'; root.mkdir(mode=0o755); root.chmod(0o755)
            body = {'root': str(root), 'action': 'inspect', 'nonce': 'fixture'}
            with patch.object(ssh_prerequisites.shutil, 'which', return_value=None):
                self.assertEqual(ssh_prerequisites.run(body)['code'], 'SSH_DOCKER_MISSING')
            with patch.object(ssh_prerequisites.shutil, 'which', return_value='/fixture/docker'), patch.object(ssh_prerequisites.subprocess, 'run', return_value=SimpleNamespace(returncode=1, stderr=b'permission denied')):
                self.assertEqual(ssh_prerequisites.run(body)['code'], 'SSH_DOCKER_PERMISSION')
            with patch.object(ssh_prerequisites.shutil, 'which', return_value='/fixture/docker'), patch.object(ssh_prerequisites.subprocess, 'run', return_value=SimpleNamespace(returncode=0)):
                self.assertEqual(ssh_prerequisites.run(body)['code'], 'SSH_DIRECTORY_UNSAFE')
                link = Path(parent) / 'link'; link.symlink_to(root)
                self.assertEqual(ssh_prerequisites.run(body | {'root': str(link)})['code'], 'SSH_DIRECTORY_UNSAFE')
            self.assertEqual(root.stat().st_mode & 0o777, 0o755)
