"""Synthetic, loopback-only remote-runtime fixture. Never deploy this server.

Its SQLite document persists reference-model state across fixture restarts. This
is NOT the selected Agno/Postgres backend, authentication, process isolation, or
proof of actual resource reclamation. Test control endpoints are intentional.
"""
from __future__ import annotations

import copy
import hashlib
import json
import socket
import sqlite3
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

from protocol import Scope

ACTORS = {
    "fixture-alice-a": Scope("tenant-1", "alice", "task-a"),
    "fixture-alice-b": Scope("tenant-1", "alice", "task-b"),
    "fixture-bob": Scope("tenant-1", "bob", "task-c"),
    "fixture-other-tenant": Scope("tenant-2", "alice", "task-a"),
}
CONTROL_TOKEN = "fixture-control-only"
DIMENSIONS = ("slots", "cpu_millis", "memory_mib")
ROOT_LIMIT = dict(slots=3, cpu_millis=2000, memory_mib=2048)
USER_LIMIT = dict(slots=4, cpu_millis=3000, memory_mib=3072)
HOST_LIMIT = dict(slots=6, cpu_millis=4000, memory_mib=4096)
DEFAULT_RESERVATION = dict(slots=1, cpu_millis=500, memory_mib=512)
MAX_CHILDREN, MAX_DEPTH = 3, 2


class Rejected(Exception):
    def __init__(self, status, code):
        self.status, self.code = status, code


def need(condition, code="invalid_request", status=400):
    if not condition:
        raise Rejected(status, code)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def fresh_id(prefix):
    return prefix + "_" + uuid.uuid4().hex


