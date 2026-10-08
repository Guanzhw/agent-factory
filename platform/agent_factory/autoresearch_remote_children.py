"""Original remote scientific delegation; no receiver-native ticket fabrication.

Three phases remain on one pinned receiver project. A lost dispatch reply never
creates a replacement. Final results are re-read through authenticated handoff
custody, not accepted from provider completion flags.
"""
import asyncio
from copy import deepcopy
import hashlib
import inspect
import re
from typing import Any, cast

from fastapi import HTTPException

from .autoresearch_children import AutoResearchChildren, PHASES
from .remote_scientific_evidence import scientific_stopped, validate_scientific_evidence, validate_scientific_scope
from .research_manifest import manifest_fingerprint, validate_manifest
from .store import canonical, digest

ERROR = 'AUTORESEARCH_REMOTE_CHILD_CUSTODY_INVALID'
TABLE = 'af_autoresearch_remote_experiments'


def require(value):
    if not value:
        raise ValueError(ERROR)


async def resolved(value):
    return await value if inspect.isawaitable(value) else value


class AutoResearchRemoteChildren:
    _parent = AutoResearchChildren._parent

    def __init__(self, store, auth, service, *, target_ref, project_id, project_pin, manifest,
                 phase_evidence_reader=None, poll_seconds=.1):
        require(all(type(value) is str and 1 <= len(value) <= 200 for value in (target_ref, project_id)))
        require(type(project_pin) is str and re.fullmatch('[a-f0-9]{64}', project_pin))
        require(type(poll_seconds) in (int, float) and .01 <= poll_seconds <= 1)
        require(phase_evidence_reader is None or callable(phase_evidence_reader))
        self.store, self.auth, self.service = store, auth, service
        self.target_ref, self.project_id, self.project_pin = target_ref, project_id, project_pin
        self.manifest = validate_manifest(manifest)
        self.manifest_sha = manifest_fingerprint(self.manifest)
        self.reader, self.poll_seconds = phase_evidence_reader, poll_seconds
        store.sql('''CREATE TABLE IF NOT EXISTS af_autoresearch_remote_experiments (
            parent_run_id TEXT PRIMARY KEY, owner_id TEXT NOT NULL,
            parent_task_id TEXT NOT NULL REFERENCES af_tasks(id), call_id TEXT NOT NULL,
            fingerprint TEXT NOT NULL, body JSONB NOT NULL)''')

    def _read(self, run):
        rows = self.store.sql('SELECT * FROM af_autoresearch_remote_experiments WHERE parent_run_id=:run', run=run)
        require(len(rows) == 1)
        row = rows[0]; body = row['body']; pin = body['binding']
        require(row['fingerprint'] == digest(pin) and pin['parentRunId'] == run
            and row['owner_id'] == pin['ownerId'] and row['parent_task_id'] == pin['parentTaskId']
            and row['call_id'] == pin['callId'] and digest(body['candidate']) == pin['candidateSha256']
            and hashlib.sha256(body['candidate']['trainPy'].encode()).hexdigest() == pin['trainPySha256']
            and pin['targetRef'] == self.target_ref and pin['projectId'] == self.project_id
            and pin['projectPin'] == self.project_pin and pin['manifestSha256'] == self.manifest_sha)
        require(set(body['phases']) <= set(PHASES))
        for phase, entry in body['phases'].items():
            require(entry['requestId'] == self._request(pin, phase)
                and digest(entry['placement']) == entry['placementSha256'])
            placement = entry['placement']
            require(placement['targetRef'] == self.target_ref and placement['projectId'] == self.project_id
                and placement['projectPin'] == self.project_pin and placement['phase'] == phase
                and placement['candidate'] == body['candidate']
                and placement['scopeBinding'] == self._scope_binding(pin)
                and placement['prior'] == {name: body['phases'][name]
                    for name in PHASES[:PHASES.index(phase)]})
        return deepcopy(body)

    @staticmethod
    def _request(binding, phase):
        return 'ar-remote:' + digest({'binding': binding, 'phase': phase})

    @staticmethod
    def _scope_binding(pin):
        return {'originParentTaskId': pin['parentTaskId'], 'originParentRunId': pin['parentRunId'],
            'originParentPlanSha256': pin['parentPlanSha256'], 'candidateSha256': pin['candidateSha256'],
            'comparisonManifestSha256': pin['manifestSha256'], 'receiverSciencePinSha256': pin['projectPin']}

    def _bound(self, ctx):
        task, plan, preset = self._parent(ctx)
        body = self._read(task['run_id']); pin = body['binding']
        require(pin['ownerId'] == task['owner_id'] and pin['parentTaskId'] == task['id']
            and pin['parentPlanId'] == plan['id'] and pin['parentPlanSha256'] == digest(plan)
            and pin['presetFingerprint'] == preset.fingerprint
            and validate_manifest(preset.manifest) == self.manifest)
        return body

    def _write(self, run, original, body):
        rows = self.store.sql('''UPDATE af_autoresearch_remote_experiments SET body=CAST(:body AS JSONB)
            WHERE parent_run_id=:run AND body=CAST(:original AS JSONB) RETURNING parent_run_id''',
            run=run, original=canonical(original), body=canonical(body))
        require(len(rows) == 1)

    def _child(self, body, phase):
        pin = body['binding']; entry = body['phases'][phase]
        rows = self.store.sql('''SELECT * FROM af_delegation_links
            WHERE owner_id=:owner AND parent_id=:parent AND request_id=:request''',
            owner=pin['ownerId'], parent=pin['parentTaskId'], request=entry['requestId'])
        require(len(rows) == 1 and rows[0]['child_id'])
        child = self.store.task(rows[0]['child_id'], pin['ownerId'])
        require(child['plan_id'] == rows[0]['plan_id'] and child['owner_id'] == pin['ownerId'])
        if entry.get('childId') is not None:
            require(child['id'] == entry['childId'])
        return child

    async def _observe(self, body, phase, *, cleanup=False):
        child = self._child(body, phase); pin = body['binding']; entry = body['phases'][phase]
        reader = self.store.remote_scientific.cleanup_phase if cleanup else self.reader or self.store.remote_scientific.origin_phase
        observed = await resolved(reader(pin['ownerId'], child['id']))
        require(type(observed) is dict and set(observed) == {'scope', 'receipt', 'status', 'allStopped'}
            and type(observed['allStopped']) is bool)
        scope = validate_scientific_scope(observed['scope'])
        require(scope['phase'] == phase and scope['originChildTaskId'] == child['id']
            and all(scope[key] == value for key, value in self._scope_binding(pin).items()))
        if entry.get('scope') is not None:
            require(scope == entry['scope'])
        evidence = validate_scientific_evidence(observed['receipt'], expected_scope=scope,
            previous=entry.get('receipt'))
        return observed, evidence

    @staticmethod
    def _complete(observed, evidence, phase):
        if observed['status'] != 'completed' or observed['allStopped'] is not True:
            return False
        if phase == 'preparation':
            return evidence['preparation'] is not None
        lease = evidence['lease']
        return (lease is not None and lease['state'] == 'RECLAIMED' and lease['capacityHeld'] is False
            and lease['executionStatus'] == 'COMPLETED' and type(lease['exitCode']) is int and lease['exitCode'] == 0
            and lease['stopEvidence']['allStopped'] is True and lease['gpuEvidence']['state'] == 'RELEASED'
            and evidence['checkpoint'] is not None and (phase != 'evaluation' or evidence['evaluation'] is not None))

    async def _verified_result(self, ctx):
        body = self._bound(ctx); facts = {}
        for phase in PHASES:
            require(body['phases'][phase]['state'] == 'COMPLETED')
            observed, evidence = await self._observe(body, phase)
            require(self._complete(observed, evidence, phase))
            self._bound(ctx); facts[phase] = evidence
        train, evaluate = facts['training'], facts['evaluation']
        require(train['scope']['variantSha256'] == evaluate['scope']['variantSha256']
            and train['checkpoint'] == evaluate['checkpoint'])
        keys = ('taskId', 'nativeRunId', 'planId', 'leaseId', 'providerJobId')
        evaluation = evaluate['evaluation']['result']
        references = {'training': {key: evaluation['trainingExecution'][key] for key in keys},
            'evaluation': {key: evaluation['evaluatorExecution'][key] for key in keys},
            'checkpoint': {'artifactId': train['checkpoint']['checkpoint']['artifactId'],
                'sha256': train['checkpoint']['checkpoint']['sha256']}}
        require(all(references['training'][key] != references['evaluation'][key]
            for key in ('taskId', 'nativeRunId', 'leaseId', 'providerJobId')))
        return {'cleanupConfirmed': True, 'independentResult': True, 'evaluation': evaluation,
            'originalReferences': references, 'scientificConclusionVerified': False}

    async def result_verifier(self, ctx, result):
        body = self._bound(ctx)
        require(body['state'] == 'DONE' and body['result'] == result)
        actual = await self._verified_result(ctx)
        require(actual == result)
        return deepcopy(actual)

    async def experiment(self, ctx, candidate, call_id, *, parent_guard=None):
        if parent_guard is not None:
            require(callable(parent_guard) and not inspect.isawaitable(parent_guard()))
        task, plan, preset = self._parent(ctx)
        require(type(call_id) is str and 1 <= len(call_id) <= 200 and type(candidate) is dict)
        candidate = cast(dict[str, Any], candidate)
        require(type(candidate.get('trainPy')) is str and 0 < len(candidate['trainPy'].encode()) <= 256 * 1024)
        require(validate_manifest(preset.manifest) == self.manifest)
        require(any(digest(value) == digest(candidate) for value in
            self.service.row(task['owner_id'], task['id'])['body']['candidates'].values()))
        pin = {'ownerId': task['owner_id'], 'parentTaskId': task['id'], 'parentRunId': task['run_id'],
            'parentPlanId': plan['id'], 'parentPlanSha256': digest(plan), 'presetFingerprint': preset.fingerprint,
            'callId': call_id, 'candidateSha256': digest(candidate),
            'trainPySha256': hashlib.sha256(candidate['trainPy'].encode()).hexdigest(),
            'targetRef': self.target_ref, 'projectId': self.project_id, 'projectPin': self.project_pin,
            'manifestSha256': self.manifest_sha}
        body = {'schema': 1, 'binding': pin, 'candidate': deepcopy(candidate), 'state': 'DISPATCHING', 'phases': {}}
        inserted = self.store.sql('''INSERT INTO af_autoresearch_remote_experiments
            VALUES(:run,:owner,:parent,:call,:fp,CAST(:body AS JSONB))
            ON CONFLICT(parent_run_id) DO NOTHING RETURNING parent_run_id''', run=task['run_id'],
            owner=task['owner_id'], parent=task['id'], call=call_id, fp=digest(pin), body=canonical(body))
        if not inserted:
            original = self._bound(ctx); require(original['binding'] == pin)
            if original['state'] == 'DONE':
                return await self.result_verifier(ctx, original['result'])
            raise ValueError('AUTORESEARCH_ORIGINAL_EXPERIMENT_UNKNOWN')
        try:
            for phase in PHASES:
                original = self._bound(ctx); body = deepcopy(original)
                placement = {'targetRef': self.target_ref, 'projectId': self.project_id, 'projectPin': self.project_pin,
                    'phase': phase, 'candidate': deepcopy(candidate), 'prior': deepcopy(body['phases']),
                    'scopeBinding': self._scope_binding(pin)}
                entry = {'requestId': self._request(pin, phase), 'placement': placement,
                    'placementSha256': digest(placement), 'state': 'DISPATCH_UNKNOWN'}
                body['phases'][phase] = entry; self._write(task['run_id'], original, body)
                self._bound(ctx)
                if parent_guard is not None:
                    require(not inspect.isawaitable(parent_guard()))
                await self.store.delegation.create(task['owner_id'], task['id'],
                    '执行固定候选的远程受管阶段：' + phase, 'remote-scientific-' + phase,
                    entry['requestId'], scientific_placement=deepcopy(placement))
                while True:
                    original = self._bound(ctx); body = deepcopy(original)
                    original_child = self._child(original, phase)
                    try:
                        await self.store.remote_scientific.start_phase(task['owner_id'], original_child['id'])
                    except HTTPException as error:
                        if (error.status_code != 503 or error.detail !=
                                'REMOTE_ACK_UNKNOWN: read the original owner-bound receipt'):
                            raise
                        # This read validates the persisted original scope, receipt
                        # and native identity. It cannot grant or replay a dispatch.
                        if self.store.remote_scientific.drive_outcome(task['owner_id'], original_child['id']) is None:
                            raise
                    observed, evidence = await self._observe(body, phase)
                    require(observed['status'] not in {'failed', 'cancelled', 'canceled'})
                    body['phases'][phase].update(childId=observed['scope']['originChildTaskId'],
                        scope=observed['scope'], receipt=observed['receipt'])
                    complete = self._complete(observed, evidence, phase)
                    if complete: body['phases'][phase]['state'] = 'COMPLETED'
                    self._bound(ctx); self._write(task['run_id'], original, body)
                    if complete: break
                    await asyncio.sleep(self.poll_seconds)
            result = await self._verified_result(ctx)
            original = self._bound(ctx); body = deepcopy(original); body.update(state='DONE', result=result)
            self._write(task['run_id'], original, body)
            return deepcopy(result)
        except BaseException:
            original = self._read(task['run_id']); body = deepcopy(original); body['state'] = 'UNKNOWN'
            self._write(task['run_id'], original, body)
            raise

    async def cleanup(self, ctx, *, timeout_seconds=5):
        require(type(timeout_seconds) in (int, float) and 0 < timeout_seconds <= 30)
        try:
            run = ctx.run_context; task = self.store.task(run.session_id, run.user_id)
            require(task['run_id'] == run.run_id)
            rows = self.store.sql('SELECT * FROM af_autoresearch_remote_experiments WHERE parent_run_id=:run', run=run.run_id)
            if not rows: return True
            body = self._read(run.run_id)
            require(body['binding']['ownerId'] == run.user_id and body['binding']['parentTaskId'] == task['id'])
            async with asyncio.timeout(timeout_seconds):
                while True:
                    stopped = True
                    for phase in body['phases']:
                        child = self._child(body, phase)
                        await resolved(self.store.remote_scientific.cancel_original(run.user_id, child['id']))
                        observed, _ = await self._observe(body, phase, cleanup=True)
                        positive = observed['allStopped'] is True and observed['status'] in {'completed', 'failed', 'cancelled', 'canceled'}
                        if phase != 'preparation':
                            positive = positive and scientific_stopped(observed['receipt'], expected_scope=observed['scope'])
                        if not positive:
                            stopped = False
                    if stopped: return True
                    await asyncio.sleep(self.poll_seconds)
                    require(self._read(run.run_id) == body)
        except Exception:
            return False
