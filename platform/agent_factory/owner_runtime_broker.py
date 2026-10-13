"""Owner-funded protocol boundary for a private application runtime.

No research controller lives here. Original ORX and its declared harness own the
tool loop. Only a short-lived local capability enters that container; each model
call resolves the original owner/vault revision outside it, without fallback.
"""
import asyncio
from copy import deepcopy
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler
import json
import os
from pathlib import Path
import secrets
import re
import socketserver
import stat
from socketserver import ThreadingMixIn
import sys
import threading
import time
from typing import Any
from urllib.parse import urlsplit

import httpx

from .model_endpoint_policy import (
    base_url, chat_headers, continuation_scope, generation_options, model_origin, requires_session,
)
from .model_protocol import decode_response, encode_request, function_call, protocol_name, protocol_path
from .model_transport import MAX_BYTES, PinnedChatTransport, read_response_json
from .personal_remote_provider import reject_credential_echo


# The inert base keeps host imports possible where AF_UNIX is unsupported.
# start() rejects those hosts before constructing any listener.
UnixServerBase: Any = getattr(socketserver, 'UnixStreamServer', object)


class OwnerModelCallError(ValueError):
    """Sanitized, non-retryable native outcome; never carries provider text."""
    def __init__(self, dispatched, *, diagnostic_id=None):
        self.code = 'OWNER_MODEL_CALL_UNCONFIRMED' if dispatched else 'OWNER_MODEL_REQUEST_REJECTED'
        # OpenCode also scans response text for 5xx numerals. An alphabetic ID
        # cannot accidentally turn a terminal rejection into a retryable error.
        self.diagnostic_id = diagnostic_id or 'diag_' + ''.join(chr(97 + int(c, 16)) for c in secrets.token_hex(16))
        super().__init__(self.code)

    def response(self):
        message = ('模型调用可能已发出，结果尚未确认；请保留原请求核对。' if self.code == 'OWNER_MODEL_CALL_UNCONFIRMED'
                   else '模型请求在发送前被拒绝；请核对配置与权限。')
        return {'error': {'message': message + ' 诊断编号：' + self.diagnostic_id,
            'type': 'owner_model_boundary', 'code': self.code}, 'diagnosticId': self.diagnostic_id}


class _SyntheticDispatchTransport(httpx.AsyncBaseTransport):
    """Track the existing injected test transport at its dispatch boundary."""
    def __init__(self, transport, on_dispatch):
        self.transport, self.on_dispatch = transport, on_dispatch
    async def handle_async_request(self, request):
        self.on_dispatch()
        return await self.transport.handle_async_request(request)
    async def aclose(self):
        await self.transport.aclose()


class _NativeCall:
    def __init__(self):
        self.done = threading.Event()
        self.value: Any = None
        # Do not retain exception tracebacks/contexts, which can hold a lease.
        self.error: tuple[str, str] | None = None


class _Server(ThreadingMixIn, UnixServerBase):
    daemon_threads = True
    block_on_close = False
    def __init__(self, *args):
        self.slots = threading.BoundedSemaphore(4)
        super().__init__(*args)
    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(10)
        return connection, address
    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request); return
        try: super().process_request(request, address)
        except BaseException:
            self.slots.release(); raise
    def process_request_thread(self, request, address):
        try: super().process_request_thread(request, address)
        finally: self.slots.release()


