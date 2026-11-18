"""Owner-authenticated personal research conversation commands and reads."""
import asyncio
import os
import re
from contextlib import AsyncExitStack
from pathlib import Path
import stat
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from starlette.background import BackgroundTask

from agent_factory.application_content import ObjectId
from .projects import Reference, RequestId
from .session_triggers import CreateTrigger
from .session_stream import SessionNotifications, session_updates
from .session_files import _directory, _open_file, _windows_path, _workspace_parts, receive_file


# openai/codex 0ed34eb9: protocol/src/user_input.rs::MAX_USER_INPUT_TEXT_CHARS.
MAX_USER_INPUT_TEXT_CHARS = 1 << 20


class CreateSession(BaseModel):
    model_config = ConfigDict(extra='forbid')
    requestId: RequestId
    title: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    boundaries: str = ''
    modelConnectionRef: Reference
    reasoningEffort: str | None = None
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
    modelConnectionRef: Reference | None = None
    reasoningEffort: str | None = None


class SessionCommand(BaseModel):
    model_config = ConfigDict(extra='forbid')
    requestId: RequestId


class ForkSession(SessionCommand):
    turnId: ObjectId | None = None
    title: str | None = Field(default=None, min_length=1)


def session_router(auth, service):
    router = APIRouter(prefix='/api/factory/research/sessions')
    subscriptions = SessionNotifications(service.store)

    @router.get('/options')
    def options(request: Request):
        return service.options(auth.request_owner(request))

    @router.get('')
    def listing(request: Request, after: str = Query(default='', max_length=200), q: str = ''):
        return service.listing(auth.request_owner(request), after, q)

    @router.post('')
    async def create(request: Request, body: CreateSession):
        owner = auth.request_owner(request)
        identifier = await asyncio.to_thread(service.create, owner, body)
        return await service.read(owner, identifier)

    @router.get('/requests/{request_id}')
    async def original(request: Request, request_id: str):
        return await service.request(auth.request_owner(request), request_id)

    @router.get('/{identifier}')
    async def read(request: Request, identifier: str):
        return await service.read(auth.request_owner(request), identifier)

    @router.post('/{identifier}/fork')
    async def fork(request: Request, identifier: str, body: ForkSession):
        owner = auth.request_owner(request)
        fork_id = await asyncio.to_thread(service.fork, owner, identifier, body)
        return await service.read(owner, fork_id)

    @router.get('/{identifier}/events')
    async def events(request: Request, identifier: str):
        owner = auth.request_owner(request)
        resources = AsyncExitStack()
        try:
            notifications = await resources.enter_async_context(subscriptions.subscribe())
            initial = await service.read(owner, identifier)
        except BaseException:
            await resources.aclose()
            raise

        async def updates():
            try:
                async for value in session_updates(request, auth, service, owner, identifier, notifications, initial):
                    yield value
            finally:
                await resources.aclose()

        return StreamingResponse(updates(), media_type='text/event-stream',
            headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
            background=BackgroundTask(resources.aclose))

    @router.post('/{identifier}/files', status_code=201)
    def upload(request: Request, identifier: str, file: UploadFile):
        workspace = service.workspace(auth.request_owner(request), identifier)
        try:
            name = receive_file(workspace, file.filename or '', file.file)
        except ValueError:
            raise HTTPException(422, '请选择具有有效文件名的文件。') from None
        return {'path': name, 'size': file.size}

    @router.get('/{identifier}/files')
    def files(request: Request, identifier: str, directory: str | None = None):
        workspace = service.workspace(auth.request_owner(request), identifier)
        workspace = _windows_path(workspace) if os.name == 'nt' else workspace
        result = []
        errors = []
        def unavailable(error):
            errors.append({'path': Path(error.filename).relative_to(workspace).as_posix(),
                           'message': error.strerror or '读取失败'})
        if directory is not None:
            try:
                parts = _workspace_parts(workspace, directory, directory=True)
                folders = []
                with _directory(workspace, parts) as parent, os.scandir(parent) as entries:
                    for entry in entries:
                        path = '/'.join([*parts, entry.name])
                        try:
                            info = entry.stat(follow_symlinks=False)
                        except FileNotFoundError:
                            continue
                        if stat.S_ISDIR(info.st_mode):
                            folders.append(path)
                        elif stat.S_ISREG(info.st_mode):
                            result.append({'path': path, 'size': info.st_size})
                return {'directories': sorted(folders), 'files': sorted(result, key=lambda f: f['path']), 'errors': []}
            except (OSError, ValueError):
                raise HTTPException(404, '目录无法读取，请返回上一级或刷新。') from None
        for folder, _, names in os.walk(workspace, onerror=unavailable):
            for name in names:
                file = Path(folder) / name
                try:
                    info = file.lstat()
                    if stat.S_ISREG(info.st_mode):
                        result.append({'path': file.relative_to(workspace).as_posix(), 'size': info.st_size})
                except FileNotFoundError:
                    continue
                except OSError as error:
                    unavailable(error)
        return {'files': sorted(result, key=lambda item: item['path']), 'errors': errors}

    @router.get('/{identifier}/files/download')
    def download(request: Request, identifier: str, path: str):
        workspace = service.workspace(auth.request_owner(request), identifier)
        try:
            parts = _workspace_parts(workspace, path)
            with _directory(workspace, parts[:-1]) as parent:
                stream = os.fdopen(_open_file(parent, parts[-1]), 'rb')
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                stream.close()
                raise ValueError()
        except (OSError, ValueError):
            raise HTTPException(404, '文件不存在或已移动，请刷新文件列表。') from None
        byte_range = request.headers.get('range')
        if byte_range:
            match = re.fullmatch(r'bytes=(\d{1,20})-(\d{1,20})', byte_range)
            info = os.fstat(stream.fileno())
            size = info.st_size
            version = f'"{info.st_dev:x}-{info.st_ino:x}-{size:x}-{info.st_mtime_ns:x}-{info.st_ctime_ns:x}"'
            if request.headers.get('if-match') not in {None, version}:
                stream.close()
                raise HTTPException(412, '文件已变化，请刷新后重新读取。')
            if not match or int(match[1]) >= size or int(match[1]) > int(match[2]):
                stream.close()
                raise HTTPException(416, headers={'Content-Range': f'bytes */{size}'})
            start, end = int(match[1]), min(size - 1, int(match[2]))
            stream.seek(start)
            def chunks():
                remaining = end - start + 1
                while remaining:
                    block = stream.read(min(65536, remaining))
                    if not block:
                        break
                    remaining -= len(block)
                    yield block
            return StreamingResponse(chunks(), status_code=206, media_type='application/octet-stream',
                headers={'Content-Range': f'bytes {start}-{end}/{size}', 'ETag': version, 'Cache-Control': 'no-store',
                         'Content-Disposition': 'attachment', 'X-Content-Type-Options': 'nosniff'},
                background=BackgroundTask(stream.close))
        return StreamingResponse(iter(lambda: stream.read(65536), b''), media_type='application/octet-stream',
            headers={'Content-Disposition': "attachment; filename*=UTF-8''" + quote(parts[-1], safe=''),
                     'Cache-Control': 'no-store'}, background=BackgroundTask(stream.close))

    @router.get('/{identifier}/triggers')
    def triggers(request: Request, identifier: str):
        return service.triggers.listing(auth.request_owner(request), identifier)

    @router.post('/{identifier}/triggers')
    async def create_trigger(request: Request, identifier: str, body: CreateTrigger):
        return await asyncio.to_thread(service.triggers.create, auth.request_owner(request), identifier, body)

    @router.delete('/{identifier}/triggers/{trigger_id}')
    async def delete_trigger(request: Request, identifier: str, trigger_id: str, requestId: RequestId):
        return await asyncio.to_thread(service.triggers.delete, auth.request_owner(request), identifier, trigger_id, requestId)

    @router.post('/{identifier}/turns')
    async def turn(request: Request, identifier: str, body: SessionTurn):
        return await service.turn(auth.request_owner(request), identifier, body)

    @router.post('/{identifier}/corrections')
    async def correct(request: Request, identifier: str, body: SessionText):
        owner = auth.request_owner(request)
        await asyncio.to_thread(service.correct, owner, identifier, body)
        return await service.read(owner, identifier)

    @router.post('/{identifier}/stop')
    async def stop(request: Request, identifier: str, body: SessionCommand):
        return await service.stop(auth.request_owner(request), identifier, body)

    return router
