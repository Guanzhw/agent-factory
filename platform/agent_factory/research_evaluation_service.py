"""Read-only original evaluator custody verification; no execution or promotion.

Checkpoint readers are trusted operator functions returning bounded streaming
identities, never checkpoint bytes. This service caps reading at 2 GiB even if
the manifest permits larger artifacts. No reader is supplied by a request/model.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
import re
from typing import Any

from .research_evaluation import validate_evaluation_contract, validate_evaluator_output
from .store import digest
from .research_manifest import manifest_fingerprint


def _require(value):
    if not value:
        raise ValueError('RESEARCH_EVALUATOR_CUSTODY_INVALID')


class ResearchEvaluationService:
    def __init__(self, store, auth, resources, operator_evaluators, *, checkpoint_reader=None):
        _require(type(operator_evaluators) is dict and bool(operator_evaluators))
        checkpoint_reader = checkpoint_reader if checkpoint_reader is not None else getattr(store, 'artifact_identity', None)
        if not callable(checkpoint_reader):
            raise ValueError('RESEARCH_CHECKPOINT_READER_REQUIRED')
        self.store, self.auth, self.resources = store, auth, resources
        self._reader: Any = checkpoint_reader
        self._targets = {}
        for fingerprint, reference in operator_evaluators.items():
            _require(type(fingerprint) is str and re.fullmatch('[a-f0-9]{64}', fingerprint) is not None
                     and type(reference) is str and reference in resources.targets)
            target = resources.targets[reference]
            _require(callable(getattr(target.provider, 'read_completed_output', None)))
            self._targets[fingerprint] = (reference, resources._target_fingerprint(target))

    def _execution(self, owner, execution, manifest, *, training=False):
        self.auth.require(owner, 'read')
        self.auth.require(owner, 'run')
        rows = self.store.sql('SELECT * FROM af_process_runs WHERE task_id=:task AND lease_id=:lease',
                              task=execution['taskId'], lease=execution['leaseId'])
        _require(len(rows) == 1)
        row = rows[0]
        _require(row['owner_id'] == owner and row['native_run_id'] == execution['nativeRunId']
                 and row['lease_id'] == execution['leaseId'] and row['task_id'] == execution['taskId'])
        _require(row['effect_key'] == 'research-process-run-v1')
        runtime = self.resources.execution_runtime(row['effect_key'])
        lease, target, task, _ = runtime._custody(execution['leaseId'])
        expected = {'ownerId': owner, 'localTaskId': execution['taskId'], 'nativeRunId': execution['nativeRunId'],
                    'planId': execution['planId'], 'providerJobId': execution['providerJobId'], 'id': execution['leaseId']}
        _require(all(lease.get(key) == value for key, value in expected.items()))
        _require(lease.get('state') == 'RECLAIMED' and lease.get('capacityHeld') is False
                 and lease.get('executionStatus') == 'COMPLETED' and type(lease.get('exitCode')) is int
                 and lease['exitCode'] == 0 and type(lease.get('stopEvidence')) is dict
                 and lease['stopEvidence'].get('allStopped') is True)
        plan = self.store.plan(execution['planId'], owner)
        _require(plan['fingerprint'] == execution['planFingerprint'] and task['id'] == execution['taskId']
                 and task['owner_id'] == owner and task['run_id'] == execution['nativeRunId']
                 and task['plan_id'] == execution['planId'] and not task['cancel_requested'])
        target_ref, current_manifest, current_variant = runtime._config(task, plan)
        expected_manifest = manifest_fingerprint(manifest)
        guard = lease.get('executionGuard')
        _require(type(guard) is dict and guard.get('manifestSha256') == expected_manifest
                 and manifest_fingerprint(current_manifest) == expected_manifest
                 and target_ref == lease['connectionRef'] and guard.get('variantSha256') == current_variant)
        if training:
            _require(current_variant == execution['variantSha256'])
        self.store.require_plan_execution(owner, plan, run_context=runtime._context(task))
        authorized = self.resources._authorize(owner, lease['connectionRef'])
        _require(self.resources._target_fingerprint(authorized) == self.resources._target_fingerprint(target)
                 and lease['targetFingerprint'] == self.resources._target_fingerprint(target))
        return lease, target

    def _checkpoint(self, contract):
        training = contract['training']
        expected = training['checkpoint']
        _require(expected['sizeBytes'] <= 2 * 1024**3)
        metadata, identity = self._reader(training['taskId'], expected['artifactId'],
            min(expected['sizeBytes'], contract['comparisonManifest']['artifactLimits']['checkpointBytes'], 2 * 1024**3))
        _require(type(metadata) is dict and type(identity) is dict and set(identity) == {'sha256', 'sizeBytes'}
                 and type(identity['sizeBytes']) is int and identity['sizeBytes'] == expected['sizeBytes']
                 and identity['sha256'] == expected['sha256']
                 and metadata.get('id') == expected['artifactId'] and metadata.get('jobId') == training['taskId']
                 and type(metadata.get('size')) is int and metadata['size'] == identity['sizeBytes']
                 and metadata.get('sha256') == expected['sha256'])
        provenance = metadata.get('provenance')
        _require(type(provenance) is dict and all(provenance.get(key) == training[key]
            for key in ('nativeRunId', 'planId', 'planFingerprint', 'leaseId', 'providerJobId', 'variantSha256')))

    def _check(self, owner, contract):
        _require(contract['training']['ownerId'] == owner and contract['evaluatorExecution']['ownerId'] == owner)
        key = digest(contract['comparisonManifest']['evaluator'])
        _require(key in self._targets)
        reference, fingerprint = self._targets[key]
        training, training_target = self._execution(owner, contract['training'], contract['comparisonManifest'], training=True)
        evaluation, evaluator_target = self._execution(owner, contract['evaluatorExecution'], contract['comparisonManifest'])
        _require(evaluation['connectionRef'] == reference and training['connectionRef'] != reference
                 and evaluator_target.provider is not training_target.provider
                 and self.resources._target_fingerprint(evaluator_target) == fingerprint)
        self._checkpoint(contract)
        return (evaluator_target.provider, getattr(training_target, 'synthetic_fixture', False) is True,
                getattr(evaluator_target, 'synthetic_fixture', False) is True)

    async def verify(self, owner, contract):
        checked = validate_evaluation_contract(contract)
        provider, _, _ = await asyncio.to_thread(self._check, owner, checked)
        execution = checked['evaluatorExecution']
        raw = await asyncio.to_thread(provider.read_completed_output, execution['leaseId'], owner)
        result = validate_evaluator_output(checked, raw)
        _, training_fixture, evaluator_fixture = await asyncio.to_thread(self._check, owner, checked)
        return {**result, 'evidenceKind': 'original_evaluator_custody', 'evaluatorCustodyVerified': True,
                'executionVerified': False, 'scientificConclusionVerified': False,
                'trainingSyntheticFixture': training_fixture,
                'evaluatorSyntheticFixture': evaluator_fixture,
                'trainingExecution': {key: value for key, value in deepcopy(checked['training']).items()
                                      if key not in {'checkpoint', 'variantSha256'}},
                'evaluatorExecution': deepcopy(execution), 'checkpoint': deepcopy(checked['training']['checkpoint'])}
