"""Immutable, explicitly public member operations over connection transactions."""
import json
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import Column, Integer, JSON, MetaData, String, Table, select

from .store import digest, now
from .tool_operations import normalize_operation, operation_hash, instantiate_operation_adapter, _descriptor

_ACTION = 'tool.operation.create'


class MemberToolOperations:
    def __init__(self, service):
        self.service = service
        self.connections = service.connections
        metadata = MetaData()
        self.operations = Table('af_member_tool_operations', metadata,
            Column('operation_id', String, primary_key=True),
            Column('version', Integer, primary_key=True), Column('owner_id', String, nullable=False),
            Column('body', JSON, nullable=False), Column('hash', String, nullable=False),
            Column('adapter_id', String, nullable=False, unique=True),
            Column('fingerprint', String, nullable=False), Column('created_at', String, nullable=False))
        metadata.create_all(self.connections.store.engine)

    @staticmethod
    def _adapter_id(operation_id, version, sha256):
        return 'member-operation-' + digest({'id': operation_id, 'version': version, 'sha256': sha256})

    def _verified(self, row):
        if row is None:
            raise HTTPException(404, 'TOOL_OPERATION_NOT_FOUND')
        try:
            data = dict(row)
            fingerprint = data.pop('fingerprint')
            for name in ('operation_id', 'owner_id'):
                self.connections._key(data[name])
            created = data['created_at']
            if type(created) is not str or not 1 <= len(created) <= 64 or any(ord(c) < 32 for c in created):
                raise ValueError()
            configuration = normalize_operation(data['body'])
            if (type(data['version']) is not int or data['version'] < 1
                    or digest(data) != fingerprint or configuration != data['body']
                    or operation_hash(configuration) != data['hash']
                    or self._adapter_id(data['operation_id'], data['version'], data['hash']) != data['adapter_id']):
                raise ValueError()
            from .personal_tools import _descriptor as public_descriptor
            descriptor = public_descriptor(_descriptor(configuration, data['adapter_id'], str(data['version'])))
            return {'operationRef': {'id': data['operation_id'], 'version': data['version'], 'sha256': data['hash']},
                'ownerId': data['owner_id'], 'configuration': configuration, 'descriptor': descriptor,
                'runtimeBinding': {'adapterId': data['adapter_id'], 'revision': str(data['version']),
                                   'config': {'operationSha256': data['hash']}}}
        except Exception:
            raise HTTPException(409, 'TOOL_OPERATION_INTEGRITY_FAILED') from None

    def _get(self, conn, operation_id, version, sha256=None):
        if type(version) is not int or version < 1:
            raise HTTPException(422, 'TOOL_OPERATION_VERSION_INVALID')
        value = self._verified(conn.execute(select(self.operations).where(
            self.operations.c.operation_id == operation_id, self.operations.c.version == version)).mappings().first())
        if sha256 is not None and sha256 != value['operationRef']['sha256']:
            raise HTTPException(409, 'TOOL_OPERATION_HASH_MISMATCH')
        return value

    def get(self, owner, operation_id, version, sha256=None):
        self.connections.auth.require_member(owner)
        self.connections._key(operation_id)
        with self.connections._read() as conn:
            return self._get(conn, operation_id, version, sha256)

    def list(self, owner):
        self.connections.auth.require_member(owner)
        with self.connections._read() as conn:
            rows = conn.execute(select(self.operations).order_by(
                self.operations.c.operation_id, self.operations.c.version)).mappings()
            return [self._verified(row) for row in rows]

    def _result(self, conn, result_ref):
        try:
            reference = json.loads(result_ref)
            if type(reference) is not dict or set(reference) != {'id', 'version'}:
                raise ValueError()
            self.connections._key(reference['id'])
        except Exception:
            raise HTTPException(409, 'TOOL_OPERATION_RESULT_INVALID') from None
        return self._get(conn, reference['id'], reference['version'])

    def result(self, owner, result_ref):
        """Resolve a recorded command with one read connection."""
        self.connections.auth.require_member(owner)
        with self.connections._read() as conn:
            return self._result(conn, result_ref)

    def create(self, owner, configuration, request_id, operation_id=None):
        connections = self.connections
        connections.auth.require_member(owner)
        connections._key(request_id)
        if operation_id is not None:
            connections._key(operation_id)
        try:
            normalized = normalize_operation(configuration)
        except ValueError:
            raise HTTPException(422, 'TOOL_OPERATION_CONFIGURATION_INVALID') from None
        intent = digest({'operation': _ACTION, 'operationId': operation_id, 'configuration': normalized})
        with connections._write() as conn:
            connections._lock(conn, owner)
            previous = connections._command(conn, owner, request_id, intent)
            if previous:
                return self._result(conn, previous['result_ref'])
            version = 1
            if operation_id is not None:
                rows = conn.execute(select(self.operations).where(
                    self.operations.c.operation_id == operation_id).order_by(self.operations.c.version)).mappings().all()
                if not rows:
                    raise HTTPException(404, 'TOOL_OPERATION_NOT_FOUND')
                values = [self._verified(row) for row in rows]
                if any(value['ownerId'] != owner for value in values):
                    raise HTTPException(403, 'TOOL_OPERATION_OWNER_REQUIRED')
                version = values[-1]['operationRef']['version'] + 1
            else:
                operation_id = 'operation-' + uuid4().hex
            sha256 = operation_hash(normalized)
            at = now()
            data = {'operation_id': operation_id, 'version': version, 'owner_id': owner, 'body': normalized,
                    'hash': sha256, 'adapter_id': self._adapter_id(operation_id, version, sha256), 'created_at': at}
            conn.execute(self.operations.insert().values(**data, fingerprint=digest(data)))
            result_ref = json.dumps({'id': operation_id, 'version': version}, sort_keys=True, separators=(',', ':'))
            conn.execute(connections.commands.insert().values(owner_id=owner, request_id=request_id,
                fingerprint=intent, action=_ACTION, result_ref=result_ref, created_at=at))
            conn.execute(connections.audit.insert().values(actor_id=owner, action=_ACTION,
                target_id=operation_id, body={'operationRef': {'id': operation_id, 'version': version, 'sha256': sha256}},
                created_at=at))
            return self._get(conn, operation_id, version)

    def by_adapter(self, adapter_id):
        """Internal lookup, independent of an account's state or visibility."""
        with self.connections._read() as conn:
            row = conn.execute(select(self.operations).where(self.operations.c.adapter_id == adapter_id)).mappings().first()
            return None if row is None else self._verified(row)

    def restore_adapter(self, adapter_id):
        value = self.by_adapter(adapter_id)
        if value is None:
            return None
        try:
            return instantiate_operation_adapter(value['configuration'], adapter_id,
                                                 value['runtimeBinding']['revision'])
        except ValueError:
            raise HTTPException(409, 'TOOL_OPERATION_ADAPTER_UNAVAILABLE') from None
