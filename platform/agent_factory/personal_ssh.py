"""Personal SSH configuration and execution through the installed OpenSSH client."""
import asyncio
import base64
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shlex
import shutil
import sys
from tempfile import TemporaryDirectory
from typing import Callable

from agno.tools.function import Function
from agno.run import RunContext
from agno.run.cancel import is_cancelled
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select, or_

from ._personal_cli_process import CLIProcessError, run_cli_process
from .personal_remote_provider import RemoteConnectionError
from .personal_tool_contract import ToolInvocationError
from .ssh_credentials import PROVIDER_ID, endpoint
from .resource_sharing import SharingCommand

CODES = frozenset({'SSH_CONNECTION_FAILED', 'SSH_CREDENTIAL_UNAVAILABLE'})


@dataclass(frozen=True)
class SSHEnrollmentConfig:
    """Compatibility configuration; enrollment no longer starts expiring agents."""


@dataclass(frozen=True)
class SSHServer:
    reference: str
    owner: str
    revision: str
    name: str
    address: str
    port: int
    username: str
    host_key: str
    allowed_root: str
    credential_ref: str
    credential_revision: str


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
        if set(configuration) - required or required - {'confirmedHostKey', 'hostKey'} - set(configuration):
            raise RemoteConnectionError('SSH_IDENTITY_INVALID')
        identity = self.service.identity(configuration)
        return {**identity, 'name': configuration['name'], 'allowedRoot': configuration['allowedRoot'],
            'credentialRef': configuration['credentialRef'], 'credentialRevision': configuration['credentialRevision'],
            'projectId': ''}

    def authorized(self, owner, configuration):
        try:
            self.service.auth.require_member(owner)
            return self.service.vault.authorize(owner=owner, reference=configuration['credentialRef'],
                revision=configuration['credentialRevision'], provider_id=PROVIDER_ID, destination=configuration['origin'])
        except Exception: return False

    def verify(self, owner, configuration):
        server = self.service.profile(owner, 'probe', 'probe', configuration)
        result = asyncio.run(self.service._run(server, ['true'], cwd='.'))
        if result['exitCode'] != 0:
            raise RemoteConnectionError('SSH_CONNECTION_FAILED')
        return {'capabilities': sorted(self.capabilities), 'identityBasis': 'openssh-host-and-credential'}

    def handle(self, owner, configuration): return SSHConnectionHandle()


