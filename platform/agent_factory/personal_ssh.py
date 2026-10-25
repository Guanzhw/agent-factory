"""Owner SSH enrollment over existing vault, remote registry and scoped bindings.

Members choose their endpoint and confirm its host identity. Application
prerequisites are checked separately when preparing an application.
"""
import asyncio
import base64
from dataclasses import dataclass, replace
import json
import os
from pathlib import Path, PurePosixPath
import secrets
import select as io_select
import shlex
import subprocess
import sys
from tempfile import TemporaryDirectory
import threading
import time
from typing import Callable, Protocol

from cryptography.hazmat.primitives import serialization
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select, or_

from .personal_remote_provider import RemoteConnectionError
from .ssh_credentials import PROVIDER_ID, endpoint
from .ssh_identity import SSHAgentLease, SSHServer, pinned_ssh
from .resource_sharing import SharingCommand

CODES = frozenset({'SSH_CONTROLLER_PLATFORM_UNSUPPORTED', 'SSH_LINUX_ARCH_REQUIRED', 'SSH_NON_ROOT_REQUIRED', 'SSH_PYTHON_MISSING',
    'SSH_PYTHON_VERSION_REQUIRED', 'SSH_DOCKER_MISSING', 'SSH_DOCKER_PERMISSION', 'SSH_DOCKER_UNAVAILABLE',
    'SSH_DIRECTORY_UNSAFE', 'SSH_DIRECTORY_PARENT_REQUIRED', 'SSH_CHECK_UNCONFIRMED',
    'SSH_AGENT_CAPACITY', 'SSH_CREDENTIAL_UNAVAILABLE'})


class _SSHProbeTransport(Protocol):
    root: Path

    def _ssh(self, server, lease, local, command, forward=None) -> subprocess.Popen: ...


@dataclass(frozen=True)
class SSHEnrollmentConfig:
    max_active_seconds: int = 300
    max_agents: int = 16

    def __post_init__(self):
        if type(self.max_active_seconds) is not int or not 1 <= self.max_active_seconds <= 86400:
            raise ValueError('SSH lease duration invalid')


class SSHAgents:
    def __init__(self, vault, *, max_agents, seconds):
        if type(max_agents) is not int or not 1 <= max_agents <= 64: raise ValueError('SSH agent capacity invalid')
        self.vault, self.max_agents, self.seconds = vault, max_agents, seconds
        self.folder = TemporaryDirectory(prefix='af-ssh-agents-')
        self.root = Path(self.folder.name)
        self.live = {}; self.lock = threading.RLock()

    def _close(self, key, expected=None):
        with self.lock:
            if expected is not None and self.live.get(key, {}).get('process') is not expected: return
            item = self.live.pop(key, None)
            if item:
                item['timer'].cancel(); item['process'].terminate()
                try: item['process'].wait(timeout=5)
                except subprocess.TimeoutExpired: item['process'].kill(); item['process'].wait(timeout=5)
                item['folder'].cleanup()

    @staticmethod
    def _lease(item, guard):
        def check():
            guard()
            if item['process'].poll() is not None: raise RemoteConnectionError('SSH_CREDENTIAL_UNAVAILABLE')
        return SSHAgentLease(item['lease'].socket, item['lease'].public_key, check)

    def acquire(self, server, destination, guard):
        if sys.platform == 'win32':
            raise RemoteConnectionError('SSH_CONTROLLER_PLATFORM_UNSUPPORTED')
        scope = dict(owner=server.owner, reference=server.credential_ref,
            revision=server.credential_revision, provider_id=PROVIDER_ID, destination=destination)
        key = tuple(scope.values())
        # SQL callbacks must never run while holding the agent mutex. Other
        # callers can already own bounded metadata-pool connections while
        # waiting for this mutex; the mutex owner cannot borrow another slot.
        with self.lock: snapshot = list(self.live.items())
        for old, item in snapshot:
            if (item['deadline'] <= time.monotonic() or item['process'].poll() is not None
                    or not self.vault.authorize(**item['scope'])): self._close(old, item['process'])
        with self.lock: item = self.live.get(key)
        if item is not None:
            lease = self._lease(item, guard); lease.validate(); return lease
        # Cached leases already run this fresh guard immediately before return.
        # A new agent must also be authorized before resolving private bytes.
        guard()
        secret = self.vault.resolve(**scope)
        raw = base64.b64decode(secret.password, validate=True)
        private = serialization.load_ssh_private_key(raw, password=None)
        public = private.public_key().public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH).decode()
        created = None
        try:
            with self.lock:
                item = self.live.get(key)
                if item is None:
                    if len(self.live) >= self.max_agents: raise RemoteConnectionError('SSH_AGENT_CAPACITY')
                    folder = TemporaryDirectory(dir=self.root, prefix='lease-'); socket = str(Path(folder.name) / 'agent.sock')
                    process = subprocess.Popen(['ssh-agent', '-D', '-t', str(self.seconds), '-a', socket],
                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        env={'PATH': '/usr/local/bin:/usr/bin:/bin'})
                    try:
                        deadline = time.monotonic() + 5
                        while not Path(socket).exists():
                            if process.poll() is not None or time.monotonic() >= deadline: raise ValueError()
                            time.sleep(.02)
                        added = subprocess.run(['ssh-add', '-t', str(self.seconds), '-'], input=raw,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10, check=False,
                            env={'PATH': '/usr/local/bin:/usr/bin:/bin', 'SSH_AUTH_SOCK': socket})
                        if added.returncode != 0: raise ValueError()
                        timer = threading.Timer(self.seconds, lambda: self._close(key, process)); timer.daemon = True
                        item = {'process': process, 'folder': folder,
                            'lease': SSHAgentLease(socket, public, lambda: None),
                            'timer': timer, 'deadline': time.monotonic() + self.seconds, 'scope': scope}
                        self.live[key] = item; created = process; timer.start()
                    except Exception:
                        if process.poll() is None:
                            process.terminate()
                            try: process.wait(timeout=5)
                            except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
                        folder.cleanup(); raise
            lease = self._lease(item, guard); lease.validate(); return lease
        except Exception as error:
            if created is not None: self._close(key, created)
            if isinstance(error, RemoteConnectionError): raise
            raise RemoteConnectionError('SSH_CREDENTIAL_UNAVAILABLE') from None
        finally:
            raw = b''; private = None; secret = None

    def close(self):
        for key in list(self.live): self._close(key)
        self.folder.cleanup()


