"""Owner-funded Chat Completions boundary for a private application runtime.

No research controller lives here. Original ORX and its declared harness own the
tool loop. Only a short-lived local capability enters that container; each model
call resolves the original owner/vault revision outside it, without fallback.
"""
import asyncio
import hmac
from http.server import BaseHTTPRequestHandler
import json
import os
from pathlib import Path
import secrets
from socketserver import ThreadingMixIn, UnixStreamServer
import threading
import time

import httpx

from .byok_model import MAX_BYTES, PinnedChatTransport, function_call
from .personal_remote_provider import reject_credential_echo


class _Server(ThreadingMixIn, UnixStreamServer):
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
        self.capability = secrets.token_urlsafe(32)
        self.deadline, self.remaining = time.monotonic() + ttl, max_calls
        self.lock = threading.Lock(); self.gate = threading.BoundedSemaphore(4)
        self.server = None; self.thread = None

    def __repr__(self): return 'OwnerRuntimeBroker(capability=<redacted>)'

    def authorized(self, token):
        return type(token) is str and hmac.compare_digest(token, self.capability) and time.monotonic() < self.deadline

    async def completion(self, body):
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
        request = {'model': self.handle.body['model'], 'messages': encoded, 'max_tokens': 4096, 'stream': False}
        if body.get('tools'):
            if type(body['tools']) is not list or len(body['tools']) > 64 or any(type(tool) is not dict
                    or tool.get('type') != 'function' or type(tool.get('function')) is not dict for tool in body['tools']):
                raise ValueError('MODEL_FUNCTION_TOOLS_ONLY')
            request.update(tools=body['tools'], parallel_tool_calls=False)
        if len(json.dumps(request).encode()) > MAX_BYTES: raise ValueError('MODEL_REQUEST_TOO_LARGE')
        self.handle.check()
        lease = self.handle.credential()
        transport_factory = self.handle.service.transport_factory
        base = self.handle.body['baseURL']
        transport = transport_factory() if transport_factory else PinnedChatTransport(base[:-3], before_send=self.handle.check)
        async with asyncio.timeout(120), httpx.AsyncClient(transport=transport, trust_env=False,
                follow_redirects=False, timeout=120) as client:
            self.handle.check()
            async with client.stream('POST', base + '/chat/completions', json=request,
                    headers={'Authorization': 'Bearer ' + lease.password, 'Accept-Encoding': 'identity'}) as response:
                if response.status_code != 200 or response.headers.get('content-encoding', 'identity') != 'identity':
                    raise ValueError('MODEL_REQUEST_FAILED')
                chunks, size = [], 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_BYTES: raise ValueError('MODEL_RESPONSE_TOO_LARGE')
                    chunks.append(chunk)
                value = json.loads(b''.join(chunks))
                reject_credential_echo(value, lease)
        self.handle.check()
        if type(value) is not dict or type(value.get('choices')) is not list or len(value['choices']) != 1:
            raise ValueError('MODEL_RESPONSE_REJECTED')
        message = value['choices'][0].get('message')
        if type(message) is not dict or message.get('role') != 'assistant' or message.get('content') is not None and type(message['content']) is not str:
            raise ValueError('MODEL_RESPONSE_REJECTED')
        if message.get('tool_calls'):
            message['tool_calls'] = [function_call(call) for call in message['tool_calls']]
        return value

    def start(self):
        broker = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_): pass
            def do_POST(self):
                if self.path != '/v1/chat/completions': return self.reply(404, {'error': 'MODEL_ROUTE_UNAVAILABLE'})
                token = self.headers.get('Authorization', '').removeprefix('Bearer ')
                if not broker.authorized(token): return self.reply(401, {'error': 'MODEL_CAPABILITY_EXPIRED'})
                if not broker.gate.acquire(blocking=False): return self.reply(429, {'error': 'MODEL_BUSY'})
                try:
                    with broker.lock:
                        if broker.remaining <= 0: return self.reply(429, {'error': 'MODEL_CALL_LIMIT'})
                        broker.remaining -= 1
                    self.connection.settimeout(10)
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 1 <= length <= MAX_BYTES or self.headers.get('Transfer-Encoding'): raise ValueError()
                    body = json.loads(self.rfile.read(length))
                    value = asyncio.run(broker.completion(body))
                    if body.get('stream') is True:
                        choice = value['choices'][0]; message = choice['message']
                        delta = {'role': 'assistant', 'content': message.get('content')}
                        if message.get('tool_calls'):
                            delta['tool_calls'] = [dict(index=i, **call) for i, call in enumerate(message['tool_calls'])]
                        chunk = {'id': value.get('id', 'chatcmpl-owner'), 'object': 'chat.completion.chunk',
                            'created': value.get('created', int(time.time())), 'model': 'factory/owner-model',
                            'choices': [{'index': 0, 'delta': delta, 'finish_reason': None}]}
                        terminal = {**chunk, 'choices': [{'index': 0, 'delta': {}, 'finish_reason': choice.get('finish_reason', 'stop')}],
                            **({'usage': value['usage']} if 'usage' in value else {})}
                        payload = ('data: ' + json.dumps(chunk) + '\n\ndata: ' + json.dumps(terminal) + '\n\ndata: [DONE]\n\n').encode()
                        self.send_response(200); self.send_header('Content-Type', 'text/event-stream')
                        self.send_header('Content-Length', str(len(payload))); self.end_headers(); self.wfile.write(payload)
                    else: self.reply(200, value)
                except Exception: self.reply(502, {'error': 'OWNER_MODEL_CALL_UNCONFIRMED'})
                finally: broker.gate.release()
            def reply(self, status, value):
                payload = json.dumps(value).encode()
                self.send_response(status); self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(payload))); self.end_headers(); self.wfile.write(payload)
        if self.path.exists() or self.path.is_symlink(): raise ValueError('MODEL_SOCKET_ALREADY_EXISTS')
        # Linux AF_UNIX has a 108-byte address limit. A held directory FD keeps
        # the same private inode custody even when the persistent workspace path
        # is long; no symlink, alternate listener or broader mount is introduced.
        descriptor = os.open(self.path.parent, os.O_DIRECTORY | os.O_NOFOLLOW)
        try: self.server = _Server(f'/proc/self/fd/{descriptor}/{self.path.name}', Handler)
        finally: os.close(descriptor)
        self.path.chmod(0o600)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()

    def close(self):
        self.deadline = 0
        if self.server is not None:
            self.server.shutdown(); self.server.server_close()
        if self.thread is not None: self.thread.join(timeout=2)
        if self.path.exists(): self.path.unlink()
