"""Owner-funded protocol boundary for a private application runtime.

The selected application runtime and its declared harness own the tool loop. Only a short-lived local capability enters that container; each model
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
    base_url, chat_headers, continuation_scope, generation_options, max_output_tokens, model_origin, requires_session,
)
from .model_protocol import (
    assistant_message_matches, decode_response, encode_request, function_call, protocol_name, protocol_path,
)
from .model_transport import MAX_BYTES, PinnedChatTransport, read_response_json
from .personal_remote_provider import reject_credential_echo


# The inert base keeps host imports possible where AF_UNIX is unsupported.
# start() rejects those hosts before constructing any listener.
UnixServerBase: Any = getattr(socketserver, 'UnixStreamServer', object)


class OwnerModelCallError(ValueError):
    """Sanitized, non-retryable native outcome; never carries provider text."""
    def __init__(self, dispatched, *, diagnostic_id=None, terminal_reason=None):
        self.code = 'OWNER_MODEL_CALL_UNCONFIRMED' if dispatched else 'OWNER_MODEL_REQUEST_REJECTED'
        # OpenCode also scans response text for 5xx numerals. An alphabetic ID
        # cannot accidentally turn a terminal rejection into a retryable error.
        self.diagnostic_id = diagnostic_id or 'diag_' + ''.join(chr(97 + int(c, 16)) for c in secrets.token_hex(16))
        self.terminal_reason = terminal_reason if terminal_reason in {'MODEL_EMPTY_OUTPUT', 'MODEL_REFUSAL'} else None
        super().__init__(self.code)

    def response(self):
        message = ('模型调用可能已发出，结果尚未确认；请保留原请求核对。' if self.code == 'OWNER_MODEL_CALL_UNCONFIRMED'
                   else '模型请求在发送前被拒绝；请核对配置与权限。')
        return {'error': {'message': message + ' 诊断编号：' + self.diagnostic_id,
            'type': 'owner_model_boundary', 'code': self.code,
            **({'terminalReason': self.terminal_reason} if self.terminal_reason else {})}, 'diagnosticId': self.diagnostic_id}


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
        self.error: tuple[str, str, str | None] | None = None


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
        # Assistant reasoning stays outside the native container. The broker lifetime,
        # call count and bounded response reader bound this cache; never evict a
        # continuation and silently resume a tool call without its reasoning.
        self.continuation_limit = max_calls
        self.continuations: dict[tuple, dict] = {}
        # One bounded, verified transcript per scoped session, with references
        # to immutable continuation records. Positions align retained suffixes;
        # they are never the identity of an assistant or its private reasoning.
        self.histories: dict[tuple[str | None, str], dict] = {}
        self.history_inflight: set[tuple[str | None, str]] = set()

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
                record.error = (error.code, error.diagnostic_id, error.terminal_reason)
            except (Exception, asyncio.CancelledError):
                error = OwnerModelCallError(True)
                record.error = (error.code, error.diagnostic_id, error.terminal_reason)
            finally:
                # Record before writing any local response. A lost downstream
                # reply may be read again, but can never dispatch again.
                record.done.set()
        elif not record.done.wait(timeout=120):
            raise OwnerModelCallError(True)
        if record.error is not None:
            code, diagnostic_id, terminal_reason = record.error
            raise OwnerModelCallError(code == 'OWNER_MODEL_CALL_UNCONFIRMED', diagnostic_id=diagnostic_id,
                terminal_reason=terminal_reason)
        if record.value is None: raise OwnerModelCallError(True)
        try:
            self.handle.check()
            reject_credential_echo(record.value, self.handle.credential())
        except Exception:
            raise OwnerModelCallError(False) from None
        return deepcopy(record.value)

    async def completion(self, body, session_id=None):
        dispatched = False
        reserved = None
        def on_dispatch():
            nonlocal dispatched
            dispatched = True
        try:
            key = (session_id, continuation_scope(self.handle.body, getattr(self.handle, 'owner', None)))
            with self.lock:
                if key in self.history_inflight:
                    raise OwnerModelCallError(False)
                self.history_inflight.add(key)
                reserved = key
            return await self._completion(body, session_id, on_dispatch)
        except OwnerModelCallError:
            raise
        except Exception:
            raise OwnerModelCallError(dispatched) from None
        finally:
            if reserved is not None:
                with self.lock:
                    self.history_inflight.discard(reserved)

    @staticmethod
    def _same_message(expected, actual):
        if expected.get('role') == actual.get('role') == 'assistant':
            return assistant_message_matches(expected, actual)
        return expected == actual

    def _history(self, encoded, session_id, scope, *, tools, require_text):
        """Associate a native transcript with previously verified records.

        OpenCode sends compaction as a separate user-only, no-tools request,
        then projects its answer before a retained suffix of the old history.
        Anchor that suffix at the original end, not at matching text or an
        assistant ordinal. Identical final answers keep their distinct records.
        """
        current = [message for message in encoded if message['role'] != 'system']
        state = self.histories.get((session_id, scope))
        previous = state['transcript'] if state else []
        mapped = [None] * len(current)
        verified_prefix = 0
        parent = None
        if not any(message['role'] == 'assistant' for message in current):
            if state and state['summary_parent'] is not None:
                # Wire messages carry no native summary ID. Do not replace an
                # unconsumed summary with another possibly identical answer.
                raise ValueError('MODEL_CONTINUATION_REQUIRED')
            if not tools and len(current) == 1 and current[0]['role'] == 'user' and state:
                parent = previous
            elif state:
                raise ValueError('MODEL_CONTINUATION_REQUIRED')
        elif previous and len(current) >= len(previous) and all(
                self._same_message(item['message'], message) for item, message in zip(previous, current)):
            mapped[:len(previous)] = [item['record'] for item in previous]
            verified_prefix = len(previous)
        elif state and state['summary_parent'] is not None:
            # Only the just-produced summary can introduce a reordered tail.
            # Native replaces the summary's input prompt with a user marker.
            old = state['summary_parent']
            if (len(current) < 2 or current[0]['role'] != 'user'
                    or not self._same_message(previous[-1]['message'], current[1])):
                raise ValueError('MODEL_CONTINUATION_REQUIRED')
            last = max(index for index, message in enumerate(current) if message['role'] == 'assistant')
            tail = current[2:last + 1]
            retained = old[len(old) - len(tail):] if tail else []
            if len(tail) > len(old) or not all(
                    self._same_message(item['message'], message) for item, message in zip(retained, tail)):
                raise ValueError('MODEL_CONTINUATION_REQUIRED')
            mapped[1] = previous[-1]['record']
            mapped[2:last + 1] = [item['record'] for item in retained]
            verified_prefix = last + 1
        elif state and any(message['role'] == 'assistant' and not message.get('tool_calls') for message in current):
            # A changed prefix must not turn known final reasoning into an
            # unmarked text answer and overwrite the verified active history.
            raise ValueError('MODEL_CONTINUATION_REQUIRED')
        continuation, transcript, position = [], [], 0
        for index, message in enumerate(encoded):
            if message['role'] == 'system':
                continue
            key = mapped[position]
            position += 1
            if message['role'] == 'assistant':
                if state and key is None and position > verified_prefix and not message.get('tool_calls'):
                    raise ValueError('MODEL_CONTINUATION_REQUIRED')
                if key is None and message.get('tool_calls'):
                    key = (session_id, scope, ('tools', *(call['id'] for call in message['tool_calls'])))
                required = bool(message.get('tool_calls')) or require_text
                if key is not None:
                    # A transcript reference never authorizes a different owner,
                    # configuration revision, destination, protocol or session.
                    if key[:2] != (session_id, scope):
                        raise ValueError('MODEL_CONTINUATION_REQUIRED')
                    entry = self.continuations.get(key)
                    if entry is None or not assistant_message_matches(entry['message'], message):
                        raise ValueError('MODEL_CONTINUATION_REQUIRED')
                    if entry['continuation'] is not None:
                        continuation.append({**deepcopy(entry['continuation']), 'message_index': index})
                elif required:
                    raise ValueError('MODEL_CONTINUATION_REQUIRED')
            transcript.append({'message': deepcopy(message), 'record': key})
        return continuation, transcript, parent

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
        if protocol == 'responses' and (type(session_id) is not str
                or not re.fullmatch(r'ses_[A-Za-z0-9]{8,120}', session_id)):
            raise ValueError('MODEL_SESSION_REJECTED')
        with self.lock:
            if len(self.continuations) >= self.continuation_limit:
                raise ValueError('MODEL_CONTINUATION_LIMIT')
            continuation, transcript, parent = self._history(encoded, session_id, scope,
                tools=bool(body.get('tools')), require_text=protocol == 'chat-completions' and bool(body.get('tools')))
        chat = {'model': self.handle.body['model'], 'messages': encoded,
            'max_tokens': max_output_tokens(self.handle.body), 'stream': False}
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
        try:
            value, record = decode_response(protocol, value)
        except ValueError as error:
            reason = {'MODEL_PROTOCOL_EMPTY_OUTPUT': 'MODEL_EMPTY_OUTPUT',
                'MODEL_PROTOCOL_REFUSAL': 'MODEL_REFUSAL'}.get(str(error))
            if reason:
                raise OwnerModelCallError(True, terminal_reason=reason) from None
            raise
        message = value['choices'][0]['message']
        calls = message.get('tool_calls', [])
        if parent is not None and calls:
            raise ValueError('MODEL_CONTINUATION_REQUIRED')
        identity = ('tools', *(call['id'] for call in calls)) if calls else ('text', secrets.token_hex(16))
        key = (session_id, scope, identity)
        entry = {'message': message, 'continuation': record}
        with self.lock:
            existing = self.continuations.get(key)
            if existing is not None and existing != entry:
                raise ValueError('MODEL_CONTINUATION_CONFLICT')
            if existing is None and len(self.continuations) >= self.continuation_limit:
                raise ValueError('MODEL_CONTINUATION_LIMIT')
            self.continuations[key] = entry
            self.histories[(session_id, scope)] = {'transcript': [*transcript,
                {'message': deepcopy(message), 'record': key}], 'summary_parent': parent}
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
