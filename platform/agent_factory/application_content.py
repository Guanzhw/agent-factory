"""Curated member publications grant access to exact artifacts, never whole jobs."""
from copy import deepcopy
from contextlib import contextmanager
import json
from typing import Annotated, Literal
from urllib.parse import quote
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Column, JSON, MetaData, String, Table, or_, select, text

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
    content: dict | None = None
    contentArtifact: ContentArtifact | None = None
    artifacts: list[ContentArtifact] = Field(default_factory=list, max_length=20)
    visibility: Literal['personal', 'team'] = 'personal'
    sourceContentIds: list[ObjectId] = Field(default_factory=list)

    @model_validator(mode='after')
    def one_body(self):
        if (self.content is None) == (self.contentArtifact is None):
            raise ValueError('Exactly one content or contentArtifact is required')
        return self


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
        for identifier in row['body'].get('sourceContentIds', []):
            source = self._row(conn, identifier)
            self.sharing.owner(conn, actor, source['reference'], source['owner_id'])
            self.auth.require_member(source['owner_id'])

    @contextmanager
    def _access(self, *, write=False):
        with self.store.transaction() as conn:
            if self.store.engine.dialect.name == 'postgresql':
                conn.execute(text("SELECT pg_advisory_xact_lock(hashtext('af_admission'))"))
            if write:
                with self.db.write():
                    yield conn
            else:
                yield conn

    def _sharing_receipt(self, conn, owner, row):
        try:
            self._readable(conn, owner, row)
        except HTTPException as error:
            if error.status_code not in {403, 404}:
                raise
            return {'id': row['id'], 'ownerId': row['owner_id'], 'createdAt': row['created_at'],
                    'contentState': 'source_unavailable',
                    **self.sharing.projection(conn, owner, row['reference'], row['owner_id'])}
        return self._project(conn, owner, row)

    def _project(self, conn, actor, row):
        body = deepcopy(row['body'])
        if body.get('contentArtifact') is not None:
            body['content'] = self._body_artifact(row['owner_id'], body['contentArtifact'])
        return {'id': row['id'], 'ownerId': row['owner_id'], **body,
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

    def _body_artifact(self, owner, reference):
        _, raw = self._artifact(owner, reference)
        try:
            content = json.loads(raw.decode('utf-8'))
            if not isinstance(content, dict):
                raise ValueError('Content must be an object')
            bounded_json(content, maximum=self.store.settings.experiment_output_bytes, ensure_ascii=False)
        except (ValueError, RecursionError) as error:
            raise HTTPException(422, 'APPLICATION_CONTENT_INVALID') from error
        MaterialGovernance._safe_data(content)
        return content

    def publish(self, owner, body: ContentPublication, request_id):
        self.auth.require_member(owner)
        value = body.model_dump()
        value.pop('contentArtifact' if body.contentArtifact is None else 'content')
        if not value['sourceContentIds']:
            value.pop('sourceContentIds')
        MaterialGovernance._safe_data(value)
        try:
            if 'content' in value:
                bounded_json(value['content'], maximum=16384)
            bounded_json(value.get('sourceContentIds', []), maximum=16384)
        except ValueError as error:
            raise HTTPException(422, 'APPLICATION_CONTENT_INVALID') from error
        fingerprint = digest({'action': 'publish', **value})
        with self._access(write=True) as conn:
            old = self.db.old(conn, self.commands, owner, request_id, fingerprint)
            if old is not None:
                row = self._row(conn, old['id'])
                self._readable(conn, owner, row)
                return self._project(conn, owner, row)
            sources = set(value.get('sourceContentIds', []))
            for identifier in tuple(sources):
                source = self._row(conn, identifier)
                self._readable(conn, owner, source)
                sources.update(source['body'].get('sourceContentIds', []))
            if sources:
                value['sourceContentIds'] = sorted(sources)
                try:
                    bounded_json(value['sourceContentIds'], maximum=16384)
                except ValueError as error:
                    raise HTTPException(422, 'APPLICATION_CONTENT_SOURCES_TOO_LARGE') from error
            for reference in value['artifacts']:
                self._artifact(owner, reference)
            if 'contentArtifact' in value:
                self._body_artifact(owner, value['contentArtifact'])
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
        with self._access() as conn:
            row = self._row(conn, identifier)
            self._readable(conn, actor, row)
            return self._project(conn, actor, row)

    def list(self, actor, *, after='', limit=50):
        self.auth.require_member(actor)
        with self._access() as conn:
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
        with self.store.transaction() as conn:
            if self.store.engine.dialect.name == 'postgresql':
                conn.execute(text("SELECT pg_advisory_xact_lock(hashtext('af_admission'))"))
            with self.db.write():
                row = self._row(conn, identifier)
                if row['owner_id'] != owner:
                    raise HTTPException(404, 'APPLICATION_CONTENT_NOT_FOUND')
                old = self.db.old(conn, self.commands, owner, request_id, fingerprint)
                if old is None:
                    self.sharing.set(conn, owner, row['reference'], visibility)
                    self.db.record(conn, self.commands, owner, request_id, fingerprint, 'content.sharing', {'id': identifier})
                return self._sharing_receipt(conn, owner, row)

    def artifact(self, actor, identifier, artifact_id):
        self.auth.require_member(actor)
        with self._access() as conn:
            row = self._row(conn, identifier)
            self._readable(conn, actor, row)
            references = list(row['body']['artifacts'])
            if row['body'].get('contentArtifact') is not None:
                references.append(row['body']['contentArtifact'])
            reference = next((item for item in references if item['artifactId'] == artifact_id), None)
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
