"""Thin public application start; existing Factory intents own durability."""
import asyncio
import json
from copy import deepcopy

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

    def tool_results(self, owner, task_id, run_id):
        """Private original CLI receipts; not permission to publish their output."""
        self.factory.auth.require_member(owner)
        store = self.factory.store
        task = store.task(task_id, owner)
        if task['id'] != task_id or not run_id or task['run_id'] != run_id:
            raise HTTPException(404, 'APPLICATION_ORIGINAL_RUN_NOT_FOUND')
        plan = store.plan(task['plan_id'], owner)
        materials = [item for item in plan['materials'] if item['kind'] == 'tool']
        bindings = plan.get('executionBindings', {}).get('tools', [])
        if (plan.get('nativeComponent') or plan.get('remoteHandoff')
                or len(materials) != 1 or len(bindings) != 1):
            raise HTTPException(409, 'APPLICATION_CLI_PROVENANCE_UNAVAILABLE')
        material, binding = materials[0], bindings[0]
        pin = {key: material[key] for key in ('id', 'version', 'sha256')}
        operation = store.personal_tools.operations.by_adapter(binding['adapterId'])
        if (plan['tools'] != [binding['toolName']] or binding['materialRef'] != pin
                or pin not in plan['materialRefs'] or operation is None
                or operation['descriptor']['transport'] != 'cli'
                or operation['descriptor']['toolName'] != binding['toolName']
                or operation['runtimeBinding']['revision'] != binding['revision']
                or operation['operationRef']['sha256'] != binding['config'].get('operationSha256')
                or material['runtimeBinding']['adapterId'] != binding['adapterId']
                or material['runtimeBinding']['revision'] != binding['revision']):
            raise HTTPException(409, 'APPLICATION_CLI_PROVENANCE_UNAVAILABLE')
        receipts = []
        for effect in store.effects(task_id):
            result = effect['result']
            if (effect['effect_key'].startswith(run_id + ':personal-tool:')
                    and effect['status'] == 'DONE' and isinstance(result, dict)
                    and result.get('outcome') == 'completed'):
                receipts.append({'effectKey': effect['effect_key'], 'outcome': 'completed',
                                 'output': deepcopy(result['output'])})
        return {'taskId': task_id, 'runId': run_id, 'planId': task['plan_id'],
                'materialRef': pin, 'operationRef': deepcopy(operation['operationRef']),
                'binding': {key: binding[key] for key in ('adapterId', 'revision', 'toolName')},
                'receipts': receipts}

    def ssh_results(self, owner, child_task_id, run_id):
        """Read private archived SSH evidence; never poll or resume remote work."""
        from .ssh_process_contract import OPERATION_PIN, LAUNCH_ADAPTER_ID, WAIT_ADAPTER_ID, REVISION, LAUNCH_TOOL, WAIT_TOOL
        from .store import digest
        from .resource_maintenance import ResourceMaintenance, _Held
        from .ssh_process_provider import EFFECT

        def require(value):
            if not value:
                raise HTTPException(409, 'APPLICATION_SSH_PROVENANCE_UNAVAILABLE')

        self.factory.auth.require_member(owner)
        store = self.factory.store
        task = store.task(child_task_id, owner)
        if task['id'] != child_task_id or not run_id or task['run_id'] != run_id:
            raise HTTPException(404, 'APPLICATION_ORIGINAL_RUN_NOT_FOUND')
        plan = store.plan(task['plan_id'], owner)
        materials = [item for item in plan['materials'] if item['kind'] == 'tool']
        bindings = plan.get('executionBindings', {}).get('tools', [])
        expected_tools = {LAUNCH_ADAPTER_ID: LAUNCH_TOOL, WAIT_ADAPTER_ID: WAIT_TOOL}
        require(not plan.get('nativeComponent') and not plan.get('remoteHandoff')
                and len(materials) == len(bindings) == 2
                and {binding['adapterId'] for binding in bindings} == set(expected_tools)
                and sorted(plan['tools']) == sorted(expected_tools.values()))
        selected = []
        for binding in bindings:
            matches = [material for material in materials
                if {key: material[key] for key in ('id', 'version', 'sha256')} == binding['materialRef']]
            require(len(matches) == 1)
            material = matches[0]
            require(binding['revision'] == REVISION and binding['toolName'] == expected_tools[binding['adapterId']]
                    and binding['materialRef'] in plan['materialRefs']
                    and material['runtimeBinding']['adapterId'] == binding['adapterId']
                    and material['runtimeBinding']['revision'] == REVISION)
            selected.append({'materialRef': deepcopy(binding['materialRef']),
                'binding': {key: binding[key] for key in ('adapterId', 'revision', 'toolName')}})
        rows = store.sql('SELECT id FROM af_external_operations WHERE owner_id=:owner AND task_id=:task AND native_run_id=:run',
            owner=owner, task=child_task_id, run=run_id)
        operations = [store.workflow.read(owner, row['id']) for row in rows]
        operations = [item for item in operations if item['adapterPin'] == OPERATION_PIN]
        require(len(operations) == 1)
        operation = operations[0]
        operation_id = operation['id']
        require(operation['id'] == operation_id and operation['taskId'] == child_task_id
                and operation['nativeRunId'] == run_id and operation['planId'] == task['plan_id']
                and operation['planSha256'] == digest(plan) and operation['adapterPin'] == OPERATION_PIN
                and operation['closed'] and operation['observation']['allStopped'])
        candidates = [item for item in store.artifacts(child_task_id)
            if item.get('provenance', {}).get('kind') == 'ssh-process'
            and item['provenance'].get('operationId') == operation_id
            and item['provenance'].get('evidenceRole') == 'receipt']
        require(len(candidates) == 1)
        metadata, raw = store.artifact(child_task_id, candidates[0]['id'])
        require(len(raw) <= 32768)
        try:
            receipt = json.loads(raw)
        except (ValueError, UnicodeDecodeError) as error:
            raise HTTPException(409, 'APPLICATION_SSH_PROVENANCE_UNAVAILABLE') from error
        require(isinstance(receipt, dict))
        try:
            lease = ResourceMaintenance(store.process_runtime.resources)._custody(receipt.get('leaseId'))
        except _Held as error:
            raise HTTPException(409, 'APPLICATION_SSH_PROVENANCE_UNAVAILABLE') from error
        require(lease['ownerId'] == owner and lease['localTaskId'] == child_task_id
                and lease['nativeRunId'] == run_id and lease['planId'] == task['plan_id']
                and lease['planHash'] == digest(plan) and lease.get('executionEffect') == EFFECT
                and lease['executionGuard'] == {'operationId': operation_id}
                and lease['stopEvidence']['allStopped'] is True
                and lease['stopEvidence']['kind'] in {'never-dispatched',
                    'original-root-reaped-and-no-live-process-group-members'})
        process = lease['processBinding']
        launch = next(binding for binding in bindings if binding['adapterId'] == LAUNCH_ADAPTER_ID)
        require(lease['connectionRef'] == 'ssh-' + digest({'actor': owner, 'material': launch['materialRef'],
            'connection': launch['connection'], 'profile': launch['config']['profileSha256']}))
        require(process['taskId'] == child_task_id and process['nativeRunId'] == run_id
                and process['planId'] == task['plan_id'])
        expected = {'kind': 'ssh-process', 'operationId': operation_id, 'leaseId': lease['id'],
            'providerJobId': lease['providerJobId'], 'nativeRunId': run_id, 'planId': task['plan_id'],
            'executionStatus': lease['executionStatus'], 'verificationStatus': 'unverified'}
        require(all(metadata['provenance'].get(key) == value for key, value in {**expected, 'evidenceRole': 'receipt'}.items())
                and metadata['jobId'] == child_task_id and receipt.get('schema') == 1
                and receipt.get('kind') == 'ssh-process' and receipt.get('operationId') == operation_id
                and receipt.get('taskId') == child_task_id and receipt.get('runId') == run_id
                and receipt.get('planId') == task['plan_id'] and receipt.get('leaseId') == lease['id']
                and receipt.get('allStopped') is True
                and all(receipt.get(key) == lease[key] for key in ('providerJobId', 'processBinding',
                    'executionStatus', 'exitCode', 'stopEvidence')))
        status = lease['executionStatus']
        require(status in {'COMPLETED', 'FAILED', 'CANCELLED', 'LIMIT_STOPPED'})
        require(operation['observation']['state'] == ('FAILED' if status in {'FAILED', 'LIMIT_STOPPED'} else status))
        artifacts = []
        output = receipt.get('output')
        if lease['stopEvidence']['kind'] == 'never-dispatched':
            require(receipt.get('outputState') == 'never_dispatched' and output is None)
        else:
            require(receipt.get('outputState') == 'artifact' and isinstance(output, dict)
                    and output.get('taskId') == child_task_id)
            output_metadata, _ = store.artifact(child_task_id, output['artifactId'])
            require(output_metadata['sha256'] == output['sha256'] and output_metadata['jobId'] == child_task_id
                    and all(output_metadata['provenance'].get(key) == value
                        for key, value in {**expected, 'evidenceRole': 'output'}.items()))
            artifacts.append({key: output[key] for key in ('taskId', 'artifactId', 'sha256')})
        return {'kind': 'ssh-process', 'taskId': child_task_id, 'runId': run_id, 'planId': task['plan_id'],
            'operationId': operation_id, 'materials': selected, 'receipt': deepcopy(receipt),
            'receiptArtifact': {'taskId': child_task_id, 'artifactId': metadata['id'], 'sha256': metadata['sha256']},
            'artifacts': artifacts}

    @staticmethod
    def _handoff(plan_id, original_request):
        # Route/body references only, never an authorization or dispatch grant.
        # The instance API rechecks current membership, ownership and resources.
        return {'authorizationURL': '/api/factory/plans/' + plan_id + '/authorization',
            'instantiateURL': '/api/factory/instances',
            'instantiateBody': {'planId': plan_id, 'requestId': original_request}}

    def _prepare(self, owner, body):
        store = self.factory.store
        self.factory.auth.require_member(owner)
        key = factory_request_id(body.requestId)
        values = body.model_dump(exclude={'interfaceVersion', 'requestId'})
        plan = store.admit_plan(owner, key, values, lambda: create_plan(store, owner,
            body.goal, body.mode, body.application, application_ref=body.applicationRef,
            material_choices=body.materialChoices, connection_refs=body.connectionRefs,
            **({'input_values': body.inputValues} if body.inputValues is not None else {})))
        return plan, key

    async def start(self, owner, body, *, allocation_id=None, delivery_id=None):
        from .factory_api import InstanceRequest
        if self.factory.store._connection.get() is not None:
            raise RuntimeError('Native admission requires a committed metadata boundary')
        if allocation_id is not None:
            def bind():
                with self.factory.store.transaction() as conn:
                    self.factory.store.local_budget_scopes.bind_request(conn, owner, allocation_id,
                        factory_request_id(body.requestId), delivery_id=delivery_id)
            await asyncio.to_thread(bind)
        plan, key = await asyncio.to_thread(self._prepare, owner, body)
        # This existing admission path scopes ordinary OwnerSubmissions, rechecks
        # current policy, reserves the original task before dispatch, and never
        # re-admits a task whose acknowledgement is unknown. No new approval or
        # retry policy is implemented here.
        options = {'allocation_id': allocation_id} if allocation_id is not None else {}
        if delivery_id is not None:
            options['delivery_id'] = delivery_id
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
            'planId': plan['id'], 'handoff': self._handoff(plan['id'], key),
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
        return service.request(factory.user(request)['id'], request_id)

    return router
