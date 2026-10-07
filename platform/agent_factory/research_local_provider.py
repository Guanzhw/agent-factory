"""Research GPU custody hooks on the existing bounded process lifecycle.

Device observation is trusted operator configuration, not physical isolation.
No source staging, checkpoint publication or evaluation implementation is implied.
"""
from copy import deepcopy
import re
from typing import cast

from .gpu_custody import GpuBinding, evidence_fingerprint, validate_gpu_evidence
from .process_provider import ProcessResourceProvider
from .process_enforcement import ResearchProcessLimits, ResearchProcessSpec, UvResearchProcessSpec
from .store import digest


def _require(value):
    if not value:
        raise ValueError('RESEARCH_LOCAL_CUSTODY_UNCONFIRMED')


class ResearchLocalProvider(ProcessResourceProvider):
    effect_key = 'research-process-run-v1'

    def __init__(self, store, root, spec, limits, *, gpu_binding, source_fingerprint,
                 manifest_fingerprint, observer, program_verifier, **kwargs):
        _require(type(gpu_binding) is GpuBinding and callable(observer) and callable(program_verifier)
                 and type(spec) in {ResearchProcessSpec, UvResearchProcessSpec} and type(limits) is ResearchProcessLimits)
        for value in (source_fingerprint, manifest_fingerprint, getattr(observer, 'configuration_fingerprint', None)):
            _require(type(value) is str and re.fullmatch('[a-f0-9]{64}', value))
        _require(getattr(program_verifier, 'configuration_fingerprint', None) == source_fingerprint)
        _require(callable(getattr(program_verifier, 'validate_spec', None)))
        program_verifier.validate_spec(spec)
        self._program_verifier = program_verifier
        self.gpu_binding = gpu_binding
        self._source = source_fingerprint
        self._manifest = manifest_fingerprint
        self._observer = observer
        self._observer_pin = observer.configuration_fingerprint
        super().__init__(store, root, spec, limits, **kwargs)

    @property
    def configuration_fingerprint(self):
        return digest({'base': super().configuration_fingerprint, 'revision': 'research-local-provider-v1',
            'gpuBinding': self.gpu_binding.to_dict(), 'sourceSha256': self._source,
            'manifestSha256': self._manifest, 'observerSha256': self._observer_pin})

    def _observe_device(self, record, snapshot, operation):
        _require(self._observer.configuration_fingerprint == self._observer_pin)
        _require(record['binding'].get('gpuBinding') == self.gpu_binding.to_dict()
                 and record['binding'].get('executionGuard', {}).get('manifestSha256') == self._manifest)
        _require(record.get('processPin') is not None)
        request = {'schema': 1, 'operation': operation, 'gpuBinding': self.gpu_binding.to_dict(),
            'leaseFingerprint': evidence_fingerprint(record['binding']), 'processPin': deepcopy(record['processPin']),
            'configurationFingerprint': self.configuration_fingerprint,
            'originalStopped': snapshot.get('stoppedProof') is True,
            'stopReceiptSha256': digest(snapshot['stopReceipt']) if snapshot.get('stopReceipt') else None}
        result = self._observer(deepcopy(request))
        _require(type(result) is dict and set(result) == {'schema', 'requestFingerprint', 'status', 'observationSha256'}
                 and type(result['schema']) is int and result['schema'] == 1
                 and result['requestFingerprint'] == digest(request)
                 and result['status'] == ('AVAILABLE' if operation == 'launch' else 'RELEASED')
                 and type(result['observationSha256']) is str and re.fullmatch('[a-f0-9]{64}', result['observationSha256']))
        return cast(dict, result)['observationSha256']

    def _before_launch(self, record, snapshot):
        # This hook runs under the original PREPARED custody lock, before dispatch.
        from .research_local_driver import ResearchDriverFailure
        phase = 'program-verification'
        try:
            _require(self._program_verifier.configuration_fingerprint == self._source)
            verified = self._program_verifier(deepcopy(record))
            proof = self._program_proof(record, verified)
            record['programVerification'] = proof
            phase = 'device-verification'
            record['gpuLaunchObservationSha256'] = self._observe_device(record, snapshot, 'launch')
        except Exception as error:
            if type(error) is ResearchDriverFailure and error.phase in {
                'binding-validation', 'runtime-config-validation', 'environment-verification',
                'config-staging', 'staged-program-verification',
            }:
                phase = error.phase
            record['preDispatchFailure'] = {'schema': 1, 'phase': phase,
                'code': 'RESEARCH_PRELAUNCH_VERIFICATION_FAILED',
                'journalId': record['processPin']['id'],
                'identitySha256': record['processPin']['identitySha256'],
                'dispatchAttempted': False}
            raise

    def _program_proof(self, record, verified):
        fields = {'descriptorSha256', 'sourceSha256', 'manifestSha256', 'variantSha256'}
        _require(type(verified) is dict and set(verified) == fields | {'schema', 'checkpoint', 'evaluationContractSha256'}
                 and type(verified['schema']) is int and verified['schema'] == 1)
        for key in fields:
            _require(type(verified[key]) is str and re.fullmatch('[a-f0-9]{64}', verified[key]))
        guard = record['binding'].get('executionGuard', {})
        _require(verified['sourceSha256'] == self._source and verified['manifestSha256'] == self._manifest
                 and guard.get('manifestSha256') == self._manifest and verified['variantSha256'] == guard.get('variantSha256'))
        if verified['checkpoint'] is not None:
            checkpoint = verified['checkpoint']
            _require(type(checkpoint) is dict and set(checkpoint) == {'artifactId', 'sha256', 'sizeBytes'})
            checkpoint = cast(dict, checkpoint)
            _require(type(checkpoint['artifactId']) is str and re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}', checkpoint['artifactId'])
                     and type(checkpoint['sha256']) is str and re.fullmatch('[a-f0-9]{64}', checkpoint['sha256'])
                     and type(checkpoint['sizeBytes']) is int and 0 < checkpoint['sizeBytes'] <= 2 * 1024**3
                     and type(verified['evaluationContractSha256']) is str
                     and re.fullmatch('[a-f0-9]{64}', verified['evaluationContractSha256']))
        else:
            _require(verified['evaluationContractSha256'] is None)
        _require(type(record.get('processPin')) is dict
                 and type(record['processPin'].get('identitySha256')) is str
                 and re.fullmatch('[a-f0-9]{64}', record['processPin']['identitySha256']))
        return {**deepcopy(verified), 'schema': 1, 'leaseBindingSha256': record['bindingHash'],
            'processIdentitySha256': record['processPin']['identitySha256'], 'executionVerified': False}

    def read_launch_proof(self, lease_id, owner):
        """Validate original completed-job proof without staging or dispatch."""
        proof = super().read_launch_proof(lease_id, owner)
        with self._transaction() as conn:
            record = self._load(conn, lease_id, owner)
        supplied = {key: value for key, value in proof.items() if key not in
            {'leaseBindingSha256', 'processIdentitySha256', 'executionVerified'}}
        _require(self._program_proof(record, supplied) == proof)
        return deepcopy(proof)

    def _before_release(self, record, snapshot):
        _require(snapshot.get('stoppedProof') is True and record.get('allStopped') is True)
        if record['stopKind'] == 'never-dispatched':
            _require((snapshot.get('stopReceipt') or {}).get('kind') == 'never-dispatched')
            observation = digest({'neverDispatched': True, 'processPin': record['processPin'],
                                  'stopReceipt': snapshot['stopReceipt'], 'binding': record['bindingHash']})
        else:
            observation = self._observe_device(record, snapshot, 'release')
        record['gpuReleaseObservationSha256'] = observation

    def _snapshot(self, record):
        result = super()._snapshot(record)
        proof = None
        if record['released']:
            observation = record.get('gpuReleaseObservationSha256')
            _require(type(observation) is str and re.fullmatch('[a-f0-9]{64}', observation))
            proof = {'kind': 'never-dispatched' if record['stopKind'] == 'never-dispatched' else
                     'original-process-stopped-and-device-released', 'processBindingFingerprint': record['bindingHash'],
                     'deviceObservationSha256': observation}
        result.update(gpuBinding=self.gpu_binding.to_dict(), gpuEvidence={'schema': 1,
            'bindingFingerprint': evidence_fingerprint(record['binding']),
            'state': 'RELEASED' if record['released'] else 'UNKNOWN' if record['state'] == 'UNKNOWN' else 'HELD',
            'releaseProof': proof})
        validate_gpu_evidence(record['binding'], result)
        return result
