"""Pure synthetic peer evidence tests; no receiver, model, GPU, DB or network."""
from copy import deepcopy
import unittest

from agent_factory.gpu_custody import GpuBinding, evidence_fingerprint
from agent_factory.remote_scientific_evidence import (project_scientific_evidence,
    validate_scientific_evidence, validate_scientific_scope, scientific_stopped, scientific_native_stopped)
from agent_factory.research_evaluation import evaluation_contract_fingerprint, validate_evaluator_output
from agent_factory.research_manifest import manifest_fingerprint
from agent_factory.store import digest
from test_remote_process_evidence import lease as process_lease  # pyright: ignore[reportMissingImports]
from test_research_evaluation import example_contract, output  # pyright: ignore[reportMissingImports]


def contract():
    value = example_contract()
    value['training']['ownerId'] = value['evaluatorExecution']['ownerId'] = 'receiver-alice'
    return value


def scope(phase='training'):
    return {'schema': 1, 'originParentTaskId': 'cloud-parent', 'originParentRunId': 'cloud-parent-run',
        'originParentPlanSha256': '1' * 64, 'originChildTaskId': 'cloud-child-' + phase,
        'sourceManifestSha256': '2' * 64, 'phase': phase, 'candidateSha256': '3' * 64,
        'comparisonManifestSha256': manifest_fingerprint(contract()['comparisonManifest']),
        'variantSha256': 'b' * 64, 'receiverSciencePinSha256': '4' * 64}


def lease(phase='training', *, released=False):
    source = contract()['training' if phase == 'training' else 'evaluatorExecution']
    value = process_lease()
    value.update(id=source['leaseId'], ownerId=source['ownerId'], localTaskId=source['taskId'],
        nativeRunId=source['nativeRunId'], planId=source['planId'], planFingerprint=source['planFingerprint'],
        providerJobId=source['providerJobId'], targetFingerprint='5' * 64,
        gpuBinding=GpuBinding('6' * 64, '7' * 64).to_dict(),
        executionGuard={'id': 'requirement', 'version': 1, 'toolCallId': 'original-call',
            'toolArgsSha256': '8' * 64, 'manifestSha256': scope(phase)['comparisonManifestSha256'],
            'variantSha256': scope(phase)['variantSha256']})
    value['processBinding'].update(taskId=source['taskId'], nativeRunId=source['nativeRunId'], planId=source['planId'])
    value['gpuEvidence'] = {'schema': 1, 'bindingFingerprint': evidence_fingerprint(value), 'state': 'HELD', 'releaseProof': None}
    if released:
        value.update(state='RECLAIMED', capacityHeld=False, executionStatus='COMPLETED', exitCode=0,
                     stopEvidence={'allStopped': True, 'kind': 'original-root-reaped-and-no-live-process-group-members'})
        value['gpuEvidence'].update(state='RELEASED', releaseProof={
            'kind': 'original-process-stopped-and-device-released',
            'processBindingFingerprint': value['processBinding']['bindingFingerprint'], 'deviceObservationSha256': '9' * 64})
    return value


def shell(phase='training'):
    source = contract()['training' if phase == 'training' else 'evaluatorExecution']
    return {'id': 'handoff-' + phase, 'originTaskId': scope(phase)['originChildTaskId'],
        'manifestHash': scope(phase)['sourceManifestSha256'], 'remoteOwnerId': source['ownerId'],
        'remoteTaskId': source['taskId'], 'remotePlanId': source['planId'], 'remoteRunId': source['nativeRunId']}


def launch(phase='training'):
    return {'schema': 1, 'descriptorSha256': 'a' * 64, 'sourceSha256': 'c' * 64,
        'manifestSha256': scope(phase)['comparisonManifestSha256'], 'variantSha256': scope(phase)['variantSha256'],
        'checkpoint': contract()['training']['checkpoint'] if phase == 'evaluation' else None,
        'evaluationContractSha256': evaluation_contract_fingerprint(contract()) if phase == 'evaluation' else None,
        'leaseBindingSha256': lease(phase)['processBinding']['bindingFingerprint'],
        'processIdentitySha256': 'd' * 64, 'executionVerified': False}


def evaluation():
    checked = contract()
    result = validate_evaluator_output(checked, output(checked))
    result.update(evidenceKind='original_evaluator_custody', evaluatorCustodyVerified=True, launchInputsVerified=True,
        trainingSyntheticFixture=True, evaluatorSyntheticFixture=True,
        trainingExecution={key: value for key, value in checked['training'].items() if key not in ('variantSha256', 'checkpoint')},
        evaluatorExecution=deepcopy(checked['evaluatorExecution']), checkpoint=deepcopy(checked['training']['checkpoint']))
    return {'contract': checked, 'result': result}


