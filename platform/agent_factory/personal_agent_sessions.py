"""Durable ordinary remote-agent intents; not a second execution queue.

A trusted Factory admission callback is mandatory. It receives exact immutable
intent and returns the original approved plan/task/native-run identity. It must
recheck current plan permission; this module cannot manufacture managed approval.
Remote observations never establish process termination or release resources.
"""
from __future__ import annotations

from copy import deepcopy
from importlib import import_module
import math
from uuid import uuid4
from typing import Any

from fastapi import HTTPException
from sqlalchemy import Column, JSON, MetaData, String, Table, select
from sqlalchemy.exc import IntegrityError

from .personal_agent_transport import (PERSONAL_CONTRACT, PERSONAL_PROVIDER_ID,
    PersonalAgentHandle, native_id)
from .store import digest, now


class PersonalAgentSessions:
    def __init__(self, connections, *, admission, engines=None, observed=None):
        if not callable(admission):
            raise ValueError('PERSONAL_TRUSTED_ADMISSION_REQUIRED')
        self.connections, self.store, self.auth = connections, connections.store, connections.auth
        self.admission, self.observed = admission, observed
        self.engines = dict(engines) if engines is not None else self._engines()
        metadata = MetaData()
        self.sessions = Table('af_personal_agent_sessions', metadata,
            Column('id', String, primary_key=True), Column('owner_id', String, nullable=False),
            Column('body', JSON, nullable=False), Column('body_hash', String, nullable=False),
            Column('state', String, nullable=False), Column('observation', JSON),
            Column('active_request', String), Column('created_at', String, nullable=False))
        self.commands = Table('af_personal_agent_commands', metadata,
            Column('owner_id', String, primary_key=True), Column('request_id', String, primary_key=True),
            Column('fingerprint', String, nullable=False), Column('intent', JSON, nullable=False),
            Column('identity', JSON, nullable=False), Column('identity_hash', String, nullable=False), Column('state', String, nullable=False),
            Column('result', JSON), Column('created_at', String, nullable=False))
        self.native_scopes = Table('af_personal_agent_native_scopes', metadata,
            Column('scope_key', String, primary_key=True), Column('owner_id', String, nullable=False),
            Column('session_id', String, nullable=False))
        metadata.create_all(self.store.engine)

    @staticmethod
    def _engines():
        # Trusted built-in class registry. Provider configuration cannot supply code.
        engines = {PERSONAL_PROVIDER_ID: PersonalAgentHandle}
        try:
            module = import_module('.personal_orx_transport', __package__)
        except ModuleNotFoundError as error:
            if error.name != f'{__package__}.personal_orx_transport':
                raise
            return engines
        engines[module.PERSONAL_ORX_PROVIDER_ID] = module.PersonalOrxHandle
        # Installed platform package reuses original ORX's wire and the same
        # persisted personal-command controller; no separate research queue.
        engines['platform-openresearch-session-v1'] = module.PersonalOrxHandle
        return engines

    def _handle(self, owner, pin=None, reference=None, capability='session:read'):
        expected = {} if pin is None else dict(expected_revision=pin['revision'],
            expected_fingerprint=pin['fingerprint'], expected_version=pin['version'])
        reference = reference if pin is None else pin['ref']
        kind = pin['kind'] if pin is not None else self.connections.inspect(owner, reference)['kind']
        current = self.connections.preflight(owner, reference, kind,
            required_capabilities=[capability], **expected)
        handle = self.connections.resolve(owner, reference, kind,
            required_capabilities=[capability],
            expected_revision=current['revision'], expected_fingerprint=current['fingerprint'],
            expected_version=current['version'])
        provider_id = getattr(getattr(handle, 'provider', None), 'provider_id', None)
        if not isinstance(provider_id, str) or provider_id not in self.engines or type(handle) is not self.engines[provider_id]:
            raise HTTPException(409, 'PERSONAL_ADAPTER_REQUIRED')
        return handle, current

    def project(self, owner, connection_ref):
        handle, pin = self._handle(owner, reference=connection_ref, capability='project:read')
        project = handle.project()
        return {**project, 'connectionPin': pin,
            'upstreamOrxProjectId': project['nativeProjectId'] if handle.namespace == 'native-openresearch' else None,
            'budgetEnforcement': 'advisory', 'modelCredentialCustody': getattr(handle.provider, 'model_credential_custody', 'remote'),
            'stopGuarantee': 'unverified'}

    @staticmethod
    def _native_scope(owner, handle, project, session):
        return digest({'owner': owner, 'provider': handle.provider.provider_id,
            'origin': handle.configuration['origin'], 'project': project, 'session': session})

    def native_sessions(self, owner, connection_ref):
        handle, pin = self._handle(owner, reference=connection_ref, capability='session:read')
        project = handle.project()
        sessions = handle.list_sessions()
        return {**project, 'connectionPin': pin, 'sessions': sessions}

    def attach(self, owner, connection_ref, native_project_id, native_session_id, request_id):
        self.auth.require(owner, 'run')
        self.connections._key(request_id)
        native_id(native_project_id); native_id(native_session_id)
        old = self._command(owner, request_id)
        if old:
            intent = old['intent']
            if (intent['action'], intent['connectionPin']['ref'], intent['nativeProjectId'], intent['nativeSessionId']) != (
                    'attach', connection_ref, native_project_id, native_session_id):
                raise HTTPException(409, 'IDEMPOTENCY_CONFLICT')
            return self.request_result(owner, request_id)
        handle, pin = self._handle(owner, reference=connection_ref, capability='session:read')
        project = handle.project()
        native = handle.session(native_session_id)
        if project['nativeProjectId'] != native_project_id or native['nativeProjectId'] != native_project_id:
            raise HTTPException(409, 'PERSONAL_PROJECT_MISMATCH')
        scope = self._native_scope(owner, handle, native_project_id, native_session_id)
        with self.store.engine.connect() as conn:
            selected = conn.execute(select(self.native_scopes.c.session_id).where(
                self.native_scopes.c.scope_key == scope, self.native_scopes.c.owner_id == owner)).scalar_one_or_none()
        if selected:
            original = self._session(owner, selected)['body']
            try:
                self._handle(owner, original['connectionPin'], capability='session:read')
            except HTTPException:
                raise HTTPException(409, 'PERSONAL_CONNECTION_REBIND_REQUIRED') from None
            if original['connectionPin']['fingerprint'] != pin['fingerprint']:
                raise HTTPException(409, 'PERSONAL_CONNECTION_REBIND_REQUIRED')
        # Never call connection/vault/network authorization inside metadata write:
        # those checks may need their own slot even on a pool of size one.
        with self.store.engine.begin() as conn:
            self.connections._lock(conn, 'personal-agent:' + owner)
            previous = conn.execute(select(self.commands).where(self.commands.c.owner_id == owner,
                self.commands.c.request_id == request_id)).mappings().first()
            if previous:
                other = previous['intent']
                if (other['action'], other['connectionPin']['ref'], other['nativeProjectId'], other['nativeSessionId']) != (
                        'attach', connection_ref, native_project_id, native_session_id):
                    raise HTTPException(409, 'IDEMPOTENCY_CONFLICT')
            else:
                existing = conn.execute(select(self.native_scopes).where(
                    self.native_scopes.c.scope_key == scope, self.native_scopes.c.owner_id == owner)).mappings().first()
                if existing and existing['session_id'] != selected:
                    raise HTTPException(409, 'PERSONAL_ATTACH_RETRY_REQUIRED')
                identifier = existing['session_id'] if existing else 'personal-' + uuid4().hex
                if not existing:
                    body = {'id': identifier, 'ownerId': owner, 'connectionPin': pin,
                        'nativeProjectId': native_project_id, 'nativeSessionId': native_session_id,
                        'namespace': handle.namespace, 'executionContract': PERSONAL_CONTRACT,
                        'modelCredentialCustody': getattr(handle.provider, 'model_credential_custody', 'remote'),
                        'attachRequestId': request_id, 'factoryIdentity': None}
                    conn.execute(self.sessions.insert().values(id=identifier, owner_id=owner, body=body,
                        body_hash=digest(body), state='ready', observation=None, active_request=None, created_at=now()))
                    conn.execute(self.native_scopes.insert().values(scope_key=scope, owner_id=owner, session_id=identifier))
                intent = self._intent('attach', request_id, identifier, pin, native_project_id, native_session_id)
                conn.execute(self.commands.insert().values(owner_id=owner, request_id=request_id,
                    fingerprint=digest(intent), intent=intent, identity=None, identity_hash=digest(None),
                    state='acknowledged', result={'nativeProjectId': native_project_id,
                        'nativeSessionId': native_session_id, 'status': 'attached_read_only'}, created_at=now()))
        self.auth.require(owner, 'run')
        self._handle(owner, pin, capability='session:read')
        return self.request_result(owner, request_id)

    def _rebind_target(self, owner, session_id, new_connection_ref, expected_old_fingerprint):
        self.auth.require(owner, 'run')
        row = self._session(owner, session_id)
        body, old = row['body'], row['body']['connectionPin']
        if old['fingerprint'] != expected_old_fingerprint:
            raise HTTPException(409, 'PERSONAL_REBIND_STALE_OLD_PIN')
        if not body['nativeSessionId']:
            raise HTTPException(409, 'PERSONAL_SESSION_ACK_UNKNOWN')
        handle, new = self._handle(owner, reference=new_connection_ref, capability='session:read')
        if (old['kind'] != new['kind'] or handle.namespace != body['namespace']
                or handle.configuration['projectId'] != body['nativeProjectId']):
            raise HTTPException(409, 'PERSONAL_REBIND_IDENTITY_MISMATCH')
        if not set(new['capabilities']) <= set(old['capabilities']):
            raise HTTPException(409, 'PERSONAL_REBIND_SCOPE_EXPANSION')
        if new['fingerprint'] == old['fingerprint']:
            raise HTTPException(409, 'PERSONAL_REBIND_NEW_PIN_REQUIRED')
        scope = self._native_scope(owner, handle, body['nativeProjectId'], body['nativeSessionId'])
        with self.store.engine.connect() as conn:
            original = conn.execute(select(self.native_scopes.c.session_id).where(
                self.native_scopes.c.scope_key == scope, self.native_scopes.c.owner_id == owner)).scalar_one_or_none()
        if original != session_id:
            raise HTTPException(409, 'PERSONAL_REBIND_IDENTITY_MISMATCH')
        # New credentials may read ONLY the already recorded exact native identity.
        project = handle.project()
        if project['nativeProjectId'] != body['nativeProjectId']:
            raise HTTPException(409, 'PERSONAL_REBIND_IDENTITY_MISMATCH')
        native = handle.session(body['nativeSessionId'])
        if (project['nativeProjectId'] != body['nativeProjectId']
                or native['nativeProjectId'] != body['nativeProjectId']
                or native['nativeSessionId'] != body['nativeSessionId']):
            raise HTTPException(409, 'PERSONAL_REBIND_IDENTITY_MISMATCH')
        return row, handle, new, scope

    def _rebind_blockers(self, conn, owner, row):
        blockers = []
        if row['active_request'] is not None:
            blockers.append({'requestId': row['active_request'], 'action': 'prompt',
                'state': 'unresolved', 'source': 'active-request'})
        # The existing effect ledger is also the interrupt in-flight fence.
        # An HTTP acknowledgement settles the local attempt only, never proves stop.
        commands = conn.execute(select(self.commands).where(self.commands.c.owner_id == owner,
            self.commands.c.state == 'ack_unknown',
            self.commands.c.intent['factorySessionId'].as_string() == row['id'],
            self.commands.c.intent['action'].as_string() == 'interrupt')
            .order_by(self.commands.c.request_id)).mappings().all()
        for command in commands:
            if digest(command['intent']) != command['fingerprint']:
                raise HTTPException(409, 'PERSONAL_REQUEST_INTEGRITY')
            blockers.append({'requestId': command['request_id'], 'action': 'interrupt',
                'state': 'ack_unknown', 'source': 'durable-command-ledger'})
        return blockers

    @staticmethod
    def _rebind_blocker_code(blockers):
        if any(item['action'] == 'interrupt' for item in blockers):
            return 'PERSONAL_INTERRUPT_ACK_UNKNOWN'
        return 'PERSONAL_PREVIOUS_TURN_UNRESOLVED' if blockers else None

    def preview_rebind(self, owner, session_id, new_connection_ref, expected_old_fingerprint):
        row, handle, new, _ = self._rebind_target(owner, session_id, new_connection_ref, expected_old_fingerprint)
        # GET-only recovery under the new verified credential preserves the
        # engine's original correlation rules. Unknown ORX remains unknown.
        if row['active_request'] is not None:
            self._refresh(owner, row, handle=handle, observation_pin=new)
        current = self._session(owner, session_id)
        if current['body_hash'] != row['body_hash']:
            raise HTTPException(409, 'PERSONAL_REBIND_STALE_OLD_PIN')
        self._handle(owner, new, capability='session:read')
        with self.store.engine.connect() as conn:
            blockers = self._rebind_blockers(conn, owner, current)
        return {'sessionId': session_id, 'oldConnectionPin': row['body']['connectionPin'],
            'newConnectionPin': new, 'nativeProjectId': row['body']['nativeProjectId'],
            'nativeSessionId': row['body']['nativeSessionId'], 'namespace': row['body']['namespace'],
            'activeRequestId': current['active_request'], 'canRebind': not blockers,
            'blocker': self._rebind_blocker_code(blockers), 'blockers': blockers,
            'observation': current['observation'], 'bindingHistory': row['body'].get('bindingHistory', [])}

    def rebind(self, owner, session_id, new_connection_ref, request_id, *,
               expected_old_fingerprint, expected_new_fingerprint):
        self.auth.require(owner, 'run')
        self.connections._key(request_id)
        def same_request(previous):
            intent = previous['intent']
            if (intent.get('action') != 'rebind' or intent.get('factorySessionId') != session_id
                    or intent.get('connectionPin', {}).get('fingerprint') != expected_old_fingerprint
                    or intent.get('newConnectionPin', {}).get('fingerprint') != expected_new_fingerprint
                    or intent.get('newConnectionPin', {}).get('ref') != new_connection_ref):
                raise HTTPException(409, 'IDEMPOTENCY_CONFLICT')
        previous = self._command(owner, request_id)
        if previous:
            same_request(previous)
            return self.request_result(owner, request_id)
        preview = self.preview_rebind(owner, session_id, new_connection_ref, expected_old_fingerprint)
        if preview['newConnectionPin']['fingerprint'] != expected_new_fingerprint:
            raise HTTPException(409, 'PERSONAL_REBIND_STALE_NEW_PIN')
        if not preview['canRebind']:
            raise HTTPException(409, preview['blocker'])
        row, _handle, new, scope = self._rebind_target(owner, session_id, new_connection_ref, expected_old_fingerprint)
        if new['fingerprint'] != expected_new_fingerprint:
            raise HTTPException(409, 'PERSONAL_REBIND_STALE_NEW_PIN')
        if row['active_request'] is not None:
            raise HTTPException(409, 'PERSONAL_PREVIOUS_TURN_UNRESOLVED')
        old = row['body']['connectionPin']
        at = now()
        history = [*row['body'].get('bindingHistory', []), {'requestId': request_id,
            'changedAt': at, 'oldConnectionPin': old, 'newConnectionPin': new}]
        if len(history) > 1024:
            raise HTTPException(409, 'PERSONAL_REBIND_HISTORY_LIMIT')
        body = {**row['body'], 'connectionPin': new, 'bindingHistory': history}
        intent = self._intent('rebind', request_id, session_id, old, body['nativeProjectId'],
            body['nativeSessionId'], newConnectionPin=new)
        self.auth.require(owner, 'run')
        self._handle(owner, new, capability='session:read')
        try:
            with self.store.engine.begin() as conn:
                self.connections._lock(conn, 'personal-agent:' + owner)
                previous = conn.execute(select(self.commands).where(self.commands.c.owner_id == owner,
                    self.commands.c.request_id == request_id)).mappings().first()
                if previous:
                    same_request(previous)
                else:
                    native = conn.execute(select(self.native_scopes.c.session_id).where(
                        self.native_scopes.c.scope_key == scope, self.native_scopes.c.owner_id == owner)).scalar_one_or_none()
                    if native != session_id:
                        raise HTTPException(409, 'PERSONAL_REBIND_IDENTITY_MISMATCH')
                    current = conn.execute(select(self.sessions).where(self.sessions.c.owner_id == owner,
                        self.sessions.c.id == session_id).with_for_update()).mappings().one()
                    blockers = self._rebind_blockers(conn, owner, current)
                    if blockers:
                        raise HTTPException(409, self._rebind_blocker_code(blockers))
                    updated = conn.execute(self.sessions.update().where(self.sessions.c.owner_id == owner,
                        self.sessions.c.id == session_id, self.sessions.c.body_hash == row['body_hash'],
                        self.sessions.c.active_request.is_(None)).values(body=body, body_hash=digest(body)))
                    if updated.rowcount != 1:
                        raise HTTPException(409, 'PERSONAL_REBIND_STALE_MAPPING')
                    conn.execute(self.commands.insert().values(owner_id=owner, request_id=request_id,
                        fingerprint=digest(intent), intent=intent, identity=None, identity_hash=digest(None),
                        state='acknowledged', result={'status': 'rebound', 'oldConnectionPin': old,
                            'newConnectionPin': new, 'changedAt': at}, created_at=at))
        except IntegrityError:
            previous = self._command(owner, request_id)
            if previous:
                same_request(previous)
            else:
                raise HTTPException(409, 'PERSONAL_REBIND_STALE_MAPPING') from None
        return self.request_result(owner, request_id)

    def list(self, owner, connection_ref=None):
        self.auth.require(owner, 'read')
        with self.store.engine.connect() as conn:
            rows = conn.execute(select(self.sessions.c.id, self.sessions.c.body).where(
                self.sessions.c.owner_id == owner).order_by(self.sessions.c.created_at).limit(100)).mappings().all()
        return [self.inspect(owner, row['id']) for row in rows
            if connection_ref is None or row['body']['connectionPin']['ref'] == connection_ref]

    def _session(self, owner, identifier):
        self.connections._key(identifier)
        with self.store.engine.connect() as conn:
            row = conn.execute(select(self.sessions).where(self.sessions.c.owner_id == owner,
                self.sessions.c.id == identifier)).mappings().first()
        if row is None: raise HTTPException(404, 'PERSONAL_SESSION_NOT_FOUND')
        if digest(row['body']) != row['body_hash'] or row['body'].get('ownerId') != owner:
            raise HTTPException(409, 'PERSONAL_SESSION_INTEGRITY')
        return dict(row)

    def _command(self, owner, request_id):
        self.connections._key(request_id)
        with self.store.engine.connect() as conn:
            row = conn.execute(select(self.commands).where(self.commands.c.owner_id == owner,
                self.commands.c.request_id == request_id)).mappings().first()
        if row and (digest(row['intent']) != row['fingerprint'] or digest(row['identity']) != row['identity_hash']):
            raise HTTPException(409, 'PERSONAL_REQUEST_INTEGRITY')
        return dict(row) if row else None

    def _authorize(self, owner, intent, expected=None):
        self.auth.require(owner, 'run')
        identity = self.admission(owner, deepcopy(intent))
        if (not isinstance(identity, dict) or set(identity) != {'planId', 'taskId', 'nativeRunId', 'executionContract'}
                or identity['executionContract'] != PERSONAL_CONTRACT):
            raise HTTPException(409, 'PERSONAL_ADMISSION_REQUIRED')
        for key in ('planId', 'taskId', 'nativeRunId'): self.connections._key(identity[key])
        if expected is not None and identity != expected:
            raise HTTPException(409, 'PERSONAL_ADMISSION_CHANGED')
        return identity

    def _reserve(self, owner, request_id, intent, identity, *, session=None):
        # Independent committed transaction: never borrow a caller transaction.
        # No IO is performed unless this immutable reservation has committed.
        try:
            with self.store.engine.begin() as conn:
                self.connections._lock(conn, 'personal-agent:' + owner)
                previous = conn.execute(select(self.commands).where(self.commands.c.owner_id == owner,
                    self.commands.c.request_id == request_id)).mappings().first()
                if previous:
                    if previous['fingerprint'] != digest(intent): raise HTTPException(409, 'IDEMPOTENCY_CONFLICT')
                    return False
                if session is not None:
                    conn.execute(self.sessions.insert().values(**session))
                else:
                    row = conn.execute(select(self.sessions).where(self.sessions.c.owner_id == owner,
                        self.sessions.c.id == intent['factorySessionId'])).mappings().one()
                    self._same_execution_mapping(row, intent)
                    if intent['action'] == 'prompt' and row['active_request'] is not None:
                        raise HTTPException(409, 'PERSONAL_PREVIOUS_TURN_UNRESOLVED')
                conn.execute(self.commands.insert().values(owner_id=owner, request_id=request_id,
                    fingerprint=digest(intent), intent=intent, identity=identity, identity_hash=digest(identity), state='ack_unknown',
                    result=None, created_at=now()))
                if intent['action'] == 'prompt':
                    conn.execute(self.sessions.update().where(self.sessions.c.owner_id == owner,
                        self.sessions.c.id == intent['factorySessionId']).values(active_request=request_id))
                if intent['action'] == 'interrupt':
                    conn.execute(self.sessions.update().where(self.sessions.c.owner_id == owner,
                        self.sessions.c.id == intent['factorySessionId']).values(state='interrupt_requested_stop_unverified'))
            return True
        except IntegrityError:
            previous = self._command(owner, request_id)
            if previous and previous['fingerprint'] == digest(intent): return False
            raise HTTPException(409, 'PERSONAL_REQUEST_CONFLICT') from None

    @staticmethod
    def _same_execution_mapping(row, intent):
        body = row['body']
        if (digest(body) != row['body_hash'] or body['connectionPin'] != intent['connectionPin']
                or body['nativeProjectId'] != intent['nativeProjectId']
                or body['nativeSessionId'] != intent['nativeSessionId']):
            raise HTTPException(409, 'PERSONAL_EXECUTION_MAPPING_CHANGED')

    def _intent(self, action, request_id, identifier, pin, project, native_session, **kwargs):
        self.connections._key(request_id)
        return dict(executionContract=PERSONAL_CONTRACT, action=action, requestId=request_id,
            factorySessionId=identifier, connectionPin=pin, nativeProjectId=project,
            nativeSessionId=native_session, **kwargs)

    def create(self, owner, connection_ref, native_project_id, request_id, *, title='Factory personal session'):
        self.auth.require(owner, 'run')
        if not isinstance(title, str) or not 1 <= len(title) <= 120:
            raise HTTPException(422, 'PERSONAL_TITLE_INVALID')
        old = self._command(owner, request_id)
        if old:
            intent = old['intent']
            if (intent['action'], intent['connectionPin']['ref'], intent['nativeProjectId'], intent.get('title')) != (
                    'create', connection_ref, native_project_id, title):
                raise HTTPException(409, 'IDEMPOTENCY_CONFLICT')
            return self.request_result(owner, request_id)
        handle, pin = self._handle(owner, reference=connection_ref, capability='session:create')
        if handle.project()['nativeProjectId'] != native_id(native_project_id):
            raise HTTPException(409, 'PERSONAL_PROJECT_MISMATCH')
        identifier = 'personal-' + uuid4().hex
        intent = self._intent('create', request_id, identifier, pin, native_project_id, None, title=title)
        identity = self._authorize(owner, intent)
        body = {'id': identifier, 'ownerId': owner, 'connectionPin': pin, 'nativeProjectId': native_project_id,
            'nativeSessionId': None, 'namespace': handle.namespace, 'executionContract': PERSONAL_CONTRACT,
            'modelCredentialCustody': getattr(handle.provider, 'model_credential_custody', 'remote'),
            'createRequestId': request_id, 'factoryIdentity': identity}
        session = dict(id=identifier, owner_id=owner, body=body, body_hash=digest(body),
            state='create_ack_unknown', observation=None, active_request=None, created_at=now())
        if self._reserve(owner, request_id, intent, identity, session=session):
            self._dispatch(owner, intent, identity)
        return self.request_result(owner, request_id)

    def prompt(self, owner, session_id, text, request_id, *, agent=None):
        if not isinstance(text, str) or not text.strip() or len(text.encode()) > 32768:
            raise HTTPException(422, 'PERSONAL_PROMPT_INVALID')
        if agent is not None: native_id(agent)
        return self._mutate(owner, session_id, request_id, 'prompt', text=text, agent=agent)

    def interrupt(self, owner, session_id, request_id):
        return self._mutate(owner, session_id, request_id, 'interrupt')

    def _mutate(self, owner, session_id, request_id, action, **kwargs):
        self.auth.require(owner, 'run')
        row = self._session(owner, session_id)
        body = row['body']
        if not body['nativeSessionId']: raise HTTPException(409, 'PERSONAL_SESSION_ACK_UNKNOWN')
        old = self._command(owner, request_id)
        if old:
            intent = old['intent']
            if intent['factorySessionId'] != session_id or intent['action'] != action or any(
                    intent.get(k) != v for k, v in kwargs.items()):
                raise HTTPException(409, 'IDEMPOTENCY_CONFLICT')
            return self.request_result(owner, request_id)
        handle, _ = self._handle(owner, body['connectionPin'], capability='session:' + action)
        handle.session(body['nativeSessionId'])
        handle.validate_agent(kwargs.get('agent'))
        intent = self._intent(action, request_id, session_id, body['connectionPin'],
            body['nativeProjectId'], body['nativeSessionId'], **kwargs)
        if action == 'prompt': intent['nativeMessageId'] = handle.new_turn_id()
        identity = self._authorize(owner, intent)
        if self._reserve(owner, request_id, intent, identity): self._dispatch(owner, intent, identity)
        return self.request_result(owner, request_id)

    def _dispatch(self, owner, intent, identity):
        # Any exception after intent commit is conservatively unknown, never replayed.
        try:
            handle, _ = self._handle(owner, intent['connectionPin'], capability='session:' + intent['action'])
            if intent['action'] != 'create': handle.session(intent['nativeSessionId'])
            elif handle.project()['nativeProjectId'] != intent['nativeProjectId']:
                raise HTTPException(409, 'PERSONAL_PROJECT_MISMATCH')
            self._authorize(owner, intent, identity)
            def before_send():
                self._same_execution_mapping(self._session(owner, intent['factorySessionId']), intent)
                self._authorize(owner, intent, identity)
                self._same_execution_mapping(self._session(owner, intent['factorySessionId']), intent)
            action = intent['action']
            if action == 'create':
                result = handle.create_session(intent['title'], before_send=before_send)
            elif action == 'prompt':
                result = handle.prompt_session(intent['nativeSessionId'], intent['text'],
                    intent.get('agent'), intent['nativeMessageId'], before_send=before_send)
            else:
                result = handle.interrupt_session(intent['nativeSessionId'], before_send=before_send)
            with self.store.engine.begin() as conn:
                conn.execute(self.commands.update().where(self.commands.c.owner_id == owner,
                    self.commands.c.request_id == intent['requestId'], self.commands.c.state == 'ack_unknown').values(state='acknowledged', result=result))
                if action == 'create':
                    row = conn.execute(select(self.sessions).where(self.sessions.c.owner_id == owner,
                        self.sessions.c.id == intent['factorySessionId'])).mappings().one()
                    scope = self._native_scope(owner, handle, intent['nativeProjectId'], result['nativeSessionId'])
                    conn.execute(self.native_scopes.insert().values(scope_key=scope, owner_id=owner,
                        session_id=intent['factorySessionId']))
                    body = {**row['body'], 'nativeSessionId': result['nativeSessionId']}
                    conn.execute(self.sessions.update().where(self.sessions.c.owner_id == owner,
                        self.sessions.c.id == intent['factorySessionId']).values(body=body,
                        body_hash=digest(body), state='ready'))
                elif action == 'interrupt':
                    conn.execute(self.sessions.update().where(self.sessions.c.owner_id == owner,
                        self.sessions.c.id == intent['factorySessionId']).values(state='interrupt_requested_stop_unverified'))
        except Exception:
            # Do not persist or return remote error bodies, secrets or exception text.
            pass

    def request_result(self, owner, request_id):
        self.auth.require(owner, 'read')
        row = self._command(owner, request_id)
        if row is None: raise HTTPException(404, 'PERSONAL_REQUEST_NOT_FOUND')
        return {'requestId': request_id, 'action': row['intent']['action'], 'state': row['state'],
            'result': row['result'], 'factoryIdentity': row['identity'], 'session': self.inspect(owner, row['intent']['factorySessionId'])}

    def inspect(self, owner, session_id, *, refresh=False):
        self.auth.require(owner, 'read')
        row = self._session(owner, session_id)
        if refresh and row['body']['nativeSessionId']:
            self._refresh(owner, row)
            row = self._session(owner, session_id)
        body = row['body']
        return {'id': session_id, 'namespace': body['namespace'], 'executionContract': PERSONAL_CONTRACT,
            'connectionRef': body['connectionPin']['ref'], 'connectionPin': body['connectionPin'], 'nativeProjectId': body['nativeProjectId'],
            'nativeSessionId': body['nativeSessionId'],
            'upstreamOrxProjectId': body['nativeProjectId'] if body['namespace'] == 'native-openresearch' else None,
            'factoryIdentity': body['factoryIdentity'], 'state': row['state'], 'activeRequestId': row['active_request'],
            'bindingHistory': body.get('bindingHistory', []), 'bindingStatus': self._binding_status(owner, body['connectionPin']),
            'observation': row['observation'], 'modelCredentialCustody': body.get('modelCredentialCustody', 'remote'),
            'budgetEnforcement': 'advisory', 'stopVerified': False, 'liveEndToEndVerified': False}

    def _binding_status(self, owner, pin):
        try:
            current = self.connections.inspect(owner, pin['ref'])
            return current['status'] if current['fingerprint'] == pin['fingerprint'] else 'changed'
        except HTTPException:
            return 'unavailable'

    def _refresh(self, owner, row, *, handle=None, observation_pin=None):
        body = row['body']; sid = body['nativeSessionId']
        if handle is None:
            handle, _ = self._handle(owner, body['connectionPin'])
        handle.session(sid)
        observation = handle.observe_session(sid)
        command = self._command(owner, row['active_request']) if row['active_request'] else None
        completed = command is not None and handle.result_matches(observation, command)
        observation.update(observedAt=now(), provenance='remote-reported', trustedMetering=False,
            sessionId=sid, projectId=body['nativeProjectId'],
            observedViaConnectionPin=observation_pin or body['connectionPin'])
        with self.store.engine.begin() as conn:
            current = conn.execute(select(self.sessions.c.state, self.sessions.c.active_request, self.sessions.c.body_hash).where(
                self.sessions.c.owner_id == owner, self.sessions.c.id == row['id']).with_for_update()).mappings().one()
            if current['body_hash'] != row['body_hash'] or current['active_request'] != row['active_request']:
                return
            values: dict[str, Any] = {'observation': observation}
            if completed and command is not None:
                values['active_request'] = None
                # Interrupt observations remain unverified even after a reply finishes.
                if current['state'] != 'interrupt_requested_stop_unverified': values['state'] = 'result_observed'
                conn.execute(self.commands.update().where(self.commands.c.owner_id == owner,
                    self.commands.c.request_id == row['active_request']).values(state='result_observed',
                    result={**(command['result'] or {}), 'nativeMessageId': command['intent']['nativeMessageId'],
                        'status': 'result_observed', 'observationEvidence': {
                            'observedAt': observation['observedAt'], 'provenance': 'remote-reported',
                            'observedViaConnectionPin': observation['observedViaConnectionPin'],
                            'nativeSessionId': sid, 'nativeProjectId': body['nativeProjectId'],
                            'correlationSource': observation.get('correlationSource', 'native-message-parent-id'),
                            'exactTurnVerified': observation.get('exactTurnVerified', False),
                            'stopVerified': False, 'scientificConclusionVerified': False}}))
            conn.execute(self.sessions.update().where(self.sessions.c.owner_id == owner,
                self.sessions.c.id == row['id'], self.sessions.c.active_request == row['active_request']).values(**values))
        if completed and command is not None and self.observed is not None:
            self.observed(owner, row['active_request'])


