"""Core owner environment custody. Preparation never submits application work.

Only operator-installed packages may prepare compute. A package implements
prepare/check/stop/connection_configuration and owns its declared runtime wire;
the core persists owner/model/package pins before crossing the effect boundary.
"""
from contextlib import contextmanager
import os
try:
    import fcntl
except ImportError:  # Platform package v1 is Linux-only; metadata remains readable.
    fcntl = None
from pathlib import Path
import re
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Column, JSON, MetaData, String, Table, select

from .applications import GovernedStorage
from .store import digest, now


class ApplicationEnvironments:
    def __init__(self, store, auth, models, connections, packages):
        self.store, self.auth, self.models, self.connections = store, auth, models, connections
        self.packages = dict(packages)
        self.db = GovernedStorage(store, 'application-environments-v1')
        self.root = Path(store.settings.workspace).resolve() / 'application-environments'
        self.root.mkdir(mode=0o700, exist_ok=True)
        if self.root.is_symlink() or os.name == 'posix' and self.root.stat().st_mode & 0o077:
            raise ValueError('ENVIRONMENT_STORAGE_NOT_PRIVATE')
        metadata = MetaData()
        self.environments = Table('af_application_environments', metadata,
            Column('id', String, primary_key=True), Column('owner_id', String, nullable=False),
            Column('application_id', String, nullable=False), Column('body', JSON, nullable=False),
            Column('body_hash', String, nullable=False), Column('state', String, nullable=False),
            Column('connection_ref', String), Column('registration_ref', String),
            Column('updated_at', String, nullable=False))
        self.requests = Table('af_environment_requests', metadata,
            Column('owner_id', String, primary_key=True), Column('request_id', String, primary_key=True),
            Column('fingerprint', String, nullable=False), Column('environment_id', String, nullable=False),
            Column('action', String, nullable=False), Column('state', String, nullable=False),
            Column('diagnostic', String), Column('created_at', String, nullable=False))
        metadata.create_all(store.engine)

    def capabilities(self, owner):
        self.auth.require(owner, 'read')
        return {'locations': sorted({key.split(':', 1)[1] if ':' in key else 'platform' for key in self.packages}),
            'applications': sorted({key.split(':', 1)[0] for key in self.packages}),
            'modelSetup': '/api/factory/personal-models', 'preparationSubmitsResearch': False,
            'selfServiceSSH': getattr(self.packages.get('openresearch:ssh'), 'personal_servers', None) is not None,
            'platformBillingEnabled': False, 'hardExternalBudgetEnforced': False}

    def servers(self, owner):
        self.auth.require(owner, 'read')
        package = self.packages.get('openresearch:ssh')
        return package.servers(owner) if package is not None else []

    def _package(self, application, body):
        location = body.get('location', 'platform')
        return self.packages.get(application if location == 'platform' else application + ':' + location)

    @contextmanager
    def _fence(self, identifier):
        # Stable opaque ID, no user-provided filesystem component. The lock spans
        # committed intents and side effects, including concurrent API workers.
        if not re.fullmatch('env-[a-f0-9]{32}', identifier): raise HTTPException(404, 'ENVIRONMENT_NOT_FOUND')
        if fcntl is None: raise HTTPException(409, 'ENVIRONMENT_PLATFORM_UNSUPPORTED')
        with (self.root / (identifier + '.lock')).open('a+b') as handle:
            try:
                getattr(fcntl, 'flock')(handle, getattr(fcntl, 'LOCK_EX') | getattr(fcntl, 'LOCK_NB'))
            except BlockingIOError:
                raise HTTPException(409, 'ENVIRONMENT_PREPARATION_IN_PROGRESS') from None
            try: yield
            finally: getattr(fcntl, 'flock')(handle, getattr(fcntl, 'LOCK_UN'))

    def _row(self, conn, owner, identifier):
        row = conn.execute(select(self.environments).where(self.environments.c.id == identifier,
            self.environments.c.owner_id == owner)).mappings().first()
        if row is None: raise HTTPException(404, 'ENVIRONMENT_NOT_FOUND')
        if digest(row['body']) != row['body_hash'] or row['body']['ownerId'] != owner:
            raise HTTPException(409, 'ENVIRONMENT_INTEGRITY')
        return dict(row)

    def _public(self, row):
        package = self._package(row['application_id'], row['body'])
        policy = getattr(package, 'lifecycle_policy', None)
        return {'id': row['id'], 'applicationId': row['application_id'], 'location': row['body'].get('location', 'platform'),
            **({key: row['body'][key] for key in ('serverRef', 'remoteDirectory')} if row['body'].get('location') == 'ssh' else {}),
            'state': row['state'].lower(), 'packageVersion': row['body']['packageVersion'],
            'projectId': row['body']['projectId'], 'connectionRef': row['connection_ref'],
            'modelReference': row['body']['modelReference'], 'modelRevision': row['body']['modelRevision'],
            'dataRetained': True, 'researchSubmitted': False, 'updatedAt': row['updated_at'],
            **({'runtimeLimits': policy()} if callable(policy) else {})}

    def inspect(self, owner, identifier):
        self.auth.require(owner, 'read')
        with self.db.read() as conn: row = self._row(conn, owner, identifier)
        result = self._public(row)
        package = self._package(row['application_id'], row['body'])
        if row['state'] == 'READY':
            # Metadata may outlive the process. Never present stale READY as a
            # live environment after host/runtime stop or credential rotation.
            try:
                self.model_handle(owner, row['body']).check()
                if package is None or not package.check(row['body']): result['state'] = 'unavailable'
            except Exception: result['state'] = 'unavailable'
        return result

    def request(self, owner, request_id):
        self.auth.require(owner, 'read')
        with self.db.read() as conn:
            row = conn.execute(select(self.requests).where(self.requests.c.owner_id == owner,
                self.requests.c.request_id == request_id)).mappings().first()
            if row is None: raise HTTPException(404, 'ENVIRONMENT_REQUEST_NOT_FOUND')
            result = dict(row)
        return {'requestId': request_id, 'action': result['action'], 'state': result['state'].lower(),
            'diagnostic': result['diagnostic'], 'environment': self.inspect(owner, result['environment_id'])}

    def model_handle(self, owner, body):
        with self.models.db.read() as conn:
            binding = self.models.binding(conn, owner, body['modelReference'])
            if binding.revision != body['modelRevision']: raise HTTPException(409, 'ENVIRONMENT_MODEL_CHANGED')
            return binding.opaque_handle

    def prepare(self, owner, application, request_id, *, location='platform', server_ref=None, directory=None):
        self.auth.require(owner, 'run')
        self.connections._key(request_id)
        package = self._package(application, {'location': location})
        if package is None: raise HTTPException(409, 'ENVIRONMENT_PACKAGE_UNAVAILABLE')
        selection = {}
        identity = {'owner': owner, 'application': application}
        intent = {'action': 'prepare', 'application': application, 'location': location}
        if location == 'ssh':
            try: selection = package.selection(owner, server_ref, directory)
            except Exception: raise HTTPException(409, 'ENVIRONMENT_SSH_SELECTION_UNAVAILABLE') from None
            identity.update(location=location, serverRef=server_ref, directory=selection['remoteDirectory'])
            intent.update(serverRef=server_ref, directory=selection['remoteDirectory'])
        elif location != 'platform' or server_ref is not None or directory is not None:
            raise HTTPException(422, 'ENVIRONMENT_LOCATION_INVALID')
        identifier = 'env-' + digest(identity)[:32]
        fingerprint = digest(intent)
        with self._fence(identifier):
            with self.db.write() as conn:
                previous = conn.execute(select(self.requests).where(self.requests.c.owner_id == owner,
                    self.requests.c.request_id == request_id)).mappings().first()
                if previous:
                    if previous['fingerprint'] != fingerprint: raise HTTPException(409, 'IDEMPOTENCY_CONFLICT')
                    # GET is the recovery operation. POST replay returns custody;
                    # an interrupted prepare requires a new explicit prepare.
                    return self.request(owner, request_id)
                model = self.models.default(owner)
                old = conn.execute(select(self.environments).where(self.environments.c.id == identifier,
                    self.environments.c.owner_id == owner)).mappings().first()
                if old:
                    row = self._row(conn, owner, identifier)
                    body = row['body']
                    if body['modelReference'] != model['reference'] or body['modelRevision'] != model['revision']:
                        raise HTTPException(409, 'ENVIRONMENT_MODEL_CHANGED: keep original work; explicit migration required')
                    if any(body.get(key) != value for key, value in selection.items()):
                        raise HTTPException(409, 'ENVIRONMENT_SERVER_CHANGED: explicit migration required')
                    if body['packageVersion'] != package.version:
                        raise HTTPException(409, 'ENVIRONMENT_UPDATE_REQUIRES_MIGRATION')
                else:
                    body = {'id': identifier, 'ownerId': owner, 'applicationId': application,
                        'packageVersion': package.version, 'projectId': str(uuid4()),
                        'modelReference': model['reference'], 'modelRevision': model['revision'], **selection}
                    conn.execute(self.environments.insert().values(id=identifier, owner_id=owner,
                        application_id=application, body=body, body_hash=digest(body), state='PREPARING',
                        updated_at=now()))
                conn.execute(self.requests.insert().values(owner_id=owner, request_id=request_id,
                    fingerprint=fingerprint, environment_id=identifier, action='prepare', state='PREPARING', created_at=now()))
                conn.execute(self.environments.update().where(self.environments.c.id == identifier).values(state='PREPARING', updated_at=now()))
            # Original project and model pins were committed before any install.
            phase = 'ENVIRONMENT_MODEL_CHECK_UNCONFIRMED'
            try:
                handle = self.model_handle(owner, body); handle.check()
                phase = 'ENVIRONMENT_RUNTIME_PREPARATION_UNCONFIRMED'
                package.prepare(body, handle)
                phase = 'ENVIRONMENT_HEALTH_UNCONFIRMED'
                handle.check()
                if not package.check(body): raise ValueError('ENVIRONMENT_HEALTH_FAILED')
                connection = None
                if old and row['connection_ref']:
                    try:
                        candidate = self.connections.inspect(owner, row['connection_ref'])
                        if candidate['available']: connection = candidate
                    except HTTPException: pass
                if connection is None:
                    phase = 'ENVIRONMENT_CONNECTION_UNCONFIRMED'
                    configuration = package.connection_configuration(body)
                    if configuration.get('projectId') != body['projectId']:
                        raise ValueError('ENVIRONMENT_PROJECT_CHANGED')
                    remote = self.connections.personal.configure(owner, package.provider_id, configuration,
                        request_id + ':configure', reference=row['registration_ref'] if old else None)
                    self.connections.personal.verify(owner, remote['registrationRef'], request_id + ':verify')
                    connection = self.connections.bind(owner, remote['registrationRef'], request_id + ':bind')
                    registration_ref = remote['registrationRef']
                else: registration_ref = row['registration_ref']
                with self.db.write() as conn:
                    conn.execute(self.environments.update().where(self.environments.c.id == identifier,
                        self.environments.c.owner_id == owner).values(state='READY', registration_ref=registration_ref,
                        connection_ref=connection['ref'], updated_at=now()))
                    conn.execute(self.requests.update().where(self.requests.c.owner_id == owner,
                        self.requests.c.request_id == request_id).values(state='READY'))
            except Exception:
                # Do not infer rollback/absence from a timeout. The next explicit
                # prepare must reconcile the same runtime and project identity.
                with self.db.write() as conn:
                    conn.execute(self.environments.update().where(self.environments.c.id == identifier,
                        self.environments.c.owner_id == owner).values(state='UNKNOWN', updated_at=now()))
                    conn.execute(self.requests.update().where(self.requests.c.owner_id == owner,
                        self.requests.c.request_id == request_id).values(state='UNKNOWN', diagnostic=phase))
            return self.request(owner, request_id)

    def stop(self, owner, identifier, request_id):
        self.auth.require(owner, 'run'); self.connections._key(request_id)
        with self._fence(identifier):
            with self.db.write() as conn:
                row = self._row(conn, owner, identifier)
                fingerprint = digest({'action': 'stop', 'id': identifier})
                old = conn.execute(select(self.requests).where(self.requests.c.owner_id == owner,
                    self.requests.c.request_id == request_id)).mappings().first()
                if old:
                    if old['fingerprint'] != fingerprint: raise HTTPException(409, 'IDEMPOTENCY_CONFLICT')
                    return self.request(owner, request_id)
                conn.execute(self.requests.insert().values(owner_id=owner, request_id=request_id,
                    fingerprint=fingerprint, environment_id=identifier, action='stop', state='STOPPING', created_at=now()))
            package = self._package(row['application_id'], row['body'])
            stopped = package is not None and package.stop(row['body'])
            state = 'STOPPED' if stopped else 'UNKNOWN'
            with self.db.write() as conn:
                conn.execute(self.environments.update().where(self.environments.c.id == identifier,
                    self.environments.c.owner_id == owner).values(state=state, updated_at=now()))
                conn.execute(self.requests.update().where(self.requests.c.owner_id == owner,
                    self.requests.c.request_id == request_id).values(state=state))
            return self.request(owner, request_id)

    def close(self):
        for package in self.packages.values(): package.close()