def receipt(phase='training', *, released=False, result=False):
    value = shell(phase)
    value['scientificEvidence'] = project_scientific_evidence(value, scope=scope(phase),
        lease=lease(phase, released=released), launch_proof=launch(phase) if result else None,
        checkpoint=contract()['training'] if result else None,
        evaluation=evaluation() if result and phase == 'evaluation' else None)
    return value


class RemoteScientificEvidenceTests(unittest.TestCase):
    def denied(self, value, *, expected=None, previous=None):
        expected = expected or scope(value['scientificEvidence']['scope']['phase'])
        with self.assertRaisesRegex(ValueError, '^REMOTE_SCIENTIFIC_EVIDENCE_INVALID$'):
            validate_scientific_evidence(value, expected_scope=expected, previous=previous)

    def test_projection_keeps_exact_receiver_ids_and_excludes_private_operator_fields(self):
        original = lease() | {'root': '/private', 'argv': ['private'], 'pid': 123, 'credential': 'fixture'}
        value = project_scientific_evidence(shell(), scope=scope(), lease=original)
        self.assertFalse({'root', 'argv', 'pid', 'credential'} & value['lease'].keys())
        self.assertEqual(value['lease']['localTaskId'], 'train-task')
        value['lease']['gpuBinding']['deviceId'] = 'e' * 64
        self.assertEqual(original['gpuBinding']['deviceId'], '7' * 64)

    def test_every_scope_pin_is_exact_and_strict_schema(self):
        original = receipt()
        for key in scope():
            value = deepcopy(original)
            value['scientificEvidence']['scope'][key] = ('evaluation' if key == 'phase' else True if key == 'schema' else 'f' * 64)
            with self.subTest(field=key): self.denied(value, expected=scope())
        for extra in ({'url': 'https://invalid'}, {'schema': True}, {'phase': 'other'}):
            with self.assertRaises(ValueError): validate_scientific_scope(scope() | extra)
        for key in ('originTaskId', 'manifestHash', 'remoteOwnerId', 'remoteTaskId', 'remotePlanId', 'remoteRunId'):
            value = deepcopy(original); value[key] = 'f' * 64
            with self.subTest(field=key): self.denied(value)

    def test_empty_or_unknown_evidence_never_counts_as_stop(self):
        value = shell(); value['scientificEvidence'] = project_scientific_evidence(value, scope=scope())
        self.assertFalse(scientific_stopped(value, expected_scope=scope()))
        early = lease(); early.update(state='UNKNOWN', executionStatus='UNKNOWN', providerJobId=None,
                                     processBinding=None, enforcement=None, gpuEvidence=None)
        value['scientificEvidence'] = project_scientific_evidence(value, scope=scope(), lease=early)
        self.assertFalse(scientific_stopped(value, expected_scope=scope()))
        validate_scientific_evidence(receipt(), expected_scope=scope(), previous=value)
        invalid = deepcopy(value); invalid['scientificEvidence']['lease']['capacityHeld'] = False
        self.denied(invalid)

    def test_positive_cas_no_dispatch_proof_is_bound_and_cannot_disappear(self):
        value = shell(); value['scientificEvidence'] = project_scientific_evidence(value, scope=scope())
        self.assertFalse(scientific_stopped(value, expected_scope=scope()))
        prior = deepcopy(value)
        value['scientificNoDispatch'] = {'schema': 1, 'scopeSha256': digest(scope()), 'receiverTaskId': value['remoteTaskId'],
            'receiverPlanId': value['remotePlanId'], 'receiverNativeRunId': value['remoteRunId']}
        validate_scientific_evidence(value, expected_scope=scope(), previous=prior)
        self.assertTrue(scientific_stopped(value, expected_scope=scope()))
        self.denied(prior, previous=value)
        for key in value['scientificNoDispatch']:
            invalid = deepcopy(value); invalid['scientificNoDispatch'][key] = True if key == 'schema' else 'e'*64
            self.denied(invalid)
        for old in (receipt(), receipt(released=True, result=True)):
            self.denied(value, previous=old)
        invalid = deepcopy(value); invalid['scientificEvidence']['lease'] = lease()
        self.denied(invalid)
        invalid = deepcopy(value); invalid['processLeases'] = {'leases': [lease()]}
        self.denied(invalid)
        invalid = deepcopy(value); invalid['scientificNoDispatch']['extra'] = 'not allowed'
        self.denied(invalid)

    def test_original_native_queue_and_persisted_terminal_both_required(self):
        value = shell()
        identity = {'run_id': value['remoteRunId'], 'session_id': value['remoteTaskId'], 'user_id': value['remoteOwnerId']}
        value['native'] = {**identity, 'agent_id': 'factory-executor', 'status': 'RunStatus.cancelled',
            'queue': {'id': value['remoteRunId'], 'session_id': value['remoteTaskId'], 'user_id': value['remoteOwnerId'],
                      'component_type': 'agent', 'component_id': 'factory-executor', 'status': 'cancelled'}}
        self.assertTrue(scientific_native_stopped(value))
        for container, keys in (('native', ('run_id', 'session_id', 'user_id', 'agent_id', 'status')),
                                ('queue', ('id', 'session_id', 'user_id', 'component_id', 'component_type', 'status'))):
            for key in keys:
                for replace in ('other', None):
                    changed = deepcopy(value)
                    target = changed['native'] if container == 'native' else changed['native']['queue']
                    target[key] = replace
                    self.assertFalse(scientific_native_stopped(changed), (container, key))
        alias = deepcopy(value); alias['native']['queue']['run_id'] = alias['native']['queue'].pop('id')
        self.assertFalse(scientific_native_stopped(alias))
        wrong_id = deepcopy(value); wrong_id['native']['queue'].update(id='other', run_id=value['remoteRunId'])
        self.assertFalse(scientific_native_stopped(wrong_id))
        for status in ('paused', 'running', 'queued', True):
            changed = deepcopy(value); changed['native']['status'] = status
            self.assertFalse(scientific_native_stopped(changed))
            changed = deepcopy(value); changed['native']['queue']['status'] = status
            self.assertFalse(scientific_native_stopped(changed))
        changed = deepcopy(value); changed['native']['detailUnavailable'] = True
        self.assertFalse(scientific_native_stopped(changed))
        for missing in ({}, shell(), value | {'native': None}, value | {'remoteRunId': None}):
            self.assertFalse(scientific_native_stopped(missing))

    def test_unobserved_held_reservation_projects_without_fabricating_gpu_evidence(self):
        reserved = lease()
        for key in ('gpuEvidence', 'providerJobId', 'processBinding', 'enforcement',
                    'aggregateEvidence', 'stopEvidence', 'executionStatus', 'exitCode'):
            reserved.pop(key, None)
        reserved.update(state='RESERVED', capacityHeld=True)
        original = deepcopy(reserved)
        value = shell(); value['scientificEvidence'] = project_scientific_evidence(value, scope=scope(), lease=reserved)
        self.assertEqual(reserved, original)
        self.assertIsNone(value['scientificEvidence']['lease']['gpuEvidence'])
        self.assertEqual(value['scientificEvidence']['lease']['executionStatus'], 'UNKNOWN')
        self.assertFalse(scientific_stopped(value, expected_scope=scope()))
        for key in ('gpuBinding', 'targetFingerprint', 'executionGuard', 'planFingerprint'):
            invalid = deepcopy(reserved); invalid.pop(key)
            with self.assertRaises(ValueError): project_scientific_evidence(shell(), scope=scope(), lease=invalid)
        invalid = deepcopy(reserved); invalid['providerJobId'] = 'observed-provider-without-gpu-proof'
        with self.assertRaises(ValueError): project_scientific_evidence(shell(), scope=scope(), lease=invalid)

    def test_positive_process_stop_and_gpu_release_both_required(self):
        value = receipt(released=True)
        self.assertTrue(scientific_stopped(value, expected_scope=scope()))
        for mutate in (lambda x: x.update(stopEvidence=None), lambda x: x.update(capacityHeld=True),
                       lambda x: x.update(gpuEvidence=None), lambda x: x['gpuEvidence'].update(state='HELD', releaseProof=None),
                       lambda x: x['gpuEvidence']['releaseProof'].update(deviceObservationSha256='bad'),
                       lambda x: x['gpuEvidence']['releaseProof'].update(processBindingFingerprint='e' * 64)):
            invalid = deepcopy(value); mutate(invalid['scientificEvidence']['lease']); self.denied(invalid)
        failed = deepcopy(value); failed['scientificEvidence']['lease'].update(executionStatus='FAILED', exitCode=1)
        self.assertTrue(scientific_stopped(failed, expected_scope=scope()))
        self.assertEqual(validate_scientific_evidence(failed, expected_scope=scope())['lease']['executionStatus'], 'FAILED')

    def test_training_checkpoint_requires_original_completed_launch_and_execution(self):
        value = receipt(released=True, result=True)
        self.assertEqual(validate_scientific_evidence(value, expected_scope=scope())['checkpoint'], contract()['training'])
        for key in ('taskId', 'nativeRunId', 'planId', 'leaseId', 'providerJobId', 'planFingerprint'):
            invalid = deepcopy(value); invalid['scientificEvidence']['checkpoint'][key] = 'f' * 64; self.denied(invalid)
        for key in ('launchProof', 'lease'):
            invalid = deepcopy(value); invalid['scientificEvidence'][key] = None; self.denied(invalid)
        invalid = deepcopy(value); invalid['scientificEvidence']['launchProof']['executionVerified'] = True; self.denied(invalid)
        invalid = deepcopy(value); invalid['scientificEvidence']['checkpoint']['checkpoint']['sizeBytes'] = True; self.denied(invalid)

    def test_evaluation_binds_independent_contract_and_keeps_non_attestation_flags(self):
        value = receipt('evaluation', released=True, result=True)
        checked = validate_scientific_evidence(value, expected_scope=scope('evaluation'))
        self.assertFalse(checked['evaluation']['result']['executionVerified'])
        self.assertFalse(checked['evaluation']['result']['scientificConclusionVerified'])
        mutations = [lambda e: e['result'].update(executionVerified=True),
                     lambda e: e['result'].update(scientificConclusionVerified=True),
                     lambda e: e['result'].update(evaluatorCustodyVerified=1),
                     lambda e: e['result']['observation'].update(valBpb=float('nan')),
                     lambda e: e['result']['observation'].update(variantSha256='f' * 64),
                     lambda e: e['result']['evaluatorExecution'].update(nativeRunId='foreign'),
                     lambda e: e['contract']['evaluatorExecution'].update(taskId=e['contract']['training']['taskId']),
                     lambda e: e['result']['checkpoint'].update(sha256='f' * 64)]
        for mutate in mutations:
            invalid = deepcopy(value); mutate(invalid['scientificEvidence']['evaluation']); self.denied(invalid)

    def test_monotonicity_rejects_replacement_disappearance_and_gpu_rebinding(self):
        old = receipt()
        good = receipt(released=True, result=True)
        validate_scientific_evidence(good, expected_scope=scope(), previous=old)
        for key in ('id', 'planFingerprint', 'targetFingerprint', 'providerJobId'):
            bad = deepcopy(old); bad['scientificEvidence']['lease'][key] = 'e' * 64
            self.denied(bad, previous=old)
        for key in ('lease', 'launchProof', 'checkpoint'):
            bad = deepcopy(good); bad['scientificEvidence'][key] = None; self.denied(bad, previous=good)
        self.denied(old, previous=good)
        bad = deepcopy(good); bad['scientificEvidence']['lease']['gpuEvidence']['releaseProof']['deviceObservationSha256'] = 'f' * 64
        self.denied(bad, previous=good)
        bad = deepcopy(old); bad['remoteRunId'] = None; self.denied(bad, previous=old)

    def test_preparation_keeps_original_producer_and_never_proves_receiver_stop(self):
        expected = scope('preparation'); value = shell('preparation')
        prep = {key: val for key, val in contract()['training'].items() if key not in ('variantSha256', 'checkpoint')}
        prep.update(schema=1, taskId='original-preparation', artifactId='tokenizer', artifactSha256='a' * 64)
        value['scientificEvidence'] = project_scientific_evidence(value, scope=expected, preparation=prep)
        self.assertNotEqual(prep['taskId'], value['remoteTaskId'])
        self.assertFalse(scientific_stopped(value, expected_scope=expected))
        for mutate in (lambda e: e.update(preparation=None), lambda e: e['preparation'].update(artifactSha256='b' * 64)):
            bad = deepcopy(value); mutate(bad['scientificEvidence']); self.denied(bad, previous=value)
        bad = deepcopy(value); bad['scientificEvidence']['preparation']['ownerId'] = 'foreign'; self.denied(bad)
        bad = deepcopy(value); bad['scientificEvidence']['lease'] = lease(); self.denied(bad)

    def test_unknown_fields_and_excess_payload_rejected(self):
        for path in ('evidence', 'lease', 'scope'):
            value = receipt(); target = value['scientificEvidence'] if path == 'evidence' else value['scientificEvidence'][path]
            target['privatePath'] = '/operator/private'; self.denied(value)
        value = receipt(released=True, result=True)
        value['scientificEvidence']['checkpoint']['checkpoint']['artifactId'] = 'x' * (256 * 1024)
        self.denied(value)


if __name__ == '__main__':
    unittest.main()
