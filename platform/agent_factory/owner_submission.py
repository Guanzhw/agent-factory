"""Compatibility facade for explicit owner submission.

All applications use the same persisted plan rule. Old owner-submission receipts
remain readable history and never grant execution or broaden connection access.
"""
from fastapi import HTTPException
from sqlalchemy import Column, MetaData, String, Table, select

from .store import digest


class OwnerSubmissions:
    def __init__(self, store):
        self.store = store
        metadata = MetaData()
        self.submissions = Table('af_owner_submissions', metadata,
            Column('plan_id', String, primary_key=True), Column('owner_id', String, nullable=False),
            Column('plan_hash', String, nullable=False), Column('created_at', String, nullable=False))
        metadata.create_all(store.engine)

    def can_submit(self, owner, plan):
        if self.store.plan_policy.current()['name'] != 'member-self-service':
            return False
        try:
            self.store.plan_policy.require_execution(owner, plan)
            return True
        except HTTPException as error:
            if error.status_code in {403, 404, 409}: return False
            raise

    def approve(self, owner, plan):
        # Kept for application callers during extraction; no second approval or
        # app/model/registration-name exception exists at this boundary.
        self.store.require_plan_execution(owner, plan)

    def approve_personal(self, owner, plan):
        self.approve(owner, plan)
        return True

    def approved(self, conn, owner, plan):
        """Read an old receipt for inspection only; plan policy never consumes it."""
        row = conn.execute(select(self.submissions).where(self.submissions.c.plan_id == plan['id'],
            self.submissions.c.owner_id == owner)).mappings().first()
        if row is None: return False
        if row['plan_hash'] != digest(plan): raise HTTPException(409, 'OWNER_SUBMISSION_INTEGRITY')
        return True
