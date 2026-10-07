"""Original delegated scientific phases under a durably paused research parent.

No task creation outside DelegationService, no replacement dispatch after UNKNOWN,
no model decisions, and no claim of scientific acceptance from process completion.
Operator phase assembly authenticates concrete source/input-bound providers; it cannot supply
completion booleans. Existing stores independently verify artifacts and evaluation.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
import hashlib
import inspect
from types import SimpleNamespace
from typing import Any, cast

from .control_commands import ControlCommand
from .research_manifest import manifest_fingerprint, validate_manifest
from .store import canonical, digest

PHASES = ('preparation', 'training', 'evaluation')
ERROR = 'AUTORESEARCH_CHILD_CUSTODY_INVALID'


def require(value):
    if not value:
        raise ValueError(ERROR)


def phase_pin(value: Any) -> dict[str, Any]:
    require(type(value) is dict and set(value) == {'targetRef', 'comparisonManifestSha256', 'variantSha256', 'comparisonManifest'})
    value = cast(dict[str, Any], value)
    require(type(value['targetRef']) is str and 1 <= len(value['targetRef']) <= 200)
    require(type(value['variantSha256']) is str and len(value['variantSha256']) == 64
            and all(char in '0123456789abcdef' for char in value['variantSha256']))
    manifest = validate_manifest(value['comparisonManifest'])
    require(manifest_fingerprint(manifest) == value['comparisonManifestSha256'])
    return deepcopy(value)


def positive_lease(lease: dict[str, Any], task: dict[str, Any], *, gpu):
    require(type(lease) is dict and all(lease.get(key) == task[field] for key, field in
        (('ownerId', 'owner_id'), ('localTaskId', 'id'), ('nativeRunId', 'run_id'), ('planId', 'plan_id'))))
    require(lease.get('state') == 'RECLAIMED' and lease.get('capacityHeld') is False
            and lease.get('executionStatus') == 'COMPLETED' and type(lease.get('exitCode')) is int
            and lease['exitCode'] == 0 and (lease.get('stopEvidence') or {}).get('allStopped') is True
            and type(lease.get('providerJobId')) is str and bool(lease['providerJobId']))
    if gpu:
        require((lease.get('gpuEvidence') or {}).get('state') == 'RELEASED')
    return lease


class AutoResearchChildren:
    def __init__(self, store, auth, service, *, phase_config, preparation, checkpoints, poll_seconds=.1):
        require(callable(phase_config) and callable(getattr(phase_config, 'register_phase', None))
                and callable(getattr(phase_config, 'verify_phase', None))
                and callable(getattr(phase_config, 'verify_authority', None))
                and callable(getattr(phase_config, 'preparation_receipt', None))
                and callable(getattr(phase_config, 'evaluation_service', None))
                and callable(getattr(phase_config, 'phase_target', None))
                and callable(getattr(phase_config, 'restore_phase', None)) and type(poll_seconds) in {int, float} and .01 <= poll_seconds <= 1)
        self.store, self.auth, self.service = store, auth, service
        self.phase_config, self.preparation, self.checkpoints = phase_config, preparation, checkpoints
        self.poll_seconds = poll_seconds
        store.sql('''CREATE TABLE IF NOT EXISTS af_autoresearch_experiments (
            parent_run_id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, parent_task_id TEXT NOT NULL REFERENCES af_tasks(id),
            call_id TEXT NOT NULL, fingerprint TEXT NOT NULL, body JSONB NOT NULL)''')

    def _parent(self, ctx):
        preset = self.service.current(ctx)
        run = ctx.run_context
        task = self.store.task(run.session_id, run.user_id)
        require(task['run_id'] == run.run_id and not task['cancel_requested'] and not task['terminal'])
        ticket = self.store.lifecycle_observer._binding(task)
        require(ticket and ticket['status'] == ticket['persistedRunStatus'] == 'paused')
        require(preset.limits['maxExperiments'] == 1)
        return task, self.store.plan(task['plan_id'], run.user_id), preset

    def _read(self, parent_run):
        rows = self.store.sql('SELECT * FROM af_autoresearch_experiments WHERE parent_run_id=:run', run=parent_run)
        require(len(rows) == 1)
        row = rows[0]; body = row['body']; pin = body['binding']
        require(digest(pin) == row['fingerprint'] and pin['parentRunId'] == row['parent_run_id']
                and pin['parentTaskId'] == row['parent_task_id'] and pin['ownerId'] == row['owner_id']
                and pin['callId'] == row['call_id'] and digest(body['candidate']) == pin['candidateSha256']
                and hashlib.sha256(body['candidate']['trainPy'].encode()).hexdigest() == pin['trainPySha256'])
        for phase, entry in body['phases'].items():
            require(phase in PHASES and digest(entry['config']) == entry['configSha256']
                    and entry['requestId'] == 'ar-child:' + digest({'binding': pin, 'phase': phase}))
        for entry in body['phases'].values():
            snapshot = entry.get('runtimeSnapshot')
            if snapshot is not None:
                require(type(snapshot) is dict and set(snapshot) == {'sha256', 'body'}
                        and type(snapshot['body']) is dict and digest(snapshot['body']) == snapshot['sha256'])
        return body

    def _persist_snapshot(self, ctx, phase, config, snapshot):
        require(type(snapshot) is dict and len(canonical(snapshot).encode()) <= 40 * 1024**2)
        body = self._bound(ctx)
        entry = body['phases'][phase]
        require(entry['config'] == config)
        wrapped = {'sha256': digest(snapshot), 'body': deepcopy(snapshot)}
        if 'runtimeSnapshot' in entry:
            require(entry['runtimeSnapshot'] == wrapped)
            return deepcopy(snapshot)
        original = canonical(body)
        require(entry['state'] == 'DISPATCH_UNKNOWN' and 'child' not in entry)
        entry['runtimeSnapshot'] = wrapped
        updated = self.store.sql('''UPDATE af_autoresearch_experiments SET body=CAST(:body AS JSONB)
            WHERE parent_run_id=:run AND body=CAST(:original AS JSONB) RETURNING parent_run_id''',
            run=ctx.run_context.run_id, original=original, body=canonical(body))
        require(len(updated) == 1)
        return deepcopy(snapshot)

    def _phase_target(self, owner, phase, pin):
        if phase != 'preparation':
            return self.store.process_runtime.resources._authorize(owner, pin['targetRef'])
        # The original producer can belong to a separate legacy control plane.
        # Resolve only its verified readonly reference, never register its provider.
        self.auth.require(owner, 'run')
        target = self.phase_config.phase_target(phase, deepcopy(pin))
        require(not inspect.isawaitable(target) and owner in target.owners)
        return target

    def _restore_phase(self, ctx, phase, body):
        if phase == 'preparation':
            # This child only verifies retained input. There is no local process
            # allocation or runtime snapshot to reconstruct in the new database.
            return
        entry = body['phases'][phase]
        resources = self.store.process_runtime.resources
        if entry['config']['targetRef'] in resources.targets:
            return
        # Reconstruction is an explicit outer custody operation, never work
        # performed from a transaction-scoped authority callback.
        require(self.store._connection.get() is None)
        snapshot = entry.get('runtimeSnapshot')
        require(snapshot and digest(snapshot['body']) == snapshot['sha256'])
        prior = {key: deepcopy(body['phases'][key]) for key in PHASES[:PHASES.index(phase)]}
        target = self.phase_config.restore_phase(ctx, phase, deepcopy(body['candidate']), prior,
            phase_pin(entry['config']), deepcopy(snapshot['body']))
        require(not inspect.isawaitable(target)
                and resources._target_fingerprint(target) == entry['targetFingerprint'])

    def _write(self, run, body):
        self.store.sql('UPDATE af_autoresearch_experiments SET body=CAST(:body AS JSONB) WHERE parent_run_id=:run',
                       run=run, body=canonical(body))

    def _bound(self, ctx):
        task, plan, preset = self._parent(ctx)
        body = self._read(task['run_id']); pin = body['binding']
        require(pin['ownerId'] == task['owner_id'] and pin['parentTaskId'] == task['id']
                and pin['parentPlanId'] == task['plan_id'] and pin['parentPlanSha256'] == digest(plan)
                and pin['presetFingerprint'] == preset.fingerprint)
        for entry in body['phases'].values():
            self._preset_manifest(preset, entry['config'])
        return body

    @staticmethod
    def _preset_manifest(preset, config):
        manifest = validate_manifest(preset.manifest)
        require(config['comparisonManifest'] == manifest
                and config['comparisonManifestSha256'] == manifest_fingerprint(manifest))

    def _child(self, owner, parent, phase):
        rows = self.store.sql('''SELECT * FROM af_delegation_links
            WHERE owner_id=:owner AND parent_id=:parent AND request_id=:request''',
            owner=owner, parent=parent, request=phase['requestId'])
        require(len(rows) == 1 and rows[0]['child_id'])
        link = rows[0]; child = self.store.task(link['child_id'], owner)
        require(child['plan_id'] == link['plan_id'] and child['owner_id'] == owner)
        if phase.get('child') is not None:
            require(phase['child'] == {key: child[key] for key in ('id', 'owner_id', 'plan_id', 'run_id')})
        return child

    def _child_plan(self, ctx, phase, parent):
        parent_plan = self.store.plan(parent['plan_id'], parent['owner_id'])
        preset = self.service.current(SimpleNamespace(run_context=self.store.process_runtime._context(parent)))
        require(ctx.plan.get('applicationRef') is not None
                and ctx.plan['applicationRef'] == parent_plan.get('applicationRef')
                and not ctx.plan.get('remoteHandoff') and not parent_plan.get('remoteHandoff')
                and ctx.plan.get('delegation') == {'parentTaskId': parent['id'], 'rootTaskId': parent['id'], 'depth': 1}
                and type(ctx.plan['delegation']['depth']) is int
                and ctx.spec.get('config') == {'presetId': preset.id, 'phase': phase})

    def _runtime_plan(self, ctx, child):
        require(child['run_id'] == ctx.run_context.run_id and child['plan_id'] == ctx.plan['id'])
        original = deepcopy(ctx.plan)
        for key, expected in (('taskId', child['id']), ('runId', child['run_id'])):
            if key in original:
                require(original.pop(key) == expected)
        require(digest(self.store.plan(child['plan_id'], ctx.run_context.user_id)) == digest(original))

    def require_child(self, ctx, phase):
        return self._require_child(ctx, phase, custody=False)

    def require_child_custody(self, ctx, phase):
        """Read original completed custody; never grants dispatch or continuation."""
        return self._require_child(ctx, phase, custody=True)

    def _require_child(self, ctx, phase, *, custody):
        require(phase in PHASES)
        run = ctx.run_context
        self.auth.require(run.user_id, 'run')
        child = self.store.task(run.session_id, run.user_id)
        ticket = self.store.lifecycle_observer._binding(child) if custody else None
        completed = ticket and ticket['status'] == ticket['persistedRunStatus'] == 'completed'
        if completed:
            require(not child['cancel_requested'])
            link = self.store.delegation._link(child['id'])
            require(link is not None and link['owner_id'] == run.user_id
                    and link['plan_id'] == child['plan_id']
                    and ctx.plan.get('delegation') == {'parentTaskId': link['parent_id'],
                        'rootTaskId': link['root_id'], 'depth': link['depth']})
        else:
            self.store.delegation.authorize_child(run)
        self._runtime_plan(ctx, child)
        binding = ctx.plan.get('delegation') or {}
        parent = self.store.task(binding.get('parentTaskId'), run.user_id)
        self._child_plan(ctx, phase, parent)
        context = SimpleNamespace(run_context=self.store.process_runtime._context(parent))
        body = self._bound(context)
        entry = body['phases'].get(phase)
        require(entry and self._child(run.user_id, parent['id'], entry)['id'] == child['id']
                and ctx.plan.get('mode') == 'scientific-' + phase)
        pin = phase_pin(entry['config'])
        resources = self.store.process_runtime.resources
        self._restore_phase(context, phase, body)
        target = self._phase_target(run.user_id, phase, pin)
        require(resources._target_fingerprint(target) == entry['targetFingerprint'])
        # Authority resolution also runs inside checkpoint metadata transactions.
        # Artifact retention belongs to registration, original launch and result
        # verification, never nested inside this identity/mandate check.
        self._verify_phase(context, phase, body, target, authority_only=True)
        return pin

    def _verify_phase(self, ctx, phase, body, target, *, authority_only=False):
        self._preset_manifest(self.service.current(ctx), body['phases'][phase]['config'])
        prior = {key: deepcopy(body['phases'][key]) for key in PHASES[:PHASES.index(phase)]}
        verify = self.phase_config.verify_authority if authority_only else self.phase_config.verify_phase
        result = verify(phase, deepcopy(body['candidate']), prior,
            phase_pin(body['phases'][phase]['config']), target)
        require(not inspect.isawaitable(result))

    async def verify_preparation(self, ctx):
        """Read the original retained producer artifact; never create a new export."""
        self.require_child(ctx, 'preparation')
        self.store.authorize_tool(ctx.run_context, 'research_preparation_verify')
        receipt = self.phase_config.preparation_receipt()
        require(type(receipt) is dict and set(receipt) == {'execution', 'artifact'})
        receipt = cast(dict[str, Any], receipt)
        self.require_child(ctx, 'preparation')
        return deepcopy(receipt)

    def _preparation_receipt(self, child):
        receipt = self.phase_config.preparation_receipt()
        require(type(receipt) is dict and set(receipt) == {'execution', 'artifact'})
        receipt = cast(dict[str, Any], receipt)
        # Producer IDs remain original. The read-only verifier is a distinct child.
        require(receipt['execution']['taskId'] != child['id']
                and receipt['execution']['nativeRunId'] != child['run_id'])
        return {**deepcopy(receipt), 'verification': {'taskId': child['id'],
            'nativeRunId': child['run_id'], 'planId': child['plan_id']}}

    async def _wait(self, ctx):
        self._bound(ctx)
        await asyncio.sleep(self.poll_seconds)
        self._bound(ctx)

    async def _drive(self, ctx, phase, entry):
        owner, parent = ctx.run_context.user_id, ctx.run_context.session_id
        runtime = self.store.process_runtime if phase == 'preparation' else self.store.research_runtime
        while True:
            self._bound(ctx)
            child = self._child(owner, parent, entry)
            if child.get('admission') == 'unknown':
                raise ValueError('AUTORESEARCH_CHILD_ADMISSION_UNKNOWN')
            ticket = self.store.lifecycle_observer._binding(child) if child.get('run_id') else None
            if ticket and ticket['status'] in {'failed', 'cancelled', 'canceled'}:
                raise ValueError('AUTORESEARCH_CHILD_FAILED')
            if phase == 'preparation' and ticket and ticket['status'] == ticket['persistedRunStatus'] == 'completed':
                require(runtime._original(child['id']) is None)
                return self._preparation_receipt(child)
            if phase != 'preparation' and ticket and ticket['status'] == ticket['persistedRunStatus'] == 'paused':
                _, manifest, variant = runtime._config(child, self.store.plan(child['plan_id'], owner))
                requirement = runtime._paused(child, manifest, variant)
                self._bound(ctx)
                # Only this fresh invocation may submit; re-entry never reaches _drive.
                lease = await runtime.submit(owner, child['id'])
                while lease['state'] != 'RECLAIMED':
                    # A pinned original guardian may still be accepting dispatch.
                    # Observe that same job within the original parent deadline;
                    # never allocate again or call this state completion.
                    dispatching = (lease.get('executionStatus') == 'DISPATCHING'
                        and type(lease.get('providerJobId')) is str and bool(lease['providerJobId']))
                    if (lease['state'] == 'UNKNOWN' and not dispatching) or lease.get('preDispatchFailure') is not None:
                        raise ValueError('AUTORESEARCH_CHILD_PROCESS_UNKNOWN')
                    await self._wait(ctx)
                    lease = await runtime.inspect_task(owner, child['id'])
                positive_lease(lease, child, gpu=True)
                artifact = self.checkpoints.import_completed(owner, lease['id']) if phase == 'training' else None
                result = self._receipt(child, lease, artifact)
                self._bound(ctx)
                await self.service.commands.submit(owner, child['id'], ControlCommand(
                    commandId=entry['requestId'] + ':complete', action='approve', approved=True,
                    requirementId=requirement['id'], version=requirement['version']))
                while True:
                    await self._wait(ctx)
                    ticket = self.store.lifecycle_observer._binding(child)
                    require(ticket and ticket['status'] not in {'failed', 'cancelled', 'canceled'})
                    if ticket['status'] == ticket['persistedRunStatus'] == 'completed':
                        return result
            await self._wait(ctx)

    def _receipt(self, task, lease, artifact):
        plan = self.store.plan(task['plan_id'], task['owner_id'])
        return {'execution': {'ownerId': task['owner_id'], 'taskId': task['id'], 'nativeRunId': task['run_id'],
            'planId': task['plan_id'], 'planFingerprint': plan['fingerprint'],
            'leaseId': lease['id'], 'providerJobId': lease['providerJobId']}, 'artifact': artifact}

    async def cleanup(self, ctx, *, timeout_seconds=5):
        """Trusted stop-only original children; parent ORX stop is checked separately.

        Includes no current run grant: revoked ownership still requires cleanup.
        Database calls retain their configured timeouts; coroutine timeout bounds
        asynchronous maintenance and polling, not arbitrary synchronous driver I/O.
        """
        require(type(timeout_seconds) in {int, float} and 0 < timeout_seconds <= 30)
        try:
            run = ctx.run_context
            parent = self.store.task(run.session_id, run.user_id)
            require(parent['run_id'] == run.run_id)
            rows = self.store.sql('SELECT * FROM af_autoresearch_experiments WHERE parent_run_id=:run', run=run.run_id)
            if not rows:
                return True
            body = self._read(run.run_id)
            require(body['binding']['ownerId'] == run.user_id and body['binding']['parentTaskId'] == parent['id'])
            async with asyncio.timeout(timeout_seconds):
                while True:
                    complete = True
                    for name, phase in body['phases'].items():
                        self._restore_phase(ctx, name, body)
                        child = self._child(run.user_id, parent['id'], phase)
                        facts = self.store.lifecycle_observer._facts(child)
                        if facts.get('stopped') is not True or facts.get('unknown') is not False:
                            complete = False
                            self.store.request_cancel(child['id'])
                    if complete:
                        return True
                    await self.store.lifecycle_observer.observe_root(parent['id'])
                    await asyncio.sleep(self.poll_seconds)
                    # Never adopt a replacement phase/identity during cleanup.
                    require(self._read(run.run_id)['phases'] == body['phases'])
        except Exception:
            return False

    async def experiment(self, ctx, candidate: dict[str, Any], call_id, *, parent_guard=None):
        if parent_guard is not None:
            require(callable(parent_guard))
            require(not inspect.isawaitable(parent_guard()))
        task, plan, preset = self._parent(ctx)
        require(type(call_id) is str and 1 <= len(call_id) <= 200 and type(candidate) is dict
                and type(candidate.get('trainPy')) is str and 0 < len(candidate['trainPy'].encode()) <= 256 * 1024)
        parent_body = self.service.row(task['owner_id'], task['id'])['body']
        require(any(digest(value) == digest(candidate) for value in parent_body['candidates'].values()))
        binding = {'ownerId': task['owner_id'], 'parentTaskId': task['id'], 'parentRunId': task['run_id'],
            'parentPlanId': plan['id'], 'parentPlanSha256': digest(plan), 'presetFingerprint': preset.fingerprint,
            'callId': call_id, 'candidateSha256': digest(candidate),
            'trainPySha256': hashlib.sha256(candidate['trainPy'].encode()).hexdigest()}
        body = {'schema': 1, 'binding': binding, 'candidate': deepcopy(candidate), 'state': 'DISPATCHING', 'phases': {}}
        inserted = self.store.sql('''INSERT INTO af_autoresearch_experiments VALUES(:run,:owner,:parent,:call,:fp,CAST(:body AS JSONB))
            ON CONFLICT(parent_run_id) DO NOTHING RETURNING parent_run_id''', run=task['run_id'], owner=task['owner_id'],
            parent=task['id'], call=call_id, fp=digest(binding), body=canonical(body))
        if not inserted:
            original = self._bound(ctx)
            require(original['binding'] == binding)
            if original['state'] == 'DONE':
                return await self.result_verifier(ctx, original['result'])
            raise ValueError('AUTORESEARCH_ORIGINAL_EXPERIMENT_UNKNOWN')
        try:
            for phase in PHASES:
                body = self._bound(ctx)
                config = self.phase_config(phase, deepcopy(candidate), deepcopy(body['phases']), context=ctx)
                require(not inspect.isawaitable(config))
                config = phase_pin(config)
                self._preset_manifest(self.service.current(ctx), config)
                entry = {'configSha256': digest(config),
                    'requestId': 'ar-child:' + digest({'binding': binding, 'phase': phase}),
                    'config': phase_pin(config), 'state': 'DISPATCH_UNKNOWN'}
                prior = deepcopy(body['phases'])
                body['phases'][phase] = entry; self._write(task['run_id'], body)
                self._bound(ctx)
                registered = self.phase_config.register_phase(ctx, phase, deepcopy(candidate), prior, config,
                    persist_snapshot=lambda snapshot: self._persist_snapshot(ctx, phase, config, snapshot))
                require(not inspect.isawaitable(registered))
                resources = self.store.process_runtime.resources
                target = self._phase_target(task['owner_id'], phase, config)
                self._verify_phase(ctx, phase, body, target)
                body = self._bound(ctx); entry = body['phases'][phase]
                entry['targetFingerprint'] = resources._target_fingerprint(target)
                self._write(task['run_id'], body)
                if parent_guard is not None:
                    require(not inspect.isawaitable(parent_guard()))
                self._bound(ctx)
                await self.store.delegation.create(task['owner_id'], task['id'],
                    '执行已固定候选的受管阶段：' + phase, 'scientific-' + phase, entry['requestId'])
                self._bound(ctx)
                child = self._child(task['owner_id'], task['id'], entry)
                require(child.get('run_id'))
                entry['child'] = {key: child[key] for key in ('id', 'owner_id', 'plan_id', 'run_id')}
                body = self._bound(ctx); body['phases'][phase] = entry; self._write(task['run_id'], body)
                receipt = await self._drive(ctx, phase, entry)
                body = self._bound(ctx)
                body['phases'][phase].update(state='COMPLETED', receipt=receipt)
                self._write(task['run_id'], body)
            body = self._bound(ctx)
            result = await self._verified_result(ctx, body)
            body = self._bound(ctx)
            body.update(state='DONE', result=result)
            self._write(task['run_id'], body)
            return deepcopy(body['result'])
        except BaseException:
            # No relaunch/resume on re-entry. Existing native/delegation lifecycle
            # remains the owner of cancellation and held UNKNOWN resources.
            body = self._read(task['run_id']); body['state'] = 'UNKNOWN'; self._write(task['run_id'], body)
            raise

    async def _verified_result(self, ctx, body):
        owner, parent = ctx.run_context.user_id, ctx.run_context.session_id
        for phase in PHASES:
            entry = body['phases'][phase]
            self._restore_phase(ctx, phase, body)
            require(entry['state'] == 'COMPLETED')
            child = self._child(owner, parent, entry)
            ticket = self.store.lifecycle_observer._binding(child)
            require(ticket and ticket['status'] == ticket['persistedRunStatus'] == 'completed')
            if phase == 'preparation':
                require(self.store.process_runtime._original(child['id']) is None)
                require(entry['receipt'] == self._preparation_receipt(child))
                target = self._phase_target(owner, phase, entry['config'])
                require(self.store.process_runtime.resources._target_fingerprint(target) == entry['targetFingerprint'])
                self._verify_phase(ctx, phase, body, target)
                continue
            runtime = self.store.research_runtime
            original = runtime._original(child['id']); require(original is not None)
            lease = runtime.resources.inspect(owner, original['lease_id'])
            positive_lease(lease, child, gpu=phase != 'preparation')
            require(self._receipt(child, lease, entry['receipt']['artifact']) == entry['receipt'])
            target = runtime.resources._authorize(owner, entry['config']['targetRef'])
            require(runtime.resources._target_fingerprint(target) == entry['targetFingerprint'])
            self._verify_phase(ctx, phase, body, target)
        prep = body['phases']['preparation']['receipt']
        self.preparation.input_pin(owner, prep['execution']['taskId'], prep['artifact']['id'])
        train = body['phases']['training']; evaluate = body['phases']['evaluation']
        metadata, checkpoint = self.checkpoints.identity(train['receipt']['execution']['taskId'],
            train['receipt']['artifact']['id'], min(train['config']['comparisonManifest']['artifactLimits']['checkpointBytes'], 2 * 1024**3))
        require(metadata['id'] == train['receipt']['artifact']['id'])
        contract = {'schema': 1, 'evidenceKind': 'offline_research_evaluation_contract',
            'comparisonManifest': train['config']['comparisonManifest'],
            'training': {**train['receipt']['execution'], 'variantSha256': train['config']['variantSha256'],
                'checkpoint': {'artifactId': metadata['id'], **checkpoint}},
            'evaluatorExecution': evaluate['receipt']['execution']}
        require(evaluate['config']['comparisonManifestSha256'] == train['config']['comparisonManifestSha256'])
        from .research_evaluation_service import ResearchEvaluationService
        verifier = self.phase_config.evaluation_service(evaluate['config'])
        require(type(verifier) is ResearchEvaluationService)
        evaluation = await verifier.verify(owner, contract)
        self._bound(ctx)
        keys = ('taskId', 'nativeRunId', 'planId', 'leaseId', 'providerJobId')
        references = {phase: {key: body['phases'][phase]['receipt']['execution'][key] for key in keys}
            for phase in ('training', 'evaluation')}
        references['checkpoint'] = {'artifactId': metadata['id'], 'sha256': checkpoint['sha256']}
        for key in ('taskId', 'nativeRunId', 'leaseId', 'providerJobId'):
            require(references['training'][key] != references['evaluation'][key])
        return {'cleanupConfirmed': True, 'independentResult': True, 'evaluation': evaluation,
            'originalReferences': references, 'scientificConclusionVerified': False}

    async def result_verifier(self, ctx, result):
        """Re-read original custody; supplied result flags never authorize success."""
        body = self._bound(ctx)
        require(body['state'] == 'DONE' and body.get('result') == result)
        verified = await self._verified_result(ctx, body)
        require(verified == result)
        return deepcopy(verified)
