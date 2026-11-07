"""Owner-authenticated personal research conversation commands and reads."""
import asyncio
import json

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent_factory.application_content import ObjectId
from .projects import Reference, RequestId


# openai/codex 0ed34eb9: protocol/src/user_input.rs::MAX_USER_INPUT_TEXT_CHARS.
MAX_USER_INPUT_TEXT_CHARS = 1 << 20


class SessionLimits(BaseModel):
    model_config = ConfigDict(extra='forbid')
    maxTurns: int | None = Field(default=None, strict=True, ge=1)
    toolCallsPerTurn: int | None = Field(default=None, strict=True, ge=1)
    operationSeconds: int | None = Field(default=None, strict=True, ge=1)


class CreateSession(BaseModel):
    model_config = ConfigDict(extra='forbid')
    requestId: RequestId
    title: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    boundaries: str = ''
    modelConnectionRef: Reference
    limits: SessionLimits = Field(default_factory=SessionLimits)
    projectId: Reference | None = None

    @model_validator(mode='after')
    def user_text_size(self):
        if len(self.goal) + len(self.boundaries) > MAX_USER_INPUT_TEXT_CHARS:
            raise ValueError('本次输入的目标与补充要求合计不能超过 1048576 个字符。')
        return self


class SessionText(BaseModel):
    model_config = ConfigDict(extra='forbid')
    requestId: RequestId
    text: str = Field(min_length=1, max_length=MAX_USER_INPUT_TEXT_CHARS)


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

    @router.get('/{identifier}/events')
    async def events(request: Request, identifier: str):
        owner = auth.user(request)['id']
        initial = await service.read(owner, identifier)

        async def updates():
            previous = None
            snapshot = initial
            while not await request.is_disconnected():
                # Recheck the actual session on each read; this stream never
                # starts a turn or manufactures progress from elapsed time.
                if auth.user(request)['id'] != owner:
                    return
                encoded = json.dumps(snapshot, ensure_ascii=False, separators=(',', ':'))
                if encoded != previous:
                    yield 'event: session\ndata: ' + encoded + '\n\n'
                    previous = encoded
                else:
                    yield ': connected\n\n'
                await asyncio.sleep(0.5)
                snapshot = await service.read(owner, identifier)

        return StreamingResponse(updates(), media_type='text/event-stream',
            headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

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
