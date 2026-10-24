"""Owner BYOK metadata and defaults using existing encrypted credential custody.

Configuration/preflight performs no network or model request. References bind the
owner, protocol, TLS destination and credential revision; stale plans fail closed.
"""
from __future__ import annotations

from uuid import uuid4
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import Column, JSON, MetaData, String, Table, or_, select

from .applications import GovernedStorage
from .byok_model import ADAPTER_ID, CAPABILITY, PROVIDER_ID, OwnerChatModel
from .connections import TrustedConnectionBinding
from .credential_vault import CredentialVaultError
from .model_endpoint_policy import ADDITIONAL_BASE_URLS, base_url, generation_options, model_id, model_origin
from .model_protocol import protocol_name
from .store import digest, now
from .resource_sharing import SharingCommand


class PersonalModels:
    def __init__(self, store, auth, connections, vault, *, transport_factory=None,
            trusted_model_proxy=None, proxy_environment_id=None):
        self.store, self.auth, self.connections, self.vault = store, auth, connections, vault
        self.transport_factory = transport_factory
        self.proxy_environment_id = proxy_environment_id
        self.trusted_model_proxy = None
        self.install_trusted_model_proxy(trusted_model_proxy)
        self.db = GovernedStorage(store, 'af_personal_models_v1')
        metadata = MetaData()
        self.models = Table('af_personal_models', metadata,
            Column('reference', String, primary_key=True), Column('owner_id', String, nullable=False),
            Column('revision', String, nullable=False), Column('body', JSON, nullable=False),
            Column('fingerprint', String, nullable=False), Column('state', String, nullable=False))
        self.defaults = Table('af_personal_model_defaults', metadata,
            Column('owner_id', String, primary_key=True), Column('reference', String, nullable=False))
        self.shared_defaults = Table('af_shared_model_defaults', metadata,
            Column('actor_id', String, primary_key=True), Column('reference', String, nullable=False),
            Column('connection_ref', String, nullable=False))
        self.commands = self.db.command_table('af_personal_model_commands', metadata)
        metadata.create_all(store.engine)

    def install_trusted_model_proxy(self, proxy):
        """Trusted same-process operator configuration only; no HTTP/env loader."""
        if proxy is not None:
            from .trusted_model_proxy import TrustedModelProxy
            if not isinstance(proxy, TrustedModelProxy) or self.transport_factory is not None:
                raise ValueError('TRUSTED_MODEL_PROXY_CONFIGURATION_INVALID')
            proxy.validate_environment(self.proxy_environment_id)
        self.trusted_model_proxy = proxy

    def _model_proxy(self, owner, body):
        if self.trusted_model_proxy is None:
            return None
        try:
            return self.trusted_model_proxy.select(owner, body, self.proxy_environment_id)
        except ValueError:
            raise HTTPException(409, 'PERSONAL_MODEL_PROXY_SCOPE_CHANGED') from None

    def capabilities(self, owner):
        self.auth.require_member(owner)
        enabled = self.vault is not None and PROVIDER_ID in self.vault.capabilities()['providerIds']
        return {'enabled': True, 'credentialsEnabled': enabled, 'providerId': PROVIDER_ID, 'providers': ['openai', 'openai-compatible'],
            'protocol': 'chat-completions-text-functions-v1', 'baseURLPath': '/v1',
            'protocols': ['chat-completions', 'responses'], 'additionalBaseURLs': list(ADDITIONAL_BASE_URLS),
            'credentialInput': '/api/factory/personal-credentials', 'credentialUsername': 'api-key',
            'platformBillingEnabled': False, 'hardExternalBudgetEnforced': False,
            'liveCompatibilityVerified': False}

    def _authorize(self, owner, body):
        if body.get('credentialRef') is None:
            return body.get('credentialRevision') is None
        return self.vault is not None and self.vault.authorize(owner=owner,
            reference=body['credentialRef'], revision=body['credentialRevision'],
            provider_id=PROVIDER_ID, destination=model_origin(body['baseURL']))

    def _row(self, conn, owner, reference, *, shared=False):
        self.connections._key(reference)
        query = select(self.models).where(self.models.c.reference == reference)
        if not shared: query = query.where(self.models.c.owner_id == owner)
        row = conn.execute(query).mappings().first()
        if row is None: raise HTTPException(404, 'PERSONAL_MODEL_NOT_FOUND')
        if shared: self.connections.sharing.owner(conn, owner, reference, row['owner_id'])
        if (digest(row['body']) != row['fingerprint'] or row['body']['ownerId'] != row['owner_id']
                or row['body']['reference'] != reference or row['body']['revision'] != row['revision']):
            raise HTTPException(409, 'PERSONAL_MODEL_INTEGRITY')
        return row

    def _public(self, conn, owner, reference):
        row = self._row(conn, owner, reference, shared=True)
        default = conn.execute(select(self.defaults.c.reference).where(self.defaults.c.owner_id == owner)).scalar()
        status = 'revoked' if row['state'] == 'REVOKED' else 'configured' if self._authorize(row['owner_id'], row['body']) else 'credential_unavailable'
        body = dict(row['body'])
        default_binding_current = True
        if row['owner_id'] != owner:
            body = {key: body[key] for key in ('ownerId', 'reference', 'revision', 'updatedAt', 'provider', 'baseURL', 'model', 'protocol', 'thinkingMode') if key in body}
            binding = conn.execute(select(self.shared_defaults).where(self.shared_defaults.c.actor_id == owner,
                self.shared_defaults.c.reference == reference)).mappings().first()
            if binding:
                body['connectionRef'] = binding['connection_ref']
                alias = self.connections._row(conn, owner, binding['connection_ref'])
                default_binding_current = alias['state'] == 'ACTIVE' and alias['body']['revision'] == row['revision']
        return {**body, **self.connections.sharing.projection(conn, owner, reference, row['owner_id']),
            'status': status, 'isDefault': default == reference and default_binding_current, 'available': status == 'configured',
            'hardExternalBudgetEnforced': False}

    def list(self, owner):
        self.auth.require_member(owner)
        with self.db.read() as conn:
            refs = conn.execute(select(self.models.c.reference).where(or_(self.models.c.owner_id == owner,
                self.models.c.reference.in_(self.connections.sharing.visible_refs(conn, owner)))).limit(100)).scalars()
            return [self._public(conn, owner, ref) for ref in refs]

    def recover(self, owner, request_id):
        """Read the original command receipt, independently of current model state."""
        self.auth.require_member(owner)
        with self.db.read() as conn:
            command = conn.execute(select(self.commands.c.action, self.commands.c.result,
                self.commands.c.created_at).where(self.commands.c.actor_id == owner,
                self.commands.c.request_id == request_id)).mappings().first()
            # A missing receipt is not proof that an in-flight command did not execute.
            if command is None: raise HTTPException(404, 'PERSONAL_MODEL_REQUEST_NOT_FOUND')
            return {'ownerId': owner, 'requestId': request_id, 'action': command['action'],
                'result': command['result'], 'completedAt': command['created_at']}

    def configure(self, owner, values, request_id, *, reference=None):
        self.auth.require_member(owner)
        try:
            if (values.get('credentialRef') is None) != (values.get('credentialRevision') is None): raise ValueError()
            values = {**values, 'credentialRef': values.get('credentialRef'), 'credentialRevision': values.get('credentialRevision')}
            values = {**values, 'baseURL': base_url(values['baseURL']), 'model': model_id(values['model'])}
            if values['provider'] not in {'openai', 'openai-compatible'}: raise ValueError()
            if 'protocol' in values and values['protocol'] is None: raise ValueError()
            if protocol_name(values) == 'chat-completions':
                # Preserve the fingerprint of legacy commands which omitted protocol.
                values.pop('protocol', None)
            generation_options(values)
            if values.get('thinkingMode') in (None, 'default'):
                values.pop('thinkingMode', None)
        except (KeyError, ValueError):
            raise HTTPException(422, 'PERSONAL_MODEL_CONFIGURATION_INVALID') from None
        if not self._authorize(owner, values): raise HTTPException(403, 'PERSONAL_MODEL_CREDENTIAL_UNAVAILABLE')
        fingerprint = digest({'action': 'configure', 'reference': reference, 'configuration': values})
        with self.db.write() as conn:
            old = self.db.old(conn, self.commands, owner, request_id, fingerprint)
            if old is not None: return old
            if reference is not None:
                if self._row(conn, owner, reference)['state'] == 'REVOKED': raise HTTPException(409, 'PERSONAL_MODEL_REVOKED')
            else: reference = 'owner-model-' + uuid4().hex
            revision = uuid4().hex
            body = {**values, 'ownerId': owner, 'reference': reference, 'revision': revision, 'updatedAt': now()}
            record = dict(reference=reference, owner_id=owner, revision=revision, body=body,
                fingerprint=digest(body), state='ACTIVE')
            if conn.execute(select(self.models.c.reference).where(self.models.c.reference == reference)).first():
                conn.execute(self.models.update().where(self.models.c.reference == reference,
                    self.models.c.owner_id == owner).values(**record))
            else: conn.execute(self.models.insert().values(**record))
            self.connections.sharing.register(conn, owner, reference)
            # Standard immutable owner connection. Dynamic registration resolution
            # uses this persisted configuration, including after process restart.
            bound = self.connections.bind(owner, reference, 'model-bind-' + revision, capabilities=[CAPABILITY])
            body['connectionRef'] = bound['ref']
            conn.execute(self.models.update().where(self.models.c.reference == reference).values(
                body=body, fingerprint=digest(body)))
            result = self._public(conn, owner, reference)
            return self.db.record(conn, self.commands, owner, request_id, fingerprint, 'model.configure', result)

    def set_default(self, owner, reference, request_id):
        self.auth.require_member(owner)
        fingerprint = digest({'action': 'default', 'reference': reference})
        with self.db.write() as conn:
            old = self.db.old(conn, self.commands, owner, request_id, fingerprint)
            if old is not None: return old
            self.binding(conn, owner, reference)
            resource = self._row(conn, owner, reference, shared=True)
            if resource['owner_id'] != owner:
                bound = self.connections.bind(owner, reference, 'shared-model-' + request_id, capabilities=[CAPABILITY])
                conn.execute(self.shared_defaults.delete().where(self.shared_defaults.c.actor_id == owner))
                conn.execute(self.shared_defaults.insert().values(actor_id=owner, reference=reference, connection_ref=bound['ref']))
            if conn.execute(select(self.defaults).where(self.defaults.c.owner_id == owner)).first():
                conn.execute(self.defaults.update().where(self.defaults.c.owner_id == owner).values(reference=reference))
            else: conn.execute(self.defaults.insert().values(owner_id=owner, reference=reference))
            return self.db.record(conn, self.commands, owner, request_id, fingerprint, 'model.default', self._public(conn, owner, reference))

    def revoke(self, owner, reference, request_id):
        self.auth.require_member(owner)
        fingerprint = digest({'action': 'revoke', 'reference': reference})
        with self.db.write() as conn:
            self._row(conn, owner, reference)
            old = self.db.old(conn, self.commands, owner, request_id, fingerprint)
            if old is not None: return old
            conn.execute(self.models.update().where(self.models.c.reference == reference,
                self.models.c.owner_id == owner).values(state='REVOKED'))
            conn.execute(self.defaults.delete().where(self.defaults.c.owner_id == owner,
                self.defaults.c.reference == reference))
            return self.db.record(conn, self.commands, owner, request_id, fingerprint, 'model.revoke', self._public(conn, owner, reference))

    def default(self, owner):
        self.auth.require_member(owner)
        with self.db.read() as conn:
            reference = conn.execute(select(self.defaults.c.reference).where(self.defaults.c.owner_id == owner)).scalar()
            if reference is None: raise HTTPException(409, 'PERSONAL_MODEL_SETUP_REQUIRED: configure your own default model at /api/factory/personal-models')
            self.binding(conn, owner, reference)
            result = self._public(conn, owner, reference)
            if not result['isDefault']:
                raise HTTPException(409, 'PERSONAL_MODEL_DEFAULT_CHANGED: select the current shared model again')
            return result

    def binding(self, conn, owner, reference):
        row = self._row(conn, owner, reference, shared=True)
        if row['state'] == 'REVOKED': raise HTTPException(409, 'PERSONAL_MODEL_REVOKED')
        body = row['body']
        resource_owner = row['owner_id']
        if not self._authorize(resource_owner, body): raise HTTPException(409, 'PERSONAL_MODEL_CREDENTIAL_UNAVAILABLE')
        # A handle contains metadata and a trusted service, never a resolved key.
        return TrustedConnectionBinding(resource_owner, 'model', ADAPTER_ID, frozenset({CAPABILITY}), row['revision'],
            available=True, opaque_handle=OwnerModelHandle(self, resource_owner, body, actor=owner), handle_ref='owner-model-' + row['revision'])

    def share(self, owner, reference, visibility, request_id):
        self.auth.require_member(owner)
        fingerprint = digest({'action': 'sharing', 'reference': reference, 'visibility': visibility})
        with self.db.write() as conn:
            self._row(conn, owner, reference)
            old = self.db.old(conn, self.commands, owner, request_id, fingerprint)
            if old is not None: return old
            self.connections.sharing.register(conn, owner, reference)
            self.connections.sharing.set(conn, owner, reference, visibility)
            return self.db.record(conn, self.commands, owner, request_id, fingerprint, 'model.sharing', self._public(conn, owner, reference))

    def register(self, bindings):
        def validate(configuration):
            if configuration: raise ValueError('Owner model material configuration must be empty')
        def create(context):
            handle = context.connection
            if not isinstance(handle, OwnerModelHandle) or handle.actor != context.plan['ownerId']:
                raise HTTPException(403, 'PERSONAL_MODEL_OWNER_REQUIRED')
            return OwnerChatModel(handle.body, handle.credential, transport_factory=self.transport_factory,
                recheck=handle.check, session_id='af-plan-' + context.plan['id'], trusted_proxy=handle.trusted_proxy)
        bindings.register('model', ADAPTER_ID, '1', create, connection_kind='model',
            required_capabilities=(CAPABILITY,), validator=validate)


