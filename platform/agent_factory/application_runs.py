"""Persist one chat request and submit its original native task."""
import asyncio
from uuid import uuid4

from fastapi import HTTPException

from .store import digest, now


def factory_request_id(request_id, application='research-chat'):
    legacy_key = 'application-start:' + request_id
    if application == 'research-chat' and len(legacy_key) <= 200:
        return legacy_key
    return 'application-run:' + digest([application, request_id])


class StartNotSubmitted(HTTPException):
    """This start attempt failed before contacting the native execution queue."""
    message = '任务在提交执行队列前失败；本轮未启动，请检查模型或工具设置后继续。'

    def __init__(self, error):
        if isinstance(error, HTTPException):
            super().__init__(error.status_code, error.detail, error.headers)
        else:
            super().__init__(503, self.message)


class ApplicationRuns:
    def __init__(self, factory, *, application='chat', instructions=()):
        self.factory = factory
        self.application, self.instructions = application, instructions

    def _prepare(self, owner, body):
        store = self.factory.store
        self.factory.auth.require_member(owner)
        key = factory_request_id(body.requestId, self.application)
        values = body.model_dump(exclude={'interfaceVersion', 'requestId'})

        fingerprint = digest(values)
        try:
            task = store.task_for_request(key, owner)
        except HTTPException as error:
            if error.status_code != 404:
                raise
            task = None
        if task is not None:
            execution = store.execution(task)
            if execution['application'] != self.application:
                raise HTTPException(409, 'APPLICATION_REQUEST_SCOPE_MISMATCH')
            original = execution.get('requestFingerprint')
            if original is None:
                legacy = self._legacy_request(owner, key)
                original = legacy['request_fingerprint'] if legacy else None
            if original != fingerprint:
                raise HTTPException(409, 'IDEMPOTENCY_CONFLICT: application request changed')
            return execution, key
        legacy = self._legacy_request(owner, key)
        if legacy is not None:
            if legacy['request_fingerprint'] != fingerprint:
                raise HTTPException(409, 'IDEMPOTENCY_CONFLICT: application request changed')
            return {**legacy['body'], 'requestFingerprint': fingerprint}, key
        execution = {'id': str(uuid4()), 'ownerId': owner, 'createdAt': now(), 'requestId': body.requestId,
            'application': self.application, 'mode': body.mode,
            'normalizedGoal': body.goal, 'inputValues': body.inputValues or {},
            'connectionRefs': body.connectionRefs,
            'instructions': body.instructions if body.instructions is not None else list(self.instructions),
            'requestFingerprint': fingerprint}
        return execution, key

    def _legacy_request(self, owner, key):
        rows = self.factory.store.sql('SELECT p.body,p.hash,r.fingerprint AS request_fingerprint '
            'FROM af_plan_requests r JOIN af_plans p ON p.id=r.plan_id '
            'WHERE r.owner_id=:owner AND p.owner_id=:owner AND r.request_id=:key', owner=owner, key=key)
        if not rows:
            return None
        row = rows[0]
        if digest(row['body']) != row['hash']:
            raise HTTPException(409, 'LEGACY_EXECUTION_INTEGRITY_MISMATCH')
        return row

    async def start(self, owner, body, *, delivery_id=None, private_event_id=None):
        if self.factory.store._connection.get() is not None:
            raise RuntimeError('Native admission requires a committed metadata boundary')
        try:
            execution, key = await asyncio.to_thread(self._prepare, owner, body)
        except Exception as error:
            raise StartNotSubmitted(error) from error
        options = {}
        if delivery_id is not None:
            options['delivery_id'] = delivery_id
        if private_event_id is not None:
            options['private_event_id'] = private_event_id
        job = await self.factory.instantiate(owner, execution, key, **options)
        return {'interfaceVersion': 1, 'requestId': body.requestId,
                'executionId': job['executionId'], 'planId': job['executionId'], 'job': job}

    def request(self, owner, request_id):
        self.factory.auth.require_member(owner)
        return self._request_receipt(owner, request_id)

    def _request_receipt(self, owner, request_id):
        """Original receipt for public authorization or an authorized private message."""
        key = factory_request_id(request_id, self.application)
        store = self.factory.store
        try:
            task = store.task_for_request(key, owner)
        except HTTPException as error:
            if error.status_code != 404: raise
            task = None
        if task is None:
            legacy = self._legacy_request(owner, key)
            if legacy is None:
                # Absence is not permission to replay a possibly in-flight start.
                raise HTTPException(404, 'APPLICATION_START_RECEIPT_NOT_FOUND')
            execution = legacy['body']
        else:
            execution = store.execution(task)
        if execution['application'] != self.application:
            raise HTTPException(404, 'APPLICATION_START_RECEIPT_NOT_FOUND')
        return {'interfaceVersion': 1, 'requestId': request_id,
            'executionId': execution['id'], 'planId': execution['id'],
            'state': 'prepared' if task is None else task['admission'],
            'taskId': task['id'] if task is not None else None,
            'runId': task['run_id'] if task is not None else None,
            'inputCommitted': True, 'preflightReady': True,
            'createsExecution': False, 'automaticReplay': False}
