"""Bounded operator-loopback transport for OpenResearch f336b121 session API.

Durability/authorization belong to the caller's mandatory commit_intent callback.
Create has NO upstream idempotency key: unknown acknowledgement must never trigger
another create or field-based session adoption. Message clientTurnId is upstream
content-bound, but this transport never resends. Context occupancy is not usage;
interrupt/busy/events are observations, never proof that processes stopped.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from copy import deepcopy
import hashlib
import inspect
import json
import math
import re
from types import MappingProxyType
from typing import Any, cast

import httpx

UPSTREAM_COMMIT = 'f336b121525d99364e2dee4fe90b2784894a54e6'
MAX_RESPONSE_BYTES = 2 * 1024**2
MAX_TEXT_BYTES = 32768
Intent = Mapping[str, str | None]


class OrxSessionError(ValueError):
    def __init__(self, code='ORX_SESSION_PROTOCOL'):
        self.code = code
        super().__init__(code)


class OrxSessionUnknown(OrxSessionError):
    def __init__(self, intent: Intent):
        self.intent = MappingProxyType(dict(intent))
        super().__init__('ORX_SESSION_ACK_UNKNOWN')


class OrxSessionCancelled(asyncio.CancelledError):
    def __init__(self, intent: Intent):
        self.intent = MappingProxyType(dict(intent))
        super().__init__('ORX_SESSION_ACK_UNKNOWN')


def _require(value):
    if not value:
        raise OrxSessionError()


def _id(value):
    _require(type(value) is str and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}', value) is not None)
    return value


def _encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode('ascii')


def _json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            _require(key not in result)
            result[key] = value
        return result
    def invalid(_):
        raise OrxSessionError()
    try:
        result = json.loads(raw, object_pairs_hook=unique, parse_constant=invalid)
        # Bound nested tool payloads independently of the HTTP byte limit.
        def check(value, depth=0):
            _require(depth <= 24)
            if isinstance(value, dict):
                for key, item in value.items():
                    _require(len(key) <= 256)
                    check(item, depth + 1)
            elif isinstance(value, list):
                _require(len(value) <= 4096)
                for item in value:
                    check(item, depth + 1)
            elif isinstance(value, float):
                _require(math.isfinite(value))
            elif isinstance(value, str):
                _require(len(value.encode('utf-8')) <= 262144)
        check(result)
        _require(type(result) is dict)
        return result
    except (ValueError, TypeError, RecursionError, OverflowError):
        raise OrxSessionError() from None


class OpenResearchSessionHTTP:
    """Operator-installed connection, not a public URL or credential resolver.

    Optional transport is a trusted test injection. No environment proxy, auth,
    redirects, retry middleware, arbitrary paths, or server error bodies are used.
    """
    def __init__(self, port: int, *, project_id: str, harness: str, model: str,
                 permission_mode: str | None = None, transport: httpx.AsyncBaseTransport | None = None,
                 timeout_seconds: float = 10):
        _require(type(port) is int and 1 <= port <= 65535)
        _require(type(timeout_seconds) in {int, float} and 0 < timeout_seconds <= 30)
        _id(project_id); _id(harness)
        _require(type(model) is str and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_./:-]{0,159}', model) is not None)
        if permission_mode is not None:
            _id(permission_mode)
        self._base = f'http://127.0.0.1:{port}'
        self.project_id, self.harness, self.model = project_id, harness, model
        self.permission_mode, self._transport, self._timeout = permission_mode, transport, timeout_seconds

    def _client(self):
        return httpx.AsyncClient(base_url=self._base, transport=self._transport or httpx.AsyncHTTPTransport(retries=0),
            timeout=self._timeout, trust_env=False, follow_redirects=False, auth=None,
            headers={'User-Agent': 'AgentFactory-OpenResearchSession/1', 'Accept': 'application/json', 'Accept-Encoding': 'identity'})

    async def _request(self, method, path, *, body=None, params=None):
        try:
            async with asyncio.timeout(self._timeout):
                async with self._client() as client:
                    async with client.stream(method, path, content=_encoded(body) if body is not None else None,
                            headers={'Content-Type': 'application/json'} if body is not None else None, params=params) as response:
                        _require(response.status_code == 200 and response.headers.get('content-encoding', 'identity') == 'identity')
                        _require(response.headers.get('content-type', '').split(';')[0].strip().lower() == 'application/json')
                        raw = bytearray()
                        async for chunk in response.aiter_bytes():
                            _require(len(raw) + len(chunk) <= MAX_RESPONSE_BYTES)
                            raw.extend(chunk)
            return _json(raw)
        except asyncio.CancelledError:
            raise
        except (httpx.HTTPError, TimeoutError, OSError, ValueError, TypeError, RecursionError):
            raise OrxSessionError() from None

    def _session(self, row, session_id=None):
        _require(type(row) is dict)
        identifier = _id(row.get('id'))
        _require(session_id is None or identifier == session_id)
        _require(row.get('projectId') == self.project_id and row.get('harness') == self.harness
                 and row.get('model') == self.model and type(row.get('busy')) is bool
                 and type(row.get('archived')) is bool)
        if self.permission_mode is not None:
            _require(row.get('permissionMode') == self.permission_mode)
        return {'id': identifier, 'projectId': self.project_id, 'harness': self.harness, 'model': self.model,
            'busy': row['busy'], 'archived': row['archived'], 'usageKnown': False, 'stoppedProof': False}

    async def read_session(self, session_id: str):
        _id(session_id)
        value = await self._request('GET', '/api/chat/sessions', params={'projectId': self.project_id})
        rows = value.get('sessions')
        _require(type(rows) is list and len(rows) <= 4096)
        matches = [row for row in rows if type(row) is dict and row.get('id') == session_id]
        _require(len(matches) == 1)
        return self._session(matches[0], session_id)

    async def _mutation(self, operation, key, path, body, *, session_id, client_turn_id, commit_intent, parse, method='POST'):
        _id(key)
        _require(callable(commit_intent))
        intent = MappingProxyType({'operation': operation, 'key': key,
            'requestHash': hashlib.sha256(_encoded({'origin': self._base, 'projectId': self.project_id,
                'harness': self.harness, 'model': self.model, 'permissionMode': self.permission_mode,
                'path': path, 'body': body})).hexdigest(),
            'sessionId': session_id, 'clientTurnId': client_turn_id})
        # Caller must durably reject an already admitted key, including UNKNOWN.
        # Errors here happen before HTTP and are NOT recategorized as lost ACK.
        committed = commit_intent(intent=intent)
        if inspect.isawaitable(committed):
            if inspect.iscoroutine(committed):
                committed.close()
            raise OrxSessionError('ORX_SESSION_INTENT_REQUIRED')
        _require(committed is None)
        try:
            return parse(await self._request(method, path, body=body))
        except asyncio.CancelledError:
            raise OrxSessionCancelled(intent) from None
        except Exception:
            raise OrxSessionUnknown(intent) from None

    async def create_session(self, *, key: str, commit_intent: Callable):
        body = {'projectId': self.project_id, 'harness': self.harness, 'model': self.model}
        if self.permission_mode is not None:
            body['permissionMode'] = self.permission_mode
        return await self._mutation('create', key, '/api/chat/sessions', body,
            session_id=None, client_turn_id=None, commit_intent=commit_intent,
            parse=lambda value: self._session(value.get('session')))

    async def rename_session(self, session_id: str, title: str, *, key: str, commit_intent: Callable):
        """Set a nonempty title before a turn, preventing upstream auto-title work."""
        _id(session_id)
        _require(type(title) is str and title == title.strip() and 0 < len(title.encode('utf-8')) <= 256)
        await self.read_session(session_id)
        def parse(value):
            row = value.get('session')
            result = self._session(row, session_id)
            _require(row.get('title') == title)
            return result | {'title': title}
        return await self._mutation('rename', key, f'/api/chat/sessions/{session_id}', {'title': title},
            session_id=session_id, client_turn_id=None, commit_intent=commit_intent, parse=parse, method='PATCH')

    async def send_message(self, session_id: str, text: str, *, client_turn_id: str, key: str, commit_intent: Callable):
        _id(session_id); _id(client_turn_id)
        _require(type(text) is str and text == text.strip() and 0 < len(text.encode('utf-8')) <= MAX_TEXT_BYTES)
        current = await self.read_session(session_id)
        _require(not current['archived'] and not current['busy'])
        def parse(value):
            turn = value.get('turn')
            _require(value.get('ok') is True and type(turn) is dict and
                type(turn.get('queued')) is bool and type(turn.get('existing')) is bool)
            turn_id = _id(turn.get('turnId'))
            _require(not turn['queued'] or turn_id == client_turn_id)
            return {'sessionId': session_id, 'clientTurnId': client_turn_id, 'turnId': turn_id,
                'queued': turn['queued'], 'existing': turn['existing'], 'usageKnown': False, 'stoppedProof': False}
        return await self._mutation('message', key, f'/api/chat/sessions/{session_id}/message',
            {'text': text, 'clientTurnId': client_turn_id}, session_id=session_id, client_turn_id=client_turn_id,
            commit_intent=commit_intent, parse=parse)

    async def interrupt(self, session_id: str, *, key: str, commit_intent: Callable):
        _id(session_id)
        await self.read_session(session_id)
        def parse(value):
            _require(value.get('ok') is True)
            return {'sessionId': session_id, 'interruptAcknowledged': True, 'stoppedProof': False}
        return await self._mutation('interrupt', key, f'/api/chat/sessions/{session_id}/interrupt', {},
            session_id=session_id, client_turn_id=None, commit_intent=commit_intent, parse=parse)

    async def read_messages(self, session_id: str):
        _id(session_id)
        await self.read_session(session_id)
        value = await self._request('GET', f'/api/chat/sessions/{session_id}/messages')
        rows, queue = value.get('messages'), value.get('queued')
        _require(type(rows) is list and type(queue) is list and len(rows) <= 4096 and len(queue) <= 128)
        seen = set()
        for row in rows:
            _require(type(row) is dict and row.get('role') in {'user', 'assistant'} and type(row.get('parts')) is list)
            identifier = _id(row.get('id'))
            _require(identifier not in seen); seen.add(identifier)
            for key in ('createdAt', 'completedAt'):
                _require(type(row.get(key)) is int or key == 'completedAt' and row.get(key) is None)
        queued = []
        for row in queue:
            _require(type(row) is dict)
            row = cast(dict, row)
            queued.append({'id': _id(row.get('id')), 'clientTurnId': _id(row.get('clientTurnId'))})
        leaf = value.get('activeLeafId')
        _require(leaf is None or type(leaf) is str and leaf in seen)
        await self.read_session(session_id)
        return {'sessionId': session_id, 'messages': deepcopy(rows), 'queued': queued,
            'activeLeafId': leaf, 'usageKnown': False, 'stoppedProof': False}

    async def events(self, session_id: str, *, max_events: int = 32):
        """Bounded lossy SSE hints only; caller MUST repair via session/messages GET."""
        _id(session_id)
        _require(type(max_events) is int and 1 <= max_events <= 128)
        await self.read_session(session_id)
        hints: list[dict[str, Any]] = []
        try:
            async with asyncio.timeout(self._timeout):
                async with self._client() as client:
                    async with client.stream('GET', '/api/events', headers={'Accept': 'text/event-stream'}) as response:
                        _require(response.status_code == 200 and response.headers.get('content-type', '').split(';')[0] == 'text/event-stream')
                        pending, total = b'', 0
                        event, data = '', []
                        async for chunk in response.aiter_bytes():
                            total += len(chunk)
                            _require(total <= 262144)
                            pending += chunk
                            while b'\n' in pending:
                                line, pending = pending.split(b'\n', 1)
                                line = line.rstrip(b'\r')
                                if not line:
                                    if event == 'resync.required':
                                        return {'events': hints, 'resyncRequired': True}
                                    if event in {'chat.session', 'chat.message', 'chat.busy', 'chat.session.deleted'} and data:
                                        value = _json(b'\n'.join(data))
                                        matching = ((value.get('session') or {}).get('id') == session_id
                                                    if event == 'chat.session' else value.get('sessionId') == session_id)
                                        if matching:
                                            hints.append({'type': event, 'sessionId': session_id})
                                            if len(hints) >= max_events:
                                                return {'events': hints, 'resyncRequired': True}
                                    event, data = '', []
                                elif line.startswith(b'event:'):
                                    event = line[6:].strip().decode('ascii')
                                elif line.startswith(b'data:'):
                                    data.append(line[5:].lstrip(b' '))
            return {'events': hints, 'resyncRequired': True}
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            return {'events': hints, 'resyncRequired': True}
        except (httpx.HTTPError, OSError, ValueError, TypeError, AttributeError):
            raise OrxSessionError() from None
