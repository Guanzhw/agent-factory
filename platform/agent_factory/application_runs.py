"""Persist one chat request and submit its original native task."""
import asyncio
from uuid import uuid4

from fastapi import HTTPException

from .store import digest, now


def factory_request_id(request_id):
    return 'application-start:' + request_id


class ApplicationRuns:
    def __init__(self, factory):
        self.factory = factory

    def _prepare(self, owner, body):
        store = self.factory.store
        self.factory.auth.require_member(owner)
        key = factory_request_id(body.requestId)
        values = body.model_dump(exclude={'interfaceVersion', 'requestId'})

        def create():
            plan = {'id': str(uuid4()), 'ownerId': owner, 'createdAt': now(),
                'application': 'research-chat', 'mode': body.mode,
                'normalizedGoal': body.goal, 'inputValues': body.inputValues or {},
                'connectionRefs': body.connectionRefs,
                'instructions': body.instructions if body.instructions is not None else getattr(store, 'research_instructions', []),
                'tools': list(getattr(getattr(store, 'research_tools', None), 'available_tools', [])),
                'status': 'ready', 'missing': []}
            plan['fingerprint'] = digest(plan)
            return store.save_plan(plan)

        return store.admit_plan(owner, key, values, create), key

    async def start(self, owner, body, *, delivery_id=None, private_event_id=None):
        from .factory_api import InstanceRequest
        if self.factory.store._connection.get() is not None:
            raise RuntimeError('Native admission requires a committed metadata boundary')
        plan, key = await asyncio.to_thread(self._prepare, owner, body)
        options = {}
        if delivery_id is not None:
            options['delivery_id'] = delivery_id
        if private_event_id is not None:
            options['private_event_id'] = private_event_id
        job = await self.factory.instantiate(owner, InstanceRequest(planId=plan['id'], requestId=key), **options)
        return {'interfaceVersion': 1, 'requestId': body.requestId, 'planId': plan['id'], 'job': job}

    def request(self, owner, request_id):
        self.factory.auth.require_member(owner)
        return self._request_receipt(owner, request_id)

    def _request_receipt(self, owner, request_id):
        """Original receipt for public authorization or an authorized private message."""
        key = factory_request_id(request_id)
        store = self.factory.store
        rows = store.sql('SELECT plan_id FROM af_plan_requests WHERE owner_id=:owner AND request_id=:key',
            owner=owner, key=key)
        if not rows:
            # Absence is not permission to replay a possibly in-flight start.
            raise HTTPException(404, 'APPLICATION_START_RECEIPT_NOT_FOUND')
        plan = store.plan(rows[0]['plan_id'], owner)
        try:
            task = store.task_for_request(key, owner)
        except HTTPException as error:
            if error.status_code != 404: raise
            task = None
        return {'interfaceVersion': 1, 'requestId': request_id,
            'planId': plan['id'],
            'state': 'prepared' if task is None else task['admission'],
            'taskId': task['id'] if task is not None else None,
            'runId': task['run_id'] if task is not None else None,
            'inputCommitted': True, 'preflightReady': plan['status'] == 'ready',
            'createsExecution': False, 'automaticReplay': False}
