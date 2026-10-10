"""Ordinary owner-funded native OpenResearch project/session transport.

Pinned source: alphaXiv/OpenResearch f336b121 src/commands/up.rs and
src/local/chat/mod.rs. Upstream owns projects, sessions, harnesses and tool loops.
This adapter creates no Factory model key, workload loop or playbook. Project
creation requires a separate explicit creation-only configuration and plan.
Use the shared PersonalAgentSessions durable command owner: no replay after
unknown acknowledgement. Usage is unavailable/remote-reported, budgets advisory,
and native idle/interrupt acknowledgements are never process-stop proof.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import hashlib
import re
import secrets
from typing import Any, Callable, cast
from urllib.parse import parse_qs, urlencode, urlsplit

from .personal_agent_transport import PersonalAgentTransport, PERSONAL_CONTRACT, native_id
from .personal_remote_provider import OpenCodeServeProvider, RemoteConnectionError, SecretLease, origin, reject_credential_echo
from .orx_research_session import OpenResearchSessionHTTP, UPSTREAM_COMMIT
from .store import digest

PERSONAL_ORX_PROVIDER_ID = 'openresearch-personal-session-v1'
CAPABILITIES = frozenset({'runtime:health', 'project:read', 'agent:read', 'session:read',
    'session:create', 'session:prompt', 'session:interrupt'})
_ID = r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}'


def require(value, code='PERSONAL_ORX_RESPONSE_INVALID'):
    if not value:
        raise RemoteConnectionError(code)


class PersonalOrxHTTPS(PersonalAgentTransport):
    """Shared TLS/DNS/response bounds, with only actual pinned native routes."""
    def __init__(self, policy=None, *, auth_mode):
        super().__init__(policy)
        require(auth_mode in {'bearer', 'basic-proxy'}, 'PERSONAL_ORX_AUTH_MODE_REQUIRED')
        self._auth_mode = auth_mode

    @staticmethod
    def anonymous_allowed(method, path):
        return method == 'GET' and path == '/api/health'

    @staticmethod
    def allows(method, path, payload):
        parsed = urlsplit(path)
        if parsed.scheme or parsed.netloc or parsed.fragment or '%' in parsed.path:
            return False
        route = parsed.path
        if parsed.query:
            try:
                query = parse_qs(parsed.query, strict_parsing=True)
            except ValueError:
                return False
            return bool(method == 'GET' and route == '/api/chat/sessions' and payload is None
                and set(query) == {'projectId'} and len(query['projectId']) == 1
                and re.fullmatch(_ID, query['projectId'][0]))
        if method == 'GET' and payload is None:
            return bool(route in {'/api/health', '/api/projects'} or re.fullmatch(rf'/api/projects/{_ID}', route)
                or re.fullmatch(rf'/api/chat/sessions/{_ID}/messages', route))
        if method == 'POST':
            if route == '/api/projects':
                from .personal_orx_projects import valid_native_request
                return valid_native_request(payload)
            return bool(route == '/api/chat/sessions' or re.fullmatch(rf'/api/chat/sessions/{_ID}/(?:message|interrupt)', route))
        return bool(method == 'PATCH' and re.fullmatch(rf'/api/chat/sessions/{_ID}', route)
                    and isinstance(payload, dict) and set(payload) == {'title'})

    def authorization_header(self, lease):
        require(isinstance(lease, SecretLease), 'REMOTE_CREDENTIAL_UNAVAILABLE')
        if self._auth_mode == 'bearer':
            # Explicit service token mode. No provider/model credential is used.
            require(all(33 <= ord(c) <= 126 for c in lease.password), 'REMOTE_CREDENTIAL_UNAVAILABLE')
            return 'Bearer ' + lease.password
        return super().authorization_header(lease)


class PersonalOrxProvider(OpenCodeServeProvider):
    provider_id = PERSONAL_ORX_PROVIDER_ID
    kind = 'orx'
    namespace = 'native-openresearch'
    required_execution_contract = PERSONAL_CONTRACT
    capabilities = CAPABILITIES
    auth_modes = ('bearer', 'basic-proxy')
    session_template_supported = True

    def __init__(self, secrets, *, transport=None, **kwargs):
        super().__init__(secrets, **kwargs)
        self._transports = {mode: transport or PersonalOrxHTTPS(kwargs.get('network_policy'), auth_mode=mode)
                            for mode in self.auth_modes}

    @staticmethod
    def configure(configuration):
        creation = type(configuration) is dict and configuration.get('projectCreation') is True
        required = {'origin', 'credentialRef', 'credentialRevision', 'authMode'} | (set() if creation else {'projectId'})
        require(isinstance(configuration, dict) and required <= set(configuration)
                and set(configuration) <= required | ({'projectCreation', 'projectId'} if creation else {'sessionTemplateId', 'sessionDefaults'}), 'REMOTE_CONFIGURATION_INVALID')
        require(not creation or configuration.get('projectId', '') == '', 'REMOTE_CONFIGURATION_INVALID')
        require(configuration['authMode'] in {'bearer', 'basic-proxy'}, 'PERSONAL_ORX_AUTH_MODE_REQUIRED')
        from .connections import _identifier
        try:
            result = {'origin': origin(configuration['origin']), 'authMode': configuration['authMode'],
                **{key: _identifier(configuration[key]) for key in ('credentialRef', 'credentialRevision')}}
            if creation:
                return {**result, 'projectCreation': True, 'projectId': ''}
            result['projectId'] = _identifier(configuration['projectId'])
            require(re.fullmatch(_ID, result['projectId']))
            if 'sessionTemplateId' in configuration:
                result['sessionTemplateId'] = native_id(configuration['sessionTemplateId'])
                require(re.fullmatch(_ID, result['sessionTemplateId']))
            if 'sessionDefaults' in configuration:
                defaults = configuration['sessionDefaults']
                require(type(defaults) is dict and set(defaults) == {'harness', 'model'}, 'REMOTE_CONFIGURATION_INVALID')
                require(defaults['harness'] in {'codex', 'opencode', 'claude-code'} and type(defaults['model']) is str
                    and 0 < len(defaults['model']) <= 200 and defaults['model'] == defaults['model'].strip(), 'REMOTE_CONFIGURATION_INVALID')
                require('sessionTemplateId' not in configuration, 'REMOTE_CONFIGURATION_INVALID')
                result['sessionDefaults'] = dict(defaults)
            return result
        except (TypeError, ValueError):
            raise RemoteConnectionError('REMOTE_CONFIGURATION_INVALID') from None

    def transport(self, configuration):
        return self._transports[configuration['authMode']]

    def effective_capabilities(self, configuration):
        return frozenset({'runtime:health', 'project:read', 'project:create'}) if configuration.get('projectCreation') else self.capabilities

    def verify(self, owner, configuration):
        config = self.configure(configuration)
        require(self.authorized(owner, config), 'REMOTE_CREDENTIAL_UNAVAILABLE')
        transport = self.transport(config)
        address = transport.addresses(config['origin'])[0]
        status, _ = transport.request(config['origin'], address, 'GET', '/api/health', None)
        require(status == 401, 'REMOTE_AUTH_REQUIRED')
        credential = self.secrets.resolve(**self._scope(owner, config))
        require(isinstance(credential, SecretLease) and self.authorized(owner, config), 'REMOTE_CREDENTIAL_UNAVAILABLE')
        status, health = transport.request(config['origin'], address, 'GET', '/api/health', credential)
        reject_credential_echo(health, credential)
        require(status == 200 and type(health) is dict and health.get('ok') is True
            and health.get('version') == '0.2.13' and type(health.get('dashboardProtocol')) is int
            and health['dashboardProtocol'] == 2, 'PERSONAL_ORX_VERSION_UNSUPPORTED')
        instance = health.get('instanceId')
        require(instance is None or isinstance(instance, str) and re.fullmatch(_ID, instance))
        require(self.authorized(owner, config), 'REMOTE_CREDENTIAL_UNAVAILABLE')
        creation = config.get('projectCreation') is True
        status, value = transport.request(config['origin'], address, 'GET', '/api/projects' if creation else '/api/projects/' + config['projectId'], credential)
        reject_credential_echo(value, credential)
        require(status == 200 and type(value) is dict, 'REMOTE_IDENTITY_MISMATCH')
        value = cast(dict[str, Any], value)
        if creation:
            require(type(value.get('projects')) is list and len(value['projects']) <= 2048, 'REMOTE_IDENTITY_MISMATCH')
        else:
            require(type(value.get('project')) is dict and value['project'].get('id') == config['projectId'], 'REMOTE_IDENTITY_MISMATCH')
        require(self.authorized(owner, config), 'REMOTE_CREDENTIAL_UNAVAILABLE')
        return {'providerVersion': health['version'], 'dashboardProtocol': 2, 'instanceId': instance,
            'projectId': config['projectId'], 'namespace': self.namespace, 'capabilities': sorted(self.effective_capabilities(config)),
            'agentNames': [], 'identityBasis': 'tls-origin-service-auth-native-project',
            'contractSourceRevision': UPSTREAM_COMMIT, 'sourceRevisionVerified': False,
            'budgetEnforcement': 'advisory', 'stopVerified': False, 'liveEndToEndVerified': False}

    def handle(self, owner, configuration):
        return PersonalOrxHandle(self, owner, self.configure(configuration))


class _NativeSessionClient(OpenResearchSessionHTTP):
    """Reuse pinned session wire validation; IO stays in the shared HTTPS guard."""
    def __init__(self, handle, row, before_send=None):
        self._handle, self._before_send = handle, before_send
        self._base = handle.configuration['origin']
        self.project_id = row['projectId']
        self.harness, self.model = row['harness'], row.get('model')
        self.permission_mode, self.service_tier = row.get('permissionMode'), row.get('serviceTier')
        self.reasoning_level, self.plan_mode = row.get('reasoningLevel'), row.get('planMode')

    async def _request(self, method, path, *, body=None, params=None):
        if params:
            path += '?' + urlencode(params)
        return self._handle.call(method, path, body, before_send=self._before_send)

    def _session(self, row, session_id=None):
        self._handle.validate_session(row, session_id)
        # Pinned ORX session_json exposes effective_permission_id: OpenCode's
        # omitted stored permission is returned as "default". Compare only this
        # proven equivalent pair; do not change the outgoing permission grant.
        def permission(value):
            if self.harness == 'opencode':
                require(value is None or value in ('default', 'auto-approve'))
                return 'default' if value is None else value
            return value
        require(row.get('harness') == self.harness and row.get('model') == self.model
                and 'permissionMode' in row
                and permission(row['permissionMode']) == permission(self.permission_mode))
        for key, value in self._optional_pins().items():
            require(row.get(key) == value and (key != 'planMode' or type(row.get(key)) is bool))
        return {'id': row['id'], 'projectId': self.project_id, 'harness': self.harness, 'model': self.model,
            'busy': row['busy'], 'archived': row['archived'], 'usageKnown': False, 'stoppedProof': False,
            **self._optional_pins()}


@dataclass(frozen=True, repr=False)
class PersonalOrxHandle:
    provider: PersonalOrxProvider
    owner: str
    configuration: dict
    recheck: Callable | None = field(default=None, repr=False)
    namespace = 'native-openresearch'
    required_execution_contract = PERSONAL_CONTRACT
    provider_id = PERSONAL_ORX_PROVIDER_ID

    def guarded(self, recheck):
        return PersonalOrxHandle(self.provider, self.owner, dict(self.configuration), recheck)

    def _check(self, capabilities):
        require(callable(self.recheck), 'PERSONAL_GUARD_REQUIRED')
        cast(Callable, self.recheck)(capabilities)
        require(self.provider.authorized(self.owner, self.configuration), 'REMOTE_CREDENTIAL_UNAVAILABLE')

    def call(self, method, path, payload=None, *, before_send=None):
        transport = self.provider.transport(self.configuration)
        require(transport.allows(method, path, payload), 'REMOTE_PATH_DENIED')
        if method == 'GET':
            required = ('runtime:health',) if path == '/api/health' else ('project:read',) if path.startswith('/api/projects') else ('session:read',)
        elif path == '/api/projects':
            required = ('project:create',)
        elif method == 'PATCH' or path == '/api/chat/sessions':
            required = ('session:create',)
        else:
            required = ('session:interrupt',) if path.endswith('/interrupt') else ('session:prompt',)
        if method != 'GET':
            require(callable(before_send), 'PERSONAL_ADMISSION_REQUIRED')
        query = parse_qs(urlsplit(path).query)
        if query:
            require(query == {'projectId': [self.configuration['projectId']]}, 'REMOTE_IDENTITY_MISMATCH')
        if path.startswith('/api/projects/'):
            require(path == '/api/projects/' + self.configuration['projectId'], 'REMOTE_IDENTITY_MISMATCH')
        if self.configuration.get('projectCreation'):
            require(path in {'/api/health', '/api/projects'}, 'REMOTE_PATH_DENIED')
        elif method == 'POST' and path == '/api/projects':
            require(False, 'REMOTE_PATH_DENIED')
        self._check(required)
        address = transport.addresses(self.configuration['origin'])[0]
        credential = self.provider.secrets.resolve(**self.provider._scope(self.owner, self.configuration))
        require(isinstance(credential, SecretLease), 'REMOTE_CREDENTIAL_UNAVAILABLE')
        self._check(required)
        if method != 'GET':
            cast(Callable, before_send)()  # Exact persisted native-intent authority, after blocking IO.
            self._check(required)  # The admission callback may itself block/revoke the connection.
        status, value = transport.request(self.configuration['origin'], address, method, path, credential, payload)
        reject_credential_echo(value, credential)
        self._check(required)
        require(status == 200, 'PERSONAL_REMOTE_RESPONSE_REJECTED')
        return value

    def inspect_identity(self):
        self._check(('runtime:health', 'project:read'))
        result = self.provider.verify(self.owner, self.configuration)
        self._check(('runtime:health', 'project:read'))
        return result

    def project(self):
        value = self.call('GET', '/api/projects/' + self.configuration['projectId'])
        require(type(value) is dict and type(value.get('project')) is dict)
        row = cast(dict[str, Any], value['project'])
        require(row.get('id') == self.configuration['projectId'], 'REMOTE_IDENTITY_MISMATCH')
        return {'nativeProjectId': row['id'], 'name': str(row.get('name', ''))[:512],
            'namespace': self.namespace, 'executionContract': PERSONAL_CONTRACT,
            'nativeProjectCreationSupported': False, 'sessionCreationSupported': bool(self.configuration.get('sessionTemplateId') or self.configuration.get('sessionDefaults'))}

    def creation_projects(self):
        require(self.configuration.get('projectCreation') is True, 'PERSONAL_ORX_CREATION_CONNECTION_REQUIRED')
        value = self.call('GET', '/api/projects')
        require(type(value) is dict and type(value.get('projects')) is list)
        value = cast(dict[str, Any], value)
        require(len(value['projects']) <= 2048)
        rows = []
        for project in value['projects']:
            require(type(project) is dict and re.fullmatch(_ID, native_id(project.get('id'))))
            rows.append({'nativeProjectId': project['id'], 'name': str(project.get('name', ''))[:512],
                'path': str(project.get('path', project.get('repoPath', '')))[:512]})
        require(len({p['nativeProjectId'] for p in rows}) == len(rows))
        return rows

    def create_project(self, request, *, before_send):
        require(self.configuration.get('projectCreation') is True, 'PERSONAL_ORX_CREATION_CONNECTION_REQUIRED')
        value = self.call('POST', '/api/projects', request, before_send=before_send)
        require(type(value) is dict and type(value.get('project')) is dict)
        row = cast(dict[str, Any], value['project'])
        identifier = native_id(row.get('id'))
        require(re.fullmatch(_ID, identifier) and row.get('name') == request['name'])
        return {'nativeProjectId': identifier, 'name': row['name'],
            'path': str(row.get('path', row.get('repoPath', '')))[:512], 'namespace': self.namespace,
            'githubSyncRequested': False, 'correlationSource': 'native-create-response', 'liveEndToEndVerified': False}

    def list_projects(self):
        # This connection is scoped to one chosen native project, not a server-wide grant.
        return [self.project()]

    def _sessions(self) -> list[dict[str, Any]]:
        value = self.call('GET', '/api/chat/sessions?' + urlencode({'projectId': self.configuration['projectId']}))
        require(type(value) is dict and type(value.get('sessions')) is list)
        rows = cast(list[dict[str, Any]], value['sessions'])
        require(len(rows) <= 2048)
        ids = set()
        for row in rows:
            self.validate_session(row)
            require(row['id'] not in ids)
            ids.add(row['id'])
        return rows

    def validate_session(self, row, identifier=None):
        require(type(row) is dict and row.get('projectId') == self.configuration['projectId']
                and (identifier is None or row.get('id') == identifier), 'REMOTE_IDENTITY_MISMATCH')
        sid = native_id(row.get('id'))
        require(re.fullmatch(_ID, sid) and type(row.get('harness')) is str and re.fullmatch(_ID, row['harness'])
                and (row.get('model') is None or type(row['model']) is str and 0 < len(row['model']) <= 200)
                and type(row.get('busy')) is bool and type(row.get('archived')) is bool)
        return {'nativeSessionId': sid, 'nativeProjectId': row['projectId'], 'harness': row['harness'],
            'model': row.get('model'), 'title': str(row.get('title') or '')[:512], 'busy': row['busy'],
            'archived': row['archived'], 'namespace': self.namespace,
            'modelSelection': 'remote-default' if row.get('model') is None else 'remote-session'}

    def list_sessions(self):
        return [self.validate_session(row) for row in self._sessions()]

    def _session_row(self, identifier):
        native_id(identifier)
        rows = [row for row in self._sessions() if row['id'] == identifier]
        require(len(rows) == 1, 'PERSONAL_NATIVE_SESSION_NOT_FOUND')
        return rows[0]

    def session(self, identifier):
        return self.validate_session(self._session_row(identifier), identifier)

    @staticmethod
    def new_turn_id():
        return None  # A clientTurnId is not a native message ID.

    def validate_agent(self, agent):
        if agent is not None:
            require(agent in {row['harness'] for row in self._sessions()}, 'PERSONAL_ORX_HARNESS_UNAVAILABLE')

    def create_session(self, title, *, before_send):
        template = self.configuration.get('sessionTemplateId')
        defaults = self.configuration.get('sessionDefaults')
        require(template is not None or defaults is not None, 'PERSONAL_ORX_SESSION_TEMPLATE_REQUIRED')
        row = self._session_row(template) if template else {'projectId': self.configuration['projectId'],
            **cast(dict, defaults), 'permissionMode': None, 'planMode': False}
        require(type(row.get('model')) is str and bool(row['model']), 'PERSONAL_ORX_EXPLICIT_TEMPLATE_MODEL_REQUIRED')
        client = _NativeSessionClient(self, row, before_send)
        created = asyncio.run(client.create_session(key='personal-create', commit_intent=lambda **_: None))
        result = self.session(created['id'])
        try:
            asyncio.run(client.rename_session(created['id'], title, key='personal-title', commit_intent=lambda **_: None))
            result['titleUpdate'] = 'acknowledged'
            result['title'] = title
        except Exception:
            # Preserve the acknowledged native session; never blind-create another.
            result['titleUpdate'] = 'unknown'
        return result

    def prompt_session(self, session_id, text, agent, message_id, *, before_send):
        row = self._session_row(session_id)
        require(agent is None or agent == row['harness'], 'PERSONAL_ORX_HARNESS_CHANGE_REQUIRES_NEW_SESSION')
        client = _NativeSessionClient(self, row, before_send)
        before = asyncio.run(client.read_messages(session_id))
        require(not row['busy'] and not before['queued'], 'PERSONAL_PREVIOUS_TURN_UNRESOLVED')
        receipt = asyncio.run(client.send_message(session_id, text, client_turn_id='client_' + secrets.token_hex(16),
            key='personal-original-turn', commit_intent=lambda **_: None))
        return {'nativeMessageId': None, 'nativeSessionId': session_id, 'nativeTurnId': None if receipt['queued'] else receipt['turnId'],
            'clientTurnId': receipt['clientTurnId'], 'queued': receipt['queued'], 'status': 'accepted',
            'beforeMessageIds': [m['id'] for m in before['messages']],
            'beforeMessagesFingerprint': digest([{'id': m['id'], 'wireSha256': digest(m)} for m in before['messages']]),
            'beforeActiveLeafId': before['activeLeafId'],
            'promptSha256': hashlib.sha256(text.encode()).hexdigest(), 'correlationSource': 'acknowledged-queued-client-turn' if receipt['queued'] else 'acknowledged-native-turn',
            'exactTurnVerified': False, 'stopVerified': False}

    def interrupt_session(self, session_id, *, before_send):
        client = _NativeSessionClient(self, self._session_row(session_id), before_send)
        asyncio.run(client.interrupt(session_id, key='personal-original-interrupt', commit_intent=lambda **_: None))
        return {'nativeSessionId': session_id, 'status': 'interrupt_requested_stop_unverified', 'stopVerified': False}

    def observe_session(self, session_id):
        row = self._session_row(session_id)
        client = _NativeSessionClient(self, row)
        transcript = asyncio.run(client.read_messages(session_id))
        current = asyncio.run(client.read_session(session_id))
        result = project_transcript(transcript, session_id)
        result.update(busy=current['busy'], queued=transcript['queued'], activeLeafId=transcript['activeLeafId'],
            namespace=self.namespace, stopVerified=False, scientificConclusionVerified=False,
            exactTurnVerified=False, usageStatus='unavailable', correlationSource='remote-session-observation')
        return result

    @staticmethod
    def result_matches(observation, command):
        # Do not recover unknown ACK from resemblance or remote idle status.
        if command.get('state') != 'acknowledged' or observation.get('busy') is not False or observation.get('queued'):
            return False
        receipt = command.get('result') or {}
        if not receipt.get('nativeTurnId') or 'beforeMessageIds' not in receipt:
            return False
        baseline = observation.get('messages', [])[:len(receipt['beforeMessageIds'])]
        if ([m['id'] for m in baseline] != receipt['beforeMessageIds'] or
                digest([{'id': m['id'], 'wireSha256': m.get('wireSha256')} for m in baseline])
                != receipt.get('beforeMessagesFingerprint')):
            return False
        known = set(receipt['beforeMessageIds'])
        added = [m for m in observation.get('messages', []) if m['id'] not in known]
        users = [m for m in added if m['role'] == 'user' and m.get('parentId') == receipt.get('beforeActiveLeafId')]
        if len(added) != 2 or len(users) != 1:
            return False
        text = '\n'.join(e['text'] for e in users[0]['events'] if e.get('type') == 'text')
        if hashlib.sha256(text.encode()).hexdigest() != receipt.get('promptSha256'):
            return False
        matches = [m for m in added if m['role'] == 'assistant' and m.get('parentId') == users[0]['id']
                   and m['id'] == observation.get('activeLeafId') and m['terminalResult']]
        if len(matches) != 1:
            return False
        observation.update(correlationSource='inferred-transcript-delta', exactTurnVerified=False,
                           nativeTurnId=receipt['nativeTurnId'], clientTurnId=receipt['clientTurnId'])
        return True


def project_transcript(transcript, session_id):
    """Native ORX WireMessage/WirePart projection; no OpenCode ID relabelling."""
    messages = []
    for row in transcript['messages']:
        events, failed = [], False
        require(len(row['parts']) <= 1024)
        for part in row['parts']:
            require(type(part) is dict)
            if part.get('type') == 'text' and type(part.get('text')) is str:
                events.append({'type': 'text', 'text': part['text'][:32768]})
            elif part.get('type') == 'tool':
                state = part.get('state') or {}
                require(type(state) is dict)
                status = str(state.get('status', 'unknown'))[:32]
                failed = failed or status != 'completed' or part.get('tool') == 'error'
                events.append({'type': 'tool', 'tool': str(part.get('tool', ''))[:200], 'status': status,
                    'output': state.get('output', '')[:32768] if type(state.get('output', '')) is str else ''})
            elif part.get('type') == 'error':
                failed = True
            elif part.get('type') == 'prompt':
                prompt = part.get('prompt') or {}
                require(type(prompt) is dict)
                resolved = prompt.get('resolved') is True
                failed = failed or not resolved
                events.append({'type': 'tool', 'tool': 'native-' + str(prompt.get('kind', 'prompt'))[:100],
                    'status': 'completed' if resolved else 'awaiting_native_action',
                    'output': str(prompt.get('question') or prompt.get('header') or 'Respond in the original OpenResearch session.')[:4000]})
        complete = type(row.get('completedAt')) is int
        messages.append({'id': row['id'], 'wireSha256': digest(row), 'role': row['role'], 'parentId': row.get('parentId'),
            'completed': complete, 'terminalResult': complete and not failed,
            'events': events, 'usage': {}, 'usageProvenance': 'unavailable'})
    return {'messages': messages, 'nativeSessionId': session_id}
