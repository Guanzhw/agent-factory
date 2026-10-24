"""Native toy round execution and sealed artifact reads; no execution queue.

Activity admission owns dispatch-once fencing. This adapter never approves HITL,
replays an uncertain submission, or treats a native terminal ticket as stop proof.
"""
import asyncio
import hashlib
import io
import json
import math
import tarfile
import time

from fastapi import HTTPException
from agent_factory.control_commands import ControlCommand
from agent_factory.runtime_hooks import effect_unresolved, runtime_custody_held
from agent_factory.store import digest
from .orx_experiment_tools import LAUNCH_EFFECT_KEY, inspect_owned_orx_experiment, inspect_orx_experiment
from .orx_local import TOY_FILES, TaskLocalORXProvider
from .research_iteration_recipe import IterationORXProvider, IterationSeedORXAdapter, IterationPromotedORXAdapter


def require(value):
    if not value:
        raise HTTPException(409, 'ITERATION_ORIGINAL_EVIDENCE_INVALID')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def recipe_for(round):
    baseline = round['baselineSource']
    require(baseline['datasetSha256'] == TOY_FILES['dataset.json']
            and baseline['evaluatorSha256'] == TOY_FILES['evaluator.py'])
    if baseline['kind'] == 'reviewedSeed':
        require(round['ordinal'] == 1 and round['previousRoundId'] is None
                and baseline['sha256'] == TOY_FILES['baseline.py'] and baseline['metricValue'] == 16.0)
        return IterationSeedORXAdapter._recipe
    require(baseline['kind'] == 'sourceArtifact' and round['ordinal'] > 1
            and baseline['sha256'] == TOY_FILES['candidate.py'] and baseline['metricValue'] == 0.0)
    return IterationPromotedORXAdapter._recipe


def source_files(raw, recipe):
    """Inspect four bounded regular members in memory; never extract a path."""
    require(type(raw) is bytes and len(raw) <= 1024 * 1024 and sha(raw) == recipe.archive_sha256)
    files = {}
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:') as archive:
        for member in archive:
            require(member.name in recipe.files() and member.name not in files and member.isfile()
                    and not member.issym() and not member.islnk() and not member.sparse
                    and 0 <= member.size <= 256 * 1024)
            stream = archive.extractfile(member)
            if stream is None:
                raise HTTPException(409, 'ITERATION_ORIGINAL_EVIDENCE_INVALID')
            content = stream.read(256 * 1024 + 1)
            require(len(content) == member.size and sha(content) == recipe.files()[member.name])
            files[member.name] = content
    require(set(files) == set(recipe.files()))
    return files


