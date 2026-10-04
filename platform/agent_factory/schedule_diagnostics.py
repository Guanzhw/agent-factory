"""Bounded, best-effort observations of rejected pre-occurrence checks.

This journal is not an admission receipt. Reading it cannot repair a clock,
release a claim, or create/replay an occurrence. Absence is not proof of no attempt.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from uuid import NAMESPACE_URL, uuid5

from fastapi import HTTPException
from sqlalchemy import create_engine, text

from .store import canonical

MAX_RECORDS = 100
RETENTION_DAYS = 30
PAGE_SIZE = 20
REASONS = frozenset({"CLOCK_BUSY", "AUTHORIZATION_DENIED", "CLAIM_CHANGED",
    "BINDING_UNAVAILABLE", "PAUSED", "DEFINITION_CHANGED", "PLAN_UNAVAILABLE", "CHECK_UNAVAILABLE"})


class ScheduleDiagnostics:
    def __init__(self, service):
        self.service = service
        self.store = service.store
        # Do not queue observations behind the application's metadata pool.
        # Bound checkout, connection establishment, statement and row-lock waits.
        self.engine = create_engine(self.store.engine.url, pool_size=1, max_overflow=0,
            pool_timeout=.01, connect_args={"connect_timeout": 1,
                "options": "-c statement_timeout=100 -c lock_timeout=50"})

    def initialize(self):
        self.store.sql("""CREATE TABLE IF NOT EXISTS af_schedule_diagnostics (
            id TEXT PRIMARY KEY, schedule_id TEXT NOT NULL REFERENCES af_schedule_bindings(schedule_id),
            owner_id TEXT NOT NULL, reason_code TEXT NOT NULL, source TEXT NOT NULL,
            observed_at TEXT NOT NULL)""")
        self.store.sql("""CREATE INDEX IF NOT EXISTS af_schedule_diagnostics_owner
            ON af_schedule_diagnostics(owner_id,schedule_id,id)""")

    @staticmethod
    def _cutoff():
        return (datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)).isoformat()

    def record(self, claimed, key, reason_code, *, source="native"):
        # Finite, site-selected data only: no request IDs, exception details,
        # native payloads, provider messages or arbitrary user metadata.
        if reason_code not in REASONS or source not in {"native", "manual"} or not claimed.user_id:
            return
        try:
            with self.engine.begin() as connection:
                # Distinct from admission lock, never wait on a competing observer.
                if not connection.execute(text("SELECT pg_try_advisory_xact_lock(hashtext(:key))"),
                        {"key": "af_schedule_diagnostics:" + claimed.id}).scalar():
                    return
                binding = connection.execute(text("""SELECT owner_id FROM af_schedule_bindings
                    WHERE schedule_id=:id AND owner_id=:owner"""),
                    {"id": claimed.id, "owner": claimed.user_id}).first()
                if binding is None:
                    return
                identifier = str(uuid5(NAMESPACE_URL, canonical({"owner": claimed.user_id,
                    "schedule": claimed.id, "key": key, "reason": reason_code})))
                values = {"id": identifier, "schedule": claimed.id, "owner": claimed.user_id,
                    "reason": reason_code, "source": source, "at": datetime.now(timezone.utc).isoformat(),
                    "cutoff": self._cutoff(), "cap": MAX_RECORDS}
                connection.execute(text("""INSERT INTO af_schedule_diagnostics
                    VALUES(:id,:schedule,:owner,:reason,:source,:at) ON CONFLICT DO NOTHING"""), values)
                connection.execute(text("""DELETE FROM af_schedule_diagnostics
                    WHERE schedule_id=:schedule AND owner_id=:owner AND
                    (observed_at<:cutoff OR id IN (SELECT id FROM af_schedule_diagnostics
                        WHERE schedule_id=:schedule AND owner_id=:owner
                        ORDER BY observed_at DESC,id DESC OFFSET :cap))"""), values)
        except Exception:
            # Observation must never replace the original denial, cause replay,
            # expose arbitrary DB errors, or alter native claim release semantics.
            return

    async def observe(self, claimed, key, reason_code, *, source="native"):
        # psycopg is synchronous; even bounded connection I/O must not occupy
        # the event loop serving native runs and other owners' reads.
        try:
            await asyncio.wait_for(asyncio.to_thread(self.record, claimed, key, reason_code,
                source=source), timeout=1.5)
        except Exception:
            return

    def catalog(self, owner, after=None):
        self.service.auth.require(owner, "read")
        if after and not self.store.sql("""SELECT schedule_id FROM af_schedule_bindings
                WHERE owner_id=:owner AND schedule_id=:after""", owner=owner, after=after):
            raise HTTPException(404, "Diagnostic schedule cursor not found")
        rows = self.store.sql("""SELECT schedule_id,created_at FROM af_schedule_bindings
            WHERE owner_id=:owner AND schedule_id>:after ORDER BY schedule_id LIMIT :limit""",
            owner=owner, after=after or "", limit=PAGE_SIZE + 1)
        return {"schema": 1, "ownerId": owner,
            "items": [{"id": row["schedule_id"], "createdAt": row["created_at"]} for row in rows[:PAGE_SIZE]],
            "nextCursor": rows[PAGE_SIZE - 1]["schedule_id"] if len(rows) > PAGE_SIZE else None}

    def page(self, owner, schedule_id, after=None):
        self.service.auth.require(owner, "read")
        self.service._history_binding(schedule_id, owner)
        cutoff = self._cutoff()
        if after and not self.store.sql("""SELECT id FROM af_schedule_diagnostics
                WHERE id=:after AND owner_id=:owner AND schedule_id=:schedule AND observed_at>=:cutoff""",
                after=after, owner=owner, schedule=schedule_id, cutoff=cutoff):
            raise HTTPException(404, "Diagnostic cursor not found")
        rows = self.store.sql("""SELECT * FROM af_schedule_diagnostics
            WHERE owner_id=:owner AND schedule_id=:schedule AND observed_at>=:cutoff
            AND id>:after ORDER BY id LIMIT :limit""", owner=owner, schedule=schedule_id,
            cutoff=cutoff, after=after or "", limit=PAGE_SIZE + 1)
        return {"schema": 1, "ownerId": owner, "scheduleId": schedule_id,
            "items": [{"id": row["id"], "ownerId": owner, "scheduleId": schedule_id,
                "reasonCode": row["reason_code"] if row["reason_code"] in REASONS else "CHECK_UNAVAILABLE",
                "source": row["source"] if row["source"] in {"native", "manual"} else "native",
                "observedAt": row["observed_at"]} for row in rows[:PAGE_SIZE]],
            "nextCursor": rows[PAGE_SIZE - 1]["id"] if len(rows) > PAGE_SIZE else None,
            "retention": {"days": RETENTION_DAYS, "maxRecords": MAX_RECORDS},
            "coverage": "retained-rejections-only", "snapshot": False}
