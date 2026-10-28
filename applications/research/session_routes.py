"""Owner-authenticated personal research conversation commands and reads."""
import asyncio

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from agent_factory.application_content import ObjectId
from .projects import Reference, RequestId


class SessionLimits(BaseModel):
    model_config = ConfigDict(extra='forbid')
    maxTurns: int = Field(strict=True, ge=1, le=20)
    toolCallsPerTurn: int = Field(strict=True, ge=1, le=128)
    operationSeconds: int = Field(strict=True, ge=1, le=600)


class CreateSession(BaseModel):
    model_config = ConfigDict(extra='forbid')
    requestId: RequestId
    title: str = Field(min_length=1, max_length=120)
    goal: str = Field(min_length=2, max_length=2000)
    boundaries: str = Field(min_length=1, max_length=2000)
    modelConnectionRef: Reference
    limits: SessionLimits


class SessionText(BaseModel):
    model_config = ConfigDict(extra='forbid')
    requestId: RequestId
    text: str = Field(min_length=1, max_length=2000)


class SessionTurn(SessionText):
    assistantQuestionId: ObjectId | None = None


class SessionCommand(BaseModel):
    model_config = ConfigDict(extra='forbid')
    requestId: RequestId


def session_router(auth, service):
    router = APIRouter(prefix='/api/factory/research/sessions')

    @router.get('/options')
    def options(request: Request):
        return service.options(auth.user(request)['id'])

    @router.get('')
    async def listing(request: Request, after: str = Query(default='', max_length=200)):
        return await service.listing(auth.user(request)['id'], after)

    @router.post('')
    async def create(request: Request, body: CreateSession):
        owner = auth.user(request)['id']
        identifier = await asyncio.to_thread(service.create, owner, body)
        return await service.read(owner, identifier)

    @router.get('/requests/{request_id}')
    async def original(request: Request, request_id: str):
        return await service.request(auth.user(request)['id'], request_id)

    @router.get('/{identifier}')
    async def read(request: Request, identifier: str):
        return await service.read(auth.user(request)['id'], identifier)

    @router.post('/{identifier}/turns')
    async def turn(request: Request, identifier: str, body: SessionTurn):
        return await service.turn(auth.user(request)['id'], identifier, body)

    @router.post('/{identifier}/corrections')
    async def correct(request: Request, identifier: str, body: SessionText):
        owner = auth.user(request)['id']
        await asyncio.to_thread(service.correct, owner, identifier, body)
        return await service.read(owner, identifier)

    @router.post('/{identifier}/stop')
    async def stop(request: Request, identifier: str, body: SessionCommand):
        return await service.stop(auth.user(request)['id'], identifier, body)

    return router
