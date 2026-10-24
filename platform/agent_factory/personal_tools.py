"""Owner tool registrations over existing connections and credential custody.

Configuration persists member-owned command metadata. MCP discovery uses the
official SDK; native invocation owns execution and credential leases.
"""
from __future__ import annotations

from dataclasses import dataclass, fields, replace
import json
import threading
from types import MappingProxyType
from typing import Any, Callable, Literal, Mapping
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Column, JSON, MetaData, String, Table, or_, select

from .connections import TrustedConnectionBinding
from .personal_remote_provider import SecretLease
from .personal_tool_contract import PersonalToolAdapter, ToolDescriptor
from .store import digest, now
from .resource_sharing import SharingCommand


def _descriptor(adapter: PersonalToolAdapter | ToolDescriptor) -> dict:
    """Freeze every declared identity field, including schema and credential scope."""
    try:
        descriptor = adapter if isinstance(adapter, ToolDescriptor) else adapter.descriptor
        if not isinstance(descriptor, ToolDescriptor) or not isinstance(adapter, ToolDescriptor) and not callable(adapter.invoke):
            raise ValueError()
        value = {}
        for field in fields(descriptor):
            parts = field.name.split('_')
            key = parts[0] + ''.join(part.title() for part in parts[1:])
            value[key] = dict(descriptor.input_schema) if field.name == 'input_schema' else getattr(descriptor, field.name)
        return json.loads(json.dumps(value, allow_nan=False))
    except (AttributeError, TypeError, ValueError, OverflowError):
        raise ValueError('PERSONAL_TOOL_DESCRIPTOR_INVALID') from None


