"""One explicitly authorized continuation, with an immutable inherited budget.

The budget path is derived from the stopped source campaign, not a new campaign
name. Reopening never grants dispatch ownership or releases a reservation.
"""
from __future__ import annotations

from pathlib import Path
import time
from uuid import UUID, uuid4

from .go_live import GoLiveCampaign, _require

EXACT_MODEL = "deepseek-flash"
SAFE_RETURNED_MODELS = frozenset({EXACT_MODEL, "deepseek-v4-flash", "deepseek-v4.1-flash", "gpt-6-luna"})


class GoSingleSmokeCampaign(GoLiveCampaign):
    @classmethod
    def create(cls, path, *, history_path, campaign_id, owner_id, confirmation_id,
               expires_at, use_balance_disabled=True, auto_reload_disabled=True):
        history_path = Path(history_path).absolute()
        # One persistent cross-campaign budget per source; changing the new
        # campaign ID or evidence directory cannot mint a fresh allowance.
        _require(Path(path).absolute() == Path(str(history_path) + ".budget.sqlite"), "BUDGET_PATH")
        history = GoLiveCampaign(history_path).inspect(include_diagnostics=False)
        _require(history["ownerId"] == owner_id, "OWNER_MISMATCH")
        _require(history["status"] == "STOPPED" and history["stopCode"] == "UNKNOWN"
                 and history["requestCount"] == 1, "HISTORY_CONTRACT")
        ticket = history["tickets"][0]
        _require(ticket["model"] == "deepseek-v4-flash" and ticket["state"] == "UNKNOWN"
                 and ticket["purpose"] == "smoke" and ticket["actual_model"] is None
                 and all(ticket[k] is None for k in ("input_tokens", "output_tokens", "total_tokens")),
                 "HISTORY_CONTRACT")
        try:
            valid_id = str(UUID(ticket["id"])) == ticket["id"]
        except (ValueError, TypeError, AttributeError):
            valid_id = False
        _require(valid_id, "HISTORY_CONTRACT")
        base = GoLiveCampaign.create(path, campaign_id=campaign_id, owner_id=owner_id,
            confirmation_id=confirmation_id, expires_at=expires_at,
            use_balance_disabled=use_balance_disabled, auto_reload_disabled=auto_reload_disabled)
        # If the process dies before this commit, the file cannot be recreated
        # and has no valid continuation metadata. It grants no dispatch.
        with base._transaction() as db:
            db.execute("CREATE TABLE continuation(source_ticket TEXT PRIMARY KEY, source_campaign TEXT NOT NULL, step_cap INTEGER NOT NULL CHECK(step_cap=2))")
            db.execute("INSERT INTO continuation VALUES(?,?,2)", (ticket["id"], history["campaignId"]))
            db.execute("INSERT INTO tickets(id,ordinal,model,purpose,session,state,output_cap,created,error_code) VALUES(?,1,'deepseek-v4-flash','smoke','historical-no-replay','UNKNOWN',?,?, 'UNKNOWN')",
                       (ticket["id"], ticket["output_cap"], ticket["created"]))
            db.execute("CREATE TRIGGER no_ticket_delete BEFORE DELETE ON tickets BEGIN SELECT RAISE(ABORT,'Budget retained'); END")
            db.execute("CREATE TRIGGER no_history_update BEFORE UPDATE ON tickets WHEN OLD.id=(SELECT source_ticket FROM continuation) BEGIN SELECT RAISE(ABORT,'History immutable'); END")
            db.execute("CREATE TRIGGER no_continuation_update BEFORE UPDATE ON continuation BEGIN SELECT RAISE(ABORT,'Budget immutable'); END")
            db.execute("CREATE TRIGGER no_continuation_delete BEFORE DELETE ON continuation BEGIN SELECT RAISE(ABORT,'Budget immutable'); END")
        result = cls(path)
        result._may_dispatch = True
        return result

    def __init__(self, path):
        super().__init__(path)
        self._may_dispatch = False
        with self._transaction(write=False) as db:
            rows = db.execute("SELECT * FROM continuation").fetchall()
            _require(len(rows) == 1 and rows[0]["step_cap"] == 2, "BUDGET_INVALID")
            self._historical_ticket = rows[0]["source_ticket"]
            _require(db.execute("SELECT COUNT(*) FROM tickets WHERE id=? AND state='UNKNOWN' AND model='deepseek-v4-flash'", (self._historical_ticket,)).fetchone()[0] == 1, "BUDGET_INVALID")

    @staticmethod
    def _active(db, model, *, owned_inflight=None):
        row = db.execute("SELECT * FROM campaign").fetchone()
        _require(row is not None and row["status"] == "ACTIVE", "CAMPAIGN_STOPPED")
        _require(time.time() < row["expires"], "CAMPAIGN_EXPIRED")
        _require(model == EXACT_MODEL, "MODEL_ORDER")
        pending = db.execute("SELECT id,state FROM tickets WHERE id NOT IN (SELECT source_ticket FROM continuation) AND state!='SETTLED'").fetchall()
        allowed = owned_inflight is not None and len(pending) == 1 and pending[0]["state"] == "INFLIGHT" and pending[0]["id"] in owned_inflight
        _require(not pending or allowed, "DISPATCH_UNCERTAIN")
        return row

    def authorize(self, session_id, model_id, *, purpose="smoke", owner_id):
        _require(self._may_dispatch and purpose == "smoke", "INSPECTION_ONLY")
        return super().authorize(session_id, model_id, purpose=purpose, owner_id=owner_id)

    def begin(self, session_id, model_id, body):
        _require(self._may_dispatch and self.journal is not None, "INSPECTION_ONLY")
        with self._transaction() as db:
            self._active(db, model_id)
            _require(db.execute("SELECT 1 FROM sessions WHERE session=? AND model=? AND purpose='smoke'", (session_id, model_id)).fetchone() is not None, "SESSION_UNAUTHORIZED")
            # Counts include the inherited UNKNOWN and every later reservation,
            # regardless of outcome. Admission is serialized across processes.
            _require(db.execute("SELECT COUNT(*) FROM tickets").fetchone()[0] < 2, "REQUEST_CAP")
            cap = self._body(body, model_id, "smoke", 0)
            _require(cap <= 64, "OUTPUT_BOUND")
            ticket = str(uuid4())
            db.execute("INSERT INTO tickets(id,ordinal,model,purpose,session,state,output_cap,created) VALUES(?,2,?,'smoke',?,'INFLIGHT',?,?)", (ticket, model_id, session_id, cap, time.time()))
            self._owned_tickets.add(ticket)
        try:
            self.record_event(ticket, "PREPARED")
        except BaseException:
            self.stop("UNKNOWN")
            raise
        return ticket

    def verify_ticket(self, ticket, session_id, model_id):
        _require(self._may_dispatch and ticket in self._owned_tickets, "TICKET_NOT_OWNED")
        with self._transaction(write=False) as db:
            self._active(db, model_id, owned_inflight=self._owned_tickets)
            row = db.execute("SELECT * FROM tickets WHERE id=?", (ticket,)).fetchone()
            _require(row is not None and row["session"] == session_id and row["model"] == model_id and row["state"] == "INFLIGHT" and ticket != self._historical_ticket, "TICKET_UNKNOWN")

    def finish(self, ticket, usage=None, actual_model=None, error_code=None):
        _require(ticket in self._owned_tickets and ticket != self._historical_ticket, "TICKET_NOT_OWNED")
        super().finish(ticket, usage=usage, actual_model=actual_model, error_code=error_code)
        # A returned concrete ID is an observation, never an alias/price mapping.
        safe_model = actual_model if isinstance(actual_model, str) and actual_model in SAFE_RETURNED_MODELS else None
        with self._transaction() as db:
            db.execute("UPDATE tickets SET actual_model=? WHERE id=?", (safe_model, ticket))
            db.execute("UPDATE campaign SET status=CASE WHEN status='ACTIVE' THEN 'DONE' ELSE status END")

    def stop(self, code):
        safe = code if code in {"AUTH", "QUOTA", "USAGE_UNKNOWN", "MODEL_MISMATCH", "TRANSPORT", "PROTOCOL", "CANCELLED", "UNKNOWN", "EXPIRED", "INPUT_BOUND", "USAGE_BOUND"} else "UNKNOWN"
        with self._transaction() as db:
            db.execute("UPDATE tickets SET state='UNKNOWN',error_code=? WHERE state='INFLIGHT' AND id!=?", (safe, self._historical_ticket))
            db.execute("UPDATE campaign SET status='STOPPED',stop_code=? WHERE status!='STOPPED'", (safe,))

    def inspect(self, *, include_diagnostics=True):
        with self._transaction(write=False) as db:
            row = dict(db.execute("SELECT * FROM campaign").fetchone())
            tickets = [dict(t) for t in db.execute("SELECT * FROM tickets ORDER BY ordinal")]
        return {"campaignId": row["id"], "status": row["status"], "stopCode": row["stop_code"],
                "requestCount": len(tickets), "modelCounts": {model: sum(t["model"] == model for t in tickets) for model in sorted(SAFE_RETURNED_MODELS)},
                "budgetCounts": {"deepseek": len(tickets), "gpt-6-luna": 0},
                "perModelRequestCap": 3, "authorizedStepCap": 2,
                "pricingStatus": "UNKNOWN", "monetaryUpperBound": None,
                "reservedInputTokenUpperBoundPerAttempt": 32768, "reservedOutputTokenUpperBound": sum(t["output_cap"] for t in tickets),
                "tickets": [{**t, "imported": t["id"] == self._historical_ticket} for t in tickets],
                **({"diagnostics": self.journal.inspect()} if include_diagnostics and self.journal is not None else {})}