def project_messages(raw, session_id) -> dict[str, Any]:
    """Project bounded owner-visible events; omit reasoning and remote error bodies."""
    if not isinstance(raw, list) or len(raw) > 2048: raise HTTPException(409, 'PERSONAL_MESSAGES_INVALID')
    messages, ids = [], set()
    for value in raw:
        if not isinstance(value, dict): raise HTTPException(409, 'PERSONAL_MESSAGES_INVALID')
        info, parts = value.get('info'), value.get('parts')
        if (not isinstance(info, dict) or info.get('sessionID') != session_id or not isinstance(parts, list)
                or len(parts) > 1024 or info.get('role') not in {'user', 'assistant'}):
            raise HTTPException(409, 'PERSONAL_MESSAGES_INVALID')
        mid = native_id(info.get('id'))
        if mid in ids: raise HTTPException(409, 'PERSONAL_MESSAGES_INVALID')
        ids.add(mid)
        events = []
        for part in parts:
            if (not isinstance(part, dict) or part.get('sessionID') != session_id or part.get('messageID') != mid):
                raise HTTPException(409, 'PERSONAL_MESSAGES_INVALID')
            if part.get('type') == 'text' and isinstance(part.get('text'), str):
                events.append({'type': 'text', 'text': part['text'][:32768]})
            elif part.get('type') == 'tool':
                state = part.get('state', {})
                if isinstance(state, dict):
                    events.append({'type': 'tool', 'tool': str(part.get('tool', ''))[:200],
                        'status': str(state.get('status', 'unknown'))[:32],
                        'output': state.get('output', '')[:32768] if isinstance(state.get('output', ''), str) else ''})
        usage = {}
        if info['role'] == 'assistant':
            cost = info.get('cost')
            if isinstance(cost, (int, float)) and not isinstance(cost, bool) and 0 <= cost <= 1e15 and math.isfinite(cost): usage['cost'] = cost
            tokens = info.get('tokens')
            if isinstance(tokens, dict):
                usage['tokens'] = {k: v for k, v in tokens.items() if k in {'input', 'output', 'reasoning', 'total'}
                    and type(v) in (int, float) and 0 <= v <= 1e18 and math.isfinite(v)}
        stamp = info.get('time', {}).get('completed') if isinstance(info.get('time'), dict) else None
        completed = isinstance(stamp, (int, float)) and not isinstance(stamp, bool) and 0 <= stamp <= 1e16 and math.isfinite(stamp)
        terminal = completed and info.get('finish') in {'stop', 'length', 'content-filter'} and not any(
            part.get('type') == 'tool' for part in parts)
        messages.append({'id': mid, 'role': info['role'], 'parentId': info.get('parentID'),
            'completed': completed, 'terminalResult': terminal, 'events': events, 'usage': usage, 'usageProvenance': 'remote-reported'})
    return {'messages': messages}
