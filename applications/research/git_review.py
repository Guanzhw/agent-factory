"""Revision-bound diff comments and reviews through ordinary native chat turns."""
import asyncio
import json
import re
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import MetaData, select

from agent_factory.store import digest, now
from .projects import Reference, RequestId
from .session_routes import SessionTurn


class RevisionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    requestId: RequestId
    reviewId: str = Field(min_length=1)


class ReviewRequest(RevisionRequest):
    modelConnectionRef: Reference | None = None
    reasoningEffort: str | None = None


class DiffComment(RevisionRequest):
    path: str = Field(min_length=1)
    side: Literal['left', 'right']
    line: int = Field(gt=0, strict=True)
    text: str = Field(min_length=1)


def diff_anchors(patch, files):
    """Return only file/side/line locations actually present in unified hunks."""
    result = set()
    paths = iter(item['path'] for item in files)
    path = None
    left = right = None
    for line in patch.split('\n'):
        if line.startswith('diff --git '):
            path = next(paths)
            left = right = None
        elif match := re.match(r'^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@', line):
            left, right = int(match[1]), int(match[2])
        elif left is not None and right is not None and line:
            if line[0] in ' -':
                result.add((path, 'left', left))
                left += 1
            if line[0] in ' +':
                result.add((path, 'right', right))
                right += 1
    return result


class ResearchGitReview:
    def __init__(self, sessions, git):
        self.sessions, self.git = sessions, git
        metadata = MetaData()
        self.commands = sessions.db.command_table('research_git_review_commands', metadata)
        metadata.create_all(sessions.store.engine)

    def listing(self, owner, identifier):
        self.sessions.auth.require_member(owner)
        with self.sessions.db.read() as conn:
            row = self.sessions._row(conn, owner, identifier)
            return {'items': row['body'].get('gitComments', [])}

    def create(self, owner, identifier, request, *, turn_id=None):
        self.sessions.auth.require_member(owner)
        value = request.model_dump(exclude={'requestId'})
        fingerprint = digest({'sessionId': identifier, **value, 'turnId': turn_id})
        with self.sessions._write() as conn:
            row = self.sessions._row(conn, owner, identifier)
            old = self.sessions.db.old(conn, self.commands, owner, request.requestId, fingerprint)
            if old is not None:
                return old
            if turn_id is not None:
                turn = conn.execute(select(self.sessions.turns).where(self.sessions.turns.c.id == turn_id,
                    self.sessions.turns.c.session_id == identifier,
                    self.sessions.turns.c.owner_id == owner)).mappings().one()
                origin = turn['body'].get('origin', {})
                if origin.get('kind') != 'git-review' or origin.get('reviewId') != request.reviewId:
                    raise HTTPException(409, '评论版本与本轮审查版本不同。')
                snapshot = {'reviewId': origin['reviewId'], 'files': origin['files'],
                    'diff': turn['body']['messages'][0]['text'].split('\nPatch:\n', 1)[1]}
            else:
                snapshot = self.git.read(owner, identifier)
            if snapshot.get('reviewId') != request.reviewId:
                raise HTTPException(409, '补丁已变化，请刷新差异后评论。')
            if (request.path, request.side, request.line) not in diff_anchors(snapshot['diff'], snapshot['files']):
                raise HTTPException(422, '评论位置不在此版本的差异中。')
            item = {'id': str(uuid4()), **value, 'createdAt': now(), 'turnId': turn_id}
            self.sessions._save_session(conn, row, {**row['body'],
                'gitComments': [*row['body'].get('gitComments', []), item]})
            self.sessions.db.record(conn, self.commands, owner, request.requestId, fingerprint, 'git.comment', item)
            return item

    def _review_turn(self, owner, identifier, request):
        configuration = request.model_dump(include={'modelConnectionRef', 'reasoningEffort'}, exclude_unset=True)
        origin = {'kind': 'git-review', 'reviewId': request.reviewId, **configuration}
        with self.sessions.db.read() as conn:
            self.sessions._row(conn, owner, identifier)
            command = conn.execute(select(self.sessions.commands).where(
                self.sessions.commands.c.actor_id == owner,
                self.sessions.commands.c.request_id == request.requestId)).mappings().first()
            if command is not None:
                result = command['result']
                if result.get('sessionId') != identifier or not result.get('turnId'):
                    raise HTTPException(409, 'IDEMPOTENCY_CONFLICT: request belongs to another command')
                turn = conn.execute(select(self.sessions.turns).where(
                    self.sessions.turns.c.id == result['turnId'])).mappings().one()
                saved_origin = turn['body'].get('origin', {})
                if {key: value for key, value in saved_origin.items() if key != 'files'} != origin:
                    raise HTTPException(409, 'IDEMPOTENCY_CONFLICT: reviewed revision changed')
                return result['turnId'], False
        snapshot = self.git.read(owner, identifier)
        if snapshot.get('reviewId') != request.reviewId:
            raise HTTPException(409, '补丁已变化，请刷新后重新审查。')
        comments = [item for item in self.listing(owner, identifier)['items'] if item['reviewId'] == request.reviewId]
        text = ('Review this exact Git patch for actionable bugs. Inspect relevant files as needed. '
            'Do not change files. For each concrete finding call research_git_comment with the reviewId, '
            'path, side (left=old, right=new), line and explanation. Comment only on lines present in the diff. '
            'Finish with findings and verification limits; if there are no findings say so.\n'
            f'Review revision: {request.reviewId}\n'
            f'Existing comments:\n{json.dumps(comments, ensure_ascii=False)}\n'
            f'Patch:\n{snapshot["diff"]}')
        try:
            turn_request = SessionTurn(requestId=request.requestId, text=text, **configuration)
        except ValidationError:
            raise HTTPException(422, '审查补丁和评论超过会话单次输入限制（1048576 个字符），请缩小本次修改后重试。') from None
        return self.sessions._reserve(owner, identifier, turn_request, origin={**origin, 'files': snapshot['files']})

    async def review(self, owner, identifier, request):
        self.sessions.auth.require_member(owner)
        await self.sessions._refresh(owner, identifier)
        turn_id, fresh = await asyncio.to_thread(self._review_turn, owner, identifier, request)
        await self.sessions._dispatch(owner, identifier, turn_id, fresh)
        return await self.sessions.read(owner, identifier)

    def invoke(self, context, call_id, values):
        execution = self.sessions.authorize_tool(context, 'research_git_comment')
        request = DiffComment(requestId='git-comment:' + digest({'runId': context.run_id, 'callId': call_id}), **values)
        return self.create(context.user_id, execution['id'], request, turn_id=execution['turnId'])


def git_review_router(auth, service):
    router = APIRouter(prefix='/api/factory/research/sessions')

    @router.get('/{identifier}/git/comments')
    def comments(request: Request, identifier: str):
        return service.listing(auth.user(request)['id'], identifier)

    @router.post('/{identifier}/git/comments')
    def comment(request: Request, identifier: str, body: DiffComment):
        return service.create(auth.user(request)['id'], identifier, body)

    @router.post('/{identifier}/git/review')
    async def review(request: Request, identifier: str, body: ReviewRequest):
        return await service.review(auth.user(request)['id'], identifier, body)

    return router