class OwnerRuntimeBroker:
    def __init__(self, path, model_handle, *, ttl=1800, max_calls=64):
        self.path, self.handle = Path(path), model_handle
        self.directory_fd: int | None = None
        self.socket_identity: tuple[int, int] | None = None
        self.capability = secrets.token_urlsafe(32)
        self.deadline, self.remaining = time.monotonic() + ttl, max_calls
        self.lock = threading.Lock(); self.gate = threading.BoundedSemaphore(4)
        self.native_calls: dict[tuple[str, str, str], _NativeCall] = {}
        self.server = None; self.thread = None
        # Tool reasoning stays outside the native container. The broker lifetime,
        # call count and bounded response reader bound this cache; never evict a
        # continuation and silently resume a tool call without its reasoning.
        self.continuation_limit = max_calls
        self.continuations: dict[tuple[str, str, tuple[str, ...]], dict] = {}

    def __repr__(self): return 'OwnerRuntimeBroker(capability=<redacted>)'

    def authorized(self, token):
        return type(token) is str and hmac.compare_digest(token, self.capability) and time.monotonic() < self.deadline

    def native_completion(self, body, session_id, request_id):
        # Pinned native user-message IDs distinguish legal turns even when their
        # text is identical. The payload digest only distinguishes tool-loop
        # calls within that turn; it is never a cross-turn deduplication key.
        if (type(session_id) is not str or not re.fullmatch(r'ses_[A-Za-z0-9]{8,120}', session_id)
                or type(request_id) is not str or not re.fullmatch(r'msg_[A-Za-z0-9]{8,120}', request_id)):
            raise OwnerModelCallError(False)
        fingerprint = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        key = (session_id, request_id, fingerprint)
        with self.lock:
            record = self.native_calls.get(key)
            fresh = record is None
            if fresh:
                if self.remaining <= 0: raise OwnerModelCallError(False)
                self.remaining -= 1
                record = _NativeCall()
                # At most max_calls records. No eviction can turn an old retry
                # into a new provider call during this broker's short lifetime.
                self.native_calls[key] = record
        assert record is not None
        if fresh:
            try:
                record.value = asyncio.run(self.completion(body, session_id))
            except OwnerModelCallError as error:
                record.error = (error.code, error.diagnostic_id)
            except (Exception, asyncio.CancelledError):
                error = OwnerModelCallError(True)
                record.error = (error.code, error.diagnostic_id)
            finally:
                # Record before writing any local response. A lost downstream
                # reply may be read again, but can never dispatch again.
                record.done.set()
        elif not record.done.wait(timeout=120):
            raise OwnerModelCallError(True)
        if record.error is not None:
            code, diagnostic_id = record.error
            raise OwnerModelCallError(code == 'OWNER_MODEL_CALL_UNCONFIRMED', diagnostic_id=diagnostic_id)
        if record.value is None: raise OwnerModelCallError(True)
        try:
            self.handle.check()
            reject_credential_echo(record.value, self.handle.credential())
        except Exception:
            raise OwnerModelCallError(False) from None
        return deepcopy(record.value)

    async def completion(self, body, session_id=None):
        dispatched = False
        def on_dispatch():
            nonlocal dispatched
            dispatched = True
        try:
            return await self._completion(body, session_id, on_dispatch)
        except Exception:
            raise OwnerModelCallError(dispatched) from None

    async def _completion(self, body, session_id, on_dispatch):
        if type(body) is not dict or body.get('model') != 'owner-model': raise ValueError('MODEL_REQUEST_REJECTED')
        messages = body.get('messages')
        if type(messages) is not list or not 1 <= len(messages) <= 200: raise ValueError('MODEL_REQUEST_REJECTED')
        encoded = []
        for original in messages:
            message = dict(original) if type(original) is dict else original
            if type(message) is not dict or message.get('role') not in {'system', 'user', 'assistant', 'tool'}:
                raise ValueError('MODEL_TEXT_FUNCTIONS_ONLY')
            content = message.get('content')
            if type(content) is list and all(type(part) is dict and set(part) == {'type', 'text'}
                    and part['type'] == 'text' and type(part['text']) is str for part in content):
                message['content'] = '\n'.join(part['text'] for part in content)
            elif content is not None and type(content) is not str: raise ValueError('MODEL_TEXT_FUNCTIONS_ONLY')
            if message.get('tool_calls'):
                for call in message['tool_calls']: function_call(call)
            encoded.append(message)
        protocol = protocol_name(self.handle.body)
        scope = continuation_scope(self.handle.body, getattr(self.handle, 'owner', None))
        continuation = []
        if protocol == 'responses':
            if type(session_id) is not str or not re.fullmatch(r'ses_[A-Za-z0-9]{8,120}', session_id):
                raise ValueError('MODEL_SESSION_REJECTED')
            with self.lock:
                if len(self.continuations) >= self.continuation_limit:
                    raise ValueError('MODEL_CONTINUATION_LIMIT')
                for message in encoded:
                    if message.get('role') == 'assistant' and message.get('tool_calls'):
                        key = (session_id, scope, tuple(call['id'] for call in message['tool_calls']))
                        record = self.continuations.get(key)
                        if record is None:
                            raise ValueError('MODEL_CONTINUATION_REQUIRED')
                        continuation.append(deepcopy(record))
        chat = {'model': self.handle.body['model'], 'messages': encoded, 'max_tokens': 4096, 'stream': False}
        if body.get('tools'):
            chat.update(tools=body['tools'], parallel_tool_calls=False)
        if body.get('tool_choice') is not None:
            chat['tool_choice'] = body['tool_choice']
        request = encode_request(protocol, chat, continuation=continuation)
        if protocol == 'chat-completions':
            request.update(generation_options(self.handle.body))
        if len(json.dumps(request).encode()) > MAX_BYTES: raise ValueError('MODEL_REQUEST_TOO_LARGE')
        self.handle.check()
        lease = self.handle.credential()
        transport_factory = self.handle.service.transport_factory
        base = base_url(self.handle.body['baseURL'])
        headers = chat_headers(base, lease, session_id)
        if session_id == self.capability: raise ValueError('MODEL_SESSION_REJECTED')
        transport = (_SyntheticDispatchTransport(transport_factory(), on_dispatch) if transport_factory else PinnedChatTransport(
            model_origin(base), base_path=urlsplit(base).path, before_send=self.handle.check, on_dispatch=on_dispatch,
            trusted_proxy=getattr(self.handle, 'trusted_proxy', None), protocol=protocol))
        async with asyncio.timeout(120), httpx.AsyncClient(transport=transport, trust_env=False,
                follow_redirects=False, timeout=120) as client:
            self.handle.check()
            async with client.stream('POST', base + protocol_path(protocol), json=request,
                    headers=headers) as response:
                value = await read_response_json(response, lease)
        self.handle.check()
        value, record = decode_response(protocol, value)
        if record is not None:
            key = (session_id, scope, tuple(call['id'] for call in record['message']['tool_calls']))
            with self.lock:
                existing = self.continuations.get(key)
                if existing is not None and existing != record:
                    raise ValueError('MODEL_CONTINUATION_CONFLICT')
                if existing is None and len(self.continuations) >= self.continuation_limit:
                    raise ValueError('MODEL_CONTINUATION_LIMIT')
                self.continuations[key] = record
        return value

    def start(self):
        if sys.platform != 'linux': raise ValueError('ENVIRONMENT_PLATFORM_UNSUPPORTED')
        broker = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_): pass
            def do_POST(self):
                if self.path != '/v1/chat/completions': return self.reply(404, {'error': 'MODEL_ROUTE_UNAVAILABLE'})
                # Consume a bounded request before an authentication rejection.
                # Closing while http.client sends its body races the 401 and
                # turns a clear rejection into BrokenPipeError. Outer handler
                # slots and the socket deadline also bound unauthenticated IO.
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 1 <= length <= MAX_BYTES or self.headers.get('Transfer-Encoding'): raise ValueError()
                    raw = self.rfile.read(length)
                    if len(raw) != length: raise ValueError()
                except (ValueError, OSError):
                    return self.reply(400, {'error': 'MODEL_REQUEST_REJECTED'})
                token = self.headers.get('Authorization', '').removeprefix('Bearer ')
                if not broker.authorized(token): return self.reply(401, {'error': 'MODEL_CAPABILITY_EXPIRED'})
                # Pinned OpenCode's custom factory provider sends session-id;
                # its built-in Go provider sends session. Preserve the native
                # conversation, never substitute the secret broker capability.
                session_id = self.headers.get('x-opencode-session')
                native_session_id = self.headers.get('x-opencode-session-id')
                if (requires_session(broker.handle.body['baseURL']) and session_id and native_session_id
                        and session_id != native_session_id):
                    return self.reply(400, {'error': 'MODEL_SESSION_REJECTED'})
                session_id = session_id or native_session_id
                if not broker.gate.acquire(blocking=False): return self.reply(429, {'error': 'MODEL_BUSY'})
                try:
                    try: body = json.loads(raw)
                    except ValueError: return self.reply(400, OwnerModelCallError(False).response())
                    value = broker.native_completion(body, session_id, self.headers.get('x-opencode-request'))
                    if body.get('stream') is True:
                        choice = value['choices'][0]; message = choice['message']
                        delta = {'role': 'assistant', 'content': message.get('content')}
                        if message.get('tool_calls'):
                            delta['tool_calls'] = [dict(index=i, **call) for i, call in enumerate(message['tool_calls'])]
                        chunk = {'id': value.get('id', 'chatcmpl-owner'), 'object': 'chat.completion.chunk',
                            'created': value.get('created', int(time.time())), 'model': 'opencode-factory/owner-model',
                            'choices': [{'index': 0, 'delta': delta, 'finish_reason': None}]}
                        terminal = {**chunk, 'choices': [{'index': 0, 'delta': {}, 'finish_reason': choice.get('finish_reason', 'stop')}],
                            **({'usage': value['usage']} if 'usage' in value else {})}
                        payload = ('data: ' + json.dumps(chunk) + '\n\ndata: ' + json.dumps(terminal) + '\n\ndata: [DONE]\n\n').encode()
                        self.send_response(200); self.send_header('Content-Type', 'text/event-stream')
                        self.send_header('Content-Length', str(len(payload))); self.end_headers(); self.wfile.write(payload)
                    else: self.reply(200, value)
                except OwnerModelCallError as error:
                    # The pinned native harness retries every 5xx, independently
                    # of SDK retries=0. A possible paid dispatch must end here.
                    # 409 is also SDK-retryable; use 422 for an unconfirmed
                    # dispatch, with no retryable status/text in its payload.
                    self.reply(422 if error.code == 'OWNER_MODEL_CALL_UNCONFIRMED' else 400, error.response())
                except OSError:
                    # The recorded outcome survives a lost local socket reply.
                    pass
                finally: broker.gate.release()
            def reply(self, status, value):
                payload = json.dumps(value).encode()
                self.send_response(status); self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(payload))); self.end_headers(); self.wfile.write(payload)
        if self.path.exists() or self.path.is_symlink(): raise ValueError('MODEL_SOCKET_ALREADY_EXISTS')
        # Linux AF_UNIX has a 108-byte address limit. A held directory FD keeps
        # the same private inode custody even when the persistent workspace path
        # is long; no symlink, alternate listener or broader mount is introduced.
        descriptor = os.open(self.path.parent, getattr(os, 'O_DIRECTORY') | getattr(os, 'O_NOFOLLOW'))
        try:
            self.server = _Server(f'/proc/self/fd/{descriptor}/{self.path.name}', Handler)
            os.chmod(self.path.name, 0o600, dir_fd=descriptor, follow_symlinks=False)
            info = os.stat(self.path.name, dir_fd=descriptor, follow_symlinks=False)
            if not stat.S_ISSOCK(info.st_mode): raise ValueError('MODEL_SOCKET_INVALID')
            self.socket_identity = (info.st_dev, info.st_ino)
            self.directory_fd = descriptor
        except BaseException:
            if self.server is not None: self.server.server_close()
            os.close(descriptor)
            raise
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()

    def close(self):
        self.deadline = 0
        if self.server is not None:
            self.server.shutdown(); self.server.server_close()
            self.server = None
        if self.thread is not None:
            self.thread.join(timeout=2); self.thread = None
        descriptor, self.directory_fd = self.directory_fd, None
        if descriptor is not None:
            try:
                try: info = os.stat(self.path.name, dir_fd=descriptor, follow_symlinks=False)
                except FileNotFoundError: return
                if stat.S_ISSOCK(info.st_mode) and (info.st_dev, info.st_ino) == self.socket_identity:
                    os.unlink(self.path.name, dir_fd=descriptor)
            finally: os.close(descriptor)
