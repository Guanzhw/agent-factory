"""Original native custody over the existing process lease maintenance path."""
import asyncio
from copy import deepcopy
from dataclasses import asdict, dataclass, replace
import hashlib
import json

from .process_runtime import ProcessRuntimeService, process_reservation
from .resource_maintenance import ResourceMaintenance
from .resources import TERMINAL, ComputePool, RemoteTarget
from .ssh_process_contract import LAUNCH_ADAPTER_ID, LAUNCH_TOOL, OPERATION_PIN, REVISION
from .ssh_process_provider import EFFECT, SSHProcessProvider, SSHProcessTransport
from .store import canonical, digest
from .workflow_contracts import validate_runtime_observation
from .workflow_operations import require


@dataclass(frozen=True)
class SSHTrainingProfile:
    spec: object
    limits: object
    interpreter: str
    pool: ComputePool

    @property
    def fingerprint(self):
        return digest({'spec': asdict(self.spec), 'limits': asdict(self.limits),
                       'interpreter': self.interpreter, 'pool': asdict(self.pool)})


class SSHOperationRuntime(ProcessRuntimeService):
    effect_key = EFFECT
    tool_name = LAUNCH_TOOL

    def __init__(self, store, resources, personal_ssh, profiles, *, pin=OPERATION_PIN):
        super().__init__(store, resources.auth, resources)
        self.pin = deepcopy(pin)
        self.personal_ssh, self.profiles = personal_ssh, dict(profiles)

    def _selected(self, task, plan):
        context = self._context(task)
        tools = self.store.execution_bindings.manifest(plan, context=context).get('tools', [])
        selected = [item for item in tools if item.get('toolName') == LAUNCH_TOOL]
        require(len(selected) == 1 and selected[0]['adapterId'] == LAUNCH_ADAPTER_ID
                and selected[0]['revision'] == REVISION)
        spec = selected[0]
        config = spec['config']
        require(set(config) == {'connectionName', 'profileId', 'profileSha256'})
        profile = self.profiles.get(config['profileId'])
        require(isinstance(profile, SSHTrainingProfile) and profile.fingerprint == config['profileSha256'])
        target_ref = 'ssh-' + digest({'actor': task['owner_id'], 'material': spec['materialRef'],
                                      'connection': spec['connection'], 'profile': profile.fingerprint})
        return spec, profile, target_ref

    def ensure_target(self, task, plan):
        spec, profile, reference = self._selected(task, plan)
        pin = spec['connection']
        connections = self.store.execution_bindings.connections
        connections.preflight(task['owner_id'], pin['ref'], expected_kind='environment',
            expected_revision=pin['revision'], expected_fingerprint=pin['fingerprint'],
            expected_version=pin['version'], required_capabilities=('ssh:execute',),
            task_id=task['id'], expected_adapter_ref='owner-ssh-server-v1')
        registration = connections.inspect(task['owner_id'], pin['ref'])['registrationRef']
        server = self.personal_ssh.server(task['owner_id'], registration, required_capability='ssh:execute')
        transport = SSHProcessTransport(server,
            lambda action: self.personal_ssh.lease(server, required_capability='ssh:execute'),
            interpreter=profile.interpreter)
        def read_lease(owner, lease_id):
            lease = self._custody(lease_id)[0]
            require(lease['ownerId'] == owner)
            return lease
        provider = SSHProcessProvider(server, target_ref=reference, spec=profile.spec, limits=profile.limits,
                                      exchange=transport, read_lease=read_lease,
                                      archive_original=lambda owner, key: self._archive(read_lease(owner, key)))
        pool = replace(profile.pool, pool_id='ssh-host-' + provider.capacity_namespace)
        reservation = process_reservation(provider)
        target = RemoteTarget(name=server.name, axis='compute', owners=frozenset({task['owner_id']}),
            provider=provider, capacity_pool=pool, configuration_revision=profile.fingerprint,
            max_leases=pool.max_owner_leases, max_cpu=pool.cpu, max_memory_mb=pool.memory_mb,
            max_disk_mb=pool.disk_mb, max_seconds=reservation['seconds'])
        self.resources.register_target(reference, target)
        return reference

    def restore_target(self, owner, reference):
        rows = self.store.sql('SELECT body FROM af_leases WHERE owner_id=:owner AND target_id=:target',
                              owner=owner, target=digest({'owner': owner, 'connectionRef': reference}))
        require(bool(rows))
        original = self.resources._body(rows[0]['body'])
        require(original['connectionRef'] == reference and original.get('executionEffect') == EFFECT)
        task = self.store.task(original['localTaskId'], owner)
        plan = self.store.plan(original['planId'], owner)
        require(task['run_id'] == original['nativeRunId'] and digest(plan) == original['planHash']
                and self._selected(task, plan)[2] == reference)
        self.ensure_target(task, plan)
        return self.resources.targets[reference]

    def _operation(self, context, operation_id):
        custody = self.store.workflow
        body = custody._load(context.owner_id, operation_id)
        custody._identity(body)
        require(custody._context(body) == context and body['adapterPin'] == self.pin)
        return body

    def _handle(self, context, handle):
        require(type(handle) is dict and set(handle) == {'adapterId', 'revision', 'id'}
                and handle['adapterId'] == self.pin['adapterId'] and handle['revision'] == self.pin['revision'])
        body = self._operation(context, handle['id'])
        require(body['handle'] == handle)
        return body

    def validate_execution(self, owner, task, plan, target_ref, execution):
        require(type(execution) is dict and set(execution) == {'nativeRunId', 'effectKey', 'requirement'}
                and execution['effectKey'] == EFFECT and execution['nativeRunId'] == task['run_id']
                and owner == task['owner_id'] and type(execution['requirement']) is dict
                and set(execution['requirement']) == {'operationId'})
        body = self.store.workflow._load(owner, execution['requirement']['operationId'])
        self.store.workflow._identity(body)
        require(body['taskId'] == task['id'] and body['nativeRunId'] == task['run_id']
                and body['planSha256'] == digest(plan) and body['adapterPin'] == self.pin
                and not body['cancelRequested'] and not body['closed'])
        require(self._selected(task, plan)[2] == target_ref)
        self.store.authorize_tool(self._context(task), LAUNCH_TOOL)

    def guard_lease(self, lease):
        self.resources._authorize(lease['ownerId'], lease['connectionRef'])
        task = self.store.task(lease['localTaskId'], lease['ownerId'])
        plan = self.store.plan(lease['planId'], lease['ownerId'])
        require(task['plan_id'] == lease['planId'] and digest(plan) == lease['planHash'])
        self.validate_execution(lease['ownerId'], task, plan, lease['connectionRef'],
            {'nativeRunId': lease['nativeRunId'], 'effectKey': EFFECT,
             'requirement': lease['executionGuard']})

    def _custody(self, lease_id):
        original = ResourceMaintenance(self.resources)._custody(lease_id)
        if original['connectionRef'] not in self.resources.targets:
            self.resources._authorize(original['ownerId'], original['connectionRef'])
        lease, target, task, ticket = super()._custody(lease_id)
        guard = lease.get('executionGuard')
        require(type(guard) is dict and set(guard) == {'operationId'})
        body = self.store.workflow._load(lease['ownerId'], guard['operationId'])
        self.store.workflow._identity(body)
        require(body['adapterPin'] == self.pin and body['taskId'] == lease['localTaskId']
                and body['nativeRunId'] == lease['nativeRunId'] and body['planSha256'] == lease['planHash'])
        return lease, target, task, ticket

    def _reason(self, lease, task, ticket):
        body = self.store.workflow._load(lease['ownerId'], lease['executionGuard']['operationId'])
        if body['cancelRequested']:
            return 'OPERATION_CANCEL_REQUESTED'
        return super()._reason(lease, task, ticket)

    async def launch(self, context, call_id):
        self.store.authorize_tool(context, LAUNCH_TOOL)
        task = self.store.task(context.session_id, context.user_id)
        plan = self.store.plan(task['plan_id'], context.user_id)
        target_ref = self.ensure_target(task, plan)
        return await self.store.workflow.start(context, 'ssh-process-launch', 'ssh-process', self.pin,
                                               {'targetRef': target_ref, 'callId': call_id})

    async def start(self, context, operation_id, inputs):
        body = self._operation(context, operation_id)
        require(type(inputs) is dict and set(inputs) == {'targetRef', 'callId'}
                and digest(inputs) == body['inputsSha256'] and not body['cancelRequested'] and not body['closed'])
        target = self.resources._authorize(body['ownerId'], inputs['targetRef'])
        await self.resources.allocate(body['ownerId'], inputs['targetRef'], body['taskId'],
            'ssh-operation-' + operation_id, process_reservation(self.resources._provider(target)),
            execution={'nativeRunId': body['nativeRunId'], 'effectKey': EFFECT,
                       'requirement': {'operationId': operation_id}})
        return await self._observe(body)

    async def lookup(self, context, operation_id):
        return await self._observe(self._operation(context, operation_id))

    async def inspect(self, context, handle):
        return await self._observe(self._handle(context, handle))

    async def cancel(self, context, handle):
        body = self._handle(context, handle)
        require(body['cancelRequested'])
        return await self._observe(body)

    async def _read(self, lease_id):
        lease = await super()._read(lease_id)
        if lease['state'] in TERMINAL | {'RECLAIMED'}:
            await self._archive(lease)
        return lease

    async def _archive(self, lease):
        lease, target, _, _ = self._custody(lease['id'])
        require(lease.get('stopEvidence', {}).get('allStopped') is True)
        operation_id = lease['executionGuard']['operationId']
        receipt_name = f'ssh-{operation_id}-receipt.json'
        never_dispatched = lease['stopEvidence'].get('kind') == 'never-dispatched'
        existing = [a for a in self.store.artifacts(lease['localTaskId']) if a['name'] == receipt_name]
        if existing:
            require(len(existing) == 1)
            metadata, saved = self.store.artifact(lease['localTaskId'], existing[0]['id'])
            receipt = json.loads(saved)
            expected = {'kind': 'ssh-process', 'operationId': operation_id, 'leaseId': lease['id'],
                'providerJobId': lease['providerJobId'], 'nativeRunId': lease['nativeRunId'],
                'planId': lease['planId'], 'executionStatus': lease['executionStatus'], 'evidenceRole': 'receipt'}
            require(all(metadata['provenance'].get(k) == v for k, v in expected.items())
                    and receipt['schema'] == 1 and receipt['allStopped'] is True
                    and receipt['kind'] == 'ssh-process' and receipt['operationId'] == operation_id
                    and receipt['leaseId'] == lease['id'] and receipt['planId'] == lease['planId']
                    and receipt['taskId'] == lease['localTaskId'] and receipt['runId'] == lease['nativeRunId']
                    and all(receipt.get(k) == lease[k] for k in ('providerJobId', 'processBinding',
                        'executionStatus', 'exitCode', 'stopEvidence')))
            output = receipt['output']
            require(receipt['outputState'] == ('never_dispatched' if never_dispatched else 'artifact'))
            if never_dispatched:
                require(output is None)
            else:
                require(output['taskId'] == lease['localTaskId'])
                output_metadata, _ = self.store.artifact(lease['localTaskId'], output['artifactId'])
                require(output_metadata['sha256'] == output['sha256'] and all(
                    output_metadata['provenance'].get(k) == v
                    for k, v in {**expected, 'evidenceRole': 'output'}.items()))
            return receipt
        raw = None if never_dispatched else await asyncio.to_thread(
            target.provider.read_completed_output, lease['id'], lease['ownerId'])
        provenance = {'kind': 'ssh-process', 'operationId': operation_id, 'leaseId': lease['id'],
            'providerJobId': lease['providerJobId'], 'nativeRunId': lease['nativeRunId'],
            'planId': lease['planId'], 'executionStatus': lease['executionStatus'],
            'verificationStatus': 'unverified'}
        def write():
            with self.store.transaction():
                self.store.workflow._lock_task(lease['ownerId'], lease['localTaskId'])
                self._custody(lease['id'])
                artifacts = self.store.artifacts(lease['localTaskId'])
                def artifact(name, data, media, role):
                    found = [a for a in artifacts if a['name'] == name]
                    metadata = {**provenance, 'evidenceRole': role}
                    if found:
                        require(len(found) == 1 and found[0]['sha256'] == hashlib.sha256(data).hexdigest()
                                and all(found[0]['provenance'].get(k) == v for k, v in metadata.items()))
                        return found[0]
                    return self.store.artifact_write(lease['localTaskId'], name, data, media, metadata)
                output = None if raw is None else artifact(
                    f'ssh-{operation_id}-output.log', raw, 'application/octet-stream', 'output')
                receipt = {key: lease[key] for key in ('providerJobId', 'processBinding', 'executionStatus',
                                                      'exitCode', 'stopEvidence')}
                receipt.update(schema=1, kind='ssh-process', operationId=operation_id,
                    taskId=lease['localTaskId'], runId=lease['nativeRunId'], planId=lease['planId'],
                    leaseId=lease['id'], allStopped=True,
                    outputState='never_dispatched' if never_dispatched else 'artifact',
                    output=None if output is None else {
                        'taskId': lease['localTaskId'], 'artifactId': output['id'], 'sha256': output['sha256']})
                artifact(receipt_name, canonical(receipt).encode(), 'application/json', 'receipt')
                return receipt
        return await asyncio.to_thread(write)

    async def _observe(self, body):
        observed = {'schema': 1, 'operationId': body['id'],
            'handle': {'adapterId': self.pin['adapterId'], 'revision': self.pin['revision'], 'id': body['id']},
            'state': 'UNKNOWN', 'allStopped': False, 'output': None, 'failure': None}
        original = self._original(body['taskId'])
        if original is not None:
            lease, _, _, _ = self._custody(original['lease_id'])
            require(lease['executionGuard']['operationId'] == body['id'])
            lease = await self.observe_lease(lease['id'])
            if lease['state'] == 'RECLAIMED':
                receipt = await self._archive(lease)
                observed['allStopped'] = True
                status = receipt['executionStatus']
                if status == 'COMPLETED':
                    observed.update(state='COMPLETED', output={
                        key: receipt[key] for key in ('kind', 'taskId', 'runId', 'leaseId', 'providerJobId',
                                                     'executionStatus', 'exitCode')})
                    observed['output']['artifacts'] = [receipt['output']]
                elif status == 'CANCELLED':
                    observed['state'] = 'CANCELLED'
                else:
                    observed.update(state='FAILED', failure={'schema': 1, 'code': 'SSH_PROCESS_FAILED',
                        'messageCode': 'SSH_PROCESS_FAILED', 'retryable': False})
            elif lease.get('executionStatus') == 'RUNNING':
                observed['state'] = 'RUNNING'
        return validate_runtime_observation(observed, body['id'], self.pin['adapterId'], self.pin['revision'])
