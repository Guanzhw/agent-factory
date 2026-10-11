"""Owner SSH enrollment over existing vault, remote registry and scoped bindings.

Network policy and application package are global deployment configuration.
Owners confirm each fixed host/identity themselves; no per-device administrator.
"""
import asyncio
import base64
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import secrets
import select as io_select
import shlex
import subprocess
from tempfile import TemporaryDirectory
import threading
import time
from typing import Callable

from cryptography.hazmat.primitives import serialization
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select

from .personal_remote_provider import RemoteConnectionError
from .ssh_credentials import PROVIDER_ID, endpoint
from .ssh_openresearch import BASE, SSHAgentLease, SSHServer, SSHOpenResearchPackage
from .platform_openresearch import PlatformOpenResearchConfig

CODES = frozenset({'SSH_LINUX_ARCH_REQUIRED', 'SSH_NON_ROOT_REQUIRED', 'SSH_PYTHON_MISSING',
    'SSH_PYTHON_VERSION_REQUIRED', 'SSH_DOCKER_MISSING', 'SSH_DOCKER_PERMISSION', 'SSH_DOCKER_UNAVAILABLE',
    'SSH_DIRECTORY_UNSAFE', 'SSH_DIRECTORY_PARENT_REQUIRED', 'SSH_CHECK_UNCONFIRMED',
    'SSH_AGENT_CAPACITY', 'SSH_CREDENTIAL_UNAVAILABLE'})


@dataclass(frozen=True)
class SSHEnrollmentConfig:
    runtime: PlatformOpenResearchConfig
    address_policy: Callable
    max_agents: int = 16


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


class SSHServerProvider:
    provider_id = PROVIDER_ID
    policy_revision = 'owner-ssh-fixed-host-v1'
    kind = 'environment'
    namespace = 'owner-ssh'
    capabilities = frozenset({'ssh:prepare'})
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
            self.service.auth.require(owner, 'run')
            if self.service.config.address_policy(configuration['address'], configuration['port']) is not True: return False
            return self.service.vault.authorize(owner=owner, reference=configuration['credentialRef'],
                revision=configuration['credentialRevision'], provider_id=PROVIDER_ID, destination=configuration['origin'])
        except Exception: return False

    def verify(self, owner, configuration):
        server = self.service.profile(owner, 'probe', 'probe', configuration)
        lease = self.service.lease(server, configuration, require_binding=False)
        self.service.probe(server, lease, 'inspect')
        return {'capabilities': sorted(self.capabilities), 'identityBasis': 'owner-confirmed-pinned-ssh-host-and-identity'}

    def handle(self, owner, configuration): return dict(configuration)