class PersonalTools:
    def __init__(self, connections, vault, adapters):
        self.connections, self.vault = connections, vault
        self.adapters: dict[str, PersonalToolAdapter] = {}
        for adapter in adapters:
            descriptor = _descriptor(adapter)
            if descriptor['adapterId'] in self.adapters:
                raise ValueError('PERSONAL_TOOL_ADAPTER_DUPLICATE')
            self.adapters[descriptor['adapterId']] = adapter
        metadata = MetaData()
        self.tools = Table('af_personal_tools', metadata,
            Column('registration_ref', String, primary_key=True), Column('owner_id', String, nullable=False),
            Column('revision', String, nullable=False), Column('body', JSON, nullable=False),
            Column('fingerprint', String, nullable=False), Column('state', String, nullable=False))
        metadata.create_all(connections.store.engine)
        self._bindings = None
        self._adapter_lock = threading.RLock()
        self._installed_ids = frozenset(self.adapters)

    def register(self, bindings):
        """Restore member resources into the same native registry as installed tools."""
        self._bindings = bindings
        with self.connections._read() as conn:
            bodies = conn.execute(select(self.tools.c.body).where(self.tools.c.state == 'ACTIVE')).scalars().all()
        for body in bodies:
            if body.get('resource'):
                try:
                    self.ensure_registered(body['adapterId'])
                except HTTPException as error:
                    if error.detail != 'PERSONAL_TOOL_ADAPTER_UNAVAILABLE':
                        raise

    def catalog_tools(self):
        """Public native declarations; resource configuration and secrets stay private."""
        result = {adapter.descriptor.tool_name: adapter.descriptor.permission for adapter in self.adapters.values()}
        with self.connections._read() as conn:
            bodies = conn.execute(select(self.tools.c.body).where(self.tools.c.state == 'ACTIVE')).scalars()
            for body in bodies:
                result[body['descriptor']['toolName']] = body['descriptor']['permission']
        return result

    def visible_runtime_adapters(self, owner, entries):
        """Filter member resource declarations without exposing the internal registry."""
        self.connections.auth.require_member(owner)
        with self.connections._read() as conn:
            shared = set(self.connections.sharing.visible_refs(conn, owner))
            rows = conn.execute(select(self.tools)).mappings()
            member_ids, visible_ids = set(), set()
            for row in rows:
                body = row['body']
                if not body.get('resource'):
                    continue
                member_ids.add(body['adapterId'])
                if row['state'] == 'ACTIVE' and (row['owner_id'] == owner or row['registration_ref'] in shared):
                    visible_ids.add(body['adapterId'])
        return [entry for entry in entries if entry['kind'] != 'tool'
            or entry['adapterId'] not in member_ids or entry['adapterId'] in visible_ids]

    def ensure_registered(self, adapter_id):
        with self._adapter_lock:
            return self._ensure_registered(adapter_id)

    def _ensure_registered(self, adapter_id):
        adapter = self.adapters.get(adapter_id)
        if adapter is None:
            with self.connections._read() as conn:
                rows = conn.execute(select(self.tools).where(self.tools.c.state == 'ACTIVE')).mappings()
                row = next((row for row in rows if row['body'].get('adapterId') == adapter_id), None)
                body = self._row(conn, row['owner_id'], row['registration_ref'])['body'] if row is not None else None
            if body is None:
                return
            try:
                adapter = self._resource_adapter(body['descriptor'], body['resource'])
            except (ValueError, KeyError, TypeError) as error:
                code = ('PERSONAL_TOOL_ADAPTER_UNAVAILABLE' if error.args and error.args[0] in {
                    'CLI_EXECUTABLE_UNAVAILABLE', 'CLI_WORKDIR_UNAVAILABLE'} else 'PERSONAL_TOOL_CONFIGURATION_INVALID')
                raise HTTPException(409, code) from None
            self.adapters[adapter_id] = adapter
        if self._bindings is not None:
            from .personal_tool_execution import personal_tool_registration
            entry = personal_tool_registration(adapter)
            key = (entry.kind, entry.adapter_id, entry.revision)
            with self._bindings._lock:
                if key not in self._bindings._adapters:
                    self._bindings.register(entry.kind, entry.adapter_id, entry.revision, entry.factory,
                        tool_name=entry.tool_name, connection_kind=entry.connection_kind,
                        required_capabilities=entry.required_capabilities, permissions=entry.permissions,
                        validator=entry.validator)

    @staticmethod
    def _resource_adapter(descriptor, resource):
        values = {}
        for field in fields(ToolDescriptor):
            parts = field.name.split('_')
            key = parts[0] + ''.join(part.title() for part in parts[1:])
            values[field.name] = descriptor[key]
        values['capabilities'] = tuple(values['capabilities'])
        declared = ToolDescriptor(**values)
        if resource['transport'] == 'cli':
            from .personal_cli import MemberCliAdapter
            return MemberCliAdapter(declared, resource)
        from .personal_mcp import MCPToolAdapter
        return MCPToolAdapter(declared, url=resource['url'], remote_tool_name=resource['remoteToolName'])

    def _row(self, conn, owner, reference, *, shared=False):
        self.connections._key(reference)
        query = select(self.tools).where(self.tools.c.registration_ref == reference)
        if not shared: query = query.where(self.tools.c.owner_id == owner)
        row = conn.execute(query).mappings().first()
        if row is None:
            raise HTTPException(404, 'PERSONAL_TOOL_NOT_FOUND')
        if shared: self.connections.sharing.owner(conn, owner, reference, row['owner_id'])
        body = row['body']
        if (not isinstance(body, dict) or digest(body) != row['fingerprint']
                or body.get('ownerId') != row['owner_id'] or body.get('registrationRef') != reference
                or body.get('revision') != row['revision'] or row['state'] not in {'ACTIVE', 'REVOKED'}):
            raise HTTPException(409, 'PERSONAL_TOOL_INTEGRITY')
        return row

    def _adapter(self, body):
        if body.get('resource'):
            self.ensure_registered(body['adapterId'])
        adapter = self.adapters.get(body['adapterId'])
        if adapter is None:
            raise HTTPException(409, {'code': 'PERSONAL_TOOL_ADAPTER_UNAVAILABLE',
                'message': 'PERSONAL_TOOL_ADAPTER_UNAVAILABLE'})
        try:
            matches = digest(_descriptor(adapter)) == digest(body['descriptor'])
        except ValueError:
            matches = False
        if not matches:
            raise HTTPException(409, {'code': 'PERSONAL_TOOL_ADAPTER_CHANGED',
                'message': 'PERSONAL_TOOL_ADAPTER_CHANGED'})
        return adapter

    @staticmethod
    def _scope(owner, body):
        descriptor = body['descriptor']
        return dict(owner=owner, reference=body['credentialRef'], revision=body['credentialRevision'],
            provider_id=descriptor['credentialProviderId'], destination=descriptor['credentialDestination'])

    def _authorized(self, owner, body):
        if body.get('resource') and body['credentialRef'] is None:
            return True
        try:
            return self.vault is not None and self.vault.authorize(**self._scope(owner, body)) is True
        except Exception:
            return False

    def _current(self, owner, row):
        if row['state'] == 'REVOKED':
            raise HTTPException(409, {'code': 'PERSONAL_TOOL_REVOKED', 'message': 'PERSONAL_TOOL_REVOKED'})
        adapter = self._adapter(row['body'])
        if not self._authorized(owner, row['body']):
            raise HTTPException(409, {'code': 'PERSONAL_TOOL_CREDENTIAL_UNAVAILABLE',
                'message': 'PERSONAL_TOOL_CREDENTIAL_UNAVAILABLE'})
        return adapter

    def _projection(self, conn, owner, reference):
        row = self._row(conn, owner, reference, shared=True)
        body = row['body']
        status = 'configured'
        try:
            self._current(row['owner_id'], row)
        except HTTPException as error:
            code = error.detail.get('code') if isinstance(error.detail, dict) else error.detail
            status = {'PERSONAL_TOOL_REVOKED': 'revoked',
                'PERSONAL_TOOL_CREDENTIAL_UNAVAILABLE': 'credential_unavailable',
                'PERSONAL_TOOL_ADAPTER_CHANGED': 'adapter_changed'}.get(str(code), 'unavailable')
        descriptor = body['descriptor']
        actions = ['inspect'] + ([] if status == 'revoked' or row['owner_id'] != owner else ['revoke', 'sharing'])
        if status == 'configured' and self.connections._can_bind(owner):
            actions.append('bind')
        public_fields = ['registrationRef', 'ownerId', 'adapterId', 'revision', 'createdAt']
        if row['owner_id'] == owner: public_fields += ['credentialRef', 'credentialRevision']
        return {key: body[key] for key in public_fields} | {
            **self.connections.sharing.projection(conn, owner, reference, row['owner_id']),
            'descriptorRevision': descriptor['revision'], 'kind': 'tool', 'expiresAt': None,
            'toolName': descriptor['toolName'], 'transport': descriptor['transport'],
            'capabilities': descriptor['capabilities'], 'status': status,
            'available': status == 'configured', 'allowedActions': actions,
            'runtimeBinding': {'adapterId': body['adapterId'], 'revision': descriptor['revision'], 'config': {}}}

    def describe(self, owner):
        self.connections.auth.require_member(owner)
        descriptions = {key: _descriptor(adapter) for key, adapter in self.adapters.items() if key in self._installed_ids}
        with self.connections._read() as conn:
            rows = conn.execute(select(self.tools).where(or_(self.tools.c.owner_id == owner,
                self.tools.c.registration_ref.in_(self.connections.sharing.visible_refs(conn, owner))),
                self.tools.c.state == 'ACTIVE')).mappings()
            for row in rows:
                body = self._row(conn, row['owner_id'], row['registration_ref'])['body']
                if body.get('resource'):
                    descriptions[body['adapterId']] = body['descriptor']
        return [description for _, description in sorted(descriptions.items())]

    def list(self, owner):
        self.connections.auth.require_member(owner)
        with self.connections._read() as conn:
            refs = conn.execute(select(self.tools.c.registration_ref).where(or_(self.tools.c.owner_id == owner,
                self.tools.c.registration_ref.in_(self.connections.sharing.visible_refs(conn, owner))))
                .order_by(self.tools.c.registration_ref).limit(100)).scalars()
            return [self._projection(conn, owner, ref) for ref in refs]

    def inspect(self, owner, reference):
        self.connections.auth.require_member(owner)
        with self.connections._read() as conn:
            return self._projection(conn, owner, reference)

    def _record(self, conn, owner, request_id, fingerprint, action, reference, at):
        service = self.connections
        service.sharing.register(conn, owner, reference)
        conn.execute(service.commands.insert().values(owner_id=owner, request_id=request_id,
            fingerprint=fingerprint, action=action, result_ref=reference, created_at=at))
        conn.execute(service.audit.insert().values(actor_id=owner, action=action,
            target_id=reference, body={'registrationRef': reference}, created_at=at))

    def configure(self, owner, adapter_id, credential_ref, credential_revision, request_id):
        service = self.connections
        service.auth.require_member(owner)
        for value in (adapter_id, credential_ref, credential_revision, request_id):
            service._key(value)
        fingerprint = digest({'operation': 'tool.configure', 'adapterId': adapter_id,
            'credentialRef': credential_ref, 'credentialRevision': credential_revision})
        with service._write() as conn:
            service._lock(conn, owner)
            previous = service._command(conn, owner, request_id, fingerprint)
            if previous:
                return self._projection(conn, owner, previous['result_ref'])
            adapter = self.adapters.get(adapter_id)
            if adapter is None or adapter_id not in self._installed_ids:
                raise HTTPException(422, 'PERSONAL_TOOL_ADAPTER_UNAVAILABLE')
            descriptor = _descriptor(adapter)
            at = now()
            reference, revision = 'owner-tool-' + uuid4().hex, uuid4().hex
            body = {'registrationRef': reference, 'ownerId': owner, 'revision': revision,
                'adapterId': adapter_id, 'descriptor': descriptor, 'credentialRef': credential_ref,
                'credentialRevision': credential_revision, 'createdAt': at}
            if not self._authorized(owner, body):
                raise HTTPException(403, 'PERSONAL_TOOL_CREDENTIAL_UNAVAILABLE')
            conn.execute(self.tools.insert().values(registration_ref=reference, owner_id=owner,
                revision=revision, body=body, fingerprint=digest(body), state='ACTIVE'))
            self._record(conn, owner, request_id, fingerprint, 'tool.configure', reference, at)
            return self._projection(conn, owner, reference)

    def configure_resource(self, owner, request):
        service = self.connections
        service.auth.require_member(owner)
        service._key(request.requestId)
        resource = request.model_dump(exclude={'requestId', 'credentialRef', 'credentialRevision'})
        if request.transport == 'mcp':
            from .personal_mcp import mcp_url
            resource['url'] = mcp_url(request.url)
            destination = resource['url']
        else:
            from .personal_cli import cli_destination
            resource['executable'] = cli_destination(request.executable)
            destination = resource['executable']
        fingerprint = digest({'operation': 'tool.configure', 'resource': resource,
            'credentialRef': request.credentialRef, 'credentialRevision': request.credentialRevision})
        with service._write() as conn:
            service._lock(conn, owner)
            previous = service._command(conn, owner, request.requestId, fingerprint)
            if previous:
                return self._projection(conn, owner, previous['result_ref'])
            adapter_id = 'member-tool-' + uuid4().hex
            descriptor = ToolDescriptor(adapter_id=adapter_id, revision='1', tool_name=request.toolName,
                description=request.description, input_schema=request.inputSchema, transport=request.transport,
                credential_provider_id='member-' + request.transport, credential_destination=destination,
                capabilities=('tool:invoke',), timeout_seconds=request.timeoutSeconds,
                max_output_bytes=request.maxOutputBytes, read_only=request.readOnly)
            public = _descriptor(descriptor)
            try:
                adapter = self._resource_adapter(public, resource)
            except ValueError:
                raise HTTPException(422, 'PERSONAL_TOOL_CONFIGURATION_INVALID') from None
            at = now()
            reference = 'owner-tool-' + uuid4().hex
            body = {'registrationRef': reference, 'ownerId': owner, 'revision': uuid4().hex,
                'adapterId': adapter_id, 'descriptor': public, 'resource': resource,
                'credentialRef': request.credentialRef, 'credentialRevision': request.credentialRevision, 'createdAt': at}
            if not self._authorized(owner, body):
                raise HTTPException(403, 'PERSONAL_TOOL_CREDENTIAL_UNAVAILABLE')
            conn.execute(self.tools.insert().values(registration_ref=reference, owner_id=owner,
                revision=body['revision'], body=body, fingerprint=digest(body), state='ACTIVE'))
            self.adapters[adapter_id] = adapter
            self.ensure_registered(adapter_id)
            self._record(conn, owner, request.requestId, fingerprint, 'tool.configure', reference, at)
            return self._projection(conn, owner, reference)

    async def discover(self, owner, request):
        from .personal_mcp import discover_mcp_tools, mcp_url
        self.connections.auth.require_member(owner)
        destination = mcp_url(request.url)
        def check():
            self.connections.auth.require_member(owner)
        def credential():
            check()
            if request.credentialRef is None:
                return None
            if self.vault is None:
                raise ValueError()
            return self.vault.resolve(owner=owner, reference=request.credentialRef,
                revision=request.credentialRevision, provider_id='member-mcp', destination=destination)
        try:
            tools = await discover_mcp_tools(destination, resolve_credential=credential, check_authorized=check)
            return {'url': destination, 'tools': tools}
        except ValueError:
            raise HTTPException(422, 'PERSONAL_TOOL_DISCOVERY_FAILED') from None

    def revoke(self, owner, reference, request_id):
        service = self.connections
        service.auth.require_member(owner)
        service._key(request_id)
        fingerprint = digest({'operation': 'tool.revoke', 'registrationRef': reference})
        with service._write() as conn:
            service._lock(conn, owner)
            self._row(conn, owner, reference)
            previous = service._command(conn, owner, request_id, fingerprint)
            if not previous:
                conn.execute(self.tools.update().where(self.tools.c.registration_ref == reference,
                    self.tools.c.owner_id == owner).values(state='REVOKED'))
                self._record(conn, owner, request_id, fingerprint, 'tool.revoke', reference, now())
            return self._projection(conn, owner, reference)

    def request_result(self, owner, request_id):
        self.connections.auth.require_member(owner)
        self.connections._key(request_id)
        with self.connections._read() as conn:
            command = conn.execute(select(self.connections.commands).where(
                self.connections.commands.c.owner_id == owner,
                self.connections.commands.c.request_id == request_id)).mappings().first()
            if command is None or command['action'] not in {'tool.configure', 'tool.revoke', 'tool.sharing'}:
                raise HTTPException(404, 'PERSONAL_TOOL_REQUEST_NOT_FOUND')
            return {'requestId': request_id, 'action': command['action'],
                'tool': self._projection(conn, owner, command['result_ref'])}

    def binding(self, conn, owner, reference):
        row = self._row(conn, owner, reference, shared=True)
        resource_owner = row['owner_id']
        adapter = self._current(resource_owner, row)
        body = row['body']
        handle = PersonalToolHandle(resource_owner, MappingProxyType(json.loads(json.dumps(body))), adapter, self, actor=owner)
        return TrustedConnectionBinding(resource_owner, 'tool', body['adapterId'],
            frozenset(body['descriptor']['capabilities']), body['revision'], available=True,
            opaque_handle=handle, handle_ref='owner-tool-handle-' + row['fingerprint'])

    def share(self, owner, reference, visibility, request_id):
        service = self.connections
        service.auth.require_member(owner); service._key(request_id)
        fingerprint = digest({'operation': 'tool.sharing', 'reference': reference, 'visibility': visibility})
        with service._write() as conn:
            service._lock(conn, owner)
            self._row(conn, owner, reference)
            if not service._command(conn, owner, request_id, fingerprint):
                service.sharing.register(conn, owner, reference)
                service.sharing.set(conn, owner, reference, visibility)
                self._record(conn, owner, request_id, fingerprint, 'tool.sharing', reference, now())
            return self._projection(conn, owner, reference)


