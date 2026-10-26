"""Bind original workflow custody to the existing native delegation service."""
import asyncio
from copy import deepcopy
from typing import Any

from fastapi import HTTPException

from .store import digest
from .workflow_contracts import (DELEGATED_OPERATION_ADAPTER, WorkflowAcknowledgementUnknown,
    WorkflowContext, delegated_result_bytes, validate_runtime_observation)
from .workflow_operations import require


DELEGATED_OPERATION_PIN = {'adapterId': DELEGATED_OPERATION_ADAPTER[0], 'revision': DELEGATED_OPERATION_ADAPTER[1],
    'configFingerprint': digest({})}


class DelegatedOperations:
    def __init__(self, delegation: Any, observer: Any, pin: dict[str, str]):
        self.delegation, self.observer = delegation, observer
        self.store = delegation.store
        self.pin = deepcopy(pin)

    def _original(self, context: WorkflowContext, operation_id: str):
        custody = self.store.workflow
        body = custody._load(context.owner_id, operation_id)
        custody._identity(body)
        require(custody._context(body) == context and body['adapterPin'] == self.pin)
        return body

    def _handle(self, context: WorkflowContext, handle: dict[str, Any]):
        require(type(handle) is dict and set(handle) == {'adapterId', 'revision', 'id'}
                and handle['adapterId'] == self.pin['adapterId'] and handle['revision'] == self.pin['revision'])
        body = self._original(context, handle['id'])
        require(body['handle'] == handle)
        return body

    def _child(self, body):
        rows = self.store.sql('SELECT * FROM af_delegation_links WHERE owner_id=:owner '
            'AND parent_id=:parent AND request_id=:request', owner=body['ownerId'],
            parent=body['taskId'], request='operation:' + body['id'])
        if not rows or rows[0]['child_id'] is None:
            return None
        link = rows[0]
        try:
            task = self.store.task(link['child_id'], body['ownerId'])
        except HTTPException as error:
            if error.status_code == 404:
                return None
            raise
        require(task['plan_id'] == link['plan_id'])
        return task

    async def start(self, context, operation_id, inputs):
        body = self._original(context, operation_id)
        require(type(inputs) is dict and set(inputs) == {'goal', 'mode'}
                and digest(inputs) == body['inputsSha256'] and not body['cancelRequested'] and not body['closed'])
        try:
            await self.delegation.create(context.owner_id, context.workflow_id,
                inputs['goal'], inputs['mode'], 'operation:' + operation_id, original_operation_id=operation_id)
        except TimeoutError as error:
            raise WorkflowAcknowledgementUnknown() from error
        except HTTPException as error:
            if error.status_code >= 500:
                raise WorkflowAcknowledgementUnknown() from error
            raise
        return await self.lookup(context, operation_id)

    async def lookup(self, context, operation_id):
        return await self._observe(self._original(context, operation_id))

    async def inspect(self, context, handle):
        return await self._observe(self._handle(context, handle))

    async def cancel(self, context, handle):
        body = self._handle(context, handle)
        def original_child():
            root_id, _ = self.delegation._ancestry(self.store.task(body['taskId'], body['ownerId']))
            with self.delegation._root_lock(root_id):
                return self._child(body)
        child = await asyncio.to_thread(original_child)
        if child is not None:
            cancelled = await self.observer.cancel_subtree(body['ownerId'], child['id'])
            if cancelled['errors']:
                raise HTTPException(503, 'DELEGATED_CHILD_CANCELLATION_UNKNOWN')
        return await self._observe(body)

    async def _observe(self, body):
        child = self._child(body)
        # The handle identifies custody, including the unknown interval before a
        # child reservation exists. Lookup never repairs or resubmits that gap.
        handle = {'adapterId': self.pin['adapterId'], 'revision': self.pin['revision'], 'id': body['id']}
        observed = {'schema': 1, 'operationId': body['id'], 'handle': handle,
            'state': 'UNKNOWN', 'allStopped': False, 'output': None, 'failure': None}
        if child is not None:
            group = await self.observer.inspect_subtree(body['ownerId'], child['id'])
            facts = [group['parent'], *group['children']]
            if group['allStopped']:
                observed['allStopped'] = True
                if any(item['failed'] for item in facts):
                    observed.update(state='FAILED', failure={'schema': 1, 'code': 'DELEGATED_CHILD_FAILED',
                        'messageCode': 'DELEGATED_CHILD_FAILED', 'retryable': False})
                elif any(item['nativeStatus'] in {'cancelled', 'canceled'} for item in facts):
                    observed['state'] = 'CANCELLED'
                else:
                    limit = self.store.plan(child['plan_id'], body['ownerId'])['budget']['outputBytes']
                    content = group['parent'].get('content')
                    failure = None
                    try:
                        if delegated_result_bytes(content) > limit:
                            failure = 'DELEGATED_RESULT_LIMIT'
                    except ValueError:
                        failure = 'DELEGATED_RESULT_INVALID'
                    if failure:
                        observed.update(state='FAILED', failure={'schema': 1, 'code': failure,
                            'messageCode': failure, 'retryable': False})
                    else:
                        observed.update(state='COMPLETED', output={'taskId': child['id'], 'runId': child['run_id'],
                            'result': content,
                            'artifacts': [{'taskId': child['id'], 'artifactId': item['id'], 'sha256': item['sha256']}
                                for item in self.store.artifacts(child['id'])]})
            elif not group['unknown']:
                observed['state'] = 'WAITING' if group['parent']['nativeStatus'] == 'paused' else 'RUNNING'
        return validate_runtime_observation(observed, body['id'], self.pin['adapterId'], self.pin['revision'])
