"""Flat original-source dependencies for research outputs that consumed peer evidence."""
from contextlib import contextmanager

from fastapi import HTTPException
from sqlalchemy import Column, JSON, MetaData, String, Table, select, text

from agent_factory.applications import GovernedStorage


class ResearchPeerSources:
    def __init__(self, store, content):
        self.content = content
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
                conn.execute(text("SELECT pg_advisory_xact_lock(hashtext('af_admission'))"))
            with self.db.write():
                yield conn

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

    def source_dependencies(self, content_id, *, actor):
        source = self.content.read(actor, content_id)
        return sorted({content_id, *source.get('sourceContentIds', [])})