@dataclass(frozen=True, repr=False)
class PersonalToolHandle:
    owner: str
    configuration: Mapping[str, Any]
    adapter: PersonalToolAdapter
    service: PersonalTools
    _recheck: Callable | None = None
    actor: str | None = None

    @property
    def requesting_actor(self):
        return self.actor or self.owner

    def guarded(self, recheck):
        previous = self._recheck
        def check(capabilities):
            if previous is not None:
                previous(capabilities)
            recheck(capabilities)
        return replace(self, _recheck=check)

    def check_authorized(self):
        self.service.connections.auth.require_member(self.requesting_actor)
        if self._recheck is not None:
            self._recheck(tuple(self.configuration['descriptor']['capabilities']))
        with self.service.connections._read() as conn:
            row = self.service._row(conn, self.owner, self.configuration['registrationRef'])
            self.service.connections.sharing.owner(conn, self.requesting_actor, self.configuration['registrationRef'], self.owner)
            if row['fingerprint'] != digest(dict(self.configuration)) or self.service._current(self.owner, row) is not self.adapter:
                raise HTTPException(409, 'PERSONAL_TOOL_CHANGED')

    def resolve_credential(self) -> SecretLease | None:
        self.check_authorized()
        if self.configuration.get('resource') and self.configuration['credentialRef'] is None:
            return None
        try:
            lease = self.service.vault.resolve(**self.service._scope(self.owner, self.configuration))
            if not isinstance(lease, SecretLease):
                raise ValueError()
        except Exception:
            raise HTTPException(409, 'PERSONAL_TOOL_CREDENTIAL_UNAVAILABLE') from None
        self.check_authorized()
        return lease


class ConfigureToolRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    adapterId: str = Field(min_length=1, max_length=200)
    credentialRef: str = Field(min_length=1, max_length=200)
    credentialRevision: str = Field(min_length=1, max_length=200)
    requestId: str = Field(min_length=1, max_length=200)


class ToolCommandRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    requestId: str = Field(min_length=1, max_length=200)


class DiscoverToolsRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    url: str = Field(min_length=1, max_length=512)
    credentialRef: str | None = Field(default=None, min_length=1, max_length=200)
    credentialRevision: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode='after')
    def credential_pair(self):
        if (self.credentialRef is None) != (self.credentialRevision is None):
            raise ValueError('PERSONAL_TOOL_CONFIGURATION_INVALID')
        return self


class ConfigureResourceRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    transport: Literal['cli', 'mcp']
    toolName: str = Field(pattern=r'^[A-Za-z_][A-Za-z0-9_-]{0,63}$')
    description: str = Field(default='Member resource tool', min_length=1, max_length=2000)
    inputSchema: dict = Field(default_factory=lambda: {'type': 'object', 'properties': {}})
    readOnly: bool = False
    timeoutSeconds: float = Field(default=30, ge=.1, le=300)
    maxOutputBytes: int = Field(default=65536, ge=1024, le=1048576)
    url: str | None = Field(default=None, max_length=512)
    remoteToolName: str | None = Field(default=None, min_length=1, max_length=256)
    executable: str | None = Field(default=None, max_length=4096)
    arguments: list[str] = Field(default_factory=list, max_length=128)
    workingDirectory: str | None = Field(default=None, max_length=4096)
    environment: dict[str, str] = Field(default_factory=dict, max_length=128)
    argumentOptions: dict[str, str] = Field(default_factory=dict, max_length=128)
    stdinJson: bool = True
    credentialEnvironmentVariable: str | None = Field(default=None, pattern=r'^[A-Za-z_][A-Za-z0-9_]*$')
    outputFormat: Literal['json', 'text'] = 'json'
    credentialRef: str | None = Field(default=None, min_length=1, max_length=200)
    credentialRevision: str | None = Field(default=None, min_length=1, max_length=200)
    requestId: str = Field(min_length=1, max_length=200)

    @model_validator(mode='after')
    def validate_resource(self):
        import re
        if ((self.credentialRef is None) != (self.credentialRevision is None)
                or self.transport == 'mcp' and (not self.url or not self.remoteToolName)
                or self.transport == 'cli' and not self.executable
                or any('\0' in item or len(item) > 8192 for item in self.arguments)
                or any(not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', key) or '\0' in value or len(value) > 16384
                    for key, value in self.environment.items())
                or any(not re.fullmatch(r'--?[A-Za-z0-9][A-Za-z0-9_-]*', value) for value in self.argumentOptions.values())
                or self.transport == 'cli' and self.credentialRef and not self.credentialEnvironmentVariable):
            raise ValueError('PERSONAL_TOOL_CONFIGURATION_INVALID')
        from .personal_tool_contract import validate_tool_schema
        self.inputSchema = validate_tool_schema(self.inputSchema)
        return self


