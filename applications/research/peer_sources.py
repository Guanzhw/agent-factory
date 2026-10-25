"""Flat original-source dependencies for research outputs that consumed peer evidence."""
from copy import deepcopy
from contextlib import contextmanager

from fastapi import HTTPException
from sqlalchemy import Column, JSON, MetaData, String, Table, select

from agent_factory.application_content import ContentPublication, ContentSource
from agent_factory.applications import GovernedStorage


class ResearchPeerSources:
    def __init__(self, store, content, scopes=None):
        self.content = content
        self.scopes = scopes
        self.db = GovernedStorage(store, 'research_projects_v1')
        metadata = MetaData()
        self.inputs = Table('research_round_peer_inputs', metadata,
            Column('round_id', String, primary_key=True), Column('project_id', String, nullable=False),
            Column('source_ids', JSON, nullable=False), Column('association_ids', JSON, nullable=False))
        self.publications = Table('research_derived_publications', metadata,
            Column('content_id', String, primary_key=True), Column('round_id', String, nullable=False),
            Column('source_ids', JSON, nullable=False), Column('body', JSON, nullable=False))
        metadata.create_all(store.engine)

    @contextmanager
    def guard(self):
        with self.db.store.transaction() as conn:
            if self.db.store.engine.dialect.name == 'postgresql':
                assert self.scopes is not None
                self.scopes.admission_lock(conn)
            with self.db.write():
                yield conn

    def dependencies(self, round_id):
        with self.db.read() as conn:
            row = conn.execute(select(self.inputs).where(self.inputs.c.round_id == round_id)).mappings().first()
            return list(row['source_ids']) if row else []

    def project_dependencies(self, project_id):
        with self.db.read() as conn:
            rows = conn.execute(select(self.inputs.c.source_ids).where(self.inputs.c.project_id == project_id)).scalars()
            return sorted({identifier for ids in rows for identifier in ids})

    def require(self, actor, source_ids):
        for identifier in source_ids:
            source = self.content.read(actor, identifier)
            if source['visibility'] != 'team':
                raise HTTPException(404, 'RESEARCH_SOURCE_UNAVAILABLE')

    def available(self, actor, source_ids):
        try:
            self.require(actor, source_ids)
        except HTTPException as error:
            if error.status_code not in {403, 404}:
                raise
            return False
        return True

    def bind(self, round_id, project_id, source_ids, association_ids):
        value = {'source_ids': sorted(set(source_ids)), 'association_ids': sorted(set(association_ids))}
        with self.db.write() as conn:
            old = conn.execute(select(self.inputs).where(self.inputs.c.round_id == round_id)).mappings().first()
            if old:
                if any(old[key] != val for key, val in value.items()) or old['project_id'] != project_id:
                    raise HTTPException(409, 'RESEARCH_PEER_INPUT_CONFLICT')
                return
            conn.execute(self.inputs.insert().values(round_id=round_id, project_id=project_id, **value))

    def bound(self, round_id):
        with self.db.read() as conn:
            row = conn.execute(select(self.inputs).where(self.inputs.c.round_id == round_id)).mappings().first()
            return dict(row) if row else None

    def publication(self, owner, round_id, identifier, revision, body, *, artifacts=()):
        dependencies = self.dependencies(round_id)
        public = body
        if dependencies:
            # No model strings, scientific outcomes, filenames or artifact grants in the shell.
            public = {key: body[key] for key in ('projectId', 'roundId', 'taskId', 'experimentId', 'attemptId') if key in body}
            public.update(kind=body['kind'], derivationRef=identifier + ':' + revision,
                          state='ended' if revision == 'terminal' else 'pending_admission')
        with self.db.write() as conn:
            result = self.content.publish(owner, ContentPublication(source=ContentSource(
                application='research', record=identifier, revision=revision), content=public, visibility='team',
                artifacts=list(artifacts), sourceContentIds=dependencies),
                'research-record:' + identifier + ':' + revision)
            if dependencies:
                old = conn.execute(select(self.publications).where(self.publications.c.content_id == result['id'])).mappings().first()
                if old is None:
                    conn.execute(self.publications.insert().values(content_id=result['id'], round_id=round_id,
                        source_ids=dependencies, body=body))
                elif old['body'] != body or old['source_ids'] != dependencies:
                    raise HTTPException(409, 'RESEARCH_DERIVED_PUBLICATION_CONFLICT')
            return result['id']

    def source_dependencies(self, content_id, *, actor):
        source = self.content.read(actor, content_id)
        with self.db.read() as conn:
            row = conn.execute(select(self.publications).where(self.publications.c.content_id == content_id)).mappings().first()
            return sorted({content_id, *source.get('sourceContentIds', []), *(row['source_ids'] if row else [])})

    def artifact(self, actor, content_id, artifact_id):
        with self.guard():
            self.read_publication(actor, content_id)
            return self.content.artifact(actor, content_id, artifact_id)

    def read_publication(self, actor, content_id):
        with self.guard() as conn:
            source = self.content.read(actor, content_id)
            row = conn.execute(select(self.publications).where(self.publications.c.content_id == content_id)).mappings().first()
            if row:
                self.require(actor, row['source_ids'])
                source['content'] = deepcopy(row['body'])
            return source
