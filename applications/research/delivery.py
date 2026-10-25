"""Immutable derived manifests remain behind every original content permission."""
from contextlib import contextmanager
from copy import deepcopy
from io import BytesIO
import json
from uuid import uuid4
from zipfile import ZIP_STORED, ZipFile

from fastapi import APIRouter, HTTPException, Query, Request, Response
from sqlalchemy import Column, JSON, MetaData, String, Table, select

from agent_factory.input_schema import bounded_json
from agent_factory.store import digest, now
from .projects import ProjectCommand, reject


class ResearchDelivery:
    def __init__(self, rounds):
        self.rounds, self.projects = rounds, rounds.projects
        self.db, self.content = rounds.db, rounds.content
        self.maximum = self.db.store.settings.experiment_output_bytes
        metadata = MetaData()
        self.deliveries = Table('research_deliveries', metadata,
            Column('id', String, primary_key=True), Column('owner_id', String, nullable=False),
            Column('project_id', String, nullable=False), Column('body', JSON, nullable=False),
            Column('created_at', String, nullable=False))
        metadata.create_all(self.db.store.engine)

    @contextmanager
    def _snapshot(self):
        with self.db.store.transaction() as conn:
            self.rounds.scopes.admission_lock(conn)
            yield conn

    def _row(self, conn, identifier):
        row = conn.execute(select(self.deliveries).where(self.deliveries.c.id == identifier)).mappings().first()
        if row is None:
            raise HTTPException(404, 'RESEARCH_DELIVERY_NOT_FOUND')
        return row

    def _sources(self, actor, row):
        self.projects.auth.require_member(actor)
        sources = row['body']['sourceIds']
        if not sources and actor != row['owner_id']:
            raise HTTPException(404, 'RESEARCH_DELIVERY_NOT_FOUND')
        return [self.content.read(actor, identifier) for identifier in sources]

    def create(self, owner, project_id, command: ProjectCommand):
        self.projects.auth.require_member(owner)
        missing = []
        fingerprint = digest({'action': 'delivery', 'projectId': project_id, **command.model_dump(exclude={'requestId'})})
        with self._snapshot() as conn, self.db.write():
            project = self.projects._owned(conn, owner, project_id)
            old = self.db.old(conn, self.projects.commands, owner, command.requestId, fingerprint)
            if old is not None:
                identifier = old['id']
                records = None
            else:
                if project['goal_version'] != command.expectedVersion:
                    reject('RESEARCH_GOAL_VERSION_CONFLICT', '原目标版本已变化')
                rows = conn.execute(select(self.rounds.rounds).where(self.rounds.rounds.c.project_id == project_id)
                    .order_by(self.rounds.rounds.c.created_at)).mappings().all()
                records = [self.content.read(owner, row['terminal_record']) for row in rows if row['terminal_record']]
                missing = ['round_not_terminal:' + row['id'] for row in rows if row['terminal'] is None]
        if records is not None:
            body = bounded_json({'schema': 1, 'kind': 'research.delivery', 'projectId': project_id,
                'goalVersion': command.expectedVersion, 'sourceIds': sorted({identifier
                    for item in records for identifier in [item['id'], *item.get('sourceContentIds', [])]}),
                'recordIds': [item['id'] for item in records],
                'records': [item['content'] for item in records],
                'missingEvidence': sorted(set(missing + ([] if records else ['published_records']) + [
                    reason for item in records for reason in item['content'].get('selectedEvidence', {}).get(
                        'missingEvidence', ['selected_evidence'])])),
                'verificationStatus': 'unverified', 'remainingQuestions': {'status': 'not_provided'},
                'evidenceFormat': 'JSON envelopes: role identifies the evidence; value contains the selected original output. Save source.value as the recipe command file and follow run_recipe.value with your own resources.',
                'continuation': 'Use these records in a new project with a new confirmed budget; do not replay an unknown operation.'}, maximum=16384)
            with self._snapshot() as conn, self.db.write():
                project = self.projects._owned(conn, owner, project_id)
                old = self.db.old(conn, self.projects.commands, owner, command.requestId, fingerprint)
                if old is None:
                    if project['goal_version'] != command.expectedVersion:
                        reject('RESEARCH_GOAL_VERSION_CONFLICT', '原目标版本已变化')
                    for source in body['sourceIds']:
                        self.content.read(owner, source)
                    identifier = str(uuid4())
                    conn.execute(self.deliveries.insert().values(id=identifier, owner_id=owner,
                        project_id=project_id, body=body, created_at=now()))
                    self.db.record(conn, self.projects.commands, owner, command.requestId, fingerprint,
                        'research.delivery', {'id': identifier})
                else:
                    identifier = old['id']
        return self.read(owner, identifier)

    def read(self, actor, identifier):
        with self._snapshot() as conn:
            row = self._row(conn, identifier)
            self._sources(actor, row)
            value = {'id': row['id'], 'ownerId': row['owner_id'], 'createdAt': row['created_at'], **deepcopy(row['body'])}
        return value

    def list(self, actor, *, after='', limit=20):
        self.projects.auth.require_member(actor)
        with self._snapshot() as conn:
            rows = conn.execute(select(self.deliveries).where(self.deliveries.c.id > after)
                .order_by(self.deliveries.c.id).limit(limit + 1)).mappings().all()
            items = []
            for row in rows[:limit]:
                try:
                    self._sources(actor, row)
                except HTTPException as error:
                    if error.status_code not in {403, 404}:
                        raise
                    continue
                items.append({'id': row['id'], 'ownerId': row['owner_id'], 'createdAt': row['created_at']})
            return {'items': items, 'nextCursor': rows[limit - 1]['id'] if len(rows) > limit else None}

    def download(self, actor, identifier):
        with self._snapshot() as conn:
            row = self._row(conn, identifier)
            records = self._sources(actor, row)
            manifest = deepcopy(row['body'])
            selected = {}
            for record in records:
                if record['id'] not in row['body']['recordIds']:
                    continue
                for item in record['content'].get('selectedEvidence', {}).get('items', []):
                    reference = item['reference']
                    if reference not in record['artifacts']:
                        raise HTTPException(409, 'RESEARCH_EVIDENCE_REFERENCE_MISMATCH')
                    selected[reference['artifactId']] = (record['id'], item)
            if sum(item['size'] for _, item in selected.values()) > self.maximum:
                raise HTTPException(413, 'RESEARCH_DELIVERY_TOO_LARGE')
            files, size = [], 0
            for source_id, item in selected.values():
                metadata, raw = self.content.artifact(actor, source_id, item['reference']['artifactId'])
                if metadata['size'] != item['size']:
                    raise HTTPException(409, 'RESEARCH_EVIDENCE_SIZE_MISMATCH')
                size += len(raw)
                if size > self.maximum:
                    raise HTTPException(413, 'RESEARCH_DELIVERY_TOO_LARGE')
                files.append(('evidence/' + metadata['id'], bytes(raw)))
        raw_manifest = json.dumps(manifest, ensure_ascii=False, allow_nan=False).encode()
        if size + len(raw_manifest) > self.maximum:
            raise HTTPException(413, 'RESEARCH_DELIVERY_TOO_LARGE')
        output = BytesIO()
        with ZipFile(output, 'w', compression=ZIP_STORED) as bundle:
            bundle.writestr('manifest.json', raw_manifest)
            for name, raw in files:
                bundle.writestr(name, raw)
        return output.getvalue()


def delivery_router(auth, service):
    router = APIRouter(prefix='/api/factory/research')

    @router.post('/projects/{project_id}/deliveries', status_code=201)
    def create(project_id: str, body: ProjectCommand, request: Request):
        return service.create(auth.user(request)['id'], project_id, body)

    @router.get('/deliveries')
    def listing(request: Request, after: str = Query(default='', max_length=200), limit: int = Query(default=20, ge=1, le=100)):
        return service.list(auth.user(request)['id'], after=after, limit=limit)

    @router.get('/deliveries/{identifier}')
    def read(identifier: str, request: Request):
        return service.read(auth.user(request)['id'], identifier)

    @router.get('/deliveries/{identifier}/download')
    def download(identifier: str, request: Request):
        return Response(service.download(auth.user(request)['id'], identifier), media_type='application/zip',
            headers={'Content-Disposition': 'attachment; filename="research-delivery.zip"'})

    return router
