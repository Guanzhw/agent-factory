"""Receiver-owned scientific phases on original authenticated handoff tasks.

Preparing a binding is inert. Only the explicit controller may register a pinned
local provider and allocate, after the original native external-execution pause.
Unknown acknowledgements are retained and never grant another dispatch.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, cast

from fastapi import HTTPException

from .autoresearch_children import phase_pin, positive_lease
from .control_commands import ControlCommand
from .execution_bindings import BindingContext
from .remote_scientific_evidence import project_scientific_evidence, validate_scientific_scope
from .research_assessment import assess_observations
from .remote_scientific_profile import PHASES, TOOLS, call_id
from .research_manifest import manifest_fingerprint, validate_manifest
from .store import canonical, digest


def require(value):
    if not value:
        raise ValueError('REMOTE_SCIENTIFIC_RECEIVER_INVALID')


@dataclass(frozen=True)
class RemoteScientificProject:
    owner: str
    project_pin: str
    assembler: Any
    preparation: Any
    checkpoints: Any
    manifest: dict
    baseline_reader: Any


class RemoteScientificReceiver:
    def __init__(self, store, auth, projects, commands, *, poll_seconds=.1, max_polls=36000, max_drives=1):
        require(type(projects) is dict and bool(projects) and .01 <= poll_seconds <= 1
                and type(max_polls) is int and 1 <= max_polls <= 36000
                and type(max_drives) is int and 1 <= max_drives <= 4)
        self.store, self.auth, self.projects, self.commands = store, auth, dict(projects), commands
        self.poll_seconds, self.max_polls = poll_seconds, max_polls
        self.max_drives, self._drives, self._closing = max_drives, {}, False
        for project in self.projects.values():
            require(type(project) is RemoteScientificProject and project.assembler.store is store
                    and project.assembler.owner == project.owner
                    and validate_manifest(project.manifest) == project.assembler.manifest
                    and len(project.project_pin) == 64 and all(c in '0123456789abcdef' for c in project.project_pin)
                    and callable(project.baseline_reader))
            require(getattr(project.assembler, 'committed_entry_reader', None) is None)
            project.assembler.committed_entry_reader = self.committed_entry
        store.sql('''CREATE TABLE IF NOT EXISTS af_remote_scientific_phases (
            receipt_id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, project_id TEXT NOT NULL,
            group_key TEXT NOT NULL, phase TEXT NOT NULL, body JSONB NOT NULL,
            UNIQUE(group_key, phase))''')
        store.sql('''CREATE TABLE IF NOT EXISTS af_remote_scientific_evidence (
            receipt_id TEXT PRIMARY KEY REFERENCES af_remote_scientific_phases(receipt_id),
            owner_id TEXT NOT NULL, scope_hash TEXT NOT NULL, fingerprint TEXT NOT NULL, body JSONB NOT NULL)''')
        store.remote_scientific_receiver = self

    def _read(self, receipt_id):
        rows = self.store.sql('SELECT * FROM af_remote_scientific_phases WHERE receipt_id=:id', id=receipt_id)
        require(len(rows) == 1)
        row = rows[0]; body = row['body']; binding = body['binding']
        scope = validate_scientific_scope(binding['scope'])
        require(binding['receiptId'] == row['receipt_id'] and binding['ownerId'] == row['owner_id']
                and binding['projectId'] == row['project_id'] and scope['phase'] == row['phase']
                and digest(body['candidate']) == scope['candidateSha256']
                and digest(binding) == body['bindingSha256'])
        project = self.projects[binding['projectId']]
        require(project.owner == binding['ownerId'] and project.project_pin == scope['receiverSciencePinSha256']
                and manifest_fingerprint(project.manifest) == scope['comparisonManifestSha256'])
        if body.get('config') is not None:
            require(digest(phase_pin(body['config'])) == body['configSha256'])
        if body.get('runtimeSnapshot') is not None:
            require(digest(body['runtimeSnapshot']['body']) == body['runtimeSnapshot']['sha256'])
        return deepcopy(body)

    def _save(self, original, body):
        rows = self.store.sql('''UPDATE af_remote_scientific_phases SET body=CAST(:body AS JSONB)
            WHERE receipt_id=:id AND body=CAST(:original AS JSONB) RETURNING receipt_id''',
            id=original['binding']['receiptId'], original=canonical(original), body=canonical(body))
        require(len(rows) == 1)
        return deepcopy(body)

    def prepare_binding(self, receipt_id, source_plan, envelope, remote_owner):
        require(type(envelope) is dict and set(envelope) == {'schema', 'projectId', 'scope', 'candidate'}
                and type(envelope['schema']) is int and envelope['schema'] == 1
                and type(receipt_id) is str and 1 <= len(receipt_id) <= 200)
        scope = validate_scientific_scope(envelope['scope'])
        project = self.projects[envelope['projectId']]
        candidate = envelope['candidate']
        require(remote_owner == project.owner and type(candidate) is dict
                and type(candidate.get('trainPy')) is str and 0 < len(cast(str, candidate['trainPy']).encode()) <= 256 * 1024
                and len(canonical(candidate).encode()) <= 300 * 1024
                and digest(candidate) == scope['candidateSha256'] and digest(source_plan) == scope['sourceManifestSha256']
                and project.project_pin == scope['receiverSciencePinSha256']
                and manifest_fingerprint(project.manifest) == scope['comparisonManifestSha256'])
        _, variant = project.assembler._candidate(candidate)
        require(variant == scope['variantSha256'])
        binding = {'receiptId': receipt_id, 'ownerId': remote_owner, 'projectId': envelope['projectId'], 'scope': scope}
        group = digest({key: scope[key] for key in ('originParentTaskId', 'originParentRunId',
            'originParentPlanSha256', 'candidateSha256', 'receiverSciencePinSha256')} | {'owner': remote_owner, 'project': envelope['projectId']})
        body = {'binding': binding, 'bindingSha256': digest(binding), 'candidate': deepcopy(candidate),
                'groupKey': group, 'state': 'PREPARED'}
        self.store.sql('''INSERT INTO af_remote_scientific_phases VALUES(:id,:owner,:project,:group,:phase,CAST(:body AS JSONB))
            ON CONFLICT DO NOTHING''', id=receipt_id, owner=remote_owner, project=envelope['projectId'],
            group=group, phase=scope['phase'], body=canonical(body))
        saved = self._read(receipt_id)
        require(saved['binding'] == binding and saved['candidate'] == candidate and saved['groupKey'] == group)
        return deepcopy(binding)

    def bind_task(self, receipt_id, task):
        body = self._read(receipt_id); original = deepcopy(body)
        owner = body['binding']['ownerId']
        current = self.store.task(task['id'], owner)
        # The lifecycle observer can change terminal/admission/body metadata
        # between reads. Custody binds immutable identity, not a stale UI row.
        require(all(current.get(key) == task.get(key) for key in
                    ('id', 'owner_id', 'plan_id', 'request_id', 'fingerprint'))
                and (task.get('run_id') is None or current.get('run_id') == task['run_id']))
        task = current
        plan = self.store.plan(task['plan_id'], owner)
        handoff = self.store.handoff_receiver._row(receipt_id, owner)
        require(plan.get('remoteHandoff', {}).get('receiptId') == receipt_id
                and handoff['body']['remotePlan'] == plan and handoff['body']['remoteTaskId'] == task['id']
                and handoff['manifest_hash'] == body['binding']['scope']['sourceManifestSha256']
                and handoff['origin_task'] == body['binding']['scope']['originChildTaskId'])
        identity = {'taskId': task['id'], 'planId': task['plan_id'], 'planSha256': digest(plan)}
        require(body.get('receiver', identity) == identity)
        body['receiver'] = identity
        if task.get('run_id'):
            require(body.get('nativeRunId', task['run_id']) == task['run_id'])
            body['nativeRunId'] = task['run_id']
        if body != original:
            try:
                self._save(original, body)
            except ValueError:
                # Another reader/executor may have bound the identical first
                # ticket and advanced phase state. Accept only that exact
                # committed identity, without replaying or overwriting its body.
                fresh = self._read(receipt_id)
                actual = self.store.task(task['id'], owner)
                require(all(actual.get(key) == task.get(key) for key in
                            ('id', 'owner_id', 'plan_id', 'request_id', 'fingerprint'))
                        and (task.get('run_id') is None or actual.get('run_id') == task['run_id'])
                        and fresh['binding'] == original['binding'] and fresh['candidate'] == original['candidate']
                        and fresh['groupKey'] == original['groupKey'] and fresh.get('receiver') == identity
                        and fresh.get('nativeRunId') == actual.get('run_id')
                        and digest(self.store.plan(actual['plan_id'], owner)) == identity['planSha256'])
                return fresh
        return body

    def _context(self, owner, task_id):
        task = self.store.task(task_id, owner); plan = self.store.plan(task['plan_id'], owner)
        return BindingContext(self.store.settings, self.store, plan, self.store.process_runtime._context(task),
            {'config': {'projectId': self._read(plan['remoteHandoff']['receiptId'])['binding']['projectId'],
                        'phase': self._read(plan['remoteHandoff']['receiptId'])['binding']['scope']['phase']}})

    def _bound(self, ctx, *, custody=False):
        owner = ctx.run_context.user_id
        task = self.store.task(ctx.run_context.session_id, owner)
        require(task['run_id'] == ctx.run_context.run_id and bool(task['run_id']))
        plan = self.store.plan(task['plan_id'], owner)
        require(ctx.plan['id'] == plan['id'] and ctx.plan['fingerprint'] == plan['fingerprint']
                and ctx.plan['remoteHandoff'] == plan['remoteHandoff'])
        body = self.bind_task(plan['remoteHandoff']['receiptId'], task)
        task = self.store.task(ctx.run_context.session_id, owner)
        require(body['nativeRunId'] == task['run_id'] == ctx.run_context.run_id
                and body['receiver']['taskId'] == task['id'] and body['receiver']['planId'] == task['plan_id'])
        if not custody:
            require(body['state'] != 'CANCELLED_NO_DISPATCH')
            require(not task['terminal'] and not task['cancel_requested'])
            self.store.handoff_receiver.authorize(ctx.run_context, TOOLS[body['binding']['scope']['phase']])
        return body, task, self.projects[body['binding']['projectId']]

    def _prior(self, body):
        phase = body['binding']['scope']['phase']; prior = {}
        rows = self.store.sql('SELECT * FROM af_remote_scientific_phases WHERE group_key=:group', group=body['groupKey'])
        for previous in PHASES[:PHASES.index(phase)]:
            matches = [r for r in rows if r['phase'] == previous]
            require(len(matches) == 1)
            item = self._read(matches[0]['receipt_id'])
            require(item['state'] == 'COMPLETED')
            task = self.store.task(item['receiver']['taskId'], item['binding']['ownerId'])
            require(task['run_id'] == item['nativeRunId'])
            ticket = self.store.lifecycle_observer._binding(task)
            require(ticket and ticket['status'] == ticket['persistedRunStatus'] == 'completed')
            prior[previous] = {'state': 'COMPLETED', 'config': item['config'], 'receipt': item['receipt']}
        return prior

    def require_phase(self, ctx, phase, *, custody=False):
        body, _, project = self._bound(ctx, custody=custody)
        require(body['state'] != 'CANCELLED_NO_DISPATCH')
        require(phase == body['binding']['scope']['phase'] and ctx.spec['config'] ==
                {'projectId': body['binding']['projectId'], 'phase': phase})
        prior = self._prior(body)
        pin = phase_pin(project.assembler(phase, body['candidate'], prior, context=ctx))
        scope = body['binding']['scope']
        require(pin['comparisonManifestSha256'] == scope['comparisonManifestSha256'] and pin['variantSha256'] == scope['variantSha256'])
        if 'config' in body:
            require(body['config'] == pin)
        else:
            require(not custody and body['state'] == 'PREPARED')
            updated = deepcopy(body); updated.update(config=pin, configSha256=digest(pin))
            self._save(body, updated)
        if body.get('targetFingerprint'):
            resources = self.store.research_runtime.resources
            target = resources.targets.get(pin['targetRef'])
            require(target is not None and resources._target_fingerprint(target) == body['targetFingerprint'])
            project.assembler.verify_authority(phase, body['candidate'], prior, pin, target)
        return pin

    def committed_entry(self, ctx, phase, candidate, pin):
        body, task, _ = self._bound(ctx, custody=True)
        require(body['binding']['scope']['phase'] == phase and body['candidate'] == candidate and body['config'] == pin)
        return {'owner_id': task['owner_id'], 'parent_task_id': task['id'], 'parent_run_id': task['run_id'],
                'body': {'candidate': deepcopy(candidate), 'phases': {phase: body}}}

    def consume_tool(self, ctx, phase, native_call_id):
        self.require_phase(ctx, phase)
        body, task, _ = self._bound(ctx)
        require(native_call_id == call_id(phase))
        if body.get('callProof'):
            require(body['callId'] == native_call_id)
            return deepcopy(body['callProof'])
        require('callId' not in body)
        original = deepcopy(body); body.update(callId=native_call_id, debitState='UNKNOWN')
        self._save(original, body)
        receiver = self.store.handoff_receiver
        row = receiver._row(body['binding']['receiptId'], task['owner_id'])
        origin = receiver._origin(task['owner_id'], row['origin_ref'], row['origin_owner'])
        proof = origin.authorize.consume_scientific_tool(row['origin_owner'], row['origin_task'], row['manifest_hash'],
            TOOLS[phase], call_id=native_call_id, receiver_task_id=task['id'], native_run_id=task['run_id'],
            phase_scope_sha256=digest(body['binding']['scope']))
        require(type(proof) is dict and type(proof.get('callProofSha256')) is str and len(cast(str, proof['callProofSha256'])) == 64)
        fresh, _, _ = self._bound(ctx); updated = deepcopy(fresh)
        updated.update(callProof=deepcopy(proof), debitState='CONFIRMED'); self._save(fresh, updated)
        return proof

    def require_completed_custody(self, owner, plan, context):
        """Current readonly proof for an original completed training checkpoint.

        This is not execution authority. The caller separately finishes current
        local policy, material/binding and non-remote execution guard checks.
        No artifact, model, provider launch or cached-science reader is invoked.
        """
        require(context.user_id == owner)
        ctx = self._context(owner, context.session_id)
        require(ctx.run_context.run_id == context.run_id and plan == ctx.plan)
        body, task, _ = self._bound(ctx, custody=True)
        require(body['binding']['scope']['phase'] == 'training' and body['state'] == 'COMPLETED'
                and not task['cancel_requested'] and task['run_id'] == context.run_id
                and type(body.get('receipt')) is dict and type(body['receipt'].get('artifact')) is dict
                and type(body['receipt']['artifact'].get('id')) is str and bool(body['receipt']['artifact']['id']))
        runtime = self.store.research_runtime
        original = runtime._original(task['id'])
        require(original is not None and original['owner_id'] == owner and original['native_run_id'] == task['run_id'])
        lease, target, actual, ticket = runtime._custody(original['lease_id'])
        require(actual['id'] == task['id'] and actual['owner_id'] == owner and actual['plan_id'] == task['plan_id']
                and actual['run_id'] == task['run_id'] and not actual['cancel_requested']
                and ticket and ticket['id'] == task['run_id'] and ticket['status'] == ticket['persistedRunStatus'] == 'completed')
        positive_lease(lease, actual, gpu=True)
        from .gpu_custody import validate_gpu_evidence
        validate_gpu_evidence(lease, {**lease, 'released': True})
        expected = {'ownerId': owner, 'taskId': task['id'], 'nativeRunId': task['run_id'], 'planId': task['plan_id'],
            'planFingerprint': plan['fingerprint'], 'leaseId': lease['id'], 'providerJobId': lease['providerJobId']}
        require(body['receipt']['execution'] == expected and lease['connectionRef'] == body['config']['targetRef']
                and runtime.resources._target_fingerprint(target) == body['targetFingerprint']
                and lease['targetFingerprint'] == body['targetFingerprint'])
        receiver = self.store.handoff_receiver
        row = receiver._row(body['binding']['receiptId'], owner)
        receiver._check_row(row, owner, execution=False)
        origin = receiver._origin(owner, row['origin_ref'], row['origin_owner'], execution=False)
        binding = self.store.remote_bindings.inspect(body['binding']['receiptId'], owner)
        require(binding['receiptId'] == body['binding']['receiptId'] and binding['receiverOwner'] == owner
                and binding['receiverPlanId'] == task['plan_id'] and binding['manifestHash'] == row['manifest_hash']
                and binding['receiverConfiguration'] == {'revision': origin.configuration_revision, 'sha256': origin.fingerprint})
        check = getattr(origin.authorize, 'check_scientific_custody', None)
        require(callable(check))
        assert callable(check)
        reply = check(row['origin_owner'], row['origin_task'], row['manifest_hash'], receiver_task_id=task['id'],
            native_run_id=task['run_id'], phase_scope_sha256=digest(body['binding']['scope']), lease_id=lease['id'])
        require(type(reply) is dict and type(reply.get('schema')) is int and all(reply.get(key) == value for key, value in {
            'schema': 1, 'tool': None, 'outcome': 'custody-readable', 'originRef': row['origin_ref'],
            'originOwner': row['origin_owner'], 'originTaskId': row['origin_task'], 'manifestSha256': row['manifest_hash'],
            'receiverIdentity': owner, 'receiverTaskId': task['id'], 'nativeRunId': task['run_id'],
            'phaseScopeSha256': digest(body['binding']['scope']), 'leaseId': lease['id']}.items())
                and type(reply.get('custodyProofSha256')) is str and len(cast(str, reply['custodyProofSha256'])) == 64
                and all(char in '0123456789abcdef' for char in cast(str, reply['custodyProofSha256']))
                and binding['sourceConfiguration'] == {'revision': reply.get('targetRevision'), 'sha256': reply.get('targetFingerprint')})
        # Re-read original custody after the remote check without asking to run.
        fresh = self._read(body['binding']['receiptId']); actual = self.store.task(task['id'], owner)
        require(fresh['binding'] == body['binding'] and fresh['receiver'] == body['receiver']
                and fresh['nativeRunId'] == body['nativeRunId'] and fresh['state'] == 'COMPLETED'
                and fresh['receipt'] == body['receipt'] and not actual['cancel_requested']
                and actual['run_id'] == task['run_id'] and actual['plan_id'] == task['plan_id'])
        return None

    async def verify_preparation(self, ctx):
        self.require_phase(ctx, 'preparation')
        body, task, project = self._bound(ctx)
        require(body.get('debitState') == 'CONFIRMED' and body.get('callProof'))
        receipt = project.assembler.preparation_receipt()
        require(receipt['execution']['taskId'] != task['id'] and receipt['execution']['nativeRunId'] != task['run_id'])
        original = deepcopy(body)
        require(body.get('receipt', receipt) == receipt)
        body.update(receipt=deepcopy(receipt), state='VERIFIED'); self._save(original, body)
        return deepcopy(receipt)

    def _snapshot(self, ctx, snapshot):
        body, _, _ = self._bound(ctx)
        require(body['state'] == 'DISPATCH_UNKNOWN' and type(snapshot) is dict and len(canonical(snapshot).encode()) <= 40 * 1024**2)
        wrapped = {'body': deepcopy(snapshot), 'sha256': digest(snapshot)}
        require(body.get('runtimeSnapshot', wrapped) == wrapped)
        updated = deepcopy(body); updated['runtimeSnapshot'] = wrapped
        self._save(body, updated)
        return deepcopy(snapshot)

    async def drive_phase(self, owner, task_id):
        self.auth.require(owner, 'run'); ctx = self._context(owner, task_id)
        body, task, project = self._bound(ctx, custody=True); phase = body['binding']['scope']['phase']
        if phase == 'preparation':
            ticket = self.store.lifecycle_observer._binding(task)
            require(body['state'] == 'VERIFIED' and ticket and ticket['status'] == ticket['persistedRunStatus'] == 'completed')
            require(body['receipt'] == project.assembler.preparation_receipt())
            updated = deepcopy(body); updated['state'] = 'COMPLETED'; self._save(body, updated)
            return deepcopy(body['receipt'])
        pin = self.require_phase(ctx, phase); body, task, project = self._bound(ctx)
        require(body['state'] == 'PREPARED')
        runtime = self.store.research_runtime
        requirement = runtime._paused(task, pin['comparisonManifest'], pin['variantSha256'])
        self.consume_tool(ctx, phase, requirement['toolCallId'])
        body, task, project = self._bound(ctx)
        require(body['state'] == 'PREPARED')
        updated = deepcopy(body); updated['state'] = 'DISPATCH_UNKNOWN'
        self._save(body, updated)
        try:
            project.assembler.register_phase(ctx, phase, body['candidate'], self._prior(body), pin,
                persist_snapshot=lambda snapshot: self._snapshot(ctx, snapshot))
            body, task, project = self._bound(ctx)
            require('runtimeSnapshot' in body)
            target = runtime.resources._authorize(owner, pin['targetRef'])
            updated = deepcopy(body); updated['targetFingerprint'] = runtime.resources._target_fingerprint(target)
            self._save(body, updated)
            lease = await runtime.submit(owner, task_id)
            for _ in range(self.max_polls):
                self._bound(ctx)
                if lease['state'] == 'RECLAIMED':
                    break
                require(lease['state'] != 'UNKNOWN' or (lease.get('executionStatus') == 'DISPATCHING' and lease.get('providerJobId')))
                require(lease.get('preDispatchFailure') is None)
                await asyncio.sleep(self.poll_seconds); lease = await runtime.inspect_task(owner, task_id)
            positive_lease(lease, task, gpu=True)
            artifact = project.checkpoints.import_completed(owner, lease['id']) if phase == 'training' else None
            plan = self.store.plan(task['plan_id'], owner)
            receipt = {'execution': {'ownerId': owner, 'taskId': task_id, 'nativeRunId': task['run_id'],
                'planId': task['plan_id'], 'planFingerprint': plan['fingerprint'], 'leaseId': lease['id'],
                'providerJobId': lease['providerJobId']}, 'artifact': artifact}
            body, _, _ = self._bound(ctx); updated = deepcopy(body); updated.update(receipt=receipt, state='CONTINUATION_UNKNOWN')
            self._save(body, updated)
            await self.commands.submit(owner, task_id, ControlCommand(commandId='remote-science:' + digest(body['binding'])[:48],
                action='approve', approved=True, requirementId=requirement['id'], version=requirement['version']))
            for _ in range(self.max_polls):
                body, task, _ = self._bound(ctx, custody=True)
                ticket = self.store.lifecycle_observer._binding(task)
                require(ticket and ticket['status'] not in {'failed', 'cancelled', 'canceled'})
                if ticket['status'] == ticket['persistedRunStatus'] == 'completed':
                    updated = deepcopy(body); updated['state'] = 'COMPLETED'; self._save(body, updated)
                    return receipt
                await asyncio.sleep(self.poll_seconds)
            raise ValueError('REMOTE_SCIENTIFIC_NATIVE_COMPLETION_UNKNOWN')
        except BaseException:
            body = self._read(body['binding']['receiptId']); updated = deepcopy(body); updated['state'] = 'UNKNOWN'
            self._save(body, updated)
            raise

    async def inspect_phase(self, owner, task_id):
        ctx = self._context(owner, task_id)
        body, task, project = self._bound(ctx, custody=True); phase = body['binding']['scope']['phase']
        original = self.store.research_runtime._original(task_id)
        if original is None:
            return {'state': body['state'], 'lease': None, 'native': self.store.lifecycle_observer._binding(task)}
        require(phase != 'preparation' and body.get('runtimeSnapshot'))
        pin = body['config']; resources = self.store.research_runtime.resources
        if pin['targetRef'] not in resources.targets:
            target = project.assembler.restore_phase(ctx, phase, body['candidate'], self._prior(body), pin, body['runtimeSnapshot']['body'])
            require(resources._target_fingerprint(target) == body['targetFingerprint'])
        require(original['owner_id'] == owner and original['native_run_id'] == task['run_id'])
        lease = await self.store.research_runtime.observe_lease(original['lease_id'])
        return {'state': body['state'], 'lease': lease, 'native': self.store.lifecycle_observer._binding(task)}

    def cancel_before_dispatch(self, owner, task_id):
        """Internal original-custody CAS, not a missing-process inference.

        Native cancellation remains the handoff lifecycle's separate obligation.
        A lost CAS or any crossed scientific boundary cannot produce this proof.
        """
        ctx = self._context(owner, task_id)
        body, task, _ = self._bound(ctx, custody=True)
        if body['binding']['scope']['phase'] == 'preparation':
            return None
        if body['state'] == 'CANCELLED_NO_DISPATCH':
            return self._no_dispatch_body(body, task)
        if body['state'] != 'PREPARED':
            return None
        require(not any(key in body for key in ('runtimeSnapshot', 'targetFingerprint', 'receipt')))
        self._no_process(task)
        proof = {'schema': 1, 'scopeSha256': digest(body['binding']['scope']), 'receiverTaskId': task_id,
            'receiverPlanId': task['plan_id'], 'receiverNativeRunId': task['run_id']}
        updated = deepcopy(body); updated.update(state='CANCELLED_NO_DISPATCH', noDispatch=proof)
        if 'driveRequest' in updated:
            updated['driveRequest']['status'] = 'CANCELLED_NO_DISPATCH'
        try:
            self._save(body, updated)
        except ValueError:
            fresh = self._read(body['binding']['receiptId'])
            if fresh['state'] != 'CANCELLED_NO_DISPATCH':
                return None
            return self._no_dispatch_body(fresh, task)
        return self._no_dispatch_body(updated, task)

    def _no_process(self, task):
        require(self.store.research_runtime._original(task['id']) is None)
        require(not self.store.sql('SELECT task_id FROM af_process_runs WHERE task_id=:task', task=task['id']))
        rows = self.store.sql("SELECT id FROM af_leases WHERE owner_id=:owner AND body->>'localTaskId'=:task",
                              owner=task['owner_id'], task=task['id'])
        require(not rows)

    def _no_dispatch_body(self, body, task):
        require(body['state'] == 'CANCELLED_NO_DISPATCH' and body['binding']['scope']['phase'] in ('training', 'evaluation')
                and not any(key in body for key in ('runtimeSnapshot', 'targetFingerprint', 'receipt')))
        self._no_process(task)
        expected = {'schema': 1, 'scopeSha256': digest(body['binding']['scope']), 'receiverTaskId': task['id'],
            'receiverPlanId': task['plan_id'], 'receiverNativeRunId': task['run_id']}
        require(body['noDispatch'] == expected)
        return deepcopy(expected)

    def no_dispatch_proof(self, receipt):
        body = self._read(receipt['id'])
        if body['state'] != 'CANCELLED_NO_DISPATCH':
            return None
        owner = body['binding']['ownerId']; task_id = body['receiver']['taskId']
        body, task, _ = self._bound(self._context(owner, task_id), custody=True)
        require(receipt['remoteOwnerId'] == owner and receipt['remoteTaskId'] == task_id
                and receipt['remotePlanId'] == task['plan_id'] and receipt['remoteRunId'] == task['run_id']
                and receipt['manifestHash'] == body['binding']['scope']['sourceManifestSha256']
                and receipt['originTaskId'] == body['binding']['scope']['originChildTaskId'])
        return self._no_dispatch_body(body, task)

    async def cancel_phase(self, owner, task_id):
        ctx = self._context(owner, task_id)
        body, _, _ = self._bound(ctx, custody=True)
        await self.commands.submit(owner, task_id, ControlCommand(
            commandId='remote-science-cancel:' + digest(body['binding'])[:48], action='cancel'))
        return await self.inspect_phase(owner, task_id)

    async def start_drive(self, owner, task_id):
        """Explicit request only: commit once before scheduling a bounded local task.

        An intent surviving process restart is not a launch grant. Repeated POSTs
        return that original intent and never reconstruct a controller coroutine.
        """
        self.auth.require(owner, 'run')
        ctx = self._context(owner, task_id)
        body, task, _ = self._bound(ctx, custody=True)
        if 'driveRequest' in body:
            return {'state': body['state'], 'driveRequest': deepcopy(body['driveRequest'])}
        require(not self._closing and len(self._drives) < self.max_drives and not task['cancel_requested']
                and body['state'] in {'PREPARED', 'VERIFIED'})
        phase = body['binding']['scope']['phase']
        self.store.handoff_receiver.authorize(ctx.run_context, TOOLS[phase])
        request = {'schema': 1, 'taskId': task_id, 'nativeRunId': task['run_id'],
            'planSha256': body['receiver']['planSha256'], 'bindingSha256': body['bindingSha256'], 'status': 'PENDING'}
        updated = deepcopy(body); updated['driveRequest'] = request
        self._save(body, updated)
        rid = body['binding']['receiptId']
        worker = asyncio.create_task(self._run_drive(owner, task_id, rid, deepcopy(request)))
        self._drives[rid] = worker
        worker.add_done_callback(lambda done: self._drives.pop(rid, None))
        return {'state': updated['state'], 'driveRequest': deepcopy(request)}

    async def _run_drive(self, owner, task_id, receipt_id, request):
        try:
            ctx = self._context(owner, task_id)
            for _ in range(self.max_polls):
                body, task, _ = self._bound(ctx, custody=True)
                require(body['driveRequest'] == request and task['run_id'] == request['nativeRunId']
                        and body['receiver']['planSha256'] == request['planSha256']
                        and body['bindingSha256'] == request['bindingSha256'] and not task['cancel_requested'])
                phase = body['binding']['scope']['phase']
                # Current origin authority includes the original parent deadline.
                self.store.handoff_receiver.authorize(ctx.run_context, TOOLS[phase])
                ticket = self.store.lifecycle_observer._binding(task)
                require(ticket and ticket['status'] not in {'failed', 'cancelled', 'canceled', 'error'})
                ready = 'completed' if phase == 'preparation' else 'paused'
                if ticket['status'] == ticket['persistedRunStatus'] == ready:
                    if phase != 'preparation':
                        require(not task['terminal'])
                    await self.drive_phase(owner, task_id)
                    body = self._read(receipt_id); updated = deepcopy(body)
                    require(body['state'] == 'COMPLETED')
                    updated['driveRequest']['status'] = 'COMPLETED'; self._save(body, updated)
                    return
                require(not task['terminal'])
                await asyncio.sleep(self.poll_seconds)
            raise ValueError('REMOTE_SCIENTIFIC_NATIVE_PAUSE_UNKNOWN')
        except BaseException as error:
            try:
                body = self._read(receipt_id); updated = deepcopy(body)
                if body['state'] != 'CANCELLED_NO_DISPATCH':
                    updated['state'] = 'UNKNOWN'; updated['driveRequest']['status'] = 'UNKNOWN'
                self._save(body, updated)
                self.store.event(task_id, 'remote_scientific_drive_unknown',
                    'Original scientific controller ended without confirmed completion',
                    {'errorType': type(error).__name__[:80]})
            except Exception:
                # The original durable intent remains non-replayable even when
                # the database is unavailable during shutdown/error recording.
                pass
            if isinstance(error, asyncio.CancelledError):
                raise

    async def close(self):
        self._closing = True
        owned = tuple(self._drives.items())
        tasks = tuple(task for _, task in owned)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        for receipt_id, _ in owned:
            try:
                body = self._read(receipt_id)
                if body['driveRequest']['status'] == 'PENDING':
                    updated = deepcopy(body); updated['state'] = 'UNKNOWN'
                    updated['driveRequest']['status'] = 'UNKNOWN'; self._save(body, updated)
            except Exception:
                pass  # Durable pending intent still forbids restart dispatch.

    async def project_baseline(self, remote_owner, project_id, project_pin):
        self.auth.require(remote_owner, 'run')
        project = self.projects[project_id]
        require(project.owner == remote_owner and project.project_pin == project_pin)
        observation = await project.baseline_reader()
        assess_observations(observation, observation)
        require(observation['status'] == 'completed'
                and observation['comparisonIdentitySha256'] == manifest_fingerprint(project.manifest)
                and observation['variantSha256'] == project.manifest['baselineSourceManifestSha256'])
        return {'schema': 1, 'projectId': project_id, 'projectPin': project_pin, 'observation': deepcopy(observation)}

    def _retained(self, phase_body, *, locked=False):
        rows = self.store.sql('SELECT * FROM af_remote_scientific_evidence WHERE receipt_id=:id' + (' FOR UPDATE' if locked else ''),
                              id=phase_body['binding']['receiptId'])
        if not rows:
            return None
        require(len(rows) == 1)
        row = rows[0]; retained = row['body']
        require(row['owner_id'] == phase_body['binding']['ownerId']
                and row['scope_hash'] == digest(phase_body['binding']['scope'])
                and digest(retained) == row['fingerprint']
                and set(retained) == {'scope', 'claims', 'basis', 'bindingSha256', 'receiver', 'nativeRunId'}
                and retained['scope'] == phase_body['binding']['scope']
                and retained['bindingSha256'] == phase_body['bindingSha256']
                and retained['receiver'] == phase_body['receiver'] and retained['nativeRunId'] == phase_body['nativeRunId']
                and retained['basis'] == 'previously-verified-original-claims'
                and set(retained['claims']) == {'launchProof', 'checkpoint', 'evaluation', 'preparation'})
        return deepcopy(retained)

    def _retain_evidence(self, receipt, evidence):
        """Merge immutable verified claims in a separate row, never the phase journal."""
        fields = ('launchProof', 'checkpoint', 'evaluation', 'preparation')
        scope = evidence['scope']
        merged = deepcopy(evidence); historical = False
        from .remote_scientific_evidence import validate_scientific_evidence
        validate_scientific_evidence({**receipt, 'scientificEvidence': evidence}, expected_scope=scope)
        with self.store.transaction():
            body = self._read(receipt['id'])
            require(body['binding']['scope'] == scope)
            initial = {'scope': deepcopy(scope), 'basis': 'previously-verified-original-claims',
                'bindingSha256': body['bindingSha256'], 'receiver': deepcopy(body['receiver']),
                'nativeRunId': body['nativeRunId'], 'claims': {key: None for key in fields}}
            self.store.sql("""INSERT INTO af_remote_scientific_evidence
                VALUES(:id,:owner,:scope,:fp,CAST(:body AS JSONB)) ON CONFLICT DO NOTHING""",
                id=receipt['id'], owner=body['binding']['ownerId'], scope=digest(scope), fp=digest(initial), body=canonical(initial))
            retained = self._retained(body, locked=True)
            require(retained is not None)
            retained = cast(dict, retained)
            changed = deepcopy(retained)
            for key in fields:
                old, fresh = retained['claims'][key], evidence[key]
                if old is not None:
                    if fresh is None:
                        # A slower reader may predate the phase's new receipt.
                        # Preserve its fresh custody observation and fill only
                        # claims already verified for this original identity.
                        merged[key] = deepcopy(old); historical = True
                    else:
                        require(old == fresh)
                elif fresh is not None:
                    changed['claims'][key] = deepcopy(fresh)
            validate_scientific_evidence({**receipt, 'scientificEvidence': merged}, expected_scope=scope)
            if changed != retained:
                self.store.sql("""UPDATE af_remote_scientific_evidence SET body=CAST(:body AS JSONB),fingerprint=:fp
                    WHERE receipt_id=:id""", id=receipt['id'], fp=digest(changed), body=canonical(changed))
        receipt['scientificClaimsRetained'] = historical
        return merged

    def _claims_only(self, receipt, body, lease=None):
        """Historical claims plus fresh custody: no artifact or evaluator authority."""
        claims = (self._retained(body) or {}).get('claims', {})
        value = project_scientific_evidence(receipt, scope=body['binding']['scope'], lease=lease,
            launch_proof=claims.get('launchProof'), checkpoint=claims.get('checkpoint'),
            evaluation=claims.get('evaluation'), preparation=claims.get('preparation'))
        # Separate receipt annotation: these claims were verified earlier, not
        # re-read under a renewed scientific grant during cancellation cleanup.
        receipt['scientificClaimsRetained'] = any(item is not None for item in claims.values())
        return value

    async def project_evidence(self, receipt):
        """Fresh original-store evidence; an empty projection is never stop proof."""
        body = self._read(receipt['id']); owner = body['binding']['ownerId']
        scope = body['binding']['scope']; phase = scope['phase']
        project = self.projects[body['binding']['projectId']]
        if 'receiver' not in body or 'nativeRunId' not in body:
            return project_scientific_evidence(receipt, scope=scope)
        task_id = body['receiver']['taskId']; ctx = self._context(owner, task_id)
        body, task, _ = self._bound(ctx, custody=True)
        custody_only = task['cancel_requested']
        if not custody_only:
            try:
                self.store.handoff_receiver.authorize(ctx.run_context, TOOLS[phase])
            except HTTPException as error:
                if error.status_code not in {403, 404, 409}:
                    raise
                custody_only = True
            except PermissionError:
                custody_only = True
        if phase == 'preparation':
            if custody_only:
                return self._claims_only(receipt, body)
            prep = None
            if body.get('receipt'):
                original = project.assembler.preparation_receipt()
                require(original == body['receipt'])
                metadata, pin = project.preparation.identity(owner, original['execution']['taskId'], original['artifact']['id'])
                require(metadata['id'] == original['artifact']['id'])
                prep = {'schema': 1, **original['execution'], 'artifactId': metadata['id'], 'artifactSha256': pin['sha256']}
            return self._retain_evidence(receipt, project_scientific_evidence(receipt, scope=scope, preparation=prep))
        state = await self.inspect_phase(owner, task_id)
        fresh = self._read(receipt['id'])
        require(fresh['bindingSha256'] == body['bindingSha256'] and fresh['binding'] == body['binding']
                and fresh['receiver'] == body['receiver'] and fresh['nativeRunId'] == body['nativeRunId'])
        body = fresh
        lease = state['lease']; launch = checkpoint = evaluation = None
        if lease is not None:
            lease = deepcopy(lease)
            plan = self.store.plan(task['plan_id'], owner)
            lease['planFingerprint'] = plan['fingerprint']
            lease['targetFingerprint'] = body['targetFingerprint']
            if custody_only:
                return self._claims_only(receipt, self._read(receipt['id']), lease)
            if body.get('receipt') and lease['state'] == 'RECLAIMED' and lease.get('executionStatus') == 'COMPLETED':
                positive_lease(lease, task, gpu=True)
                resources = self.store.research_runtime.resources
                target = resources._authorize(owner, body['config']['targetRef'])
                launch = resources._provider(target).read_launch_proof(lease['id'], owner)
                training = body if phase == 'training' else self._prior(body)['training']
                original = training['receipt']
                metadata, identity = project.checkpoints.identity(original['execution']['taskId'], original['artifact']['id'],
                    min(project.manifest['artifactLimits']['checkpointBytes'], 2 * 1024**3))
                require(metadata['id'] == original['artifact']['id'])
                checkpoint = {**original['execution'], 'variantSha256': scope['variantSha256'],
                              'checkpoint': {'artifactId': metadata['id'], **identity}}
                if phase == 'evaluation':
                    contract = {'schema': 1, 'evidenceKind': 'offline_research_evaluation_contract',
                        'comparisonManifest': deepcopy(project.manifest), 'training': checkpoint,
                        'evaluatorExecution': body['receipt']['execution']}
                    result = await project.assembler.evaluation_service(body['config']).verify(owner, contract)
                    evaluation = {'contract': contract, 'result': result}
        if custody_only:
            return self._claims_only(receipt, self._read(receipt['id']), lease)
        return self._retain_evidence(receipt, project_scientific_evidence(receipt, scope=scope, lease=lease,
            launch_proof=launch, checkpoint=checkpoint, evaluation=evaluation))
