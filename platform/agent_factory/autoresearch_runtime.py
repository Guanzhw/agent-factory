"""Real ORX turn wiring; research decisions remain inside the upstream harness.

Only an ephemeral capability reaches the isolated launcher. Provider credentials
are supplied by the operator callback to the host broker. No restart adoption,
provider retries, arbitrary MCP tools, or busy/interrupt-based stop claims.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import contextmanager
import hmac
import json
import os
import re
from pathlib import Path
import secrets
import socket
import stat
import time
from typing import Any, cast
from uuid import uuid4

import httpx
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
import uvicorn

from .autoresearch_profile import DESCRIPTIONS, ORXResearchModel, TOOL_NAMES, SESSION_RESOURCE_LIMITS
from .orx_research_broker import ORXResearchBroker
from .orx_research_session import OpenResearchSessionHTTP, OrxSessionError, OrxSessionUnknown, OrxSessionCancelled, _json
from .go_diagnostics import safe_diagnostic
from .store import digest

ERROR = 'AUTORESEARCH_RUNTIME_UNCONFIRMED'
PROTOCOL = '2025-03-26'
_SCHEMAS = {
    'research_context': {},
    'research_candidate': {'hypothesis': {'type': 'string', 'maxLength': 4000},
                           'trainPy': {'type': 'string', 'maxLength': 262144}},
    'research_experiment': {'candidateId': {'type': 'string', 'maxLength': 64}},
    'research_result': {'candidateId': {'type': 'string', 'maxLength': 64}},
    'research_decision': {'action': {'type': 'string', 'enum': ['continue', 'stop']},
                          'reason': {'type': 'string', 'maxLength': 4000}},
}


def _require(value):
    if not value:
        raise ValueError(ERROR)


class _PrivateServer(uvicorn.Server):
    @contextmanager
    def capture_signals(self):
        # Embedded task listener must never replace the Factory process handlers.
        yield


class AutoResearchRuntime:
    """Trusted constructor used by ResearchPreset.runtime_factory.

    ``launcher`` is the operator-created scripts/orx_research_runtime.Runtime.
    It receives no model credential. Transport injection is for offline tests.
    The persisted Factory effect prevents creating another instance after UNKNOWN.
    """
    def __init__(self, ctx, service, *, launcher, project_id: str, credential: Callable[[], str], billing_authorized: Callable[[], bool],
                 max_requests: int = 3, max_output_tokens: int = 512,
                 broker_transport=None, session_transport=None, poll_seconds=0.25):
        _require(callable(credential) and callable(billing_authorized) and type(project_id) is str and bool(project_id))
        _require(type(poll_seconds) in {int, float} and 0.01 <= poll_seconds <= 2)
        self.ctx, self.service, self.launcher = ctx, service, launcher
        self.project_id = project_id
        self._billing_authorized = billing_authorized
        self._fixture = broker_transport is not None
        preset = service.current(ctx)
        _require(type(max_requests) is int and 1 <= max_requests <= preset.limits['modelRequests']
                 and type(max_output_tokens) is int and 1 <= max_output_tokens <= preset.limits['modelOutputTokens'])
        self.capability = secrets.token_urlsafe(32)
        limits = SESSION_RESOURCE_LIMITS
        for attribute, key in (('cpus', 'cpus'), ('memory_mb', 'memoryMb'), ('pids', 'pids')):
            value = getattr(launcher.config, attribute, None)
            _require(type(value) is int and 1 <= value <= limits[key])
        _require(type(preset.limits['totalSeconds']) is int
                 and 1 <= preset.limits['totalSeconds'] <= limits['maxSessionSeconds'])
        _require(type(launcher.config.max_output_tokens) is int
                 and launcher.config.max_output_tokens == max_output_tokens)
        self._session_transport = session_transport
        self._poll_seconds = poll_seconds
        self.session: dict[str, Any] | None = None
        self.turn: dict[str, Any] | None = None
        self._http: OpenResearchSessionHTTP | None = None
        self._container_id: str | None = None
        self._launch_task: asyncio.Task | None = None
        self._launch_deadline = 0.0
        self._started = False
        self._run_phase = 'admission'
        self.runtime_failure: dict[str, Any] | None = None
        self._cancelled = False
        self._tool_lock = asyncio.Lock()
        self._stop_lock = asyncio.Lock()
        self._server: Any = None
        self._server_task: asyncio.Task | None = None
        self._socket: socket.socket | None = None
        self._socket_pin = None
        self._stop_proof = False
        self._stop_receipt: dict[str, Any] | None = None
        self._stop_recorded = False
        self._model = ORXResearchModel(ctx)
        self.broker = ORXResearchBroker(capability=self.capability,
            session_id=digest({'task': ctx.run_context.session_id, 'run': ctx.run_context.run_id}),
            credential=credential, current_authority=self._broker_authority,
            reserve=self._reserve, settle=self._settle, hold=self._hold,
            transport=broker_transport, max_requests=max_requests, max_output_tokens=max_output_tokens)

    async def _authority(self):
        _require(not self._cancelled)
        self.service.current(self.ctx)
        return True

    async def _broker_authority(self):
        await self._authority()
        _require(self._billing_authorized() is True)
        return True

    async def _reserve(self, ordinal, input_bound, output_bound, body):
        await self._authority()
        # Synchronous COMMIT is intentional: cancellation cannot lose the returned
        # reservation identity between threaded admission and credential access.
        return self.ctx.store.usage_ledger.begin_attempt(self.ctx.run_context, self.ctx.plan,
            self._model, streaming=body.get('stream', False), arguments=(body,))

    async def _settle(self, ticket, usage):
        self.ctx.store.usage_ledger.finish_attempt(ticket, usage)
        self.service.record(self.ctx, 'action',
            '离线代理 fixture 返回合成响应。' if self._fixture else '研究模型返回已核对的用量与响应。',
            accepted=None if self._fixture else 'modelExecuted')

    async def _hold(self, ticket, reason):
        self.ctx.store.usage_ledger.finish_attempt(ticket, None)

    def _commit(self, *, intent):
        _require(not self._cancelled)
        self.service.commit_intent(self.ctx, intent=intent)

    async def __call__(self, scope, receive, send):
        """Capability-authenticated, stateless Streamable HTTP MCP plus broker."""
        if scope['type'] != 'http':
            raise ValueError(ERROR)
        if scope['path'] == '/v1/chat/completions':
            await self.broker(scope, receive, send)
            return
        request = Request(scope, receive)
        response: Response
        try:
            authorization = request.headers.getlist('authorization')
            _require(len(authorization) == 1 and hmac.compare_digest(
                authorization[0], 'Bearer ' + self.capability))
            _require(scope['path'] == '/mcp' and request.method == 'POST')
            _require(not request.headers.get('origin'))
            _require(request.headers.get('content-type', '').split(';')[0] == 'application/json')
            version = request.headers.get('mcp-protocol-version')
            _require(version is None or version == PROTOCOL)
            raw = bytearray()
            async with asyncio.timeout(5):
                async for chunk in request.stream():
                    _require(len(raw) + len(chunk) <= 300000)
                    raw.extend(chunk)
            value = _json(raw)
            _require(value.get('jsonrpc') == '2.0' and set(value) <= {'jsonrpc', 'id', 'method', 'params'})
            identity = value.get('id')
            _require(identity is None or type(identity) is int and 0 <= identity < 2**53
                     or type(identity) is str and 1 <= len(identity) <= 128)
            method, params = value.get('method'), value.get('params', {})
            _require(type(params) is dict)
            await self._authority()
            if method == 'notifications/initialized' and identity is None:
                response = Response(status_code=202)
            else:
                _require(identity is not None)
                if method == 'initialize':
                    _require(params.get('protocolVersion') in {PROTOCOL, '2024-11-05', '2025-06-18', '2025-11-25'})
                    result = {'protocolVersion': PROTOCOL, 'capabilities': {'tools': {'listChanged': False}},
                              'serverInfo': {'name': 'factory-research', 'version': '1'}}
                elif method == 'ping':
                    result = {}
                elif method == 'tools/list':
                    _require(not params)
                    result = {'tools': [{'name': name, 'description': DESCRIPTIONS[name],
                        'inputSchema': {'type': 'object', 'properties': _SCHEMAS[name],
                            'required': list(_SCHEMAS[name]), 'additionalProperties': False}}
                        for name in TOOL_NAMES]}
                elif method == 'tools/call':
                    _require(set(params) <= {'name', 'arguments', '_meta'} and params.get('name') in TOOL_NAMES)
                    arguments = params.get('arguments', {})
                    _require(type(arguments) is dict and '_factoryCallId' not in arguments)
                    async with self._tool_lock:
                        await self._authority()
                        # Same MCP request ID repeats the original durable tool effect,
                        # never an independently generated replacement effect.
                        call_id = digest({'session': self.ctx.run_context.session_id, 'rpcId': identity})
                        output = await self.service.tool(self.ctx, params['name'],
                            {**arguments, '_factoryCallId': call_id})
                        await self._authority()
                    encoded = json.dumps(output, ensure_ascii=True, allow_nan=False)
                    _require(len(encoded.encode()) <= 1024**2)
                    result = {'content': [{'type': 'text', 'text': encoded}], 'isError': False}
                else:
                    raise ValueError(ERROR)
                response = JSONResponse({'jsonrpc': '2.0', 'id': identity, 'result': result})
        except Exception:
            # Do not echo exception messages, tool inputs, or capability values.
            response = JSONResponse({'error': ERROR}, status_code=403)
        await response(scope, receive, send)

    async def _start_host(self):
        root = Path(self.launcher.config.session_root)
        _require(root.is_absolute() and root.resolve() == root)
        info = root.lstat()
        _require(stat.S_ISDIR(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o700)
        directory = root / 'sockets'
        directory.mkdir(mode=0o700, exist_ok=True)
        info = directory.lstat()
        _require(stat.S_ISDIR(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o700)
        path = directory / 'broker.sock'
        family = getattr(socket, 'AF_UNIX', None)
        _require(type(family) is int or isinstance(family, socket.AddressFamily))
        sock = socket.socket(cast(int, family), socket.SOCK_STREAM)
        self._socket = sock
        sock.bind(str(path)); path.chmod(0o600); sock.listen(16)
        self._socket_pin = (path, path.lstat().st_dev, path.lstat().st_ino)
        self._server = _PrivateServer(uvicorn.Config(self, lifespan='off', access_log=False,
            log_config=None, log_level='critical', timeout_graceful_shutdown=5))
        self._server_task = asyncio.create_task(self._server.serve(sockets=[sock]))
        async with asyncio.timeout(5):
            while not self._server.started:
                _require(not self._server_task.done())
                await asyncio.sleep(0.01)

    async def _await_launch(self):
        """Repeated caller cancellation cannot cancel the original launch task.

        Timeout retains the task for later reconciliation; it never authorizes a
        replacement launch. The deadline belongs to the original launch attempt.
        """
        task = self._launch_task
        _require(task is not None)
        task = cast(asyncio.Task, task)
        cancelled = False
        while not task.done():
            remaining = self._launch_deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise TimeoutError(ERROR)
            try:
                await asyncio.wait_for(asyncio.shield(task), remaining)
            except asyncio.CancelledError:
                if task.cancelled():
                    raise ValueError(ERROR) from None
                cancelled = True
        receipt = task.result()
        _require(type(receipt) is dict and type(receipt.get('containerId')) is str
                 and re.fullmatch('[a-f0-9]{64}', receipt['containerId']) is not None)
        self._container_id = receipt['containerId']
        return receipt, cancelled

    async def _poll_original(self, session_id):
        """Only GET timeout observations may be retried under run's deadline.

        Neither a new session/turn nor another broker request is admitted here.
        Shape/authority/status failures remain terminal and preserve UNKNOWN.
        """
        client = self._http
        _require(client is not None)
        client = cast(OpenResearchSessionHTTP, client)
        while True:
            self._run_phase = 'poll-authority'
            await self._authority()
            _require(self.broker.stopped_reason is None)
            try:
                self._run_phase = 'poll-messages'
                transcript = await client.read_messages(session_id)
                self._run_phase = 'poll-session'
                current = await client.read_session(session_id)
                return transcript, current
            except OrxSessionError as error:
                details = error.session_diagnostic
                retryable = (type(error) is OrxSessionError and details is not None
                    and details.get('route') in {'sessions', 'messages'}
                    and details.get('phase') in {'request', 'body'}
                    and details.get('rejectionCode') == 'TRANSPORT_TIMEOUT')
                if not retryable:
                    raise
                # The enclosing original deadline remains active during sleep
                # and every subsequent GET. Recheck current authority first.
                await self._authority()
                await asyncio.sleep(self._poll_seconds)

    async def run(self):
        try:
            return await self._run()
        except BaseException as error:
            classified = safe_diagnostic('FAILED', error=error)
            code = ('ORX_PROTOCOL' if type(error) is OrxSessionError else
                    'ORX_ACK_UNKNOWN' if type(error) in {OrxSessionUnknown, OrxSessionCancelled} else
                    'RUNTIME_EXCEPTION')
            failure = {'schema': 1, 'phase': self._run_phase, 'code': code,
                'sessionKnown': self.session is not None, 'turnKnown': self.turn is not None,
                **{key: classified[key] for key in ('errorType', 'errorCategory', 'rejectionCode', 'exceptionChain')}}
            if type(error) in {OrxSessionError, OrxSessionUnknown}:
                details = cast(OrxSessionError, error).session_diagnostic
                if details is not None:
                    failure['sessionDiagnostic'] = dict(details)
            self.runtime_failure = failure
            try:
                self.service.change(self.ctx.run_context.user_id, self.ctx.run_context.session_id,
                    lambda body: body.update(runtimeFailure=dict(failure)))
            except Exception:
                # Preserve original failure; unavailable persistence cannot turn
                # the failure into a different apparent provider rejection.
                pass
            raise

    async def _run(self):
        _require(not self._started)
        self._started = True
        preset = self.service.current(self.ctx)
        total = preset.limits['totalSeconds']
        _require(type(total) is int and 1 <= total <= 3600)
        deadline = self.service.row(self.ctx.run_context.user_id, self.ctx.run_context.session_id)['body']['deadline']
        remaining = min(total, deadline - time.time())
        _require(remaining > 0)
        async with asyncio.timeout(remaining):
            self._run_phase = 'host-start'
            await self._start_host()
            await self._authority()
            # start may create an OS effect while cancellation arrives; retain its
            # exact receipt before re-raising so finally.stop can prove custody.
            self._run_phase = 'launcher-start'
            self._launch_deadline = asyncio.get_running_loop().time() + 120
            self._launch_task = asyncio.create_task(asyncio.to_thread(self.launcher.start, self.capability))
            receipt, cancelled = await self._await_launch()
            if cancelled:
                raise asyncio.CancelledError()
            _require(receipt.get('projectId') == self.project_id)
            transport = self._session_transport or httpx.AsyncHTTPTransport(uds=receipt['orxSocket'], retries=0)
            self._http = OpenResearchSessionHTTP(4791, project_id=self.project_id,
                harness='opencode', model='factory/deepseek-flash', transport=transport)
            # Read-only readiness retries are bounded; no POST is retried.
            self._run_phase = 'session-readiness'
            async with asyncio.timeout(30):
                while True:
                    await self._authority()
                    try:
                        await self._http._request('GET', '/api/chat/sessions', params={'projectId': self.project_id})
                        break
                    except ValueError:
                        await asyncio.sleep(self._poll_seconds)
            self._run_phase = 'session-create'
            session = await self._http.create_session(key='orx-create', commit_intent=self._commit)
            self.session = session
            self.service.change(self.ctx.run_context.user_id, self.ctx.run_context.session_id,
                                lambda body: body.update(session=dict(self.session or {})))
            self._run_phase = 'session-title'
            await self._http.rename_session(session['id'], 'Factory bounded research',
                                           key='orx-title', commit_intent=self._commit)
            row = self.service.row(self.ctx.run_context.user_id, self.ctx.run_context.session_id)['body']
            goal = row['goal']
            instructions = preset.instructions
            _require(type(instructions) is str and 0 < len(instructions.encode('utf-8')) <= 24000)
            prompt = ('Use only the Factory research tools. First read research_context, then choose actions '
                'within the approved project instructions. Candidate proposals, managed experiments, independent '
                'results and subsequent decisions are available research stages, not mandatory actions. '
                'Do not run an experiment unless these project instructions authorize it. '
                'Never invent execution evidence.\nApproved project instructions:\n' + instructions + '\nGoal: ' + goal)
            self._run_phase = 'message-send'
            turn = await self._http.send_message(session['id'], prompt,
                client_turn_id=uuid4().hex, key='orx-message', commit_intent=self._commit)
            self.turn = turn
            self.service.change(self.ctx.run_context.user_id, self.ctx.run_context.session_id,
                                lambda body: body.update(turn=dict(self.turn or {})))
            while True:
                transcript, current = await self._poll_original(session['id'])
                self._run_phase = 'poll-inspect'
                leaf = next((row for row in transcript['messages'] if row['id'] == transcript['activeLeafId']), None)
                if not current['busy'] and not transcript['queued'] and leaf and leaf['role'] == 'assistant' and leaf['completedAt'] is not None:
                    _require(not any(part.get('type') == 'error' for part in leaf['parts']))
                    final = '\n'.join(part['text'] for part in leaf['parts']
                        if part.get('type') == 'text' and type(part.get('text')) is str)
                    _require(0 < len(final.encode()) <= 32768)
                    self._run_phase = 'completed'
                    return {'sessionId': session['id'], 'turnId': turn['turnId'],
                        'clientTurnId': turn['clientTurnId'], 'finalText': final,
                        'scientificConclusionVerified': False}
                await asyncio.sleep(self._poll_seconds)

    async def stop(self):
        async with self._stop_lock:
            self._cancelled = True
            if self._stop_proof:
                return True
            try:
                if self._launch_task is not None:
                    try:
                        await self._await_launch()
                    except Exception:
                        # A failed/unknown start can retain an OS effect; keep its
                        # original handle, never infer absence or replay launch.
                        return False
                if self._stop_receipt is None:
                    receipt = await asyncio.to_thread(self.launcher.stop)
                    matched = (self._container_id is not None and receipt.get('containerId') == self._container_id
                        and receipt.get('stopped') is True and receipt.get('status') == 'STOPPED'
                        and receipt.get('proofKind') == 'docker-state-exited')
                    if not matched:
                        return False
                    self._stop_receipt = {key: receipt[key] for key in
                        ('containerId', 'stopped', 'status', 'proofKind')}
                    if type(receipt.get('exitCode')) is int:
                        self._stop_receipt['exitCode'] = receipt['exitCode']
                    finished = receipt.get('finishedAt')
                    if type(finished) is str and re.fullmatch(r'[0-9TZ:.+\-]{1,64}', finished):
                        self._stop_receipt['finishedAt'] = finished
                if not self._stop_recorded:
                    # Persist original positive stop evidence before removing the
                    # stopped container. Failed reclaim retries only reclamation.
                    self.service.change(self.ctx.run_context.user_id, self.ctx.run_context.session_id,
                        lambda body: body.update(runtimeStop=dict(self._stop_receipt or {})))
                    self._stop_recorded = True
                reclaimed = await asyncio.to_thread(self.launcher.reclaim)
                confirmed = (type(reclaimed) is dict and reclaimed.get('reclaimed') is True
                                   and reclaimed.get('containerId') == self._container_id)
                self.service.change(self.ctx.run_context.user_id, self.ctx.run_context.session_id,
                    lambda body: body.update(runtimeReclaim={'containerId': self._container_id,
                                                            'reclaimed': confirmed}))
                self._stop_proof = confirmed
            finally:
                if self._server is not None:
                    self._server.should_exit = True
                if self._server_task is not None:
                    try:
                        await asyncio.wait_for(asyncio.shield(self._server_task), 6)
                    except (TimeoutError, asyncio.CancelledError):
                        self._server_task.cancel()
                        await asyncio.gather(self._server_task, return_exceptions=True)
                if self._socket is not None:
                    self._socket.close()
                if self._socket_pin is not None:
                    path, device, inode = self._socket_pin
                    try:
                        info = path.lstat()
                        if (info.st_dev, info.st_ino) == (device, inode):
                            os.unlink(path)
                    except FileNotFoundError:
                        pass
                # Advisory finite diagnostics never replace the ledger or stop proof.
                try:
                    self.service.change(self.ctx.run_context.user_id, self.ctx.run_context.session_id,
                        lambda body: body.update(providerDiagnostics=self.broker.diagnostics))
                except Exception:
                    pass
            return self._stop_proof

    async def cancel(self):
        self._cancelled = True
        # Container exit, not interrupt ACK, is the authoritative cleanup boundary.
        return await self.stop()