class OwnerModelHandle:
    def __init__(self, service, owner, body, *, actor=None):
        self.service, self.owner, self.body = service, owner, dict(body)
        self.actor = actor or owner
        self.trusted_proxy = service._model_proxy(owner, self.body)

    def __repr__(self): return 'OwnerModelHandle(credentials=<redacted>)'

    def check(self):
        self.service.auth.require_member(self.actor)
        with self.service.db.read() as conn:
            row = self.service._row(conn, self.owner, self.body['reference'])
            self.service.connections.sharing.owner(conn, self.actor, self.body['reference'], self.owner)
            if row['state'] != 'ACTIVE' or row['revision'] != self.body['revision']:
                raise HTTPException(409, 'PERSONAL_MODEL_CHANGED')
            if not self.service._authorize(self.owner, row['body']):
                raise HTTPException(409, 'PERSONAL_MODEL_CREDENTIAL_UNAVAILABLE')
            if self.service._model_proxy(self.owner, row['body']) is not self.trusted_proxy:
                raise HTTPException(409, 'PERSONAL_MODEL_PROXY_ROUTE_CHANGED')
            if self.service._model_proxy(self.owner, self.body) is not self.trusted_proxy:
                raise HTTPException(409, 'PERSONAL_MODEL_PROXY_SCOPE_CHANGED')

    def credential(self):
        self.check()
        if self.body['credentialRef'] is None:
            return None
        try:
            lease = self.service.vault.resolve(owner=self.owner, reference=self.body['credentialRef'],
                revision=self.body['credentialRevision'], provider_id=PROVIDER_ID, destination=model_origin(self.body['baseURL']))
            self.check()
            return lease
        except CredentialVaultError:
            raise HTTPException(409, 'PERSONAL_MODEL_CREDENTIAL_UNAVAILABLE') from None


class RedactedInputRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()
        async def safe(request):
            try:
                response = await handler(request)
                response.headers['Cache-Control'] = 'private, no-store'
                return response
            except RequestValidationError:
                return JSONResponse({'code': 'PERSONAL_MODEL_CONFIGURATION_INVALID', 'message': 'Invalid owner model configuration'}, status_code=422,
                    headers={'Cache-Control': 'private, no-store'})
        return safe


class ConfigureModel(BaseModel):
    model_config = ConfigDict(extra='forbid')
    provider: str = Field(min_length=1, max_length=100)
    baseURL: str = Field(min_length=1, max_length=512)
    model: str = Field(min_length=1, max_length=120)
    credentialRef: str | None = Field(default=None, min_length=1, max_length=200)
    credentialRevision: str | None = Field(default=None, min_length=1, max_length=200)
    protocol: Literal['chat-completions', 'responses'] | None = None
    thinkingMode: Literal['default', 'disabled'] | None = None
    requestId: str = Field(min_length=8, max_length=100)

    @model_validator(mode='after')
    def credential_pair(self):
        if (self.credentialRef is None) != (self.credentialRevision is None):
            raise ValueError('PERSONAL_MODEL_CONFIGURATION_INVALID')
        return self

    @field_validator('protocol', mode='before')
    @classmethod
    def explicit_protocol(cls, value):
        if value is None: raise ValueError('An explicit protocol cannot be null')
        return value


