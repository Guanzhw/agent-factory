"""Owner BYOK metadata and defaults using existing encrypted credential custody.

Configuration/preflight performs no network or model request. References bind the
owner, protocol, TLS destination and credential revision; stale plans fail closed.
"""
from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Column, JSON, MetaData, String, Table, select

from .applications import GovernedStorage
from .byok_model import ADAPTER_ID, CAPABILITY, PROVIDER_ID, OwnerChatModel, base_url, model_id
from .connections import TrustedConnectionBinding
from .credential_vault import CredentialVaultError
from .store import digest, now


class PersonalModels:
    def __init__(self, store, auth, connections, vault, *, transport_factory=None):
        self.store, self.auth, self.connections, self.vault = store, auth, connections, vault
        self.transport_factory = transport_factory
        self.db = GovernedStorage(store, 'af_personal_models_v1')
        metadata = MetaData()
        self.models = Table('af_personal_models', metadata,
            Column('reference', String, primary_key=True), Column('owner_id', String, nullable=False),
            Column('revision', String, nullable=False), Column('body', JSON, nullable=False),
            Column('fingerprint', String, nullable=False), Column('state', String, nullable=False))
        self.defaults = Table('af_personal_model_defaults', metadata,
            Column('owner_id', String, primary_key=True), Column('reference', String, nullable=False))
        self.commands = self.db.command_table('af_personal_model_commands', metadata)
        metadata.create_all(store.engine)

    def capabilities(self, owner):
        self.auth.require(owner, 'read')
        enabled = self.vault is not None and PROVIDER_ID in self.vault.capabilities()['providerIds']
        return {'enabled': enabled, 'providerId': PROVIDER_ID, 'providers': ['openai', 'openai-compatible'],
            'protocol': 'chat-completions-text-functions-v1', 'baseURLPath': '/v1',
            'credentialInput': '/api/factory/personal-credentials', 'credentialUsername': 'api-key',
            'platformBillingEnabled': False, 'hardExternalBudgetEnforced': False,
            'liveCompatibilityVerified': False}

    def _authorize(self, owner, body):
        return self.vault is not None and self.vault.authorize(owner=owner,
            reference=body['credentialRef'], revision=body['credentialRevision'],
            provider_id=PROVIDER_ID, destination=body['baseURL'][:-3])

    def _row(self, conn, owner, reference):
        self.connections._key(reference)
        row = conn.execute(select(self.models).where(self.models.c.owner_id == owner,
            self.models.c.reference == reference)).mappings().first()
        if row is None: raise HTTPException(404, 'PERSONAL_MODEL_NOT_FOUND')
        if (digest(row['body']) != row['fingerprint'] or row['body']['ownerId'] != owner
                or row['body']['reference'] != reference or row['body']['revision'] != row['revision']):
            raise HTTPException(409, 'PERSONAL_MODEL_INTEGRITY')
        return row

    def _public(self, conn, owner, reference):
        row = self._row(conn, owner, reference)
        default = conn.execute(select(self.defaults.c.reference).where(self.defaults.c.owner_id == owner)).scalar()
        status = 'revoked' if row['state'] == 'REVOKED' else 'configured' if self._authorize(owner, row['body']) else 'credential_unavailable'
        return {**row['body'], 'status': status, 'isDefault': default == reference,
            'available': status == 'configured', 'hardExternalBudgetEnforced': False}

    def list(self, owner):
        self.auth.require(owner, 'read')
        with self.db.read() as conn:
            refs = conn.execute(select(self.models.c.reference).where(self.models.c.owner_id == owner).limit(100)).scalars()
            return [self._public(conn, owner, ref) for ref in refs]

    def configure(self, owner, values, request_id, *, reference=None):
        self.auth.require(owner, 'run')
        if not self.capabilities(owner)['enabled']: raise HTTPException(409, 'PERSONAL_MODEL_VAULT_UNAVAILABLE')
        try:
            values = {**values, 'baseURL': base_url(values['baseURL']), 'model': model_id(values['model'])}
            if values['provider'] not in {'openai', 'openai-compatible'}: raise ValueError()
        except (KeyError, ValueError):
            raise HTTPException(422, 'PERSONAL_MODEL_CONFIGURATION_INVALID') from None
        if not self._authorize(owner, values): raise HTTPException(403, 'PERSONAL_MODEL_CREDENTIAL_UNAVAILABLE')
        fingerprint = digest({'action': 'configure', 'reference': reference, 'configuration': values})
        with self.db.write() as conn:
            old = self.db.old(conn, self.commands, owner, request_id, fingerprint)
            if old is not None: return self._public(conn, owner, old['reference'])
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
            # Standard immutable owner connection. Dynamic registration resolution
            # uses this persisted configuration, including after process restart.
            bound = self.connections.bind(owner, reference, 'model-bind-' + revision, capabilities=[CAPABILITY])
            body['connectionRef'] = bound['ref']
            conn.execute(self.models.update().where(self.models.c.reference == reference).values(
                body=body, fingerprint=digest(body)))
            result = self._public(conn, owner, reference)
            return self.db.record(conn, self.commands, owner, request_id, fingerprint, 'model.configure', result)

    def set_default(self, owner, reference, request_id):
        self.auth.require(owner, 'run')
        fingerprint = digest({'action': 'default', 'reference': reference})
        with self.db.write() as conn:
            old = self.db.old(conn, self.commands, owner, request_id, fingerprint)
            if old is not None: return self._public(conn, owner, reference)
            self.binding(conn, owner, reference)
            if conn.execute(select(self.defaults).where(self.defaults.c.owner_id == owner)).first():
                conn.execute(self.defaults.update().where(self.defaults.c.owner_id == owner).values(reference=reference))
            else: conn.execute(self.defaults.insert().values(owner_id=owner, reference=reference))
            return self.db.record(conn, self.commands, owner, request_id, fingerprint, 'model.default', self._public(conn, owner, reference))

    def revoke(self, owner, reference, request_id):
        self.auth.require(owner, 'read')
        fingerprint = digest({'action': 'revoke', 'reference': reference})
        with self.db.write() as conn:
            self._row(conn, owner, reference)
            old = self.db.old(conn, self.commands, owner, request_id, fingerprint)
            if old is not None: return self._public(conn, owner, reference)
            conn.execute(self.models.update().where(self.models.c.reference == reference,
                self.models.c.owner_id == owner).values(state='REVOKED'))
            conn.execute(self.defaults.delete().where(self.defaults.c.owner_id == owner,
                self.defaults.c.reference == reference))
            return self.db.record(conn, self.commands, owner, request_id, fingerprint, 'model.revoke', self._public(conn, owner, reference))

    def default(self, owner):
        self.auth.require(owner, 'run')
        with self.db.read() as conn:
            reference = conn.execute(select(self.defaults.c.reference).where(self.defaults.c.owner_id == owner)).scalar()
            if reference is None: raise HTTPException(409, 'PERSONAL_MODEL_SETUP_REQUIRED: configure your own default model at /api/factory/personal-models')
            self.binding(conn, owner, reference)
            return self._public(conn, owner, reference)

    def binding(self, conn, owner, reference):
        row = self._row(conn, owner, reference)
        if row['state'] == 'REVOKED': raise HTTPException(409, 'PERSONAL_MODEL_REVOKED')
        body = row['body']
        if not self._authorize(owner, body): raise HTTPException(409, 'PERSONAL_MODEL_CREDENTIAL_UNAVAILABLE')
        # A handle contains metadata and a trusted service, never a resolved key.
        return TrustedConnectionBinding(owner, 'model', ADAPTER_ID, frozenset({CAPABILITY}), row['revision'],
            available=True, opaque_handle=OwnerModelHandle(self, owner, body), handle_ref='owner-model-' + row['revision'])

    def register(self, bindings):
        def validate(configuration):
            if configuration: raise ValueError('Owner model material configuration must be empty')
        def create(context):
            handle = context.connection
            if not isinstance(handle, OwnerModelHandle) or handle.owner != context.plan['ownerId']:
                raise HTTPException(403, 'PERSONAL_MODEL_OWNER_REQUIRED')
            return OwnerChatModel(handle.body, handle.credential, transport_factory=self.transport_factory, recheck=handle.check)
        bindings.register('model', ADAPTER_ID, '1', create, connection_kind='model',
            required_capabilities=(CAPABILITY,), validator=validate)


