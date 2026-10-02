"""Durable Factory event pages; no claim to be an Agno/native stream cursor.

The append-only source is af_events. A per-task UUID survives API restart; signed
cursors bind its owner and position. PostgreSQL ID allocation is not commit
ordering: late commits below a cursor are explicitly detected and require replay.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
import hmac
import json
import re
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import text

from .store import canonical, digest

CURSOR_SCHEMA = 1
CURSOR_FIELDS = {"schema", "streamId", "taskId", "ownerId", "after", "afterSequence"}
MAX_ROW_ID = 2**63 - 1
RESPONSE_RESERVE = 4096


class EventReplay:
    def __init__(self, store: Any, auth: Any, *, signing_key: str | bytes,
                 max_page_bytes: int = 1048576, max_event_bytes: int = 262144):
        key = signing_key.encode() if isinstance(signing_key, str) else signing_key
        if not isinstance(key, bytes) or len(key) < 32:
            raise ValueError("Event replay requires a trusted configured signing key of at least 32 bytes")
        if type(max_page_bytes) is not int or not 8192 <= max_page_bytes <= 8388608:
            raise ValueError("Event page byte budget must be 8 KiB through 8 MiB")
        if type(max_event_bytes) is not int or not 512 <= max_event_bytes <= min(1048576, max_page_bytes - RESPONSE_RESERVE):
            raise ValueError("Inline event budget must fit inside the bounded page payload")
        if store.engine.dialect.name not in {"postgresql", "sqlite"}:
            raise ValueError("Event replay supports PostgreSQL and explicitly owned portable SQLite fixtures")
        self.store, self.auth = store, auth
        self.max_page_bytes, self.max_event_bytes = max_page_bytes, max_event_bytes
        self._cursor_key = hmac.digest(key, b"agent-factory:event-replay:cursors:v1", "sha256")
        self._initialized = False

    @contextmanager
    def _read(self):
        shared = getattr(self.store, "_connection", None)
        existing = shared.get() if shared is not None else None
        if existing is not None:
            yield existing
        else:
            with self.store.engine.connect() as conn:
                yield conn

    @contextmanager
    def _write(self):
        shared = getattr(self.store, "_connection", None)
        existing = shared.get() if shared is not None else None
        if existing is not None:
            yield existing, False
            return
        with self.store.engine.begin() as conn:
            token = shared.set(conn) if shared is not None else None
            try:
                yield conn, True
            finally:
                if shared is not None and token is not None:
                    shared.reset(token)

    @staticmethod
    def _identifier(value):
        if not isinstance(value, str) or not value or len(value.encode()) > 256:
            raise HTTPException(400, "A bounded verified task and owner identity is required")

    def _scope(self, owner, task_id):
        self._identifier(owner)
        self._identifier(task_id)
        self.auth.require(owner, "read")
        task = self.store.task(task_id, owner)
        self._identifier(task["id"])
        return task

    def _stream(self, owner, task):
        initialized_owned = False
        with self._write() as (conn, owned):
            if not self._initialized:
                if self.store.engine.dialect.name == "postgresql":
                    # Concurrent API instances serialize lazy DDL; stream creation
                    # itself remains a database CAS and needs no global event lock.
                    conn.execute(text("SELECT pg_advisory_xact_lock(hashtext('af_event_stream_schema_v1'))"))
                conn.execute(text("CREATE TABLE IF NOT EXISTS af_event_streams ("
                    "task_id TEXT PRIMARY KEY REFERENCES af_tasks(id), owner_id TEXT NOT NULL, "
                    "stream_id TEXT NOT NULL UNIQUE, schema_version INTEGER NOT NULL)"))
                initialized_owned = owned
            current = self.store.task(task["id"], owner)
            self.auth.require(owner, "read")
            conn.execute(text("INSERT INTO af_event_streams(task_id,owner_id,stream_id,schema_version) "
                              "VALUES(:task,:owner,:stream,:schema) ON CONFLICT(task_id) DO NOTHING"),
                         {"task": current["id"], "owner": owner, "stream": str(uuid4()), "schema": CURSOR_SCHEMA})
            row = conn.execute(text("SELECT * FROM af_event_streams WHERE task_id=:task"), {"task": current["id"]}).mappings().one()
            if row["owner_id"] != owner or row["schema_version"] != CURSOR_SCHEMA:
                raise HTTPException(409, "Event stream identity or schema differs from the scoped task")
            try:
                stream = str(UUID(row["stream_id"]))
            except (ValueError, TypeError, AttributeError) as error:
                raise HTTPException(409, "Persisted event stream identity is invalid") from error
        if initialized_owned:
            self._initialized = True
        return stream

    @staticmethod
    def _encode(value):
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")

    @classmethod
    def _unbase64(cls, value):
        if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
            raise ValueError("Invalid cursor encoding")
        raw = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
        if cls._encode(raw) != value:
            raise ValueError("Noncanonical cursor encoding")
        return raw

    def _sign(self, *, stream, task, owner, after, sequence):
        body = canonical({"schema": CURSOR_SCHEMA, "streamId": stream, "taskId": task, "ownerId": owner,
                          "after": after, "afterSequence": sequence}).encode()
        return "er1." + self._encode(body) + "." + self._encode(hmac.digest(self._cursor_key, body, "sha256"))

    def _position(self, cursor, *, stream, task, owner):
        if cursor is None:
            return 0, 0
        try:
            if not isinstance(cursor, str) or not 1 <= len(cursor) <= 4096:
                raise ValueError("Invalid cursor length")
            prefix, payload, signature = cursor.split(".")
            if prefix != "er1":
                raise ValueError("Unsupported cursor schema")
            raw, claimed = self._unbase64(payload), self._unbase64(signature)
            if not hmac.compare_digest(hmac.digest(self._cursor_key, raw, "sha256"), claimed):
                raise ValueError("Invalid cursor signature")
            value = json.loads(raw)
            if not isinstance(value, dict) or set(value) != CURSOR_FIELDS or type(value["schema"]) is not int or value["schema"] != CURSOR_SCHEMA:
                raise ValueError("Invalid cursor schema")
            for field in ("after", "afterSequence"):
                if type(value[field]) is not int or not 0 <= value[field] <= MAX_ROW_ID:
                    raise ValueError("Invalid cursor position")
            if value["afterSequence"] > value["after"]:
                raise ValueError("Invalid cursor sequence")
        except (ValueError, TypeError, UnicodeDecodeError) as error:
            raise HTTPException(400, "INVALID_EVENT_CURSOR: cursor cannot be verified") from error
        if value["streamId"] != stream or value["taskId"] != task or value["ownerId"] != owner:
            raise HTTPException(404, "Scoped event cursor not found")
        return value["after"], value["afterSequence"]

    def _snapshot(self, task, after, limit):
        postgres = self.store.engine.dialect.name == "postgresql"
        # Materialize IDs only, not historical JSON bodies. The byte window limits
        # selected inline data before driver decoding, and Python checks the exact
        # normalized UTF-8 payload before returning it.
        size = "octet_length" if postgres else "length"
        cast = "TEXT" if postgres else "BLOB"
        expression = (f"{size}(CAST(e.data AS {cast})) + 6 * ("
                      f"{size}(CAST(e.message AS {cast})) + {size}(CAST(e.type AS {cast})) + "
                      f"{size}(CAST(e.created_at AS {cast}))) + 512")
        statement = text(f"""
            WITH event_ids AS MATERIALIZED (
                SELECT id, row_number() OVER (ORDER BY id) AS sequence
                FROM af_events WHERE task_id=:task
            ), bounds AS (
                SELECT COALESCE(MAX(id),0) AS high_watermark, COUNT(*) AS total,
                    COALESCE(MAX(CASE WHEN id<=:after THEN sequence ELSE 0 END),0) AS prefix_sequence,
                    COALESCE(MAX(CASE WHEN id=:after THEN 1 ELSE 0 END),0) AS has_position
                FROM event_ids
            ), candidate AS (
                SELECT id,sequence FROM event_ids WHERE id>:after ORDER BY id LIMIT :scan_limit
            ), sized AS (
                SELECT e.*,c.sequence,{expression} AS payload_size
                FROM candidate c JOIN af_events e ON e.id=c.id
            ), sized_page AS (
                SELECT sized.*,SUM(payload_size) OVER (ORDER BY id) AS cumulative_size FROM sized
            )
            SELECT b.*,p.id,p.sequence,p.payload_size,
                CASE WHEN p.payload_size<=:event_bytes AND p.cumulative_size<=:query_bytes THEN p.type ELSE NULL END AS type,
                CASE WHEN p.payload_size<=:event_bytes AND p.cumulative_size<=:query_bytes THEN p.message ELSE NULL END AS message,
                CASE WHEN p.payload_size<=:event_bytes AND p.cumulative_size<=:query_bytes THEN p.data ELSE NULL END AS data,
                CASE WHEN p.payload_size<=:event_bytes AND p.cumulative_size<=:query_bytes THEN p.created_at ELSE NULL END AS created_at,
                CASE WHEN p.payload_size<=:event_bytes AND p.cumulative_size<=:query_bytes THEN 1 ELSE 0 END AS inline
            FROM bounds b LEFT JOIN sized_page p ON TRUE ORDER BY p.id
        """)
        with self._read() as conn:
            rows = list(conn.execute(statement, {"task": task, "after": after, "scan_limit": limit + 1,
                "event_bytes": self.max_event_bytes, "query_bytes": self.max_page_bytes - RESPONSE_RESERVE}).mappings())
        return rows

    def page(self, owner: str, task_id: str, *, cursor: str | None = None, limit: int = 100):
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise HTTPException(400, "Event page limit must be one through one thousand")
        task = self._scope(owner, task_id)
        stream = self._stream(owner, task)
        after, expected_sequence = self._position(cursor, stream=stream, task=task["id"], owner=owner)
        rows = self._snapshot(task["id"], after, limit)
        bounds = rows[0]
        if bounds["prefix_sequence"] != expected_sequence or after and not bounds["has_position"]:
            raise HTTPException(409, "EVENT_PREFIX_CHANGED: earlier commits changed the cursor prefix; replay from the start and deduplicate event IDs")
        events, used = [], 2
        for row in rows:
            if row["id"] is None or len(events) == limit:
                break
            if not row["inline"]:
                if not events and row["payload_size"] > self.max_event_bytes:
                    raise HTTPException(413, "EVENT_INLINE_LIMIT: event exceeds the bounded inline payload; operator reconciliation is required")
                break
            data = row["data"]
            if self.store.engine.dialect.name == "sqlite":
                data = json.loads(data) if isinstance(data, str) else data
            event = {"id": row["id"], "jobId": task["id"], "sequence": row["sequence"], "type": row["type"],
                     "message": row["message"], "data": data, "createdAt": row["created_at"]}
            # A late lower-ID commit can change projected sequence numbers. Hash
            # intrinsic persisted evidence so replay can still deduplicate by ID
            # and content; the page hash below includes its derived sequences.
            event["payloadSha256"] = digest({key: value for key, value in event.items() if key != "sequence"})
            try:
                encoded = json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
            except (TypeError, ValueError) as error:
                raise HTTPException(409, "Persisted event has an invalid JSON payload") from error
            if len(encoded) > self.max_event_bytes:
                if not events:
                    raise HTTPException(413, "EVENT_INLINE_LIMIT: event exceeds the bounded inline payload; operator reconciliation is required")
                break
            if used + len(encoded) + bool(events) > self.max_page_bytes - RESPONSE_RESERVE:
                break
            used += len(encoded) + bool(events)
            events.append(event)
        end = events[-1]["id"] if events else after
        sequence = events[-1]["sequence"] if events else expected_sequence
        self._scope(owner, task["id"])
        result = {"events": events, "nextCursor": self._sign(stream=stream, task=task["id"], owner=owner, after=end, sequence=sequence),
                  "highWatermark": bounds["high_watermark"], "highWatermarkSequence": bounds["total"],
                  "hasMore": bounds["total"] > sequence, "streamId": stream, "schema": CURSOR_SCHEMA,
                  "startSequence": events[0]["sequence"] if events else None,
                  "endSequence": events[-1]["sequence"] if events else None,
                  "afterSequence": expected_sequence, "payloadSha256": digest(events), "payloadBytes": used,
                  "source": "factory-af_events", "nativeCursor": False}
        if not events and result["hasMore"]:
            raise HTTPException(413, "EVENT_PAGE_LIMIT: first pending event cannot fit the bounded page")
        if len(canonical(result).encode()) > self.max_page_bytes:
            raise HTTPException(413, "EVENT_PAGE_LIMIT: normalized event page exceeds its configured byte budget")
        return result


def event_replay_router(auth, service):
    """Root mounts this only for local tasks; remote relay uses the scoped client."""
    router = APIRouter(prefix="/api/factory")

    @router.get("/jobs/{task_id}/events")
    def events(task_id: str, request: Request, cursor: str | None = Query(default=None, max_length=4096),
               limit: int = Query(default=100, ge=1, le=1000)):
        return service.page(auth.user(request)["id"], task_id, cursor=cursor, limit=limit)

    return router
