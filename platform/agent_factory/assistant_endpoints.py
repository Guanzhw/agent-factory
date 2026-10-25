"""Stable member endpoints with immutable application defaults, not native sessions."""
from copy import deepcopy
import time
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from sqlalchemy import Boolean, Column, JSON, MetaData, String, Table, or_, select, text

from .applications import GovernedStorage
from .local_budget_scopes import _caps
from .material_governance import MaterialGovernance, PinnedRef
from .store import digest, now


Identifier = Annotated[str, Field(min_length=1, max_length=200, pattern=r'^[A-Za-z0-9_.:-]+$')]
EndpointRequestId = Annotated[str, Field(min_length=8, max_length=80, pattern=r'^[A-Za-z0-9][A-Za-z0-9_.:-]+$')]


class AutomaticBudget(BaseModel):
    model_config = ConfigDict(extra='forbid')
    scopeId: Identifier
    caps: dict
    deadline: float = Field(allow_inf_nan=False)


class EndpointConfiguration(BaseModel):
    model_config = ConfigDict(extra='forbid')
    automaticBudget: AutomaticBudget | None = None
    name: str = Field(min_length=1, max_length=100)
    applicationRef: PinnedRef
    mode: str = Field(min_length=1, max_length=100, pattern=r'^[A-Za-z0-9_.:-]+$')
    materialChoices: dict[Identifier, PinnedRef] = Field(default_factory=dict, max_length=30)
    connectionRefs: dict[Identifier, Identifier] = Field(default_factory=dict, max_length=30)


class ConfigureEndpoint(EndpointConfiguration):
    requestId: EndpointRequestId


class EndpointState(BaseModel):
    model_config = ConfigDict(extra='forbid')
    requestId: EndpointRequestId
    enabled: StrictBool