class PersonalSSHServers:
    @staticmethod
    def static_unavailable(**scope):
        raise RemoteConnectionError('SSH_STATIC_CREDENTIAL_UNAVAILABLE')

    def __init__(self, auth, connections, vault, config=None, **_):
        self.auth, self.connections, self.vault = auth, connections, vault
        self.provider = SSHServerProvider(self)
        connections.personal.providers[PROVIDER_ID] = self.provider

    def identity(self, values):
        try:
            identity = endpoint(values['address'], values['port'], values['username'], values.get('hostKey'))
            if not values['allowedRoot'] or '\0' in values['allowedRoot'] or not values['name']:
                raise ValueError()
            return identity
        except Exception: raise RemoteConnectionError('SSH_IDENTITY_INVALID') from None

    @staticmethod
    def profile(owner, reference, revision, values):
        return SSHServer(reference, owner, revision, values['name'], values['address'], values['port'],
            values['username'], values.get('hostKey', ''), values['allowedRoot'], values['credentialRef'], values['credentialRevision'])

    def _configuration(self, conn, owner, reference):
        row, body = self.connections.personal._row(conn, owner, reference, shared=True)
        if body['providerId'] != PROVIDER_ID: raise HTTPException(404, 'SSH_SERVER_NOT_FOUND')
        return row, body

    def server(self, owner, reference, *, required_capability=None):
        self.auth.require_member(owner)
        with self.connections._read() as conn:
            row, body = self._configuration(conn, owner, reference)
            if row['state'] == 'REVOKED':
                raise HTTPException(409, 'SSH_SERVER_REVOKED')
            return self.profile(body['ownerId'], reference, body['revision'], body['configuration'])

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
            'username': config['username'], 'hostFingerprint': config.get('hostFingerprint', ''), 'allowedRoot': config['allowedRoot'],
            'hostKey': config.get('hostKey', ''),
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
                        self.connections.sharing.visible_refs(conn, owner))))).scalars().all()
            matching = [r for r in refs if self.connections.personal._row(conn, owner, r, shared=True)[1]['providerId'] == PROVIDER_ID]
        return [self.inspect(owner, r) for r in matching]

    def available(self, owner):
        return [{'reference': r['reference'], 'name': r['name'], 'defaultDirectory': r['defaultDirectory']}
            for r in self.list(owner) if r['enabled']]

    async def run(self, owner, reference, argv, *, cwd=None, run_id=None):
        return await self._run(self.server(owner, reference), argv, cwd=cwd, run_id=run_id)

    async def _run(self, server, argv, *, cwd=None, run_id=None):
        if not argv or any(not isinstance(item, str) or '\0' in item for item in argv):
            raise ValueError('SSH_COMMAND_INVALID')
        executable = shutil.which('ssh')
        if executable is None:
            raise RemoteConnectionError('SSH_SYSTEM_CLIENT_UNAVAILABLE')
        destination = endpoint(server.address, server.port, server.username, server.host_key)['origin']
        scope = dict(owner=server.owner, reference=server.credential_ref,
            revision=server.credential_revision, provider_id=PROVIDER_ID, destination=destination)
        secret = self.vault.resolve(**scope)
        command = 'cd ' + shlex.quote(cwd or server.allowed_root) + ' && exec ' + shlex.join(argv)
        with TemporaryDirectory(prefix='factory-ssh-') as folder:
            root = Path(folder)
            key = root / 'identity'
            # OpenSSH needs a plaintext identity file. Create it private and set
            # the Windows ACL before writing any key bytes; the directory is temporary.
            with os.fdopen(os.open(key, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as stream:
                if sys.platform == 'win32':
                    import win32api
                    import win32con
                    import win32security
                    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
                    try:
                        user = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
                        acl = win32security.ACL()
                        acl.AddAccessAllowedAce(win32security.ACL_REVISION, win32con.GENERIC_READ, user)
                        win32security.SetNamedSecurityInfo(str(key), win32security.SE_FILE_OBJECT,
                            win32security.DACL_SECURITY_INFORMATION | win32security.PROTECTED_DACL_SECURITY_INFORMATION,
                            None, None, acl, None)
                    finally:
                        win32api.CloseHandle(token)
                stream.write(base64.b64decode(secret.password, validate=True))
            args = ['-tt', '-i', str(key), '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes']
            if server.host_key:
                known = root / 'known_hosts'
                known.write_text('factory-remote ' + server.host_key + '\n')
                args += ['-o', 'HostKeyAlias=factory-remote', '-o', 'UserKnownHostsFile=' + str(known),
                    '-o', 'StrictHostKeyChecking=yes']
            else:
                args += ['-o', 'StrictHostKeyChecking=accept-new']
            args += ['-p', str(server.port), '-l', server.username, server.address, command]
            def check_cancelled():
                if run_id and is_cancelled(run_id):
                    raise asyncio.CancelledError()
            try:
                result = await run_cli_process(executable=executable, argv=args, env=dict(os.environ), cwd=root,
                    stdin=b'', timeout_seconds=None, max_output_bytes=None,
                    before_spawn=check_cancelled, check_authorized=check_cancelled)
            except CLIProcessError as error:
                # Closing SSH requests remote foreground termination; a local
                # process exit cannot prove an arbitrary remote descendant died.
                raise ToolInvocationError('SSH_' + error.code, outcome='unknown', stopped=False) from error
            return {'exitCode': result.returncode, 'stdout': result.stdout.decode(errors='replace'),
                'stderr': result.stderr.decode(errors='replace'), 'stopped': result.stopped and result.returncode != 255}

    def functions(self, owner):
        def ssh_servers():
            """List available SSH servers with names, references and default directories. Use a returned reference with ssh_run."""
            return self.available(owner)

        async def ssh_run(run_context: RunContext, reference: str, argv: list[str], cwd: str | None = None):
            """Run a command on a configured SSH server and return its actual output and exit code."""
            return await self.run(owner, reference, argv, cwd=cwd, run_id=run_context.run_id)
        return [Function.from_callable(ssh_servers), Function.from_callable(ssh_run)]

    def close(self):
        pass


class IdentityRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1)
    address: str = Field(min_length=1)
    port: int = Field(default=22, ge=1, le=65535, strict=True)
    username: str = Field(min_length=1)
    hostKey: str = ''
    allowedRoot: str = Field(min_length=1)


class ConfigureSSHRequest(IdentityRequest):
    credentialRef: str = Field(min_length=1)
    credentialRevision: str = Field(min_length=1)
    confirmedHostKey: bool | None = None
    requestId: str = Field(min_length=1)


class SSHCommand(BaseModel):
    model_config = ConfigDict(extra='forbid')
    requestId: str = Field(min_length=1)


async def body(request, schema):
    try:
        raw = b''
        async for chunk in request.stream():
            raw += chunk
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
        return {'enabled': service is not None, 'keyType': 'openssh-private-key', 'learnsHostKeys': True,
                'controllerDiagnostic': None}

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
