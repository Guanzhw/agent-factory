"""Curated member publications grant access to exact artifacts, never whole jobs."""
from copy import deepcopy
from typing import Annotated, Literal
from urllib.parse import quote
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Column, JSON, MetaData, String, Table, or_, select

from .applications import GovernedStorage
from .input_schema import bounded_json
from .material_governance import MaterialGovernance
from .resource_sharing import SharingCommand
from .store import digest, now


Label = Annotated[str, Field(min_length=1, max_length=200, pattern=r'^[A-Za-z0-9_.:-]+$')]
ObjectId = Annotated[str, Field(pattern=r'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$')]


class ContentSource(BaseModel):
    model_config = ConfigDict(extra='forbid')
    application: Label
    record: Label
    revision: Label


class ContentArtifact(BaseModel):
    model_config = ConfigDict(extra='forbid')
    taskId: ObjectId
    artifactId: ObjectId
    sha256: str = Field(pattern=r'^[a-f0-9]{64}$')


class ContentPublication(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source: ContentSource
    content: dict
    artifacts: list[ContentArtifact] = Field(default_factory=list, max_length=20)
    visibility: Literal['personal', 'team'] = 'personal'


class PublishContent(ContentPublication):
    requestId: str = Field(min_length=8, max_length=200, pattern=r'^[A-Za-z0-9][A-Za-z0-9_.:-]+$')


class ApplicationContent:
    def __init__(self, store, auth, sharing):
        self.store, self.auth, self.sharing = store, auth, sharing
        self.db = GovernedStorage(store, 'af_application_content_v1')
        metadata = MetaData()
        self.contents = Table('af_application_content', metadata,
            Column('id', String, primary_key=True), Column('owner_id', String, nullable=False),
            Column('reference', String, nullable=False, unique=True),
            Column('body', JSON, nullable=False), Column('created_at', String, nullable=False))
        self.commands = self.db.command_table('af_application_content_commands', metadata)
        metadata.create_all(store.engine)

    def _row(self, conn, identifier):
        row = conn.execute(select(self.contents).where(self.contents.c.id == identifier)).mappings().first()
        if row is None:
            raise HTTPException(404, 'APPLICATION_CONTENT_NOT_FOUND')
        return row

    def _readable(self, conn, actor, row):
        self.sharing.owner(conn, actor, row['reference'], row['owner_id'])
        self.auth.require_member(row['owner_id'])

    def _project(self, conn, actor, row):
        return {'id': row['id'], 'ownerId': row['owner_id'], **deepcopy(row['body']),
            'createdAt': row['created_at'], 'verificationStatus': 'unverified',
            **self.sharing.projection(conn, actor, row['reference'], row['owner_id'])}

    def _artifact(self, owner, reference):
        self.store.task(reference['taskId'], owner)
        sizes = self.store.sql('SELECT length(content) AS size FROM af_artifacts WHERE task_id=:task AND id=:id',
            task=reference['taskId'], id=reference['artifactId'])
        if not sizes:
            raise HTTPException(404, 'Artifact not found')
        if sizes[0]['size'] > self.store.settings.experiment_output_bytes:
            raise HTTPException(409, 'APPLICATION_CONTENT_ARTIFACT_TOO_LARGE')
        metadata, raw = self.store.artifact(reference['taskId'], reference['artifactId'])
        if metadata['sha256'] != reference['sha256']:
            raise HTTPException(409, 'APPLICATION_CONTENT_ARTIFACT_CHANGED')
        provenance = metadata.get('provenance', {})
        safe = {key: metadata[key] for key in ('id', 'jobId', 'name', 'mediaType', 'size', 'sha256', 'createdAt')}
        safe['provenance'] = {key: deepcopy(provenance[key]) for key in
            ('evidenceKind', 'verificationStatus', 'applicationInterfaceVersion', 'applicationRef') if key in provenance}
        return safe, raw

    def publish(self, owner, body: ContentPublication, request_id):
        self.auth.require_member(owner)
        value = body.model_dump()
        MaterialGovernance._safe_data(value)
        try:
            bounded_json(value['content'], maximum=16384)
        except ValueError as error:
            raise HTTPException(422, 'APPLICATION_CONTENT_INVALID') from error
        fingerprint = digest({'action': 'publish', **value})
        with self.db.write() as conn:
            old = self.db.old(conn, self.commands, owner, request_id, fingerprint)
            if old is not None:
                return self._project(conn, owner, self._row(conn, old['id']))
            for reference in value['artifacts']:
                self._artifact(owner, reference)
            identifier = str(uuid4())
            reference = 'content:' + identifier
            visibility = value.pop('visibility')
            conn.execute(self.contents.insert().values(id=identifier, owner_id=owner, reference=reference,
                body=value, created_at=now()))
            self.sharing.register(conn, owner, reference)
            self.sharing.set(conn, owner, reference, visibility)
            self.db.record(conn, self.commands, owner, request_id, fingerprint, 'content.publish', {'id': identifier})
            return self._project(conn, owner, self._row(conn, identifier))

    def read(self, actor, identifier):
        self.auth.require_member(actor)
        with self.db.read() as conn:
            row = self._row(conn, identifier)
            self._readable(conn, actor, row)
            return self._project(conn, actor, row)

    def list(self, actor, *, after='', limit=50):
        self.auth.require_member(actor)
        with self.db.read() as conn:
            rows = conn.execute(select(self.contents).where(self.contents.c.id > after,
                or_(self.contents.c.owner_id == actor,
                    self.contents.c.reference.in_(self.sharing.visible_refs(conn, actor))))
                .order_by(self.contents.c.id).limit(limit + 1)).mappings().all()
            items = []
            for row in rows[:limit]:
                try:
                    self._readable(conn, actor, row)
                except HTTPException as error:
                    if error.status_code not in {403, 404}:
                        raise
                    continue
                items.append(self._project(conn, actor, row))
            return {'items': items, 'nextCursor': rows[limit - 1]['id'] if len(rows) > limit else None}

    def set_visibility(self, owner, identifier, visibility, request_id):
        self.auth.require_member(owner)
        fingerprint = digest({'action': 'sharing', 'id': identifier, 'visibility': visibility})
        with self.db.write() as conn:
            row = self._row(conn, identifier)
            if row['owner_id'] != owner:
                raise HTTPException(404, 'APPLICATION_CONTENT_NOT_FOUND')
            old = self.db.old(conn, self.commands, owner, request_id, fingerprint)
            if old is None:
                self.sharing.set(conn, owner, row['reference'], visibility)
                self.db.record(conn, self.commands, owner, request_id, fingerprint, 'content.sharing', {'id': identifier})
            return self._project(conn, owner, row)

    def artifact(self, actor, identifier, artifact_id):
        self.auth.require_member(actor)
        with self.db.read() as conn:
            row = self._row(conn, identifier)
            self._readable(conn, actor, row)
            reference = next((item for item in row['body']['artifacts'] if item['artifactId'] == artifact_id), None)
            if reference is None:
                raise HTTPException(404, 'APPLICATION_CONTENT_ARTIFACT_NOT_FOUND')
            return self._artifact(row['owner_id'], reference)


def application_content_router(auth, service):
    router = APIRouter(prefix='/api/factory/application-content')

    @router.post('', status_code=201)
    def publish(body: PublishContent, request: Request):
        return service.publish(auth.user(request)['id'],
            ContentPublication.model_validate(body.model_dump(exclude={'requestId'})), body.requestId)

    @router.get('')
    def listing(request: Request, after: str = Query(default='', max_length=200),
                limit: int = Query(default=50, ge=1, le=100)):
        return service.list(auth.user(request)['id'], after=after, limit=limit)

    @router.get('/{identifier}')
    def read(identifier: str, request: Request):
        return service.read(auth.user(request)['id'], identifier)

    @router.post('/{identifier}/sharing')
    def share(identifier: str, body: SharingCommand, request: Request):
        return service.set_visibility(auth.user(request)['id'], identifier, body.visibility, body.requestId)

    @router.get('/{identifier}/artifacts/{artifact_id}')
    def artifact(identifier: str, artifact_id: str, request: Request):
        metadata, raw = service.artifact(auth.user(request)['id'], identifier, artifact_id)
        return Response(raw, media_type=metadata['mediaType'], headers={
            'Content-Disposition': "attachment; filename*=UTF-8''" + quote(metadata['name']),
            'X-Content-SHA256': metadata['sha256'], 'Cache-Control': 'private, no-store'})

    return router