class AssistantEndpoints:
    def __init__(self, store, auth, applications):
        self.store, self.auth, self.applications = store, auth, applications
        self.db = GovernedStorage(store, 'af_assistant_endpoints_v1')
        metadata = MetaData()
        self.endpoints = Table('af_assistant_endpoints', metadata,
            Column('id', String, primary_key=True), Column('owner_id', String, nullable=False),
            Column('configuration', JSON, nullable=False), Column('enabled', Boolean, nullable=False),
            Column('created_at', String, nullable=False))
        self.commands = self.db.command_table('af_assistant_endpoint_commands', metadata)
        metadata.create_all(store.engine)

    def _row(self, conn, endpoint_id):
        row = conn.execute(select(self.endpoints).where(self.endpoints.c.id == endpoint_id)).mappings().first()
        if row is None:
            raise HTTPException(404, 'ASSISTANT_ENDPOINT_NOT_FOUND')
        return row

    @staticmethod
    def _summary(row):
        configuration = row['configuration']
        return {'id': row['id'], 'ownerId': row['owner_id'], 'name': configuration['name'],
            'applicationRef': deepcopy(configuration['applicationRef']), 'mode': configuration['mode'],
            'enabled': row['enabled'], 'createdAt': row['created_at']}

    @classmethod
    def _owned(cls, row):
        configuration = row['configuration']
        return {**cls._summary(row),
            **({'automaticBudget': deepcopy(configuration['automaticBudget'])} if configuration.get('automaticBudget') else {}),
            'defaults': {
            'application': configuration['applicationRef']['id'],
            **{key: deepcopy(configuration[key]) for key in
               ('applicationRef', 'mode', 'materialChoices', 'connectionRefs')}}}

    def _current(self, configuration):
        application = self.applications.require_current(configuration['applicationRef'])
        mode = application['modes'].get(configuration['mode'])
        if mode is None:
            raise HTTPException(422, 'ASSISTANT_MODE_NOT_FOUND')
        self.applications.chosen_refs(mode, configuration['materialChoices'])
        schema = mode.get('inputSchema')
        if schema is not None and (schema['properties'].get('goal', {}).get('type') != 'string'
                or set(schema.get('required', [])) - {'goal'}):
            raise HTTPException(422, 'ASSISTANT_TEXT_INPUT_INCOMPATIBLE')
        return schema is not None

    def require_budget(self, conn, owner, budget):
        caps = _caps(budget['caps'])
        if caps['rounds'] != 1:
            raise HTTPException(422, 'LOCAL_BUDGET_ONE_ROUND_REQUIRED')
        scope = self.store.local_budget_scopes._scope(conn, owner, budget['scopeId'])
        if (scope['state'] != 'ACTIVE' or not time.time() < budget['deadline'] <= scope['body']['deadline']):
            raise HTTPException(409, 'LOCAL_BUDGET_CLOSED_OR_EXPIRED')
        total = scope['body']['caps']
        if ((caps['tokenLimit'] is None) != (total['tokenLimit'] is None)
                or caps['currency'] != total['currency']):
            raise HTTPException(409, 'LOCAL_BUDGET_METERING_MISMATCH')
        if any(caps[key] is not None and caps[key] > total[key]
               for key in ('toolCalls', 'tokenLimit', 'amountMicros')):
            raise HTTPException(422, 'LOCAL_BUDGET_CAPS_INVALID')

    def configure(self, owner, configuration: EndpointConfiguration, request_id):
        self.auth.require_member(owner)
        value = configuration.model_dump()
        if value["automaticBudget"] is None:
            value.pop("automaticBudget")
        MaterialGovernance._safe_data(value)
        fingerprint = digest({'action': 'configure', 'configuration': value})
        with self.db.write() as conn:
            old = self.db.old(conn, self.commands, owner, request_id, fingerprint)
            if old is not None:
                return old
            self._current(value)
            if value.get("automaticBudget"):
                self.require_budget(conn, owner, value["automaticBudget"])
            identifier = str(uuid4())
            conn.execute(self.endpoints.insert().values(id=identifier, owner_id=owner,
                configuration=value, enabled=True, created_at=now()))
            return self.db.record(conn, self.commands, owner, request_id, fingerprint,
                'assistant.configure', self._owned(self._row(conn, identifier)))

    def owned(self, owner, endpoint_id):
        self.auth.require_member(owner)
        with self.db.read() as conn:
            row = self._row(conn, endpoint_id)
            if row['owner_id'] != owner:
                raise HTTPException(404, 'ASSISTANT_ENDPOINT_NOT_FOUND')
            return self._owned(row)

    def get(self, actor, endpoint_id):
        self.auth.require_member(actor)
        with self.db.read() as conn:
            row = self._row(conn, endpoint_id)
            self.auth.require_member(row['owner_id'])
            if not row['enabled'] and row['owner_id'] != actor:
                raise HTTPException(404, 'ASSISTANT_ENDPOINT_NOT_FOUND')
            return self._summary(row)

    def list(self, actor, *, after='', limit=50):
        self.auth.require_member(actor)
        with self.db.read() as conn:
            rows = conn.execute(select(self.endpoints).where(self.endpoints.c.id > after,
                or_(self.endpoints.c.enabled.is_(True), self.endpoints.c.owner_id == actor))
                .order_by(self.endpoints.c.id).limit(limit + 1)).mappings().all()
            items = []
            for row in rows[:limit]:
                try:
                    self.auth.require_member(row['owner_id'])
                except HTTPException as error:
                    if error.status_code != 403:
                        raise
                    continue
                items.append(self._summary(row))
            return {'items': items, 'nextCursor': rows[limit - 1]['id'] if len(rows) > limit else None}

    def resolve(self, endpoint_id):
        """Trusted admission reads owner defaults; callers still use native admission."""
        with self.db.read() as conn:
            row = self._row(conn, endpoint_id)
            self.auth.require_member(row['owner_id'])
            if not row['enabled']:
                raise HTTPException(409, 'ASSISTANT_ENDPOINT_DISABLED')
            text_input = self._current(row['configuration'])
            return {**self._owned(row), 'textInput': text_input}

    def set_enabled(self, owner, endpoint_id, enabled, request_id):
        self.auth.require_member(owner)
        fingerprint = digest({'action': 'state', 'id': endpoint_id, 'enabled': enabled})
        with self.store.transaction() as conn:
            if self.store.engine.dialect.name == 'postgresql':
                conn.execute(text("SELECT pg_advisory_xact_lock(hashtext('af_admission'))"))
            with self.db.write():
                row = self._row(conn, endpoint_id)
                if row['owner_id'] != owner:
                    raise HTTPException(404, 'ASSISTANT_ENDPOINT_NOT_FOUND')
                old = self.db.old(conn, self.commands, owner, request_id, fingerprint)
                if old is not None:
                    return old
                if enabled:
                    self._current(row['configuration'])
                conn.execute(self.endpoints.update().where(self.endpoints.c.id == endpoint_id).values(enabled=enabled))
                return self.db.record(conn, self.commands, owner, request_id, fingerprint,
                    'assistant.state', self._owned(self._row(conn, endpoint_id)))


def assistant_endpoints_router(auth, service):
    router = APIRouter(prefix='/api/factory/assistants')

    @router.post('', status_code=201)
    def configure(body: ConfigureEndpoint, request: Request):
        return service.configure(auth.user(request)['id'],
            EndpointConfiguration.model_validate(body.model_dump(exclude={'requestId'})), body.requestId)

    @router.get('')
    def listing(request: Request, after: str = Query(default='', max_length=200),
                limit: int = Query(default=50, ge=1, le=100)):
        return service.list(auth.user(request)['id'], after=after, limit=limit)

    @router.get('/{endpoint_id}')
    def read(endpoint_id: str, request: Request):
        return service.get(auth.user(request)['id'], endpoint_id)

    @router.post('/{endpoint_id}/state')
    def state(endpoint_id: str, body: EndpointState, request: Request):
        return service.set_enabled(auth.user(request)['id'], endpoint_id, body.enabled, body.requestId)

    return router
