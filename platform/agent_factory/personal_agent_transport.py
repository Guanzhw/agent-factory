"""Ordinary OpenCode HTTP contract, isolated from managed workload execution.

Official APIs: https://opencode.ai/docs/server/ (checked 2026-10-08).
No provider/model credential API, shell, permission approval, redirects or retries.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
import json
import re
import secrets
import socket
import threading
import time
from typing import Callable
from urllib.parse import urlsplit

from .personal_remote_provider import (OpenCodeServeProvider, PinnedHTTPSProbe,
    RemoteConnectionError, SecretLease, _PinnedHTTPS, origin, MAX_BYTES, HTTP_TOTAL_SECONDS, reject_credential_echo)

PERSONAL_CONTRACT = 'personal-external-v1'
PERSONAL_PROVIDER_ID = 'opencode-personal-session-v1'
PERSONAL_CAPABILITIES = frozenset({'runtime:health', 'project:read', 'agent:read',
    'session:read', 'session:create', 'session:prompt', 'session:interrupt'})
_ID = r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}'


def native_id(value):
    if not isinstance(value, str) or not re.fullmatch(_ID, value):
        raise RemoteConnectionError('PERSONAL_NATIVE_ID_INVALID')
    return value


_message_lock = threading.Lock()
_message_tick = 0


def message_id():
    """OpenCode's timestamp-ordered client ID shape, not random UUID ordering.

    Reference: packages/opencode/src/id/id.ts. Clocks should be synchronized,
    as for upstream clients; an ID is correlation, never an execution receipt.
    """
    global _message_tick
    with _message_lock:
        _message_tick = max(int(time.time() * 1000) * 4096, _message_tick + 1)
        prefix = format(_message_tick & ((1 << 48) - 1), '012x')
    alphabet = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'
    return 'msg_' + prefix + ''.join(secrets.choice(alphabet) for _ in range(14))


class PersonalAgentTransport(PinnedHTTPSProbe):
    """Fixed allowlist, fresh DNS pin, TLS/SNI verification and total IO deadline."""
    @staticmethod
    def allows(method, path, payload):
        read = path in {'/project/current', '/session/status', '/session'} or re.fullmatch(
            rf'/session/{_ID}(?:/message(?:/{_ID})?)?', path)
        write = path == '/session' or re.fullmatch(rf'/session/{_ID}/(?:prompt_async|abort)', path)
        return bool((method == 'GET' and read and payload is None) or (method == 'POST' and write))

    @staticmethod
    def anonymous_allowed(method, path):
        return False

    @staticmethod
    def authorization_header(lease):
        return 'Basic ' + base64.b64encode((lease.username + ':' + lease.password).encode()).decode()

    def request(self, destination, address, method, path, lease, payload=None):
        if not self.allows(method, path, payload):
            raise RemoteConnectionError('REMOTE_PATH_DENIED')
        if not isinstance(lease, SecretLease) and not (lease is None and self.anonymous_allowed(method, path)):
            raise RemoteConnectionError('REMOTE_CREDENTIAL_UNAVAILABLE')
        host = urlsplit(origin(destination)).hostname
        if not self.policy.permits(host, address):
            raise RemoteConnectionError('REMOTE_ADDRESS_DENIED')
        raw = None if payload is None else json.dumps(payload, allow_nan=False, separators=(',', ':')).encode()
        if raw is not None and len(raw) > 65536:
            raise RemoteConnectionError('REMOTE_REQUEST_REJECTED')
        headers = {'Accept': 'application/json', 'Accept-Encoding': 'identity',
            'Content-Type': 'application/json'}
        if lease is not None:
            headers['Authorization'] = self.authorization_header(lease)
        conn = _PinnedHTTPS(host, address)
        deadline = time.monotonic() + HTTP_TOTAL_SECONDS
        conn.deadline = deadline
        expired = threading.Event()
        active: list[socket.socket | None] = [None]
        def interrupt():
            expired.set()
            sock = active[0] or conn.sock
            if sock is not None:
                try: sock.shutdown(socket.SHUT_RDWR)
                except OSError: pass
            conn.close()
        timer = threading.Timer(HTTP_TOTAL_SECONDS, interrupt)
        timer.daemon = True
        timer.start()
        response = None
        try:
            conn.request(method, path, body=raw, headers=headers)
            active[0] = conn.sock
            response = conn.getresponse()
            chunks, size = [], 0
            while size <= MAX_BYTES:
                if expired.is_set() or time.monotonic() >= deadline:
                    raise RemoteConnectionError('REMOTE_DEADLINE')
                chunk = response.read1(min(16384, MAX_BYTES + 1 - size))
                if not chunk: break
                chunks.append(chunk)
                size += len(chunk)
            if size > MAX_BYTES or response.getheader('Content-Encoding', 'identity') != 'identity':
                raise RemoteConnectionError('REMOTE_RESPONSE_REJECTED')
            if expired.is_set() or time.monotonic() >= deadline:
                raise RemoteConnectionError('REMOTE_DEADLINE')
            if response.status not in {200, 204}: return response.status, None
            if response.status == 204: return 204, None
            def unique(pairs):
                result = {}
                for key, value in pairs:
                    if key in result: raise ValueError()
                    result[key] = value
                return result
            def invalid(value): raise ValueError()
            value = json.loads(b''.join(chunks), object_pairs_hook=unique, parse_constant=invalid)
            reject_credential_echo(value, lease)
            return response.status, value
        except RemoteConnectionError:
            raise
        except Exception:
            raise RemoteConnectionError('PERSONAL_REMOTE_IO_UNKNOWN') from None
        finally:
            timer.cancel(); timer.join()
            if response is not None: response.close()
            conn.close()


class PersonalOpenCodeServeProvider(OpenCodeServeProvider):
    """Operator-installed ordinary contract. No user flag weakens managed plans."""
    provider_id = PERSONAL_PROVIDER_ID
    capabilities = PERSONAL_CAPABILITIES

    def __init__(self, secrets, *, transport=None, **kwargs):
        super().__init__(secrets, **kwargs)
        self.transport = transport or PersonalAgentTransport(kwargs.get('network_policy'))

    def handle(self, owner, configuration):
        return PersonalAgentHandle(self, owner, dict(configuration))


@dataclass(frozen=True, repr=False)
class PersonalAgentHandle:
    namespace = 'opencode'
    provider: PersonalOpenCodeServeProvider
    owner: str
    configuration: dict
    recheck: Callable | None = field(default=None, repr=False)

    def guarded(self, recheck):
        return PersonalAgentHandle(self.provider, self.owner, self.configuration, recheck)

    def _check(self, capabilities):
        if self.recheck is None:
            raise RemoteConnectionError('PERSONAL_GUARD_REQUIRED')
        self.recheck(capabilities)
        if not self.provider.authorized(self.owner, self.configuration):
            raise RemoteConnectionError('REMOTE_CREDENTIAL_UNAVAILABLE')

    def call(self, method, path, payload=None, *, before_send=None):
        if method == 'GET' and path == '/project/current':
            required = ('project:read',)
        elif method == 'GET' and (path in {'/session/status', '/session'} or re.fullmatch(rf'/session/{_ID}(?:/message(?:/{_ID})?)?', path)):
            required = ('session:read',)
        elif method == 'POST' and path == '/session':
            required = ('session:create',)
        elif method == 'POST' and re.fullmatch(rf'/session/{_ID}/prompt_async', path):
            required = ('session:prompt',)
        elif method == 'POST' and re.fullmatch(rf'/session/{_ID}/abort', path):
            required = ('session:interrupt',)
        else:
            raise RemoteConnectionError('REMOTE_PATH_DENIED')
        self._check(required)
        if method == 'POST' and not callable(before_send):
            raise RemoteConnectionError('PERSONAL_TRUSTED_SEND_GUARD_REQUIRED')
        destination = self.configuration['origin']
        addresses = self.provider.transport.addresses(destination)
        lease = self.provider.secrets.resolve(**self.provider._scope(self.owner, self.configuration))
        self._check(required)  # Revoke/rotation fence after DNS and credential retrieval.
        if method == 'POST':
            assert before_send is not None
            before_send()
            self._check(required)
        status, result = self.provider.transport.request(destination, addresses[0], method, path, lease, payload)
        reject_credential_echo(result, lease)  # Also covers operator-injected transport implementations.
        self._check(required)  # Never publish a response under stale authority.
        expected_status = 204 if method == 'POST' and path.endswith('/prompt_async') else 200
        if status != expected_status:
            raise RemoteConnectionError('PERSONAL_REMOTE_RESPONSE_REJECTED')
        return result

    def inspect_identity(self):
        self._check(('runtime:health', 'project:read', 'agent:read'))
        result = self.provider.verify(self.owner, self.configuration)
        self._check(('runtime:health', 'project:read', 'agent:read'))
        return result

    def project(self):
        value = self.call('GET', '/project/current')
        if not isinstance(value, dict) or value.get('id') != self.configuration['projectId']:
            raise RemoteConnectionError('REMOTE_IDENTITY_MISMATCH')
        return {'nativeProjectId': native_id(value['id']), 'namespace': 'opencode',
            'executionContract': PERSONAL_CONTRACT}

    def session(self, identifier):
        value = self.call('GET', '/session/' + native_id(identifier))
        return self.validate_session(value, identifier)

    def validate_session(self, value, identifier=None):
        if (not isinstance(value, dict) or value.get('projectID') != self.configuration['projectId']
                or identifier is not None and value.get('id') != identifier):
            raise RemoteConnectionError('REMOTE_IDENTITY_MISMATCH')
        return {'nativeSessionId': native_id(value.get('id')), 'nativeProjectId': value['projectID']}

    def list_sessions(self):
        values = self.call('GET', '/session')
        if not isinstance(values, list) or len(values) > 2048:
            raise RemoteConnectionError('PERSONAL_SESSIONS_INVALID')
        result = []
        for value in values:
            if not isinstance(value, dict): raise RemoteConnectionError('PERSONAL_SESSIONS_INVALID')
            if value.get('projectID') != self.configuration['projectId']: continue
            result.append({**self.validate_session(value), 'namespace': self.namespace,
                'title': str(value.get('title', ''))[:120]})
        return result

    @staticmethod
    def new_turn_id():
        return message_id()

    def validate_agent(self, agent):
        if agent is not None and agent not in self.inspect_identity()['agentNames']:
            raise RemoteConnectionError('PERSONAL_AGENT_UNAVAILABLE')

    def create_session(self, title, *, before_send):
        return self.validate_session(self.call('POST', '/session', {'title': title}, before_send=before_send))

    def prompt_session(self, session_id, text, agent, message_id, *, before_send):
        payload = {'messageID': message_id, 'parts': [{'type': 'text', 'text': text}]}
        if agent is not None: payload['agent'] = agent
        self.call('POST', '/session/' + native_id(session_id) + '/prompt_async', payload, before_send=before_send)
        return {'nativeMessageId': message_id, 'status': 'accepted'}

    def interrupt_session(self, session_id, *, before_send):
        self.call('POST', '/session/' + native_id(session_id) + '/abort', {}, before_send=before_send)
        return {'status': 'interrupt_requested_stop_unverified', 'stopVerified': False}

    def observe_session(self, session_id):
        from .personal_agent_sessions import project_messages
        return project_messages(self.call('GET', '/session/' + native_id(session_id) + '/message'), session_id)

    @staticmethod
    def result_matches(observation, command):
        return any(m['role'] == 'assistant' and m['parentId'] == command['intent']['nativeMessageId']
            and m['terminalResult'] for m in observation['messages'])
