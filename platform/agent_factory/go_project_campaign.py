"""Persistent subscription project admission; no credentials or networking.

Migration supersedes artificial request caps, never historical outcomes. Request
reservations remain serialized and immutable once terminal. Stops need an
explicit reviewed policy action; billing/auth/quota stops cannot be cleared here.
"""
from __future__ import annotations

import json
import time
from uuid import uuid4

from .go_live import GoLiveCampaign, GoLiveGateError, _IDENTITY, _STOP_CODES, _require
from .go_single_smoke import SAFE_RETURNED_MODELS

PROJECT_MODELS = ("deepseek-flash", "gpt-6-luna")


class GoProjectCampaign(GoLiveCampaign):
    @classmethod
    def create(cls, *args, **kwargs):
        raise GoLiveGateError("PROJECT_EXISTING_LINEAGE_REQUIRED")

    @classmethod
    def migrate(cls, path, *, owner_id, confirmation_id, max_output_tokens=4096):
        _require(all(type(v) is str and _IDENTITY.fullmatch(v) for v in (owner_id, confirmation_id)), "INVALID_IDENTITY")
        _require(type(max_output_tokens) is int and 1 <= max_output_tokens <= 4096, "OUTPUT_BOUND")
        base = GoLiveCampaign(path)
        with base._transaction() as db:
            exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='project_policy'").fetchone()
            if exists:
                policy = db.execute("SELECT owner,max_output FROM project_policy").fetchone()
                _require(policy["owner"] == owner_id, "OWNER_MISMATCH")
                _require(policy["max_output"] == max_output_tokens, "PROJECT_POLICY_CHANGED")
                return cls(path)
            campaign = db.execute("SELECT * FROM campaign").fetchone()
            _require(campaign["owner"] == owner_id, "OWNER_MISMATCH")
            authority = db.execute("SELECT * FROM final_authorization WHERE singleton=1").fetchone()
            prior = [dict(r) for r in db.execute("SELECT * FROM tickets ORDER BY ordinal")]
            _require(authority is not None and authority["owner"] == owner_id and len(prior) == 3
                     and [r["ordinal"] for r in prior] == [1, 2, 3]
                     and [r["model"] for r in prior] == ["deepseek-v4-flash", "deepseek-flash", "deepseek-flash"]
                     and all(r["state"] == "UNKNOWN" for r in prior), "HISTORY_CONTRACT")
            _require(campaign["status"] == "STOPPED" and campaign["stop_code"] in {"UNKNOWN", "PROTOCOL", "TRANSPORT"}, "STOP_REQUIRES_REVIEW")
            db.execute("CREATE TABLE project_policy(singleton INTEGER PRIMARY KEY CHECK(singleton=1),owner TEXT NOT NULL,confirmation TEXT NOT NULL,created REAL NOT NULL,max_output INTEGER NOT NULL,prior_facts TEXT NOT NULL,prior_status TEXT NOT NULL,prior_stop TEXT,prior_expires REAL NOT NULL)")
            db.execute("INSERT INTO project_policy VALUES(1,?,?,?,?,?,?,?,?)", (owner_id, confirmation_id, time.time(), max_output_tokens, json.dumps(prior, sort_keys=True), campaign["status"], campaign["stop_code"], campaign["expires"]))
            db.execute("CREATE TABLE project_sessions(session TEXT PRIMARY KEY,model TEXT NOT NULL,purpose TEXT NOT NULL)")
            db.execute("INSERT INTO project_sessions(session,model,purpose) SELECT session,model,purpose FROM sessions WHERE model IN ('deepseek-flash','gpt-6-luna')")
            db.execute("CREATE TABLE project_policy_events(seq INTEGER PRIMARY KEY AUTOINCREMENT,created REAL NOT NULL,action TEXT NOT NULL,previous_stop TEXT)")
            for table in ("project_policy", "project_policy_events"):
                for operation in ("UPDATE", "DELETE"):
                    db.execute(f"CREATE TRIGGER immutable_{table}_{operation.lower()} BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT,'Policy history immutable'); END")
            db.execute("CREATE TRIGGER immutable_project_history BEFORE UPDATE ON tickets WHEN OLD.ordinal<=3 BEGIN SELECT RAISE(ABORT,'Historical attempts immutable'); END")
            db.execute("CREATE TRIGGER immutable_project_terminal BEFORE UPDATE ON tickets WHEN OLD.ordinal>3 AND OLD.state!='INFLIGHT' BEGIN SELECT RAISE(ABORT,'Terminal attempts immutable'); END")
            db.execute("DROP TRIGGER final_ticket_cap")
            db.execute("INSERT INTO project_policy_events(created,action,previous_stop) VALUES(?,'SUBSCRIPTION_POLICY_MIGRATED',?)", (time.time(), campaign["stop_code"]))
            db.execute("UPDATE campaign SET status='ACTIVE',stop_code=NULL")
        return cls(path)

    def __init__(self, path):
        super().__init__(path)
        with self._transaction(write=False) as db:
            policy = db.execute("SELECT * FROM project_policy WHERE singleton=1").fetchone()
            campaign = db.execute("SELECT owner FROM campaign").fetchone()
            _require(policy is not None and policy["owner"] == campaign["owner"], "PROJECT_POLICY_INVALID")
            prior = [dict(r) for r in db.execute("SELECT * FROM tickets WHERE ordinal<=3 ORDER BY ordinal")]
            _require(json.dumps(prior, sort_keys=True) == policy["prior_facts"], "HISTORY_CONTRACT")

    @staticmethod
    def _active(db, model, *, owned_inflight=None):
        row = db.execute("SELECT * FROM campaign").fetchone()
        _require(row is not None and row["status"] == "ACTIVE", "CAMPAIGN_STOPPED")
        _require(model in PROJECT_MODELS, "MODEL_ORDER")
        pending = db.execute("SELECT id FROM tickets WHERE state='INFLIGHT'").fetchall()
        _require(not pending or (owned_inflight is not None and len(pending) == 1 and pending[0]["id"] in owned_inflight), "DISPATCH_UNCERTAIN")
        return row

    @staticmethod
    def _stage(db, model, purpose):
        _require(purpose in {"smoke", "product"}, "INVALID_PURPOSE")
        if purpose == "product":
            _require(db.execute("SELECT 1 FROM tickets WHERE ordinal>3 AND model=? AND purpose='smoke' AND state='SETTLED' AND error_code IS NULL", (model,)).fetchone() is not None, "PURPOSE_ORDER")

    def authorize(self, session_id, model_id, *, purpose="smoke", owner_id):
        _require(type(session_id) is str and _IDENTITY.fullmatch(session_id), "INVALID_SESSION")
        with self._transaction() as db:
            campaign = self._active(db, model_id)
            _require(campaign["owner"] == owner_id, "OWNER_MISMATCH")
            self._stage(db, model_id, purpose)
            previous = db.execute("SELECT model,purpose FROM project_sessions WHERE session=?", (session_id,)).fetchone()
            if previous is not None:
                _require(previous["model"] == model_id and previous["purpose"] == purpose, "SESSION_CHANGED")
            else:
                db.execute("INSERT INTO project_sessions VALUES(?,?,?)", (session_id, model_id, purpose))

    def check(self, session_id, model_id):
        with self._transaction(write=False) as db:
            self._active(db, model_id)
            row = db.execute("SELECT purpose FROM project_sessions WHERE session=? AND model=?", (session_id, model_id)).fetchone()
            _require(row is not None, "SESSION_UNAUTHORIZED")
            self._stage(db, model_id, row["purpose"])

    def begin(self, session_id, model_id, body):
        _require(self.journal is not None, "DIAGNOSTICS_UNAVAILABLE")
        with self._transaction() as db:
            self._active(db, model_id)
            binding = db.execute("SELECT purpose FROM project_sessions WHERE model=? AND session=?", (model_id, session_id)).fetchone()
            _require(binding is not None, "SESSION_UNAUTHORIZED")
            purpose = binding["purpose"]
            self._stage(db, model_id, purpose)
            _require(type(body) is dict, "BODY_INVALID")
            key = "max_output_tokens" if model_id == "gpt-6-luna" else "max_tokens"
            cap = body.get(key)
            limit = db.execute("SELECT max_output FROM project_policy").fetchone()[0]
            _require(type(cap) is int and 1 <= cap <= limit, "OUTPUT_BOUND")
            try:
                encoded = json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
            except (TypeError, ValueError, UnicodeError):
                raise GoLiveGateError("BODY_INVALID") from None
            _require(len(encoded) <= 8192, "INPUT_BOUND")
            normalized = dict(body)
            normalized[key] = min(cap, 512)
            messages = body.get("input" if model_id == "gpt-6-luna" else "messages", [])
            tool_result = isinstance(messages, list) and any(isinstance(m, dict) and (m.get("role") == "tool" or m.get("type") == "function_call_output") for m in messages)
            try:
                self._body(normalized, model_id, purpose, int(tool_result))
            except (TypeError, ValueError, AttributeError, KeyError):
                raise GoLiveGateError("BODY_INVALID") from None
            ticket = str(uuid4())
            ordinal = db.execute("SELECT COALESCE(MAX(ordinal),0)+1 FROM tickets").fetchone()[0]
            db.execute("INSERT INTO tickets(id,ordinal,model,purpose,session,state,output_cap,created) VALUES(?,?,?,?,?,'INFLIGHT',?,?)", (ticket, ordinal, model_id, purpose, session_id, cap, time.time()))
            self._owned_tickets.add(ticket)
        try:
            self.record_event(ticket, "PREPARED")
        except BaseException:
            self.stop("UNKNOWN")
            raise GoLiveGateError("DIAGNOSTICS_UNAVAILABLE") from None
        return ticket

    def verify_ticket(self, ticket, session_id, model_id):
        _require(ticket in self._owned_tickets, "TICKET_NOT_OWNED")
        with self._transaction(write=False) as db:
            self._active(db, model_id, owned_inflight=self._owned_tickets)
            row = db.execute("SELECT * FROM tickets WHERE id=?", (ticket,)).fetchone()
            _require(row is not None and row["state"] == "INFLIGHT" and row["session"] == session_id and row["model"] == model_id, "TICKET_UNKNOWN")

    def finish(self, ticket, usage=None, actual_model=None, error_code=None):
        _require(ticket in self._owned_tickets, "TICKET_NOT_OWNED")
        usage = usage if isinstance(usage, dict) else {}
        with self._transaction() as db:
            row = db.execute("SELECT * FROM tickets WHERE id=?", (ticket,)).fetchone()
            _require(row is not None and row["state"] == "INFLIGHT", "TICKET_FINISHED")
            valid = (set(usage) == {"input_tokens", "output_tokens", "total_tokens"}
                     and all(type(v) is int and 0 <= v <= 2**63-1 for v in usage.values())
                     and usage["input_tokens"] + usage["output_tokens"] == usage["total_tokens"])
            exceeds = valid and (usage["input_tokens"] > 32768 or usage["output_tokens"] > row["output_cap"])
            code = None
            if error_code is not None:
                code = error_code if isinstance(error_code, str) and error_code in (_STOP_CODES | {"BILLING"}) else "UNKNOWN"
            elif actual_model != row["model"]:
                code = "MODEL_MISMATCH"
            elif not valid:
                code = "USAGE_UNKNOWN"
            elif exceeds:
                code = "USAGE_BOUND"
            safe_model = actual_model if isinstance(actual_model, str) and actual_model in SAFE_RETURNED_MODELS else None
            db.execute("UPDATE tickets SET state=?,input_tokens=?,output_tokens=?,total_tokens=?,actual_model=?,error_code=? WHERE id=?",
                       ("SETTLED" if valid else "UNKNOWN", usage.get("input_tokens") if valid else None,
                        usage.get("output_tokens") if valid else None, usage.get("total_tokens") if valid else None,
                        safe_model, code, ticket))
            if code is not None:
                db.execute("UPDATE campaign SET status='STOPPED',stop_code=? WHERE status='ACTIVE'", (code,))

    def stop(self, code):
        safe = code if isinstance(code, str) and code in (_STOP_CODES | {"BILLING"}) else "UNKNOWN"
        with self._transaction() as db:
            db.execute("UPDATE campaign SET status='STOPPED',stop_code=? WHERE status='ACTIVE'", (safe,))
            db.execute("UPDATE tickets SET state='UNKNOWN',error_code=? WHERE state='INFLIGHT'", (safe,))

    def acknowledge_stop(self, *, reason, owner_id):
        _require(reason in {"PROTOCOL_FIX_REVIEWED", "TRANSPORT_FIX_REVIEWED", "DIAGNOSTICS_REVIEWED"}, "INVALID_POLICY_ACTION")
        with self._transaction() as db:
            row = db.execute("SELECT * FROM campaign").fetchone()
            _require(row["owner"] == owner_id, "OWNER_MISMATCH")
            _require(row["status"] == "STOPPED" and row["stop_code"] in {"PROTOCOL", "TRANSPORT", "UNKNOWN", "USAGE_UNKNOWN"}, "STOP_REQUIRES_REVIEW")
            _require(db.execute("SELECT 1 FROM tickets WHERE state='INFLIGHT'").fetchone() is None, "DISPATCH_UNCERTAIN")
            db.execute("INSERT INTO project_policy_events(created,action,previous_stop) VALUES(?,?,?)", (time.time(), reason, row["stop_code"]))
            db.execute("UPDATE campaign SET status='ACTIVE',stop_code=NULL")

    def inspect(self, *, include_diagnostics=True):
        facts = super().inspect(include_diagnostics=include_diagnostics)
        with self._transaction(write=False) as db:
            policy = dict(db.execute("SELECT * FROM project_policy").fetchone())
            events = [dict(r) for r in db.execute("SELECT * FROM project_policy_events ORDER BY seq")]
        tickets = facts["tickets"]
        facts.update(currentModel=None, perModelRequestCap=None,
            modelCounts={m: sum(t["model"] == m for t in tickets) for m in sorted(SAFE_RETURNED_MODELS)},
            budgetCounts={"deepseek": sum(t["model"].startswith("deepseek-") for t in tickets), "gpt-6-luna": sum(t["model"] == "gpt-6-luna" for t in tickets)},
            pricingStatus="UNKNOWN", monetaryUpperBound=None,
            reservedInputTokenUpperBoundPerAttempt=32768,
            reservedOutputTokenUpperBound=sum(t["output_cap"] for t in tickets),
            projectPolicy={"confirmationId": policy["confirmation"], "createdAt": policy["created"], "maxOutputTokens": policy["max_output"], "historicalCount": 3, "previousExpiresAt": policy["prior_expires"], "previousStatus": policy["prior_status"], "previousStopCode": policy["prior_stop"], "events": events})
        return facts