class ActualORXRoundDriver:
    def __init__(self, store, auth, bridge, commands, *, research):
        self.research = research.require_store(store)
        self.store, self.auth, self.bridge, self.commands = store, auth, bridge, commands

    def _bound(self, owner, round):
        self.research.require_store(self.store, ready=True)
        require(round['ownerId'] == owner)
        task = self.store.task(round['taskId'], owner)
        plan = self.store.plan(round['planId'], owner)
        require(task['owner_id'] == owner and task['plan_id'] == plan['id'] == round['planId']
                and task['request_id'] == round['requestId'] and digest(plan) == round['planSha256']
                and (round.get('runId') is None or round['runId'] == task['run_id']))
        return task, plan

    def reserve(self, owner, activity, round):
        self.research.require_store(self.store, ready=True)
        self.auth.require_member(owner)
        require(self.store._connection.get() is not None and owner == activity['ownerId'] == round['ownerId']
                and activity['pins'] == round['pins'])
        recipe_for(round)
        pins = round['pins']
        proposal = self.store.composition.propose(owner, activity['goal'], mode=pins['mode'],
            application_ref=pins['applicationRef'], connection_refs=pins['connectionRefs'],
            request_id=round['requestId'] + ':proposal')
        plan = self.store.composition.accept(owner, proposal['id'], round['requestId'] + ':accept')
        require(plan['status'] == 'ready' and plan['applicationRef'] == pins['applicationRef'] and plan['mode'] == pins['mode'])
        self.store.require_plan_execution(owner, plan)
        task, _ = self.store.reserve_task(plan, round['requestId'])
        return {'taskId': task['id'], 'planId': plan['id'], 'planSha256': digest(plan)}

    async def dispatch(self, owner, round):
        try:
            self.auth.require_member(owner)
            task, plan = self._bound(owner, round)
            require(round['dispatchAttempted'] is True and not task['cancel_requested']
                    and not task['terminal'] and task['run_id'] is None
                    and time.time() + round['roundSeconds'] <= round['deadline'])
            self.store.require_plan_execution(owner, plan)
        except HTTPException:
            # No bridge call has started. The coordinator owns atomically
            # recording rejection on the original fenced round and task.
            return {'notSubmitted': True, 'reason': 'preflight_rejected'}
        try:
            receipt = await self.bridge.submit({**plan, 'task_id': task['id']}, owner, round['requestId'])
            self.store.accept(task['id'], receipt['run_id'])
        except BaseException:
            self.store.admission_unknown(task['id'])
            raise

    def _artifact(self, task, artifact_id, expected_sha, result, kind):
        metadata, raw = self.store.artifact(task['id'], artifact_id)
        require(type(raw) is bytes and len(raw) <= 1024 * 1024
                and metadata['id'] == artifact_id and metadata['sha256'] == expected_sha == sha(raw))
        provenance = metadata['provenance']
        require(provenance['evidenceKind'] == kind and provenance['taskId'] == task['id']
                and provenance['nativeRunId'] == task['run_id']
                and provenance['effectFingerprint'] == result['effectFingerprint']
                and provenance['orxRunId'] == result['orxRunId'])
        return raw

    def _native(self, task):
        # Continuation keeps the original run; its queue ticket may retain a
        # paused/running status after the persisted session run has completed.
        # The lifecycle binding verifies both identities and the original
        # admission envelope before exposing the persisted run status.
        observer = getattr(self.store, 'lifecycle_observer', None)
        if observer is None:
            return None
        native = observer._binding(task)
        if native is None:
            return None
        status = native.get('persistedRunStatus') or native['status']
        return {**native, 'status': {'error': 'failed', 'canceled': 'cancelled'}.get(status, status)}

    def verified_evaluation(self, owner, round):
        """Re-read the original completed task and both persisted artifacts."""
        task, _ = self._bound(owner, round)
        effects = self.store.effects(task['id'])
        require(task['terminal'] is True and task['run_id'] and not task['cancel_requested']
                and not runtime_custody_held(self.store, task['id'])
                and not any(effect_unresolved(e, self.store) for e in effects))
        native = self._native(task) or {}
        require(native.get('id') == task['run_id'] and native.get('session_id') == task['id']
                and native.get('user_id') == owner and native.get('status') == 'completed')
        matching = [e for e in effects if e['effect_key'] == task['run_id'] + ':' + LAUNCH_EFFECT_KEY]
        require(len(matching) == 1 and matching[0]['status'] == 'DONE')
        result = matching[0]['result']
        # Store.effects is a public projection without the original intent
        # fingerprint. Read that exact durable row without widening its scope.
        intents = self.store.sql(
            'SELECT fingerprint FROM af_effects WHERE task_id=:task AND run_id=:run AND effect_key=:key',
            task=task['id'], run=task['run_id'], key=matching[0]['effect_key'])
        require(len(intents) == 1)
        owned = inspect_owned_orx_experiment(self.store, task['id'])
        observed = inspect_orx_experiment(self.store, owner, task['id'])
        keys = ('taskId', 'planId', 'nativeRunId', 'effectFingerprint', 'projectId', 'experimentId',
                'orxRunId', 'status', 'provenance', 'evaluation', 'sourceArtifactId', 'sourceArtifactSha256',
                'artifactId', 'artifactSha256', 'stopEvidence')
        require(isinstance(result, dict) and isinstance(owned, dict) and isinstance(observed, dict)
                and all(result.get(k) == owned.get(k) == observed.get(k) for k in keys)
                and result['taskId'] == task['id'] and result['planId'] == task['plan_id']
                and result['nativeRunId'] == task['run_id'] and result['status'] == 'done'
                and result['stopEvidence'].get('allStopped') is True
                and result.get('sourceVerified') is True and result.get('scopeVerified') is True
                and intents[0].get('fingerprint') == result['effectFingerprint'])
        recipe = recipe_for(round)
        provenance = result['provenance']
        require(provenance['recipeIdentity'] == recipe.identity and provenance['recipeSourceCommit'] == recipe.commit
                and provenance['recipeArchiveSha256'] == provenance['sourceArchiveSha256'] == recipe.archive_sha256
                and provenance['fileSha256'] == recipe.files() and provenance['taskId'] == task['id']
                and provenance['ownerSha256'] == sha(owner.encode()))
        raw = self._artifact(task, result['sourceArtifactId'], result['sourceArtifactSha256'], result,
                             'original_reviewed_toy_source')
        files = source_files(raw, recipe)
        evaluation_raw = self._artifact(task, result['artifactId'], result['artifactSha256'], result, 'toy_local_evaluation')
        payload = json.loads(evaluation_raw)
        require(payload == {'schema': 1, 'result': {k: v for k, v in result.items()
                    if k not in ('artifactId', 'artifactSha256')}})
        evaluation = result['evaluation']
        require(isinstance(evaluation, dict) and evaluation.get('status') == 'done'
                and evaluation.get('metric') == 'mean_squared_error' and evaluation.get('sampleCount') == 7
                and evaluation.get('taskId') == task['id'] and evaluation.get('ownerSha256') == sha(owner.encode())
                and evaluation.get('runId') == result['orxRunId'] and evaluation.get('fileSha256') == recipe.files())
        a, b, delta = evaluation['baseline']['value'], evaluation['candidate']['value'], evaluation['improvement']
        require(all(type(v) in (int, float) and math.isfinite(v) for v in (a, b, delta))
                and a == recipe.baseline_mse == round['baselineSource']['metricValue'] and b == 0.0 and delta == a - b)
        common = {'ownerId': owner, 'taskId': task['id'], 'nativeRunId': task['run_id'],
                  'effectFingerprint': result['effectFingerprint'], 'recipeIdentity': recipe.identity,
                  'datasetSha256': sha(files['dataset.json']), 'evaluatorSha256': sha(files['evaluator.py'])}
        return {'sourcePin': {**common, 'kind': 'sourceArtifact', 'artifactId': result['sourceArtifactId'],
                             'archiveSha256': sha(raw), 'sha256': sha(files['candidate.py'])},
                'evaluation': {**common, 'artifactId': result['artifactId'], 'sha256': sha(evaluation_raw),
                               'metric': 'mean_squared_error', 'baselineValue': a, 'candidateValue': b,
                               'baselineSourceSha256': sha(files['baseline.py']),
                               'candidateSourceSha256': sha(files['candidate.py'])}}

    def _observe(self, owner, round):
        task, _ = self._bound(owner, round)
        reply = {'taskId': task['id'], 'runId': task['run_id'], 'state': 'unknown'}
        if task['run_id'] is None:
            # A stale observation from before the dispatch fence is not proof.
            persisted = self.research.iterations.round_for_task(owner, task['id'])
            require(persisted['id'] == round['id'])
            task, _ = self._bound(owner, persisted)
            reply['runId'] = task['run_id']
            if ((persisted.get('dispatchAttempted') is False or persisted.get('dispatchRejected') is True)
                    and task['run_id'] is None
                    and task.get('admission') == 'rejected' and task['terminal'] is True
                    and not self.store.effects(task['id'])
                    and not runtime_custody_held(self.store, task['id'])):
                return {**reply, 'state': 'stopped', 'failed': True}
        native = self._native(task) if task['run_id'] else None
        if not native:
            return reply
        require(native['id'] == task['run_id'] and native['session_id'] == task['id'] and native['user_id'] == owner)
        if native['status'] not in ('completed', 'failed', 'cancelled'):
            return {**reply, 'state': 'pending', 'approvalRequired': native['status'] == 'paused'}
        effects = self.store.effects(task['id'])
        if (not task['terminal'] or runtime_custody_held(self.store, task['id'])
                or any(effect_unresolved(e, self.store) for e in effects)):
            return reply
        launch = [e for e in effects if e['effect_key'] == task['run_id'] + ':' + LAUNCH_EFFECT_KEY]
        if launch and (len(launch) != 1 or not isinstance(launch[0].get('result'), dict)
                       or launch[0]['result'].get('stopEvidence', {}).get('allStopped') is not True):
            return reply
        if native['status'] != 'completed' or task['cancel_requested']:
            return {**reply, 'state': 'stopped', 'failed': True}
        return {**reply, 'state': 'stopped', **self.verified_evaluation(owner, round)}

    async def observe(self, owner, round):
        self.auth.require_member(owner)
        task, _ = self._bound(owner, round)
        if round.get('dispatchAttempted') is True and task['run_id'] is None:
            finder = getattr(self.bridge, 'find_run', None)
            receipt = await finder(task['id'], owner) if finder else None
            if receipt:
                self.store.accept(task['id'], receipt['run_id'])
        observer = getattr(self.store, 'lifecycle_observer', None)
        if observer is not None:
            await observer.observe_root(task['id'])
        return await asyncio.to_thread(self._observe, owner, round)

    async def cancel(self, owner, round):
        self.auth.require_member(owner)
        task, _ = self._bound(owner, round)
        return await self.commands.submit(owner, task['id'], ControlCommand(
            commandId='iteration-cancel:' + digest({'round': round['id'], 'task': task['id']})[:48], action='cancel'))