class _RedactedToolRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()
        async def safe(request):
            try:
                response = await handler(request)
                response.headers['Cache-Control'] = 'private, no-store'
                return response
            except RequestValidationError:
                return JSONResponse({'detail': 'PERSONAL_TOOL_CONFIGURATION_INVALID'}, status_code=422,
                    headers={'Cache-Control': 'private, no-store'})
        return safe


def personal_tool_router(auth, service):
    router = APIRouter(prefix='/api/factory/personal-tools', tags=['personal-tools'], route_class=_RedactedToolRoute)
    def owner(request):
        return auth.user(request)['id']
    @router.get('/descriptors')
    def descriptors(request: Request):
        return service.describe(owner(request))
    @router.get('')
    def listing(request: Request):
        return service.list(owner(request))
    @router.post('', status_code=201)
    def configure(body: ConfigureToolRequest, request: Request):
        return service.configure(owner(request), body.adapterId, body.credentialRef, body.credentialRevision, body.requestId)
    @router.post('/discover')
    async def discover(body: DiscoverToolsRequest, request: Request):
        return await service.discover(owner(request), body)
    @router.post('/resources', status_code=201)
    def resource(body: ConfigureResourceRequest, request: Request):
        try:
            return service.configure_resource(owner(request), body)
        except ValueError:
            raise HTTPException(422, 'PERSONAL_TOOL_CONFIGURATION_INVALID') from None
    @router.get('/requests/{request_id}')
    def request_result(request_id: str, request: Request):
        return service.request_result(owner(request), request_id)
    @router.get('/{reference}')
    def inspect(reference: str, request: Request):
        return service.inspect(owner(request), reference)
    @router.post('/{reference}/revoke')
    def revoke(reference: str, body: ToolCommandRequest, request: Request):
        return service.revoke(owner(request), reference, body.requestId)
    @router.post('/{reference}/sharing')
    def sharing(reference: str, body: SharingCommand, request: Request):
        return service.share(owner(request), reference, body.visibility, body.requestId)
    return router
