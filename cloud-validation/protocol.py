"""Transport and projection helpers for the proposed Factory boundary contract.

This is test support, not an Agno client or a production execution engine.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import socket
from dataclasses import dataclass
from urllib import error, parse, request

MAX_RESPONSE_BYTES = 1024 * 1024


class ContractError(Exception):
    def __init__(self, status: int, code: str):
        super().__init__(f"HTTP {status}: {code}")
        self.status, self.code = status, code


class UnknownAcknowledgement(Exception):
    """A mutation may have committed. Reconcile its original key; never blind retry."""


class ProtocolViolation(Exception):
    pass


class SnapshotRequired(ProtocolViolation):
    pass


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ProtocolViolation("Redirects are forbidden; do not forward credentials")


class ContractClient:
    def __init__(self, base_url: str, token: str, timeout: float = 2.0):
        parts = parse.urlsplit(base_url)
        if (parts.scheme != "http" or parts.hostname not in {"127.0.0.1", "::1"}
                or parts.username or parts.password or parts.query or parts.fragment
                or parts.path not in {"", "/"}):
            raise ValueError("Only explicit loopback HTTP test adapters are supported")
        self.base_url = base_url.rstrip("/")
        self.token, self.timeout = token, timeout
        self.opener = request.build_opener(request.ProxyHandler({}), NoRedirect())

    def call(self, method: str, path: str, body: dict | None = None,
             key: str | None = None) -> dict:
        if not path.startswith("/") or path.startswith("//"):
            raise ValueError("Contract path must be relative to the test adapter")
        headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
        if key is not None:
            headers["Idempotency-Key"] = key
        data = None if body is None else json.dumps(body, allow_nan=False).encode()
        req = request.Request(self.base_url + path, data=data, headers=headers, method=method)
        try:
            with self.opener.open(req, timeout=self.timeout) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise ProtocolViolation("Response exceeds contract byte limit")
                result = json.loads(raw)
                if not isinstance(result, dict):
                    raise ProtocolViolation("Response must be a JSON object")
                return result
        except error.HTTPError as exc:
            if method != "GET" and (exc.code >= 500 or exc.code == 408):
                raise UnknownAcknowledgement("Server error does not establish mutation outcome") from None
            raw = exc.read(MAX_RESPONSE_BYTES + 1)
            try:
                code = json.loads(raw).get("error", "invalid_error_response")
            except (ValueError, AttributeError):
                code = "invalid_error_response"
            raise ContractError(exc.code, code) from None
        except ProtocolViolation as exc:
            if method != "GET":
                raise UnknownAcknowledgement("Unusable acknowledgement; reconcile the original key") from exc
            raise
        except (ValueError, UnicodeError) as exc:
            if method != "GET":
                raise UnknownAcknowledgement("Invalid acknowledgement; reconcile the original key") from exc
            raise ProtocolViolation("Response is not valid JSON") from exc
        except (error.URLError, socket.timeout, ConnectionError,
                http.client.HTTPException) as exc:
            if method != "GET":
                raise UnknownAcknowledgement("Reconcile using the original operation key") from exc
            raise

    def get(self, path: str) -> dict:
        return self.call("GET", path)

    def post(self, path: str, body: dict, key: str | None = None) -> dict:
        return self.call("POST", path, body, key)


@dataclass(frozen=True)
class Scope:
    tenant_id: str
    user_id: str
    task_id: str

    def as_dict(self) -> dict:
        return dict(tenant_id=self.tenant_id, user_id=self.user_id, task_id=self.task_id)


class Projection:
    """A scoped client view. Gaps require a snapshot; stale events cannot win."""
    def __init__(self, scope: Scope, run_id: str):
        self.scope, self.run_id = scope.as_dict(), run_id
        self.sequence = 0
        self.state = None

    def _validate(self, item: dict):
        if item.get("scope") != self.scope or item.get("run_id") != self.run_id:
            raise ProtocolViolation("Cross-scope frame rejected")
        sequence = item.get("sequence")
        if type(sequence) is not int or sequence < 1:
            raise ProtocolViolation("Sequence must be a positive integer")
        state = item.get("state")
        if (not isinstance(state, dict) or state.get("scope") != self.scope
                or state.get("run_id") != self.run_id
                or type(state.get("sequence")) is not int
                or state.get("sequence") != sequence):
            raise ProtocolViolation("State must match its scope, run and sequence envelope")

    def snapshot(self, item: dict) -> bool:
        self._validate(item)
        if item["sequence"] <= self.sequence:
            return False
        self.sequence, self.state = item["sequence"], item["state"]
        return True

    def event(self, item: dict) -> bool:
        self._validate(item)
        if item["sequence"] <= self.sequence:
            return False
        if item["sequence"] != self.sequence + 1:
            raise SnapshotRequired("Sequence gap; fetch authoritative snapshot")
        self.sequence, self.state = item["sequence"], item["state"]
        return True


def verify_artifact(artifact: dict, scope: Scope, run_id: str) -> bytes:
    if artifact.get("scope") != scope.as_dict() or artifact.get("run_id") != run_id:
        raise ProtocolViolation("Cross-scope artifact rejected")
    content = artifact["content"].encode("utf-8")
    if len(content) != artifact["size_bytes"]:
        raise ProtocolViolation("Artifact size mismatch")
    if hashlib.sha256(content).hexdigest() != artifact["sha256"]:
        raise ProtocolViolation("Artifact digest mismatch")
    return content
