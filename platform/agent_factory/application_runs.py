"""Thin public application start; existing Factory intents own durability."""
import asyncio

from fastapi import APIRouter, HTTPException, Path, Request
from .application_interface import ApplicationStart
from .catalog import create_plan
from .remote_handoff import FactoryPublicRoute


def factory_request_id(request_id):
    # Separate from legacy/direct request IDs without changing their ledgers.
    return 'application-start:' + request_id


class ApplicationRuns:
    def __init__(self, factory):
        self.factory = factory

    def _prepare(self, owner, body):
        store = self.factory.store
        self.factory.auth.require(owner, 'run')
        key = factory_request_id(body.requestId)
        values = body.model_dump(exclude={'interfaceVersion', 'requestId'})
        plan = store.admit_plan(owner, key, values, lambda: create_plan(store, owner,
            body.goal, body.mode, body.application, application_ref=body.applicationRef,
            material_choices=body.materialChoices, connection_refs=body.connectionRefs,
            **({'input_values': body.inputValues} if body.inputValues is not None else {})))
        return plan, key

    async def start(self, owner, body):
        from .factory_api import InstanceRequest
        plan, key = await asyncio.to_thread(self._prepare, owner, body)
        # This existing admission path scopes ordinary OwnerSubmissions, rechecks
        # current policy, reserves the original task before dispatch, and never
        # re-admits a task whose acknowledgement is unknown. No new approval or
        # retry policy is implemented here.
        job = await self.factory.instantiate(owner, InstanceRequest(planId=plan['id'], requestId=key))
        return {'interfaceVersion': 1, 'requestId': body.requestId, 'job': job}

    def request(self, owner, request_id):
        self.factory.auth.require(owner, 'read')
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
            'state': 'prepared' if task is None else task['admission'],
            'taskId': task['id'] if task is not None else None,
            'runId': task['run_id'] if task is not None else None,
            'inputCommitted': True, 'preflightReady': plan['status'] == 'ready',
            'createsExecution': False, 'automaticReplay': False}


def application_runs_router(factory):
    service = ApplicationRuns(factory)
    router = APIRouter(prefix='/application-interface/v1', route_class=FactoryPublicRoute)

    @router.post('/starts', status_code=202)
    async def start(body: ApplicationStart, request: Request):
        owner = factory.user(request)['id']
        return await service.start(owner, body)

    @router.get('/starts/{request_id}')
    def receipt(request: Request, request_id: str = Path(min_length=8, max_length=80, pattern=r'^[A-Za-z0-9_.:-]+$')):
        return service.request(factory.user(request, 'read')['id'], request_id)

    return router