class OwnerModelHandle:
    def __init__(self, service, owner, body):
        self.service, self.owner, self.body = service, owner, dict(body)

    def __repr__(self): return 'OwnerModelHandle(credentials=<redacted>)'

    def check(self):
        self.service.auth.require(self.owner, 'run')
        with self.service.db.read() as conn:
            row = self.service._row(conn, self.owner, self.body['reference'])
            if row['state'] != 'ACTIVE' or row['revision'] != self.body['revision']:
                raise HTTPException(409, 'PERSONAL_MODEL_CHANGED')
            if not self.service._authorize(self.owner, row['body']):
                raise HTTPException(409, 'PERSONAL_MODEL_CREDENTIAL_UNAVAILABLE')

    def credential(self):
        self.check()
        try:
            lease = self.service.vault.resolve(owner=self.owner, reference=self.body['credentialRef'],
                revision=self.body['credentialRevision'], provider_id=PROVIDER_ID, destination=self.body['baseURL'][:-3])
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
    credentialRef: str = Field(min_length=1, max_length=200)
    credentialRevision: str = Field(min_length=1, max_length=200)
    requestId: str = Field(min_length=8, max_length=100)


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
    @router.post('', status_code=201)
    def configure(body: ConfigureModel, request: Request):
        return service.configure(owner(request), body.model_dump(exclude={'requestId'}), body.requestId)
    @router.post('/{reference}/configure')
    def rotate(reference: str, body: ConfigureModel, request: Request):
        return service.configure(owner(request), body.model_dump(exclude={'requestId'}), body.requestId, reference=reference)
    @router.post('/{reference}/default')
    def default(reference: str, body: ModelCommand, request: Request):
        return service.set_default(owner(request), reference, body.requestId)
    @router.post('/{reference}/revoke')
    def revoke(reference: str, body: ModelCommand, request: Request):
        return service.revoke(owner(request), reference, body.requestId)
    return router