class PersonalSSHServers:
    @staticmethod
    def static_unavailable(**scope):
        raise RemoteConnectionError('SSH_STATIC_CREDENTIAL_UNAVAILABLE')
    def __init__(self, auth, connections, vault, config):
        if (not isinstance(config, SSHEnrollmentConfig) or not callable(config.address_policy)
                or PROVIDER_ID not in vault.capabilities()['providerIds']):
            raise ValueError('Self-service SSH requires global runtime, network policy and SSH vault policy')
        self.auth, self.connections, self.vault, self.config = auth, connections, vault, config
        self.agents = SSHAgents(vault, max_agents=config.max_agents, seconds=config.runtime.max_active_seconds + 30)
        self.package: SSHOpenResearchPackage | None = None
        self.provider = SSHServerProvider(self)
        self.probe_source = (BASE / 'ssh_prerequisites.py').read_text()
        self.provider.policy_revision = 'owner-ssh-v1-' + hashlib.sha256(self.probe_source.encode()).hexdigest()[:20]
        if PROVIDER_ID in connections.personal.providers: raise ValueError('Duplicate SSH server provider')
        connections.personal.providers[PROVIDER_ID] = self.provider

    def identity(self, values):
        try:
            identity = endpoint(values['address'], values['port'], values['username'], values['hostKey'])
            if self.config.address_policy(identity['address'], identity['port']) is not True: raise ValueError()
            root = PurePosixPath(values['allowedRoot'])
            if (not root.is_absolute() or '..' in root.parts or str(root) != values['allowedRoot']
                    or any(c in str(root) for c in '\n\r,:') or len(str(root / 'research' / 'connections' / ('a' * 24) / 'broker.sock').encode()) >= 104
                    or not isinstance(values['name'], str) or not 1 <= len(values['name']) <= 80
                    or any(ord(c) < 32 for c in values['name'])): raise ValueError()
            return identity
        except Exception: raise RemoteConnectionError('SSH_IDENTITY_INVALID') from None

    @staticmethod
    def profile(owner, reference, revision, values):
        return SSHServer(reference, owner, revision, values['name'], values['address'], values['port'],
            values['username'], values['hostKey'], values['allowedRoot'], values['credentialRef'], values['credentialRevision'])

    def _configuration(self, conn, owner, reference):
        row, body = self.connections.personal._row(conn, owner, reference)
        if body['providerId'] != PROVIDER_ID: raise HTTPException(404, 'SSH_SERVER_NOT_FOUND')
        return row, body

    def server(self, owner, reference):
        self.auth.require(owner, 'run')
        with self.connections._read() as conn:
            _, body = self._configuration(conn, owner, reference)
            rows = conn.execute(select(self.connections.references).where(
                self.connections.references.c.owner_id == owner,
                self.connections.references.c.registration_ref == reference,
                self.connections.references.c.state == 'ACTIVE')).mappings().all()
            for row in rows:
                if row['body']['taskId'] is not None or 'ssh:prepare' not in row['body']['capabilities']: continue
                try: self.connections._current(conn, owner, dict(row), task_id=None)
                except HTTPException: continue
                return self.profile(owner, reference, body['revision'], body['configuration'])
        raise HTTPException(409, 'SSH_SERVER_NOT_ENABLED')

    def inspect(self, owner, reference):
        self.auth.require(owner, 'read')
        with self.connections._read() as conn:
            row, body = self._configuration(conn, owner, reference)
            public = self.connections.personal._projection(conn, owner, reference)
        try: self.server(owner, reference); enabled = True
        except HTTPException: enabled = False
        config = body['configuration']; proof = row['verification'] or {}
        return {'reference': reference, 'name': config['name'], 'address': config['address'], 'port': config['port'],
            'username': config['username'], 'hostFingerprint': config['hostFingerprint'], 'allowedRoot': config['allowedRoot'],
            'hostKey': config['hostKey'],
            'defaultDirectory': str(PurePosixPath(config['allowedRoot']) / 'research'), 'status': public['status'], 'enabled': enabled,
            'diagnostic': proof.get('errorCode'), 'lastCheckRequestId': proof.get('requestId'),
            'credentialRef': config['credentialRef'], 'credentialRevision': config['credentialRevision']}

    def list(self, owner):
        self.auth.require(owner, 'read')
        with self.connections._read() as conn:
            refs = conn.execute(select(self.connections.personal.resources.c.registration_ref).where(
                self.connections.personal.resources.c.owner_id == owner).limit(100)).scalars().all()
            matching = [r for r in refs if self.connections.personal._row(conn, owner, r)[1]['providerId'] == PROVIDER_ID]
        return [self.inspect(owner, r) for r in matching]

    def available(self, owner):
        return [{'reference': r['reference'], 'name': r['name'], 'defaultDirectory': r['defaultDirectory']}
            for r in self.list(owner) if r['enabled']]

    def lease(self, server, configuration=None, *, require_binding=True):
        if configuration is None:
            with self.connections._read() as conn:
                _, body = self._configuration(conn, server.owner, server.reference)
                configuration = body['configuration']
        def guard():
            if require_binding:
                # server() rechecks owner authority, active scoped binding,
                # both network policies and the exact live vault revision.
                if self.server(server.owner, server.reference).pin() != server.pin():
                    raise RemoteConnectionError('SSH_CONFIGURATION_CHANGED')
            elif not self.provider.authorized(server.owner, configuration):
                raise RemoteConnectionError('SSH_CREDENTIAL_UNAVAILABLE')
        return self.agents.acquire(server, configuration['origin'], guard)

    def probe(self, server, lease, action):
        if self.package is None: raise RemoteConnectionError('SSH_CHECK_UNCONFIRMED')
        lease.validate()
        nonce = secrets.token_hex(12)
        source = self.probe_source
        command = 'if command -v python3 >/dev/null 2>&1; then exec python3 -I -B -c ' + shlex.quote(source)
        command += '; else printf \'%s\\n\' ' + shlex.quote(json.dumps({'nonce': nonce, 'ok': False, 'code': 'SSH_PYTHON_MISSING'})) + '; fi'
        with TemporaryDirectory(dir=self.package.root, prefix='probe-') as folder:
            process = self.package._ssh(server, lease, Path(folder), command)
            assert process.stdin is not None and process.stdout is not None
            try:
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
                if result.get('code') != 'SSH_PREREQUISITES_READY' or type(result.get('directoryExists')) is not bool: raise ValueError()
                if process.wait(timeout=max(.1, deadline - time.monotonic())) != 0: raise ValueError()
                lease.validate(); return result
            except RemoteConnectionError: raise
            except Exception: raise RemoteConnectionError('SSH_CHECK_UNCONFIRMED') from None
            finally:
                if process.poll() is None:
                    process.terminate()
                    try: process.wait(timeout=5)
                    except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)

    def close(self): self.agents.close()


class IdentityRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=80)
    address: str = Field(min_length=1, max_length=64)
    port: int = Field(default=22, ge=1, le=65535, strict=True)
    username: str = Field(min_length=1, max_length=32)
    hostKey: str = Field(min_length=1, max_length=200)
    allowedRoot: str = Field(min_length=1, max_length=80)


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
        identifier = auth.user(request)['id']; auth.require(identifier, action)
        if service is None: raise HTTPException(404, 'SSH_SELF_SERVICE_UNAVAILABLE')
        return identifier

    @router.get('/capabilities')
    def capabilities(request: Request):
        auth.require(auth.user(request)['id'], 'read')
        return {'enabled': service is not None, 'keyType': 'dedicated-ed25519', 'learnsHostKeys': False}

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
        if action == 'bind':
            receipt = service.connections.request_result(actor, request_id)
            if receipt['action'] != 'bind': raise HTTPException(409, 'SSH_REQUEST_MISMATCH')
            reference = receipt['connection']['registrationRef']
        elif action in {'configure', 'verify', 'revoke'}:
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
        elif action == 'verify': service.connections.personal.verify(actor, reference, request_id)
        elif action == 'revoke': service.connections.personal.revoke(actor, reference, request_id)
        else: raise HTTPException(422, 'SSH_ACTION_INVALID')
        return service.inspect(actor, reference)

    @router.post('/{reference}/{action}')
    async def command(reference: str, action: str, request: Request):
        request_id = (await body(request, SSHCommand)).requestId
        return await asyncio.to_thread(execute_command, reference, action, request, request_id)
    return router
