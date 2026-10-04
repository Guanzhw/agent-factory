"""Owner-only discovery and historical recovery of immutable compositions.

Read authority never accepts a proposal, renews a review, restores a withdrawn
material or admits execution. Cursor boundaries are keyset windows, not snapshots.
"""
from __future__ import annotations

import base64
from copy import deepcopy
from datetime import datetime
import json
import re
from typing import Any, cast

from fastapi import HTTPException
from sqlalchemy import and_, or_, select

from .store import canonical, digest

_UUID = re.compile(r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}\Z")
_STATES = {"pending", "revised", "rejected", "accepted"}


def _require(value, status=409):
    if not value:
        raise HTTPException(status, "COMPOSITION_INBOX_INVALID")


class CompositionInboxService:
    def __init__(self, composition):
        self.composition = composition
        self.store, self.auth = composition.store, composition.auth
        self.table = composition.proposals

    @staticmethod
    def _key(proposal):
        identifier, created = proposal.get("id"), proposal.get("createdAt")
        _require(type(identifier) is str and _UUID.fullmatch(identifier))
        _require(type(created) is str and len(created) <= 40)
        try:
            parsed = datetime.fromisoformat(created)
            offset = parsed.utcoffset()
            _require(parsed.tzinfo is not None and offset is not None and offset.total_seconds() == 0)
        except (ValueError, TypeError, AttributeError):
            raise HTTPException(409, "COMPOSITION_INBOX_INVALID") from None
        return [created, identifier]

    def _cursor(self, owner, value, conn):
        _require(type(value) is str and 1 <= len(value) <= 2048 and re.fullmatch(r"[A-Za-z0-9_-]+", value), 400)
        try:
            body = json.loads(base64.urlsafe_b64decode(value + '=' * (-len(value) % 4)))
            _require(type(body) is dict and set(body) == {"schema", "scope", "after", "ceiling"}, 400)
            body = cast(dict[str, Any], body)
            _require(type(body["schema"]) is int and body["schema"] == 1 and body["scope"] == digest({"owner": owner}), 400)
            for field in ("after", "ceiling"):
                key = body[field]
                _require(type(key) is list and len(key) == 2 and all(type(v) is str for v in key), 400)
                row = self.composition._row(conn, owner, key[1])
                _require(self._key(row["body"]) == key, 400)
            _require(body["after"] <= body["ceiling"], 400)
            return body
        except (ValueError, TypeError, KeyError, UnicodeError, HTTPException):
            # No distinction between another owner's anchor and an unknown one.
            raise HTTPException(400, "COMPOSITION_INBOX_CURSOR_INVALID") from None

    @staticmethod
    def _encode(owner, after, ceiling):
        raw = canonical({"schema": 1, "scope": digest({"owner": owner}), "after": after, "ceiling": ceiling})
        return base64.urlsafe_b64encode(raw.encode()).decode().rstrip('=')

    def _summary(self, row):
        value = self.composition._projection(row)
        self._key(value)
        _require(value["state"] in _STATES and (value["state"] == "accepted") == (value["planId"] is not None))
        candidate = value["candidate"]
        goal = candidate["normalizedGoal"]
        _require(type(goal) is str and 2 <= len(goal) <= 2000)
        return {"id": value["id"], "ownerId": value["ownerId"], "createdAt": value["createdAt"],
            "state": value["state"], "fingerprint": value["fingerprint"], "parentId": value["parentId"],
            "planId": value["planId"], "applicationRef": deepcopy(candidate["applicationRef"]),
            "mode": candidate["mode"], "goalPreview": goal[:160], "preflightStatus": candidate["status"]}

    def list(self, owner, *, after=None, limit: Any = 20):
        self.auth.require(owner, "read")
        _require(type(limit) is int and 1 <= limit <= 50, 400)
        created = self.table.c.body["createdAt"].as_string()
        with self.composition.db.read() as conn:
            ceiling = None
            boundary = self._cursor(owner, after, conn) if after is not None else None
            if boundary:
                ceiling = boundary["ceiling"]
            else:
                top = conn.execute(select(self.table.c.id).where(self.table.c.owner_id == owner)
                    .order_by(created.desc(), self.table.c.id.desc()).limit(1)).scalar()
                if top is not None:
                    ceiling = self._key(self.composition._row(conn, owner, top)["body"])
            items, next_cursor = [], None
            if ceiling is not None:
                query = select(self.table.c.id).where(self.table.c.owner_id == owner,
                    or_(created < ceiling[0], and_(created == ceiling[0], self.table.c.id <= ceiling[1])))
                if boundary:
                    start = boundary["after"]
                    query = query.where(or_(created > start[0], and_(created == start[0], self.table.c.id > start[1])))
                ids = conn.execute(query.order_by(created, self.table.c.id).limit(limit + 1)).scalars().all()
                items = [self._summary(self.composition._row(conn, owner, identifier)) for identifier in ids[:limit]]
                if len(ids) > limit:
                    next_cursor = self._encode(owner, self._key(items[-1]), ceiling)
        self.auth.require(owner, "read")
        return {"schema": 1, "ownerId": owner, "items": items, "nextCursor": next_cursor, "snapshot": False}

    def read(self, owner, proposal_id):
        proposal = self.composition.inspect(owner, proposal_id)
        plan = None
        if proposal["state"] == "accepted":
            _require(type(proposal.get("planId")) is str)
            plan = self.store.plan(proposal["planId"], owner)
            expected = {**deepcopy(proposal["candidate"]), "id": proposal["planId"],
                "createdAt": plan.get("createdAt"), "compositionProposalId": proposal["id"]}
            expected["fingerprint"] = digest({key: value for key, value in expected.items()
                                             if key not in {"id", "createdAt", "fingerprint"}})
            _require(plan == expected and plan.get("ownerId") == owner)
        else:
            _require(proposal["state"] in _STATES and proposal.get("planId") is None)
        self.auth.require(owner, "read")
        return {"proposal": deepcopy(proposal), "plan": deepcopy(plan), "historical": True, "executionAuthorized": False}