class IterationRoundProvider(TaskLocalORXProvider):
    """One connection handle, with recipe selection bound to the persisted round."""
    revision = '1'

    def __init__(self, *, research, driver, **kwargs):
        self.research, self.driver = research, driver
        super().__init__(**kwargs)

    def create_experiment_adapter(self, *, owner_id, task_id, **kwargs):
        self.research.require_store(self.driver.store, ready=True)
        round = self.research.iterations.round_for_task(owner_id, task_id)
        self.driver._bound(owner_id, round)
        recipe = recipe_for(round)
        if round['baselineSource']['kind'] == 'sourceArtifact':
            baseline = round['baselineSource']
            previous = self.research.iterations.round_for_task(owner_id, baseline['taskId'])
            require(previous['id'] == round['previousRoundId'] and previous['activityId'] == round['activityId']
                    and previous['ordinal'] + 1 == round['ordinal'] and previous['pins'] == round['pins'])
            verified = self.driver.verified_evaluation(owner_id, previous)
            promoted = {**verified['sourcePin'], 'metricValue': verified['evaluation']['candidateValue'],
                        'evaluationArtifactId': verified['evaluation']['artifactId'],
                        'evaluationSha256': verified['evaluation']['sha256']}
            require(baseline == promoted)
        selected = IterationORXProvider(recipe='seed' if recipe is IterationSeedORXAdapter._recipe else 'promoted',
            binary=self.binary, source_archive=self.source_archive, git_binary=self.git_binary, python_binary=self.python_binary)
        return selected.create_experiment_adapter(owner_id=owner_id, task_id=task_id, **kwargs)