class Store:
    def __init__(self, path, mutant=None):
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS fixture (id INTEGER PRIMARY KEY, state TEXT)")
        row = self.db.execute("SELECT state FROM fixture WHERE id=1").fetchone()
        self.state = json.loads(row[0]) if row else dict(
            sessions={}, runs={}, operations={}, revoked=[], effects=0,
            environment_creations=0, drop_next=None)
        self.mutant = mutant
        self.save()

    def save(self):
        self.db.execute("INSERT OR REPLACE INTO fixture VALUES (1, ?)", (canonical(self.state),))
        self.db.commit()

    def close(self):
        self.db.close()

    def visible(self, collection, ident, scope):
        obj = self.state[collection].get(ident)
        need(obj is not None and obj["scope"] == scope, "not_found", 404)
        return obj

    def publish(self, run):
        run["sequence"] += 1
        state = {k: copy.deepcopy(v) for k, v in run.items() if k != "events"}
        event = dict(scope=run["scope"], run_id=run["run_id"],
                     sequence=run["sequence"], state=state)
        run["events"].append(event)

    def view(self, run):
        return dict(scope=run["scope"], run_id=run["run_id"],
                    sequence=run["sequence"],
                    state={k: copy.deepcopy(v) for k, v in run.items() if k != "events"})

    def active(self):
        return [r for r in self.state["runs"].values() if r["cleanup_state"] != "verified"]

    def total(self, runs):
        return {d: sum(r["reservation"][d] for r in runs) for d in DIMENSIONS}

    def reserve(self, scope, reservation, parent):
        need(isinstance(reservation, dict) and set(reservation) == set(DIMENSIONS))
        need(all(type(reservation[d]) is int and reservation[d] > 0 for d in DIMENSIONS))
        active = self.active()
        user = [r for r in active if all(r["scope"][k] == scope[k]
                                       for k in ("tenant_id", "user_id"))]
        groups = [(active, HOST_LIMIT), (user, USER_LIMIT)]
        if parent:
            need(parent["execution_state"] == "running"
                 and parent["cleanup_state"] == "pending" and not parent["lease_expired"],
                 "parent_not_running", 409)
            need(parent["depth"] < MAX_DEPTH, "depth_limit", 429)
            root = parent["root_run_id"]
            descendants = [r for r in self.state["runs"].values()
                           if r["root_run_id"] == root and r["parent_run_id"] is not None]
            need(len(descendants) < MAX_CHILDREN, "child_limit", 429)
            groups.append(([r for r in active if r["root_run_id"] == root], ROOT_LIMIT))
        else:
            groups.append(([], ROOT_LIMIT))
        for group, limit in groups:
            total = self.total(group)
            need(all(total[d] + reservation[d] <= limit[d] for d in DIMENSIONS),
                 "resource_budget_exceeded", 429)

    def handle(self, method, path, body, token, key):
        with self.lock:
            before = copy.deepcopy(self.state)
            try:
                result = self.dispatch(method, path, body, token, key)
                matches = self.state["drop_next"] == path and method == "POST"
                drop = self.state.get("response_fault", "disconnect") if matches else None
                if drop:
                    self.state["drop_next"] = None
                    self.state.pop("response_fault", None)
                self.save()  # Commit the operation BEFORE deliberately losing the ACK.
                return result, drop
            except Exception:
                self.state = before
                raise

    def dispatch(self, method, path, body, token, key):
        parsed = urlsplit(path)
        parts = [unquote(p) for p in parsed.path.split("/") if p]
        if parts == ["_test", "control"]:
            need(token == CONTROL_TOKEN, "forbidden", 403)
            need(method == "POST")
            return self.control(body)
        need(token in ACTORS, "unauthenticated", 401)
        scope = ACTORS[token].as_dict()
        need(canonical(scope) not in self.state["revoked"], "revoked", 403)
        need(parts and parts[0] == "v1", "not_found", 404)
        if method == "GET" and parts[1:] == ["health"]:
            return dict(contract="factory-runtime-test/v1", fixture=True)
        if method == "GET" and len(parts) == 3 and parts[1] == "operations":
            op = self.state["operations"].get(canonical([scope, parts[2]]))
            need(op is not None, "operation_unresolved", 404)
            return dict(state="accepted", result=op["result"])
        if method == "GET" and parts[1:] == ["resources"]:
            runs = [r for r in self.active() if all(r["scope"][k] == scope[k]
                                                  for k in ("tenant_id", "user_id"))]
            return dict(scope=scope, reserved=self.total(runs), limit=USER_LIMIT)
        if method == "GET" and len(parts) >= 4 and parts[1] == "runs":
            run = self.visible("runs", parts[2], scope)
            if parts[3:] == ["snapshot"]:
                return self.view(run)
            if parts[3:] == ["events"]:
                try:
                    after = int(parse_qs(parsed.query).get("after", ["0"])[0])
                except ValueError:
                    raise Rejected(400, "invalid_cursor") from None
                need(after >= 0, "invalid_cursor")
                floor = run.get("event_floor", 0)
                if after < floor or after > run["sequence"]:
                    return dict(snapshot_required=True, events=[])
                return dict(snapshot_required=False, events=[e for e in run["events"]
                                                            if e["sequence"] > after])
            if parts[3:] == ["artifacts", "report"]:
                content = "Synthetic research fixture; not a research finding.\n"
                return dict(scope=scope, run_id=run["run_id"], artifact_id="report",
                            size_bytes=len(content.encode()), content=content,
                            sha256=hashlib.sha256(content.encode()).hexdigest())
            raise Rejected(404, "not_found")
        need(method == "POST", "not_found", 404)
        need(isinstance(key, str) and 1 <= len(key) <= 128, "idempotency_key_required")
        op_key = canonical([scope, key])
        fingerprint = canonical([method, path, body])
        if op_key in self.state["operations"]:
            op = self.state["operations"][op_key]
            need(op["fingerprint"] == fingerprint, "idempotency_conflict", 409)
            return op["result"]
        result = self.mutate(parts, body, scope)
        self.state["operations"][op_key] = dict(fingerprint=fingerprint, result=copy.deepcopy(result))
        return result

    def mutate(self, parts, body, scope):
        if parts[1:] == ["sessions"]:
            need(body == {}, "unknown_fields")
            sid = fresh_id("session")
            session = dict(session_id=sid, scope=scope, attached=False)
            self.state["sessions"][sid] = session
            return copy.deepcopy(session)
        if len(parts) == 4 and parts[1] == "sessions":
            session = self.visible("sessions", parts[2], scope)
            if parts[3] in {"attach", "detach"}:
                need(body == {}, "unknown_fields")
                session["attached"] = parts[3] == "attach"
                return copy.deepcopy(session)
            if parts[3] == "runs":
                need(set(body) <= {"input", "reservation", "parent_run_id"}, "unknown_fields")
                need(isinstance(body.get("input"), str) and len(body["input"]) <= 4096)
                parent = (self.visible("runs", body["parent_run_id"], scope)
                          if body.get("parent_run_id") else None)
                reservation = body.get("reservation", DEFAULT_RESERVATION)
                self.reserve(scope, reservation, parent)
                rid = fresh_id("run")
                run = dict(run_id=rid, session_id=session["session_id"], scope=scope,
                           root_run_id=parent["root_run_id"] if parent else rid,
                           parent_run_id=parent["run_id"] if parent else None,
                           depth=parent["depth"] + 1 if parent else 0,
                           execution_state="running", business_state="unverified",
                           cleanup_state="pending", reservation=reservation,
                           processes=dict(runtime=1, tool=0, browser=0, mcp=0, experiment=0),
                           temporary_data_clean=False, effects=0, wait=None,
                           sequence=0, events=[], lease_expired=False)
                self.state["runs"][rid] = run
                self.publish(run)
                return self.view(run)
        if len(parts) == 4 and parts[1] == "runs":
            run = self.visible("runs", parts[2], scope)
            if parts[3] == "cancel":
                need(body == {}, "unknown_fields")
                if run["execution_state"] not in {"completed", "cancelled"}:
                    run["execution_state"] = "cancel_requested"
                    run["wait"] = None
                    if self.mutant == "release_on_cancel":
                        run["cleanup_state"] = "verified"
                    self.publish(run)
                return self.view(run)
            if parts[3] == "step":
                need(body == {}, "unknown_fields")
                need(run["execution_state"] == "running" and not run["lease_expired"]
                     and run["cleanup_state"] == "pending",
                     "not_runnable", 409)
                run["effects"] += 1
                self.state["effects"] += 1
                self.publish(run)
                return self.view(run)
            if parts[3] == "reply":
                wait = run["wait"]
                need(wait is not None, "no_pending_interaction", 409)
                need(run["execution_state"] == "waiting_" + wait["kind"]
                     and run["cleanup_state"] == "pending" and not run["lease_expired"],
                     "not_waiting", 409)
                need(body.get("interaction_id") == wait["interaction_id"], "stale_interaction", 409)
                need(body.get("kind") == wait["kind"], "interaction_kind_mismatch", 409)
                need(not wait["expired"], "expired_interaction", 409)
                if wait["kind"] == "approval":
                    need(set(body) == {"interaction_id", "kind", "binding", "approve"}, "unknown_fields")
                    need(body.get("binding") == wait["binding"], "approval_binding_changed", 409)
                    need(type(body.get("approve")) is bool)
                    run["approval_outcome"] = "approved" if body["approve"] else "denied"
                else:
                    need(set(body) == {"interaction_id", "kind", "answer"}, "unknown_fields")
                    need(isinstance(body.get("answer"), str))
                run["wait"] = None
                run["execution_state"] = "running"
                self.publish(run)
                return self.view(run)
            if parts[3] == "reclaim":
                need(body == {}, "unknown_fields")
                need(run["execution_state"] in {"completed", "cancelled"}, "not_terminal", 409)
                need(all(v == 0 for v in run["processes"].values())
                     and run["temporary_data_clean"], "cleanup_unverified", 409)
                children = [r for r in self.state["runs"].values() if r["parent_run_id"] == run["run_id"]]
                need(all(r["cleanup_state"] == "verified" for r in children), "children_not_reclaimed", 409)
                run["cleanup_state"] = "verified"
                self.publish(run)
                return self.view(run)
        raise Rejected(404, "not_found")

    def control(self, body):
        op = body.get("op")
        if op == "inspect":
            return copy.deepcopy(self.state)
        if op == "drop_next_response":
            self.state["drop_next"] = body["path"]
            self.state["response_fault"] = body.get("fault", "disconnect")
            need(self.state["response_fault"] in {
                "disconnect", "server_error", "invalid_json", "invalid_array", "oversized_json"})
            return dict(armed=True)
        if op == "revoke":
            self.state["revoked"].append(canonical(ACTORS[body["actor"]].as_dict()))
            return dict(revoked=True)
        run = self.state["runs"].get(body.get("run_id"))
        need(run is not None, "not_found", 404)
        if op == "wait":
            need(body["kind"] in {"question", "approval"})
            run["wait"] = dict(interaction_id=fresh_id("interaction"), kind=body["kind"],
                               expired=body.get("expired", False), binding=body.get("binding"))
            run["execution_state"] = "waiting_" + body["kind"]
        elif op == "complete":
            run["execution_state"] = body.get("state", "completed")
            need(run["execution_state"] in {"completed", "cancelled"})
            run["business_state"] = body.get("business_state", "unverified")
            run["wait"] = None
        elif op == "cleanup_evidence":
            processes = body["processes"]
            need(set(processes) == set(run["processes"]))
            need(all(type(v) is int and v >= 0 for v in processes.values()))
            need(type(body["temporary_data_clean"]) is bool)
            run["processes"], run["temporary_data_clean"] = processes, body["temporary_data_clean"]
        elif op == "expire_lease":
            run["lease_expired"] = True
        elif op == "expire_events":
            run["event_floor"] = run["sequence"]
        else:
            raise Rejected(400, "unknown_control")
        self.publish(run)
        return self.view(run)


