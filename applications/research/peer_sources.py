"""Flat original-source dependencies for research outputs that consumed peer evidence."""
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
            Column('source_ids', JSON, nullable=False), Column('association_ids', JSON, nullable=False),
            Column('content_ids', JSON, nullable=False))
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

    def bind(self, round_id, project_id, source_ids, association_ids, content_ids=()):
        value = {'source_ids': sorted(set(source_ids)), 'association_ids': sorted(set(association_ids)),
                 'content_ids': sorted(set(content_ids))}
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
        return self.content.publish(owner, ContentPublication(source=ContentSource(
            application='research', record=identifier, revision=revision), content=body, visibility='team',
            artifacts=list(artifacts), sourceContentIds=self.dependencies(round_id)),
            'research-record:' + identifier + ':' + revision)['id']

    def source_dependencies(self, content_id, *, actor):
        source = self.content.read(actor, content_id)
        return sorted({content_id, *source.get('sourceContentIds', [])})