@dataclass(frozen=True, repr=False)
class SSHConnectionHandle:
    _recheck: Callable | None = None

    def guarded(self, recheck):
        return SSHConnectionHandle(recheck)

    def check_authorized(self, capabilities=()):
        if self._recheck is None:
            raise HTTPException(409, 'SSH_CONNECTION_NOT_BOUND')
        self._recheck(capabilities)


class SSHServerProvider:
    requires_credential_reference = True
    provider_id = PROVIDER_ID
    policy_revision = 'owner-ssh-fixed-host-v1'
    kind = 'environment'
    namespace = 'owner-ssh'
    capabilities = frozenset({'ssh:prepare', 'ssh:execute'})
    verification_error_codes = CODES
    record_verification_request_id = True

    def __init__(self, service): self.service = service

    def configure(self, configuration):
        required = {'name', 'address', 'port', 'username', 'hostKey', 'allowedRoot',
            'credentialRef', 'credentialRevision', 'confirmedHostKey'}
        if set(configuration) != required or configuration['confirmedHostKey'] is not True:
            raise RemoteConnectionError('SSH_IDENTITY_INVALID')
        identity = self.service.identity(configuration)
        return {**identity, 'name': configuration['name'], 'allowedRoot': configuration['allowedRoot'],
            'credentialRef': configuration['credentialRef'], 'credentialRevision': configuration['credentialRevision'],
            'confirmedHostKey': True, 'projectId': ''}

    def authorized(self, owner, configuration):
        try:
            self.service.auth.require_member(owner)
            return self.service.vault.authorize(owner=owner, reference=configuration['credentialRef'],
                revision=configuration['credentialRevision'], provider_id=PROVIDER_ID, destination=configuration['origin'])
        except Exception: return False

    def verify(self, owner, configuration):
        server = self.service.profile(owner, 'probe', 'probe', configuration)
        lease = self.service.lease(server, configuration, require_binding=False)
        self.service.probe(server, lease, 'inspect')
        return {'capabilities': sorted(self.capabilities), 'identityBasis': 'owner-confirmed-pinned-ssh-host-and-identity'}

    def handle(self, owner, configuration): return SSHConnectionHandle()


