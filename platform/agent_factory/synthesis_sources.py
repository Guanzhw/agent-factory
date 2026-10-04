"""Immutable owner-scoped selections from verified literature artifacts.

Snapshots are plan inputs, never published materials or execution permissions.
Historical reads do not grant current consumption: runtime calls revalidate.
"""
from __future__ import annotations

from copy import deepcopy
import re
from uuid import uuid4
from typing import Any, cast

from fastapi import HTTPException
from sqlalchemy import Column, JSON, MetaData, String, Table, and_, or_, select

from .applications import GovernedStorage
from .literature_evidence import inspect_literature_evidence
from .literature_synthesis import build_source_context
from .store import canonical, digest, now

_HASH = re.compile(r'[a-f0-9]{64}\Z')


def _require(value, code='SYNTHESIS_SOURCE_INVALID', status=409):
    if not value:
        raise HTTPException(status, code)


def _hash(value):
    return type(value) is str and bool(_HASH.fullmatch(value))


class SynthesisSourceService:
    def __init__(self, store, auth):
        self.store, self.auth = store, auth
        self.db = GovernedStorage(store, 'af_synthesis_sources_v1')
        metadata = MetaData()
        self.snapshots = Table('af_synthesis_sources', metadata,
            Column('id', String, primary_key=True), Column('owner_id', String, nullable=False, index=True),
            Column('body', JSON, nullable=False), Column('sha', String, nullable=False))
        self.commands = self.db.command_table('af_synthesis_source_commands', metadata)
        metadata.create_all(store.engine)

    def preview(self, owner, source_task_id):
        self.auth.require(owner, 'read')
        _require(type(source_task_id) is str and 1 <= len(source_task_id) <= 128, status=422)
        # Task ownership precedes every artifact read, even unavailable evidence.
        task = self.store.task(source_task_id, owner)
        _require(task.get('id') == source_task_id and task.get('terminal') is True
                 and task.get('body', {}).get('lastStatus') == 'completed' and not task.get('cancel_requested'),
                 'SYNTHESIS_SOURCE_NOT_COMPLETED')
        _require(task.get('run_id') is None or type(task['run_id']) is str and 1 <= len(task['run_id']) <= 128)
        plan = self.store.plan(task['plan_id'], owner)
        projection = inspect_literature_evidence(self.store, owner, source_task_id)
        _require(type(projection) is dict and projection.get('status') == 'ready', 'SYNTHESIS_SOURCE_UNAVAILABLE')
        pins = []
        rows = self.store.artifacts(source_task_id)
        for field in ('reportArtifactId', 'bundleArtifactId'):
            matches = [row for row in rows if row['id'] == projection[field]]
            _require(len(matches) == 1)
            row = matches[0]
            _require(type(row.get('id')) is str and 1 <= len(row['id']) <= 128)
            _require(_hash(row.get('sha256')) and type(row.get('size')) is int and row['size'] > 0)
            _require(type(row.get('provenance')) is dict and len(canonical(row['provenance']).encode()) <= 16384)
            pins.append({'id': row['id'], 'sha256': row['sha256'], 'size': row['size'],
                         'provenance': deepcopy(row['provenance'])})
        value = {'schema': 1, 'ownerId': owner, 'sourceTaskId': source_task_id, 'sourceRunId': task.get('run_id'),
                 'sourcePlanId': plan['id'],
                 'sourcePlanFingerprint': plan['fingerprint'], 'sourcePlanHash': digest(plan),
                 'artifacts': pins, 'projection': deepcopy(projection)}
        self.auth.require(owner, 'read')
        return {**value, 'fingerprint': digest(value)}

    def _row(self, conn, owner, identifier):
        row = conn.execute(select(self.snapshots).where(self.snapshots.c.id == identifier,
                           self.snapshots.c.owner_id == owner)).mappings().first()
        if row is None:
            raise HTTPException(404, 'SYNTHESIS_SOURCE_NOT_FOUND')
        value = cast(dict[str, Any], row['body'])
        _require(type(value) is dict and value.get('id') == identifier and value.get('ownerId') == owner)
        _require(row['sha'] == digest(value) and _hash(value.get('fingerprint')))
        _require(value['fingerprint'] == digest({key: item for key, item in value.items() if key != 'fingerprint'}))
        try:
            context = build_source_context(value['question'], value['projection'])
            _require(value['contextFingerprint'] == context.provenance['snapshotSha256'])
            _require(value['sourceIds'] == [source['sourceId'] for source in value['projection']['sources']])
        except (ValueError, TypeError, KeyError):
            raise HTTPException(409, 'SYNTHESIS_SOURCE_INVALID') from None
        return deepcopy(value)

    def read(self, owner, identifier):
        self.auth.require(owner, 'read')
        with self.db.read() as conn:
            value = self._row(conn, owner, identifier)
        self.auth.require(owner, 'read')
        return value

    def list(self, owner, *, source_task_id=None, after_id=None, limit=20):
        self.auth.require(owner, 'read')
        _require(type(limit) is int and 1 <= limit <= 50, status=422)
        created = self.snapshots.c.body['createdAt'].as_string()
        with self.db.read() as conn:
            query = select(self.snapshots.c.id).where(self.snapshots.c.owner_id == owner)
            if source_task_id is not None:
                self.store.task(source_task_id, owner)
                query = query.where(self.snapshots.c.body['sourceTaskId'].as_string() == source_task_id)
            if after_id is not None:
                anchor = self._row(conn, owner, after_id)
                _require(source_task_id is None or anchor['sourceTaskId'] == source_task_id, status=422)
                query = query.where(or_(created < anchor['createdAt'],
                    and_(created == anchor['createdAt'], self.snapshots.c.id < anchor['id'])))
            ids = conn.execute(query.order_by(created.desc(), self.snapshots.c.id.desc()).limit(limit + 1)).scalars().all()
            rows = [self._row(conn, owner, identifier) for identifier in ids[:limit]]
        self.auth.require(owner, 'read')
        return {'schema': 1, 'ownerId': owner, 'items': rows,
                'nextCursor': rows[-1]['id'] if len(ids) > limit else None, 'snapshot': False}

    def create(self, owner, *, source_task_id, source_ids, question, expected_fingerprint, request_id):
        self.auth.require(owner, 'run')
        _require(type(question) is str and 1 <= len(question.strip()) <= 1000, status=422)
        question = question.strip()
        _require(type(source_ids) is list and 1 <= len(source_ids) <= 3
                 and all(type(item) is str and 1 <= len(item) <= 320 for item in source_ids)
                 and len(set(source_ids)) == len(source_ids), status=422)
        _require(_hash(expected_fingerprint), status=422)
        command = digest({'sourceTaskId': source_task_id, 'sourceIds': sorted(source_ids),
                          'question': question, 'expectedFingerprint': expected_fingerprint})
        with self.db.write() as conn:
            previous = self.db.old(conn, self.commands, owner, request_id, command)
            if previous is not None:
                return self.revalidate(owner, previous['id'], expected_fingerprint=previous['fingerprint'])
            preview = self.preview(owner, source_task_id)
            _require(preview['fingerprint'] == expected_fingerprint, 'SYNTHESIS_SOURCE_STALE')
            projection = deepcopy(preview['projection'])
            projection['sources'] = [row for row in projection['sources'] if row['sourceId'] in source_ids]
            _require(len(projection['sources']) == len(source_ids), 'SYNTHESIS_SOURCE_SELECTION_INVALID', 422)
            projection['sourceCount'] = len(projection['sources'])
            try:
                context = build_source_context(question, projection)
            except (ValueError, TypeError, KeyError):
                raise HTTPException(422, 'SYNTHESIS_SOURCE_CONTEXT_INVALID') from None
            value = {'schema': 1, 'id': str(uuid4()), 'ownerId': owner, 'createdAt': now(),
                'question': question, 'requestId': request_id, 'sourceIds': [row['sourceId'] for row in projection['sources']],
                'sourceTaskId': source_task_id, 'sourceRunId': preview['sourceRunId'], 'sourcePlanId': preview['sourcePlanId'],
                'sourcePlanFingerprint': preview['sourcePlanFingerprint'], 'sourcePlanHash': preview['sourcePlanHash'],
                'artifacts': preview['artifacts'], 'projection': projection,
                'sourceFingerprint': preview['fingerprint'], 'contextFingerprint': context.provenance['snapshotSha256']}
            value['fingerprint'] = digest(value)
            # Recheck current authority and artifact bytes immediately before persistence.
            _require(self.preview(owner, source_task_id)['fingerprint'] == preview['fingerprint'], 'SYNTHESIS_SOURCE_STALE')
            self.auth.require(owner, 'run')
            conn.execute(self.snapshots.insert().values(id=value['id'], owner_id=owner, body=value, sha=digest(value)))
            self.db.record(conn, self.commands, owner, request_id, command, 'synthesis-source-create',
                           {'id': value['id'], 'fingerprint': value['fingerprint']})
            return deepcopy(value)

    def revalidate(self, owner, identifier, *, expected_fingerprint=None):
        self.auth.require(owner, 'run')
        value = self.read(owner, identifier)
        if expected_fingerprint is not None:
            _require(_hash(expected_fingerprint) and value['fingerprint'] == expected_fingerprint, 'SYNTHESIS_SOURCE_STALE')
        preview = self.preview(owner, value['sourceTaskId'])
        _require(preview['fingerprint'] == value['sourceFingerprint'], 'SYNTHESIS_SOURCE_STALE')
        for key in ('sourceTaskId', 'sourceRunId', 'sourcePlanId', 'sourcePlanFingerprint', 'sourcePlanHash', 'artifacts'):
            _require(preview[key] == value[key], 'SYNTHESIS_SOURCE_STALE')
        projection = deepcopy(preview['projection'])
        projection['sources'] = [source for source in projection['sources'] if source['sourceId'] in value['sourceIds']]
        projection['sourceCount'] = len(projection['sources'])
        _require(projection == value['projection'], 'SYNTHESIS_SOURCE_STALE')
        context = build_source_context(value['question'], projection)
        _require(context.provenance['snapshotSha256'] == value['contextFingerprint'])
        self.auth.require(owner, 'run')
        return value