class ModelCommand(BaseModel):
    model_config = ConfigDict(extra='forbid')
    requestId: str = Field(min_length=8, max_length=100)


def personal_model_router(auth, service):
    router = APIRouter(prefix='/api/factory/personal-models', route_class=RedactedInputRoute)
    def owner(request): return auth.user(request)['id']
    @router.get('/capabilities')
    def capabilities(request: Request): return service.capabilities(owner(request))
    @router.get('')
    def listing(request: Request): return service.list(owner(request))
    @router.get('/requests/{request_id}')
    def recovery(request_id: str, request: Request): return service.recover(owner(request), request_id)
    @router.post('', status_code=201)
    def configure(body: ConfigureModel, request: Request):
        return service.configure(owner(request), body.model_dump(exclude={'requestId'}, exclude_none=True), body.requestId)
    @router.post('/{reference}/configure')
    def rotate(reference: str, body: ConfigureModel, request: Request):
        return service.configure(owner(request), body.model_dump(exclude={'requestId'}, exclude_none=True), body.requestId, reference=reference)
    @router.post('/{reference}/default')
    def default(reference: str, body: ModelCommand, request: Request):
        return service.set_default(owner(request), reference, body.requestId)
    @router.post('/{reference}/revoke')
    def revoke(reference: str, body: ModelCommand, request: Request):
        return service.revoke(owner(request), reference, body.requestId)
    @router.post('/{reference}/sharing')
    def sharing(reference: str, body: SharingCommand, request: Request):
        return service.share(owner(request), reference, body.visibility, body.requestId)
    return router
