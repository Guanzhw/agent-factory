"""Owner tool registrations over existing connections and credential custody.

Configuration is metadata-only. Trusted adapters own transport execution; this
service never starts a process, contacts a server or caches credential leases.
"""
from __future__ import annotations

from dataclasses import dataclass, fields, replace
import json
from types import MappingProxyType
from typing import Any, Callable, Mapping
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Column, JSON, MetaData, String, Table, select

from .connections import TrustedConnectionBinding
from .personal_remote_provider import SecretLease
from .personal_tool_contract import PersonalToolAdapter, ToolDescriptor
from .store import digest, now


def _descriptor(adapter: PersonalToolAdapter) -> dict:
    """Freeze every declared identity field, including schema and credential scope."""
    try:
        descriptor = adapter.descriptor
        if not isinstance(descriptor, ToolDescriptor) or not callable(adapter.invoke):
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

    def _row(self, conn, owner, reference):
        self.connections._key(reference)
        row = conn.execute(select(self.tools).where(self.tools.c.registration_ref == reference,
            self.tools.c.owner_id == owner)).mappings().first()
        if row is None:
            raise HTTPException(404, 'PERSONAL_TOOL_NOT_FOUND')
        body = row['body']
        if (not isinstance(body, dict) or digest(body) != row['fingerprint']
                or body.get('ownerId') != owner or body.get('registrationRef') != reference
                or body.get('revision') != row['revision'] or row['state'] not in {'ACTIVE', 'REVOKED'}):
            raise HTTPException(409, 'PERSONAL_TOOL_INTEGRITY')
        return row

    def _adapter(self, body):
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
        row = self._row(conn, owner, reference)
        body = row['body']
        status = 'configured'
        try:
            self._current(owner, row)
        except HTTPException as error:
            code = error.detail.get('code') if isinstance(error.detail, dict) else error.detail
            status = {'PERSONAL_TOOL_REVOKED': 'revoked',
                'PERSONAL_TOOL_CREDENTIAL_UNAVAILABLE': 'credential_unavailable',
                'PERSONAL_TOOL_ADAPTER_CHANGED': 'adapter_changed'}.get(str(code), 'unavailable')
        descriptor = body['descriptor']
        actions = ['inspect'] + ([] if status == 'revoked' else ['revoke'])
        if status == 'configured' and self.connections._can_bind(owner):
            actions.append('bind')
        return {key: body[key] for key in ('registrationRef', 'ownerId', 'adapterId', 'revision',
            'credentialRef', 'credentialRevision', 'createdAt')} | {
            'descriptorRevision': descriptor['revision'], 'kind': 'tool', 'expiresAt': None,
            'toolName': descriptor['toolName'], 'transport': descriptor['transport'],
            'capabilities': descriptor['capabilities'], 'status': status,
            'available': status == 'configured', 'allowedActions': actions}

    def describe(self, owner):
        self.connections.auth.require(owner, 'read')
        return [_descriptor(adapter) for _, adapter in sorted(self.adapters.items())]

    def list(self, owner):
        self.connections.auth.require(owner, 'read')
        with self.connections._read() as conn:
            refs = conn.execute(select(self.tools.c.registration_ref).where(self.tools.c.owner_id == owner)
                .order_by(self.tools.c.registration_ref).limit(100)).scalars()
            return [self._projection(conn, owner, ref) for ref in refs]

    def inspect(self, owner, reference):
        self.connections.auth.require(owner, 'read')
        with self.connections._read() as conn:
            return self._projection(conn, owner, reference)

    def _record(self, conn, owner, request_id, fingerprint, action, reference, at):
        service = self.connections
        conn.execute(service.commands.insert().values(owner_id=owner, request_id=request_id,
            fingerprint=fingerprint, action=action, result_ref=reference, created_at=at))
        conn.execute(service.audit.insert().values(actor_id=owner, action=action,
            target_id=reference, body={'registrationRef': reference}, created_at=at))

    def configure(self, owner, adapter_id, credential_ref, credential_revision, request_id):
        service = self.connections
        service.auth.require(owner, 'run')
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
            if adapter is None:
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

    def revoke(self, owner, reference, request_id):
        service = self.connections
        service.auth.require(owner, 'read')
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
        self.connections.auth.require(owner, 'read')
        self.connections._key(request_id)
        with self.connections._read() as conn:
            command = conn.execute(select(self.connections.commands).where(
                self.connections.commands.c.owner_id == owner,
                self.connections.commands.c.request_id == request_id)).mappings().first()
            if command is None or command['action'] not in {'tool.configure', 'tool.revoke'}:
                raise HTTPException(404, 'PERSONAL_TOOL_REQUEST_NOT_FOUND')
            return {'requestId': request_id, 'action': command['action'],
                'tool': self._projection(conn, owner, command['result_ref'])}

    def binding(self, conn, owner, reference):
        row = self._row(conn, owner, reference)
        adapter = self._current(owner, row)
        body = row['body']
        handle = PersonalToolHandle(owner, MappingProxyType(json.loads(json.dumps(body))), adapter, self)
        return TrustedConnectionBinding(owner, 'tool', body['adapterId'],
            frozenset(body['descriptor']['capabilities']), body['revision'], available=True,
            opaque_handle=handle, handle_ref='owner-tool-handle-' + row['fingerprint'])


@dataclass(frozen=True, repr=False)
class PersonalToolHandle:
    owner: str
    configuration: Mapping[str, Any]
    adapter: PersonalToolAdapter
    service: PersonalTools
    _recheck: Callable | None = None

    def guarded(self, recheck):
        previous = self._recheck
        def check(capabilities):
            if previous is not None:
                previous(capabilities)
            recheck(capabilities)
        return replace(self, _recheck=check)

    def check_authorized(self):
        self.service.connections.auth.require(self.owner, 'run')
        if self._recheck is not None:
            self._recheck(tuple(self.configuration['descriptor']['capabilities']))
        with self.service.connections._read() as conn:
            row = self.service._row(conn, self.owner, self.configuration['registrationRef'])
            if row['fingerprint'] != digest(dict(self.configuration)) or self.service._current(self.owner, row) is not self.adapter:
                raise HTTPException(409, 'PERSONAL_TOOL_CHANGED')

    def resolve_credential(self) -> SecretLease:
        self.check_authorized()
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
    @router.get('/requests/{request_id}')
    def request_result(request_id: str, request: Request):
        return service.request_result(owner(request), request_id)
    @router.get('/{reference}')
    def inspect(reference: str, request: Request):
        return service.inspect(owner(request), reference)
    @router.post('/{reference}/revoke')
    def revoke(reference: str, body: ToolCommandRequest, request: Request):
        return service.revoke(owner(request), reference, body.requestId)
    return router