class PrepareEnvironment(BaseModel):
    model_config = ConfigDict(extra='forbid')
    requestId: str = Field(min_length=8, max_length=80, pattern=r'^[A-Za-z0-9_.:-]+$')
    applicationId: str = 'openresearch'
    location: str = 'platform'
    serverRef: str | None = Field(default=None, max_length=80)
    directory: str | None = Field(default=None, max_length=4096)


class StopEnvironment(BaseModel):
    model_config = ConfigDict(extra='forbid')
    requestId: str = Field(min_length=8, max_length=80, pattern=r'^[A-Za-z0-9_.:-]+$')


def environment_router(auth, service):
    router = APIRouter(prefix='/api/factory/application-environments')
    def owner(request): return auth.user(request)['id']
    @router.get('/capabilities')
    def capabilities(request: Request): return service.capabilities(owner(request))
    @router.get('/servers')
    def servers(request: Request): return service.servers(owner(request))
    @router.post('/prepare', status_code=202)
    def prepare(body: PrepareEnvironment, request: Request):
        current = owner(request)
        if request.headers.get('X-Factory-Expected-Owner') != current:
            raise HTTPException(409, 'EXPECTED_OWNER_MISMATCH')
        return service.prepare(current, body.applicationId, body.requestId, location=body.location,
            server_ref=body.serverRef, directory=body.directory)
    @router.get('/requests/{request_id}')
    def recovery(request_id: str, request: Request): return service.request(owner(request), request_id)
    @router.get('/{identifier}')
    def inspect(identifier: str, request: Request): return service.inspect(owner(request), identifier)
    @router.post('/{identifier}/stop', status_code=202)
    def stop(identifier: str, body: StopEnvironment, request: Request):
        current = owner(request)
        if request.headers.get('X-Factory-Expected-Owner') != current: raise HTTPException(409, 'EXPECTED_OWNER_MISMATCH')
        return service.stop(current, identifier, body.requestId)
    return router
