"""Member activity commands and pure reads; native approvals remain task controls."""
import math
import time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select


class Caps(BaseModel):
    model_config = ConfigDict(extra='forbid')
    rounds: int = Field(strict=True, ge=1, le=2)
    toolCalls: int = Field(strict=True, ge=1, le=1000)
    tokenLimit: int | None = Field(default=None, strict=True, ge=0, le=10**15)
    amountMicros: int | None = Field(default=None, strict=True, ge=0, le=10**15)
    currency: str | None = None


class Start(BaseModel):
    model_config = ConfigDict(extra='forbid')
    presetId: str = Field(min_length=1, max_length=200)
    goal: str = Field(min_length=2, max_length=2000)
    requestId: str = Field(min_length=8, max_length=200)
    caps: Caps
    deadline: float


class Advance(BaseModel):
    model_config = ConfigDict(extra='forbid')
    previousRoundId: str = Field(min_length=1, max_length=200)
    requestId: str = Field(min_length=8, max_length=200)


class Empty(BaseModel):
    model_config = ConfigDict(extra='forbid')


def iteration_router(auth, service):
    router = APIRouter(prefix='/api/factory/research-iterations', tags=['research-iterations'])

    def owner(request):
        value = auth.user(request)['id']
        auth.require_member(value)
        return value

    def available():
        if service is None:
            raise HTTPException(409, 'ITERATION_PRESET_UNAVAILABLE')
        return service

    @router.get('/presets')
    def presets(request: Request):
        actor = owner(request)
        if service is None:
            return []
        return [{'id': p.id, 'name': '本地 ORX 两轮比较', 'ready': True, 'blockers': [],
            'roundCaps': dict(p.round_caps), 'roundSeconds': p.round_seconds,
            'defaultTotalSeconds': min(3600, max(300, 4 * p.round_seconds)),
            'baseline': {'metric': 'mean_squared_error', 'value': p.baseline_source['metricValue'],
                         'kind': p.baseline_source['kind']}}
            for p in service.presets.values() if p.owner_id == actor]

    @router.get('')
    def listing(request: Request):
        actor = owner(request)
        if service is None:
            return {'items': []}
        with service.store.transaction(read_only=True) as conn:
            ids = conn.execute(select(service.activities.c.id).where(service.activities.c.owner_id == actor)
                .order_by(service.activities.c.id).limit(50)).scalars().all()
            return {'items': [service.inspect(actor, identity) for identity in ids]}

    @router.post('', status_code=201)
    async def start(body: Start, request: Request):
        actor, current = owner(request), available()
        if not math.isfinite(body.deadline) or body.deadline > time.time() + 3600:
            raise HTTPException(422, 'ITERATION_DEADLINE')
        return await current.start(actor, body.presetId, body.goal, body.requestId,
                                   caps=body.caps.model_dump(), deadline=body.deadline)

    @router.get('/requests/{request_id}')
    def recover(request_id: str, request: Request):
        actor, current = owner(request), available()
        with current.store.transaction(read_only=True) as conn:
            identifier = conn.execute(select(current.activities.c.id).where(
                current.activities.c.owner_id == actor, current.activities.c.request_id == request_id)).scalar_one_or_none()
            if identifier is None:
                raise HTTPException(404, 'ITERATION_REQUEST_NOT_FOUND')
            return current.inspect(actor, identifier)

    @router.get('/{activity_id}')
    def inspect(activity_id: str, request: Request):
        return available().inspect(owner(request), activity_id)

    @router.post('/{activity_id}/reconcile')
    async def reconcile(activity_id: str, body: Empty, request: Request):
        return await available().reconcile(owner(request), activity_id)

    @router.post('/{activity_id}/advance')
    async def advance(activity_id: str, body: Advance, request: Request):
        return await available().advance(owner(request), activity_id, body.previousRoundId, body.requestId)

    @router.post('/{activity_id}/cancel')
    async def cancel(activity_id: str, body: Empty, request: Request):
        return await available().cancel(owner(request), activity_id)

    return router