class FixtureServer:
    def __init__(self, db_path, mutant=None):
        self.db_path, self.mutant = db_path, mutant
        self.server = self.store = self.thread = None

    def start(self):
        self.store = Store(self.db_path, self.mutant)
        store = self.store

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass  # Do not put test credentials or request bodies into logs.

            def do_GET(self):
                self.respond()

            def do_POST(self):
                self.respond()

            def respond(self):
                drop = None
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    need(0 <= length <= 16384, "request_too_large", 413)
                    body = json.loads(self.rfile.read(length)) if length else {}
                    need(isinstance(body, dict))
                    token = self.headers.get("Authorization", "").removeprefix("Bearer ")
                    result, drop = store.handle(self.command, self.path, body, token,
                                                self.headers.get("Idempotency-Key"))
                    if drop == "disconnect":
                        self.close_connection = True
                        self.connection.shutdown(socket.SHUT_RDWR)
                        self.connection.close()
                        return
                    status = 503 if drop == "server_error" else 200
                    if drop == "server_error":
                        result = dict(error="injected_after_commit")
                except Rejected as exc:
                    status, result = exc.status, dict(error=exc.code)
                except (ValueError, KeyError, TypeError):
                    status, result = 400, dict(error="invalid_request")
                payload = canonical(result).encode()
                if drop == "invalid_json":
                    payload = b"invalid-json"
                elif drop == "invalid_array":
                    payload = b"[]"
                elif drop == "oversized_json":
                    payload = canonical({"padding": "x" * (1024 * 1024)}).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       kwargs={"poll_interval": 0.01}, daemon=True)
        self.thread.start()
        return self

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server.server_port}"

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.thread.join(timeout=2)
            self.store.close()
            self.server = None

    def restart(self):
        self.stop()
        return self.start()
