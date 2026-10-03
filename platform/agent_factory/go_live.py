"""Explicit, durable six-request development campaign; no credential discovery.

The operator creates one private SQLite file after account confirmation. Unknown
dispatches consume their slot permanently; no API resets or resumes a campaign.
Only bounded metadata is retained, never prompts, responses, headers or keys.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import stat
import time
from uuid import uuid4

MODELS = ("deepseek-v4-flash", "gpt-6-luna")
_IDENTITY = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_STOP_CODES = frozenset({"AUTH", "QUOTA", "USAGE_UNKNOWN", "MODEL_MISMATCH", "TRANSPORT",
                         "PROTOCOL", "CANCELLED", "UNKNOWN", "EXPIRED", "INPUT_BOUND", "USAGE_BOUND"})


class GoLiveGateError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _require(condition, code):
    if not condition:
        raise GoLiveGateError(code)


class GoLiveCampaign:
    @classmethod
    def create(cls, path, *, campaign_id, owner_id, confirmation_id,
               use_balance_disabled=True, auto_reload_disabled=True, expires_at):
        _require(all(isinstance(value, str) and _IDENTITY.fullmatch(value)
                     for value in (campaign_id, owner_id, confirmation_id)), "INVALID_IDENTITY")
        _require(use_balance_disabled is True and auto_reload_disabled is True, "BILLING_UNCONFIRMED")
        now = time.time()
        _require(type(expires_at) in {int, float} and math.isfinite(expires_at)
                 and now < expires_at <= now + 86400, "INVALID_EXPIRY")
        path = Path(path).absolute()
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0), 0o600)
            os.close(fd)
        except OSError:
            raise GoLiveGateError("CAMPAIGN_CREATE_DENIED") from None
        try:
            with sqlite3.connect(path) as db:
                db.executescript("""
                    PRAGMA journal_mode=DELETE;
                    CREATE TABLE campaign(id TEXT PRIMARY KEY, owner TEXT NOT NULL, confirmation TEXT NOT NULL,
                        created REAL NOT NULL, expires REAL NOT NULL, status TEXT NOT NULL,
                        current_model INTEGER NOT NULL, stop_code TEXT, balance_disabled INTEGER NOT NULL,
                        auto_reload_disabled INTEGER NOT NULL);
                    CREATE TABLE sessions(model TEXT NOT NULL, purpose TEXT NOT NULL, session TEXT NOT NULL UNIQUE,
                        PRIMARY KEY(model,purpose));
                    CREATE TABLE tickets(id TEXT PRIMARY KEY, ordinal INTEGER NOT NULL UNIQUE,
                        model TEXT NOT NULL, purpose TEXT NOT NULL, session TEXT NOT NULL,
                        state TEXT NOT NULL, output_cap INTEGER NOT NULL, created REAL NOT NULL,
                        input_tokens INTEGER, output_tokens INTEGER, total_tokens INTEGER, error_code TEXT, actual_model TEXT);
                    CREATE TABLE completions(model TEXT PRIMARY KEY, artifact_sha256 TEXT NOT NULL);
                """)
                db.execute("INSERT INTO campaign VALUES(?,?,?,?,?,'ACTIVE',0,NULL,1,1)",
                           (campaign_id, owner_id, confirmation_id, now, expires_at))
            return cls(path)
        except (OSError, sqlite3.Error):
            # A failed create is never reused or overwritten. The operator must
            # inspect that file; automatic retries cannot reset spent authority.
            raise GoLiveGateError("CAMPAIGN_STORAGE") from None

    def __init__(self, path):
        self.path = Path(path).absolute()
        self._owned_tickets = set()
        self._identity = self._file_identity()
        with self._transaction(write=False) as db:
            row = db.execute("SELECT * FROM campaign").fetchall()
            _require(len(row) == 1 and row[0]["balance_disabled"] == 1
                     and row[0]["auto_reload_disabled"] == 1, "CAMPAIGN_INVALID")

    def _file_identity(self):
        try:
            info = self.path.lstat()
            _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                     and stat.S_IMODE(info.st_mode) == 0o600, "CAMPAIGN_FILE_UNSAFE")
            return info.st_dev, info.st_ino
        except OSError:
            raise GoLiveGateError("CAMPAIGN_STORAGE") from None

    @contextmanager
    def _transaction(self, *, write=True):
        db = None
        try:
            _require(self._file_identity() == self._identity, "CAMPAIGN_FILE_CHANGED")
            # mode=rw refuses implicit creation if the original file disappears.
            db = sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True, timeout=5, isolation_level=None)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            _require(self._file_identity() == self._identity, "CAMPAIGN_FILE_CHANGED")
            yield db
            db.commit()
        except (sqlite3.Error, OSError):
            raise GoLiveGateError("CAMPAIGN_STORAGE") from None
        finally:
            if db is not None:
                db.close()

    @staticmethod
    def _active(db, model, *, owned_inflight=None):
        row = db.execute("SELECT * FROM campaign").fetchone()
        _require(row is not None and row["status"] == "ACTIVE", "CAMPAIGN_STOPPED")
        _require(time.time() < row["expires"], "CAMPAIGN_EXPIRED")
        _require(model in MODELS and MODELS[row["current_model"]] == model, "MODEL_ORDER")
        pending = db.execute("SELECT id,state FROM tickets WHERE state!='SETTLED'").fetchall()
        allowed_current = (owned_inflight is not None and len(pending) == 1
                           and pending[0]["state"] == "INFLIGHT" and pending[0]["id"] in owned_inflight)
        _require(not pending or allowed_current, "DISPATCH_UNCERTAIN")
        return row

    @staticmethod
    def _stage(db, model, purpose):
        _require(purpose in {"smoke", "product"}, "INVALID_PURPOSE")
        smoke = db.execute("SELECT COUNT(*) FROM tickets WHERE model=? AND purpose='smoke' AND state='SETTLED'", (model,)).fetchone()[0]
        _require((purpose == "smoke" and smoke == 0) or (purpose == "product" and smoke == 1), "PURPOSE_ORDER")

    def authorize(self, session_id, model_id, *, purpose="smoke", owner_id):
        _require(isinstance(session_id, str) and _IDENTITY.fullmatch(session_id), "INVALID_SESSION")
        with self._transaction() as db:
            campaign = self._active(db, model_id)
            _require(owner_id == campaign["owner"], "OWNER_MISMATCH")
            self._stage(db, model_id, purpose)
            previous = db.execute("SELECT session FROM sessions WHERE model=? AND purpose=?", (model_id, purpose)).fetchone()
            if previous:
                _require(previous["session"] == session_id, "SESSION_CHANGED")
            else:
                _require(not db.execute("SELECT 1 FROM sessions WHERE session=?", (session_id,)).fetchone(), "SESSION_CHANGED")
                db.execute("INSERT INTO sessions VALUES(?,?,?)", (model_id, purpose, session_id))

    def check(self, session_id, model_id):
        with self._transaction(write=False) as db:
            self._active(db, model_id)
            row = db.execute("SELECT purpose FROM sessions WHERE session=? AND model=?", (session_id, model_id)).fetchone()
            _require(row is not None, "SESSION_UNAUTHORIZED")
            self._stage(db, model_id, row["purpose"])

    def preflight(self, model_id, owner_id):
        with self._transaction(write=False) as db:
            # The lifecycle observer rechecks authority during the owner's
            # current HTTP operation. It does not reserve another dispatch.
            row = self._active(db, model_id, owned_inflight=self._owned_tickets)
            _require(row["owner"] == owner_id, "OWNER_MISMATCH")

    def verify_ticket(self, ticket, session_id, model_id):
        _require(ticket in self._owned_tickets, "TICKET_NOT_OWNED")
        with self._transaction(write=False) as db:
            campaign = db.execute("SELECT * FROM campaign").fetchone()
            _require(campaign["status"] == "ACTIVE", "CAMPAIGN_STOPPED")
            _require(time.time() < campaign["expires"], "CAMPAIGN_EXPIRED")
            _require(model_id in MODELS and MODELS[campaign["current_model"]] == model_id, "MODEL_ORDER")
            rows = db.execute("SELECT * FROM tickets WHERE state!='SETTLED'").fetchall()
            _require(len(rows) == 1 and rows[0]["id"] == ticket and rows[0]["session"] == session_id
                     and rows[0]["model"] == model_id and rows[0]["state"] == "INFLIGHT", "TICKET_UNKNOWN")
            _require(db.execute("SELECT 1 FROM sessions WHERE session=? AND model=? AND purpose=?",
                                (session_id, model_id, rows[0]["purpose"])).fetchone() is not None, "SESSION_UNAUTHORIZED")

    @staticmethod
    def _body(body, model, purpose, product_count):
        _require(isinstance(body, dict), "BODY_INVALID")
        try:
            encoded = json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
        except (TypeError, ValueError, UnicodeError):
            raise GoLiveGateError("BODY_INVALID") from None
        _require(len(encoded) <= 8192, "INPUT_BOUND")
        responses = model == "gpt-6-luna"
        message_key, cap_key = ("input", "max_output_tokens") if responses else ("messages", "max_tokens")
        allowed = {"model", "stream", message_key, cap_key, "tools", "tool_choice", "parallel_tool_calls",
                   "store" if responses else "stream_options"}
        _require(not set(body) - allowed and body.get("model") == model and body.get("stream") is True, "BODY_INVALID")
        cap = body.get(cap_key)
        _require(type(cap) is int and 1 <= cap <= 512, "OUTPUT_BOUND")
        _require(body.get("store") is False if responses else body.get("stream_options") == {"include_usage": True}, "BODY_INVALID")
        messages = body.get(message_key)
        _require(isinstance(messages, list) and 1 <= len(messages) <= 32, "BODY_INVALID")
        for message in messages:
            _require(isinstance(message, dict), "BODY_INVALID")
            if responses and message.get("type") in {"function_call", "function_call_output"}:
                _require(purpose == "product" and product_count == 1, "TOOL_SCOPE")
                if message["type"] == "function_call":
                    _require(set(message) <= {"type", "call_id", "name", "arguments"}
                             and message.get("name") == "checksum" and isinstance(message.get("arguments"), str), "TOOL_SCOPE")
                else:
                    _require(set(message) <= {"type", "call_id", "output"} and isinstance(message.get("output"), str), "TOOL_SCOPE")
                _require(isinstance(message.get("call_id"), str) and bool(message["call_id"]), "TOOL_SCOPE")
            else:
                _require(set(message) <= {"role", "content", "tool_calls", "tool_call_id"}
                         and message.get("role") in {"system", "user", "assistant", "tool"}
                         and (isinstance(message.get("content"), str) or message.get("content") is None), "BODY_INVALID")
                if message.get("role") == "tool" or message.get("tool_calls"):
                    _require(purpose == "product" and product_count == 1, "TOOL_SCOPE")
                for call in message.get("tool_calls", []):
                    _require(isinstance(call, dict) and set(call) <= {"id", "type", "function"}
                             and call.get("type") == "function" and isinstance(call.get("function"), dict)
                             and set(call["function"]) <= {"name", "arguments"}
                             and call["function"].get("name") == "checksum"
                             and isinstance(call["function"].get("arguments"), str), "TOOL_SCOPE")
        tools = body.get("tools", [])
        _require(isinstance(tools, list) and len(tools) <= (0 if purpose == "smoke" else 1), "TOOL_SCOPE")
        _require(body.get("parallel_tool_calls", False) is False, "TOOL_SCOPE")
        if purpose == "smoke":
            _require(body.get("tool_choice", "none") == "none", "TOOL_SCOPE")
        else:
            _require(len(tools) <= 1 and body.get("tool_choice", "auto") in (
                {"auto", "required"} if product_count == 0 else {"auto", "none"}), "TOOL_SCOPE")
        for tool in tools:
            _require(isinstance(tool, dict) and tool.get("type") == "function", "TOOL_SCOPE")
            _require(responses or set(tool) <= {"type", "function"}, "TOOL_SCOPE")
            function = tool if responses else tool.get("function")
            if not isinstance(function, dict):
                raise GoLiveGateError("TOOL_SCOPE")
            _require(function.get("name") == "checksum"
                     and set(function) <= {"type", "name", "description", "parameters", "strict"}, "TOOL_SCOPE")
            parameters = function.get("parameters")
            _require(isinstance(parameters, dict) and parameters.get("type") == "object"
                     and set(parameters) <= {"type", "properties", "required", "additionalProperties", "description", "title"}
                     and parameters.get("additionalProperties", False) is False
                     and isinstance(parameters.get("properties"), dict)
                     and set(parameters["properties"]) == {"text"}
                     and isinstance(parameters["properties"]["text"], dict)
                     and set(parameters["properties"]["text"]) <= {"type", "description", "title"}
                     and parameters["properties"]["text"].get("type") == "string"
                     and parameters.get("required") == ["text"], "TOOL_SCOPE")
        return cap

    def begin(self, session_id, model_id, body):
        with self._transaction() as db:
            self._active(db, model_id)
            binding = db.execute("SELECT purpose FROM sessions WHERE session=? AND model=?", (session_id, model_id)).fetchone()
            _require(binding is not None, "SESSION_UNAUTHORIZED")
            purpose = binding["purpose"]
            self._stage(db, model_id, purpose)
            total = db.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]
            per_model = db.execute("SELECT COUNT(*) FROM tickets WHERE model=?", (model_id,)).fetchone()[0]
            product_count = db.execute("SELECT COUNT(*) FROM tickets WHERE model=? AND purpose='product'", (model_id,)).fetchone()[0]
            _require(total < 6 and per_model < 3 and (purpose != "product" or product_count < 2), "REQUEST_CAP")
            try:
                cap = self._body(body, model_id, purpose, product_count)
            except (TypeError, ValueError, AttributeError, KeyError):
                raise GoLiveGateError("BODY_INVALID") from None
            ticket = str(uuid4())
            db.execute("INSERT INTO tickets(id,ordinal,model,purpose,session,state,output_cap,created) VALUES(?,?,?,?,?,'INFLIGHT',?,?)",
                       (ticket, total + 1, model_id, purpose, session_id, cap, time.time()))
            # Publish local ownership before the committed row becomes visible
            # to an observer on another thread. A failed COMMIT grants nothing:
            # both verification and admission still require the durable row.
            self._owned_tickets.add(ticket)
        return ticket

    def finish(self, ticket, usage=None, actual_model=None, error_code=None):
        usage = usage if isinstance(usage, dict) else {}
        with self._transaction() as db:
            row = db.execute("SELECT * FROM tickets WHERE id=?", (ticket,)).fetchone()
            _require(row is not None, "TICKET_UNKNOWN")
            _require(row["state"] in {"INFLIGHT", "UNKNOWN"}, "TICKET_FINISHED")
            valid = (set(usage) == {"input_tokens", "output_tokens", "total_tokens"}
                     and all(type(value) is int and 0 <= value <= 2**63 - 1 for value in usage.values())
                     and usage["input_tokens"] + usage["output_tokens"] == usage["total_tokens"])
            exceeds = valid and (usage["input_tokens"] > 32768 or usage["output_tokens"] > row["output_cap"])
            db.execute("UPDATE tickets SET actual_model=? WHERE id=?", (row["model"] if actual_model == row["model"] else None, ticket))
            if valid:
                db.execute("UPDATE tickets SET state='SETTLED',input_tokens=?,output_tokens=?,total_tokens=? WHERE id=?",
                           (usage["input_tokens"], usage["output_tokens"], usage["total_tokens"], ticket))
            if error_code is not None or actual_model != row["model"] or not valid or exceeds:
                code = (error_code if isinstance(error_code, str) and error_code in _STOP_CODES else "UNKNOWN") if error_code is not None else (
                    "MODEL_MISMATCH" if actual_model != row["model"] else "USAGE_UNKNOWN" if not valid else "USAGE_BOUND")
                db.execute("UPDATE tickets SET state=?,error_code=? WHERE id=?", ("SETTLED" if valid else "UNKNOWN", code, ticket))
                db.execute("UPDATE campaign SET status='STOPPED',stop_code=?", (code,))

    def stop(self, code):
        safe = code if isinstance(code, str) and code in _STOP_CODES else "UNKNOWN"
        with self._transaction() as db:
            db.execute("UPDATE campaign SET status='STOPPED',stop_code=? WHERE status='ACTIVE'", (safe,))
            db.execute("UPDATE tickets SET state='UNKNOWN',error_code=? WHERE state='INFLIGHT'", (safe,))

    def complete_model(self, model, artifact_sha256):
        _require(isinstance(artifact_sha256, str) and _HASH.fullmatch(artifact_sha256), "ARTIFACT_INVALID")
        with self._transaction() as db:
            campaign = self._active(db, model)
            rows = db.execute("SELECT purpose,state FROM tickets WHERE model=? ORDER BY ordinal", (model,)).fetchall()
            _require([(row["purpose"], row["state"]) for row in rows]
                     == [("smoke", "SETTLED"), ("product", "SETTLED"), ("product", "SETTLED")], "MODEL_INCOMPLETE")
            db.execute("INSERT INTO completions VALUES(?,?)", (model, artifact_sha256))
            index = campaign["current_model"] + 1
            db.execute("UPDATE campaign SET current_model=?,status=?", (index, "DONE" if index == len(MODELS) else "ACTIVE"))

    def inspect(self):
        with self._transaction(write=False) as db:
            row = dict(db.execute("SELECT * FROM campaign").fetchone())
            tickets = [dict(value) for value in db.execute("SELECT * FROM tickets ORDER BY ordinal")]
            return {"campaignId": row["id"], "ownerId": row["owner"], "confirmationId": row["confirmation"],
                    "createdAt": row["created"], "useBalanceDisabled": row["balance_disabled"] == 1,
                    "autoReloadDisabled": row["auto_reload_disabled"] == 1,
                    "expiresAt": row["expires"], "status": row["status"], "stopCode": row["stop_code"],
                    "currentModel": MODELS[row["current_model"]] if row["current_model"] < len(MODELS) else None,
                    "requestCount": len(tickets), "modelCounts": {model: sum(t["model"] == model for t in tickets) for model in MODELS},
                    "tickets": tickets, "completions": [dict(value) for value in db.execute("SELECT * FROM completions")]}
