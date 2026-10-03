"""One final authorized dispatch in the original three-request budget file.

No new campaign, reset, replay, credentials or networking. Prior UNKNOWN tickets
and the previous stop facts are retained permanently. Reopened objects inspect.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import time
from uuid import uuid4

from .go_live import GoLiveCampaign, GoLiveGateError, _require
from .go_single_smoke import EXACT_MODEL, GoSingleSmokeCampaign

_IDENTITY = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")


class GoFinalSmokeCampaign(GoSingleSmokeCampaign):
    @classmethod
    def create(cls, *args, **kwargs):
        raise GoLiveGateError("FINAL_EXISTING_BUDGET_REQUIRED")

    @classmethod
    def authorize_final(cls, path, *, owner_id, confirmation_id):
        _require(all(type(value) is str and _IDENTITY.fullmatch(value)
                     for value in (owner_id, confirmation_id)), "INVALID_IDENTITY")
        path = Path(path).absolute()
        suffix = ".budget.sqlite"
        _require(str(path).endswith(suffix), "BUDGET_PATH")
        # Verify that this is the existing continuation file derived from its
        # original source campaign. Neither file may be created by this API.
        source = GoLiveCampaign(str(path)[:-len(suffix)]).inspect(include_diagnostics=False)
        base = GoSingleSmokeCampaign(path)
        with base._transaction() as db:
            exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='final_authorization'").fetchone()
            _require(exists is None, "FINAL_ALREADY_AUTHORIZED")
            campaign = db.execute("SELECT * FROM campaign").fetchone()
            continuation = db.execute("SELECT * FROM continuation").fetchone()
            _require(source["ownerId"] == owner_id == campaign["owner"], "OWNER_MISMATCH")
            _require(source["campaignId"] == continuation["source_campaign"], "HISTORY_CONTRACT")
            _require(campaign["status"] == "STOPPED", "HISTORY_CONTRACT")
            prior = [dict(row) for row in db.execute("SELECT * FROM tickets ORDER BY ordinal")]
            _require(len(prior) == 2 and [row["ordinal"] for row in prior] == [1, 2]
                     and [row["model"] for row in prior] == ["deepseek-v4-flash", EXACT_MODEL]
                     and all(row["state"] == "UNKNOWN" and row["purpose"] == "smoke" for row in prior)
                     and prior[0]["id"] == continuation["source_ticket"], "HISTORY_CONTRACT")
            sessions = db.execute("SELECT session FROM sessions WHERE model=? AND purpose='smoke'", (EXACT_MODEL,)).fetchall()
            _require(len(sessions) == 1 and sessions[0]["session"] == prior[1]["session"], "SESSION_UNAUTHORIZED")
            now = time.time()
            expires = now + 3600
            db.execute("""CREATE TABLE final_authorization(
                singleton INTEGER PRIMARY KEY CHECK(singleton=1), owner TEXT NOT NULL,
                confirmation TEXT NOT NULL, authorized REAL NOT NULL, expires REAL NOT NULL,
                previous_status TEXT NOT NULL, previous_stop_code TEXT,
                previous_expires REAL NOT NULL, previous_ticket_facts TEXT NOT NULL,
                session TEXT NOT NULL, request_cap INTEGER NOT NULL CHECK(request_cap=3))""")
            db.execute("INSERT INTO final_authorization VALUES(1,?,?,?,?,?,?,?,?,?,3)",
                (owner_id, confirmation_id, now, expires, campaign["status"], campaign["stop_code"],
                 campaign["expires"], json.dumps(prior, sort_keys=True), sessions[0]["session"]))
            # Individual execute statements preserve the surrounding atomic
            # transaction; executescript would implicitly commit it early.
            db.execute("CREATE TRIGGER no_final_authorization_update BEFORE UPDATE ON final_authorization BEGIN SELECT RAISE(ABORT,'Final authorization immutable'); END")
            db.execute("CREATE TRIGGER no_final_authorization_delete BEFORE DELETE ON final_authorization BEGIN SELECT RAISE(ABORT,'Final authorization immutable'); END")
            db.execute("CREATE TRIGGER no_prior_two_update BEFORE UPDATE ON tickets WHEN OLD.ordinal<3 BEGIN SELECT RAISE(ABORT,'Historical attempts immutable'); END")
            db.execute("CREATE TRIGGER no_prior_two_delete BEFORE DELETE ON tickets WHEN OLD.ordinal<3 BEGIN SELECT RAISE(ABORT,'Historical attempts immutable'); END")
            db.execute("CREATE TRIGGER final_ticket_cap BEFORE INSERT ON tickets WHEN NEW.ordinal!=3 OR (SELECT COUNT(*) FROM tickets)>=3 BEGIN SELECT RAISE(ABORT,'Final request cap'); END")
            db.execute("UPDATE campaign SET status='ACTIVE',stop_code=NULL,expires=?", (expires,))
        # If the process stops after COMMIT but before this return, reopening
        # deliberately cannot recover the ephemeral permission to dispatch.
        result = cls(path)
        result._may_dispatch = True
        return result

    def __init__(self, path):
        super().__init__(path)
        with self._transaction(write=False) as db:
            row = db.execute("SELECT * FROM final_authorization WHERE singleton=1").fetchone()
            _require(row is not None and row["request_cap"] == 3, "FINAL_AUTHORIZATION_INVALID")
            previous = [dict(value) for value in db.execute("SELECT * FROM tickets WHERE ordinal<3 ORDER BY ordinal")]
            _require(json.dumps(previous, sort_keys=True) == row["previous_ticket_facts"], "HISTORY_CONTRACT")
            self.final_session = row["session"]

    @staticmethod
    def _active(db, model, *, owned_inflight=None):
        row = db.execute("SELECT * FROM campaign").fetchone()
        _require(row is not None and row["status"] == "ACTIVE", "CAMPAIGN_STOPPED")
        authorization = db.execute("SELECT * FROM final_authorization WHERE singleton=1").fetchone()
        _require(authorization is not None and authorization["owner"] == row["owner"], "FINAL_AUTHORIZATION_INVALID")
        _require(time.time() < min(row["expires"], authorization["expires"]), "CAMPAIGN_EXPIRED")
        _require(model == EXACT_MODEL, "MODEL_ORDER")
        pending = db.execute("SELECT id,state FROM tickets WHERE ordinal>=3 AND state!='SETTLED'").fetchall()
        allowed = (owned_inflight is not None and len(pending) == 1 and pending[0]["state"] == "INFLIGHT"
                   and pending[0]["id"] in owned_inflight)
        _require(not pending or allowed, "DISPATCH_UNCERTAIN")
        return row

    def authorize(self, session_id, model_id, *, purpose="smoke", owner_id):
        _require(session_id == self.final_session, "SESSION_CHANGED")
        return super().authorize(session_id, model_id, purpose=purpose, owner_id=owner_id)

    def begin(self, session_id, model_id, body):
        _require(self._may_dispatch and self.journal is not None, "INSPECTION_ONLY")
        _require(session_id == self.final_session, "SESSION_CHANGED")
        with self._transaction() as db:
            self._active(db, model_id)
            _require(db.execute("SELECT 1 FROM sessions WHERE session=? AND model=? AND purpose='smoke'",
                                (session_id, model_id)).fetchone() is not None, "SESSION_UNAUTHORIZED")
            _require(db.execute("SELECT COUNT(*) FROM tickets").fetchone()[0] == 2, "REQUEST_CAP")
            try:
                cap = self._body(body, model_id, "smoke", 0)
            except (TypeError, ValueError, AttributeError, KeyError):
                raise GoLiveGateError("BODY_INVALID") from None
            _require(cap <= 64, "OUTPUT_BOUND")
            ticket = str(uuid4())
            db.execute("INSERT INTO tickets(id,ordinal,model,purpose,session,state,output_cap,created) VALUES(?,3,?,'smoke',?,'INFLIGHT',?,?)",
                       (ticket, model_id, session_id, cap, time.time()))
            self._owned_tickets.add(ticket)
        try:
            self.record_event(ticket, "PREPARED")
        except BaseException:
            self.stop("UNKNOWN")
            raise
        return ticket

    def inspect(self, *, include_diagnostics=True):
        facts = super().inspect(include_diagnostics=include_diagnostics)
        with self._transaction(write=False) as db:
            authority = dict(db.execute("SELECT * FROM final_authorization WHERE singleton=1").fetchone())
        facts["authorizedStepCap"] = 3
        facts["tickets"] = [{**ticket, "imported": ticket["ordinal"] < 3} for ticket in facts["tickets"]]
        facts["finalAuthorization"] = {"confirmationId": authority["confirmation"], "authorizedAt": authority["authorized"],
            "expiresAt": authority["expires"], "previousStatus": authority["previous_status"],
            "previousStopCode": authority["previous_stop_code"], "previousExpiresAt": authority["previous_expires"],
            "requestCap": authority["request_cap"], "sessionId": authority["session"]}
        return facts
