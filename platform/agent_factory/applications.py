"""Shared transaction and original-request storage helpers."""
from contextlib import contextmanager

from fastapi import HTTPException
from sqlalchemy import Column, JSON, String, Table, select, text

from .store import now


class GovernedStorage:
    def __init__(self, store, namespace):
        self.store, self.namespace = store, namespace

    @contextmanager
    def read(self):
        shared = getattr(self.store, "_connection", None)
        conn = shared.get() if shared is not None else None
        if conn is not None:
            yield conn
        else:
            with self.store.engine.connect() as conn:
                # Nested current-publication checks must borrow this read's
                # connection, including when the metadata pool has one slot.
                token = shared.set(conn) if shared is not None else None
                try:
                    yield conn
                finally:
                    if shared is not None and token is not None:
                        shared.reset(token)

    @contextmanager
    def write(self):
        shared = getattr(self.store, "_connection", None)
        conn = shared.get() if shared is not None else None
        if conn is not None:
            if self.store.engine.dialect.name == "postgresql":
                conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": self.namespace})
            yield conn
            return
        with self.store.engine.begin() as conn:
            if self.store.engine.dialect.name == "postgresql":
                conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": self.namespace})
            token = shared.set(conn) if shared is not None else None
            try:
                yield conn
            finally:
                if shared is not None and token is not None:
                    shared.reset(token)

    @staticmethod
    def command_table(name, metadata):
        return Table(name, metadata, Column("actor_id", String, primary_key=True),
            Column("request_id", String, primary_key=True), Column("fingerprint", String, nullable=False),
            Column("action", String, nullable=False), Column("result", JSON, nullable=False), Column("created_at", String, nullable=False))

    @staticmethod
    def old(conn, table, actor, key, fingerprint):
        if not isinstance(key, str) or not key:
            raise HTTPException(400, "Request ID is required")
        row = conn.execute(select(table).where(table.c.actor_id == actor, table.c.request_id == key)).mappings().first()
        if row and row["fingerprint"] != fingerprint:
            raise HTTPException(409, "IDEMPOTENCY_CONFLICT: governed intent changed")
        return row["result"] if row else None

    @staticmethod
    def record(conn, table, actor, key, fingerprint, action, result):
        conn.execute(table.insert().values(actor_id=actor, request_id=key, fingerprint=fingerprint,
                     action=action, result=result, created_at=now()))
        return result