class PersonalSSHServers:
    @staticmethod
    def static_unavailable(**scope):
        raise RemoteConnectionError('SSH_STATIC_CREDENTIAL_UNAVAILABLE')
    def __init__(self, auth, connections, vault, config, *, probe_source: str | None = None):
        if (not isinstance(config, SSHEnrollmentConfig) or PROVIDER_ID not in vault.capabilities()['providerIds']):
            raise ValueError('Self-service SSH requires lease limits and SSH vault support')
        self.auth, self.connections, self.vault, self.config = auth, connections, vault, config
        self.agents = SSHAgents(vault, max_agents=config.max_agents, seconds=config.max_active_seconds + 30)
        self.package: _SSHProbeTransport | None = None
        self.provider = SSHServerProvider(self)
        self.probe_source = probe_source
        self.provider.policy_revision = 'owner-ssh-endpoint-v2'
        if PROVIDER_ID in connections.personal.providers: raise ValueError('Duplicate SSH server provider')
        connections.personal.providers[PROVIDER_ID] = self.provider

    def identity(self, values):
        try:
            identity = endpoint(values['address'], values['port'], values['username'], values['hostKey'])
            root = PurePosixPath(values['allowedRoot'])
            if (not root.is_absolute() or '..' in root.parts or str(root) != values['allowedRoot']
                    or any(ord(c) < 32 for c in str(root))
                    or not isinstance(values['name'], str) or not 1 <= len(values['name']) <= 80
                    or any(ord(c) < 32 for c in values['name'])): raise ValueError()
            return identity
        except Exception: raise RemoteConnectionError('SSH_IDENTITY_INVALID') from None

    @staticmethod
    def profile(owner, reference, revision, values):
        return SSHServer(reference, owner, revision, values['name'], values['address'], values['port'],
            values['username'], values['hostKey'], values['allowedRoot'], values['credentialRef'], values['credentialRevision'])

    def _configuration(self, conn, owner, reference):
        row, body = self.connections.personal._row(conn, owner, reference, shared=True)
        if body['providerId'] != PROVIDER_ID: raise HTTPException(404, 'SSH_SERVER_NOT_FOUND')
        return row, body

    def server(self, owner, reference, *, required_capability='ssh:prepare'):
        self.auth.require_member(owner)
        with self.connections._read() as conn:
            _, body = self._configuration(conn, owner, reference)
            rows = conn.execute(select(self.connections.references).where(
                self.connections.references.c.owner_id == owner,
                self.connections.references.c.registration_ref == reference,
                self.connections.references.c.state == 'ACTIVE')).mappings().all()
            for row in rows:
                if row['body']['taskId'] is not None or required_capability not in row['body']['capabilities']: continue
                try: self.connections._current(conn, owner, dict(row), task_id=None)
                except HTTPException: continue
                return replace(self.profile(body['ownerId'], reference, body['revision'], body['configuration']), actor=owner)
        raise HTTPException(409, 'SSH_SERVER_NOT_ENABLED')

    def inspect(self, owner, reference):
        self.auth.require_member(owner)
        with self.connections._read() as conn:
            row, body = self._configuration(conn, owner, reference)
            public = self.connections.personal._projection(conn, owner, reference)
        try: self.server(owner, reference); enabled = True
        except HTTPException: enabled = False
        try: self.server(owner, reference, required_capability='ssh:execute'); execution_enabled = True
        except HTTPException: execution_enabled = False
        config = body['configuration']; proof = row['verification'] or {}
        result = {'reference': reference, 'ownerId': body['ownerId'], 'visibility': public['visibility'],
            'isOwner': body['ownerId'] == owner, 'name': config['name'], 'address': config['address'], 'port': config['port'],
            'username': config['username'], 'hostFingerprint': config['hostFingerprint'], 'allowedRoot': config['allowedRoot'],
            'hostKey': config['hostKey'],
            'defaultDirectory': config['allowedRoot'], 'status': public['status'], 'enabled': enabled,
            'executionEnabled': execution_enabled,
            'diagnostic': proof.get('errorCode'), 'lastCheckRequestId': proof.get('requestId')}
        if result['isOwner']:
            result.update(credentialRef=config['credentialRef'], credentialRevision=config['credentialRevision'])
        return result

    def list(self, owner):
        self.auth.require_member(owner)
        with self.connections._read() as conn:
            refs = conn.execute(select(self.connections.personal.resources.c.registration_ref).where(
                or_(self.connections.personal.resources.c.owner_id == owner,
                    self.connections.personal.resources.c.registration_ref.in_(
                        self.connections.sharing.visible_refs(conn, owner)))).limit(100)).scalars().all()
            matching = [r for r in refs if self.connections.personal._row(conn, owner, r, shared=True)[1]['providerId'] == PROVIDER_ID]
        return [self.inspect(owner, r) for r in matching]

    def available(self, owner):
        return [{'reference': r['reference'], 'name': r['name'], 'defaultDirectory': r['defaultDirectory']}
            for r in self.list(owner) if r['enabled']]

    def lease(self, server, configuration=None, *, require_binding=True, required_capability='ssh:prepare'):
        if not require_binding and required_capability != 'ssh:prepare':
            raise HTTPException(409, 'SSH_SERVER_NOT_ENABLED')
        if configuration is None:
            with self.connections._read() as conn:
                _, body = self._configuration(conn, server.owner, server.reference)
                configuration = body['configuration']
        def guard():
            if require_binding:
                # server() rechecks owner authority, active scoped binding,
                # the exact live vault revision.
                if self.server(server.actor or server.owner, server.reference, required_capability=required_capability).pin() != server.pin():
                    raise RemoteConnectionError('SSH_CONFIGURATION_CHANGED')
            elif not self.provider.authorized(server.owner, configuration):
                raise RemoteConnectionError('SSH_CREDENTIAL_UNAVAILABLE')
        return self.agents.acquire(server, configuration['origin'], guard)

    def probe(self, server, lease, action):
        lease.validate()
        nonce = secrets.token_hex(12)
        if action == 'inspect':
            success = json.dumps({'nonce': nonce, 'ok': True, 'code': 'SSH_CONNECTION_READY', 'directoryExists': True})
            missing = json.dumps({'nonce': nonce, 'ok': True, 'code': 'SSH_CONNECTION_READY', 'directoryExists': False})
            command = 'if test -d ' + shlex.quote(server.allowed_root) + '; then printf \'%s\\n\' ' + shlex.quote(success)
            command += '; else printf \'%s\\n\' ' + shlex.quote(missing) + '; fi'
            transport = pinned_ssh
            folder_root = self.agents.root
        elif action == 'prepare' and self.package is not None and self.probe_source is not None:
            command = 'if command -v python3 >/dev/null 2>&1; then exec python3 -I -B -c ' + shlex.quote(self.probe_source)
            command += '; else printf \'%s\\n\' ' + shlex.quote(json.dumps({'nonce': nonce, 'ok': False, 'code': 'SSH_PYTHON_MISSING'})) + '; fi'
            transport = self.package._ssh
            folder_root = self.package.root
        else:
            raise RemoteConnectionError('SSH_CHECK_UNCONFIRMED')
        with TemporaryDirectory(dir=folder_root, prefix='probe-') as folder:
            process = transport(server, lease, Path(folder), command)
            assert process.stdin is not None and process.stdout is not None
            try:
                if action == 'prepare':
                    process.stdin.write(json.dumps({'nonce': nonce, 'root': server.allowed_root, 'action': action}).encode() + b'\n')
                process.stdin.close(); output = b''; deadline = time.monotonic() + 30
                while b'\n' not in output:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or not io_select.select([process.stdout], [], [], remaining)[0]: raise ValueError()
                    chunk = os.read(process.stdout.fileno(), 4096)
                    if not chunk: raise ValueError()
                    output += chunk
                    if len(output) > 8192: raise ValueError()
                result = json.loads(output)
                if result.get('nonce') != nonce or type(result.get('ok')) is not bool: raise ValueError()
                if not result['ok']:
                    code = result.get('code')
                    raise RemoteConnectionError(code if code in CODES else 'SSH_CHECK_UNCONFIRMED')
                if (result.get('code') != ('SSH_CONNECTION_READY' if action == 'inspect' else 'SSH_PREREQUISITES_READY')
                        or type(result.get('directoryExists')) is not bool): raise ValueError()
                if process.wait(timeout=max(.1, deadline - time.monotonic())) != 0: raise ValueError()
                lease.validate(); return result
            except RemoteConnectionError: raise
            except Exception: raise RemoteConnectionError('SSH_CHECK_UNCONFIRMED') from None
            finally:
                if process.poll() is None:
                    process.terminate()
                    try: process.wait(timeout=5)
                    except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
                process.stdin.close(); process.stdout.close()

    def close(self): self.agents.close()


class IdentityRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=80)
    address: str = Field(min_length=1, max_length=253)
    port: int = Field(default=22, ge=1, le=65535, strict=True)
    username: str = Field(min_length=1, max_length=128)
    hostKey: str = Field(min_length=1, max_length=16384)
    allowedRoot: str = Field(min_length=1, max_length=4096)


class ConfigureSSHRequest(IdentityRequest):
    credentialRef: str = Field(min_length=1, max_length=200)
    credentialRevision: str = Field(min_length=1, max_length=200)
    confirmedHostKey: bool = Field(strict=True)
    requestId: str = Field(min_length=1, max_length=200)


class SSHCommand(BaseModel):
    model_config = ConfigDict(extra='forbid')
    requestId: str = Field(min_length=1, max_length=200)


async def body(request, schema):
    try:
        raw = b''
        async for chunk in request.stream():
            raw += chunk
            if len(raw) > 8192: raise ValueError()
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result: raise ValueError()
                result[key] = value
            return result
        return schema.model_validate(json.loads(raw, object_pairs_hook=unique))
    except (ValueError, ValidationError): raise HTTPException(422, {'code': 'SSH_INPUT_INVALID'}) from None


def personal_ssh_router(auth, service):
    router = APIRouter(prefix='/api/factory/personal-ssh', tags=['personal-ssh'])
    def owner(request, action='read'):
        identifier = auth.user(request)['id']; auth.require_member(identifier)
        if service is None: raise HTTPException(404, 'SSH_SELF_SERVICE_UNAVAILABLE')
        return identifier

    @router.get('/capabilities')
    def capabilities(request: Request):
        auth.require_member(auth.user(request)['id'])
        return {'enabled': service is not None, 'keyType': 'openssh-private-key', 'learnsHostKeys': False,
                'controllerDiagnostic': 'SSH_CONTROLLER_PLATFORM_UNSUPPORTED' if sys.platform == 'win32' else None}

    @router.post('/identity')
    async def identity(request: Request):
        values = (await body(request, IdentityRequest)).model_dump()
        def inspect_identity():
            owner(request)
            try: return service.identity(values)
            except RemoteConnectionError: raise HTTPException(422, {'code': 'SSH_IDENTITY_INVALID'}) from None
        return await asyncio.to_thread(inspect_identity)

    @router.get('')
    def listing(request: Request): return service.list(owner(request))

    def persist_configuration(request, values, reference=None):
        actor = owner(request, 'run')
        request_id = values.pop('requestId')
        if reference is not None: service.inspect(actor, reference)
        remote = service.connections.personal.configure(actor, PROVIDER_ID, values, request_id, reference=reference)
        return service.inspect(actor, remote['registrationRef'])

    async def save_configuration(request, reference=None):
        values = (await body(request, ConfigureSSHRequest)).model_dump()
        return await asyncio.to_thread(persist_configuration, request, values, reference)

    @router.post('', status_code=201)
    async def configure(request: Request): return await save_configuration(request)

    @router.post('/{reference}/configure')
    async def reconfigure(reference: str, request: Request): return await save_configuration(request, reference)

    @router.get('/requests/{request_id}')
    def recover(request_id: str, action: str, request: Request):
        actor = owner(request)
        if action in {'bind', 'bind-execution'}:
            receipt = service.connections.request_result(actor, request_id)
            expected = {'ssh:prepare'} if action == 'bind' else {'ssh:prepare', 'ssh:execute'}
            if receipt['action'] != 'bind' or set(receipt['connection']['capabilities']) != expected:
                raise HTTPException(409, 'SSH_REQUEST_MISMATCH')
            reference = receipt['connection']['registrationRef']
        elif action in {'configure', 'verify', 'revoke', 'sharing'}:
            receipt = service.connections.personal.request_result(actor, request_id)
            if receipt['action'] != 'remote.' + action: raise HTTPException(409, 'SSH_REQUEST_MISMATCH')
            reference = receipt['remote']['registrationRef']
        else: raise HTTPException(422, 'SSH_REQUEST_INVALID')
        return {'requestId': request_id, 'action': action, 'server': service.inspect(actor, reference)}

    @router.get('/{reference}')
    def inspect(reference: str, request: Request): return service.inspect(owner(request), reference)

    def execute_command(reference, action, request, request_id):
        actor = owner(request, 'read' if action == 'revoke' else 'run')
        service.inspect(actor, reference)
        if action == 'bind': service.connections.bind(actor, reference, request_id, capabilities=['ssh:prepare'])
        elif action == 'bind-execution': service.connections.bind(actor, reference, request_id, capabilities=['ssh:prepare', 'ssh:execute'])
        elif action == 'verify': service.connections.personal.verify(actor, reference, request_id)
        elif action == 'revoke': service.connections.personal.revoke(actor, reference, request_id)
        else: raise HTTPException(422, 'SSH_ACTION_INVALID')
        return service.inspect(actor, reference)

    @router.post('/{reference}/sharing')
    async def share(reference: str, request: Request):
        command = await body(request, SharingCommand)
        actor = owner(request)
        service.connections.personal.share(actor, reference, command.visibility, command.requestId)
        return service.inspect(actor, reference)

    @router.post('/{reference}/{action}')
    async def command(reference: str, action: str, request: Request):
        request_id = (await body(request, SSHCommand)).requestId
        return await asyncio.to_thread(execute_command, reference, action, request, request_id)
    return router
