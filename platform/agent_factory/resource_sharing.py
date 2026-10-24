"""Owner-controlled visibility for member resources; credential custody stays local."""
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Column, MetaData, String, Table, select


class SharingCommand(BaseModel):
    model_config = ConfigDict(extra='forbid')
    visibility: Literal['personal', 'team']
    requestId: str = Field(min_length=8, max_length=200)


class ResourceSharing:
    def __init__(self, store, auth):
        self.auth = auth
        metadata = MetaData()
        self.resources = Table('af_resource_sharing', metadata,
            Column('reference', String, primary_key=True),
            Column('owner_id', String, nullable=False),
            Column('visibility', String, nullable=False))
        metadata.create_all(store.engine)

    def register(self, conn, owner, reference):
        row = conn.execute(select(self.resources).where(self.resources.c.reference == reference)).mappings().first()
        if row is None:
            conn.execute(self.resources.insert().values(reference=reference, owner_id=owner, visibility='personal'))
        elif row['owner_id'] != owner:
            raise HTTPException(409, 'RESOURCE_OWNER_CHANGED')

    def visibility(self, conn, reference):
        return conn.execute(select(self.resources.c.visibility).where(
            self.resources.c.reference == reference)).scalar() or 'personal'

    def owner(self, conn, actor, reference, resource_owner):
        self.auth.require_member(actor)
        if actor != resource_owner and self.visibility(conn, reference) != 'team':
            raise HTTPException(404, 'RESOURCE_NOT_FOUND')
        return resource_owner

    def set(self, conn, owner, reference, visibility):
        self.auth.require_member(owner)
        if visibility not in {'personal', 'team'}:
            raise HTTPException(422, 'RESOURCE_VISIBILITY_INVALID')
        # Resource services establish ownership before registering existing rows.
        row = conn.execute(select(self.resources).where(self.resources.c.reference == reference)).mappings().first()
        if row is None or row['owner_id'] != owner:
            raise HTTPException(404, 'RESOURCE_NOT_FOUND')
        conn.execute(self.resources.update().where(self.resources.c.reference == reference).values(visibility=visibility))

    def visible_refs(self, conn, actor):
        self.auth.require_member(actor)
        return list(conn.execute(select(self.resources.c.reference).where(
            self.resources.c.visibility == 'team')).scalars())

    def projection(self, conn, actor, reference, owner):
        return {'ownerId': owner, 'visibility': self.visibility(conn, reference), 'isOwner': actor == owner}
