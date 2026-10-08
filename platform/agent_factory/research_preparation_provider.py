"""Preparation proof hooks on the original generic bounded process provider."""
from copy import deepcopy
import re

from .process_enforcement import ProcessLimits
from .process_provider import ProcessResourceProvider
from .store import digest


def _require(ok):
    if not ok:
        raise ValueError('PREPARATION_PROVIDER_INVALID')


class PreparationProvider(ProcessResourceProvider):
    def __init__(self, store, root, spec, limits, *, driver, **kwargs):
        _require(callable(driver) and callable(getattr(driver, 'validate_spec', None)))
        for value in (driver.configuration_fingerprint, driver.manifest_sha256):
            _require(type(value) is str and re.fullmatch('[a-f0-9]{64}', value))
        _require(type(limits) is ProcessLimits and limits.file_size_bytes == 65536)
        driver.validate_spec(spec)
        self.driver = driver
        self._source = driver.configuration_fingerprint
        self._manifest = driver.manifest_sha256
        super().__init__(store, root, spec, limits, **kwargs)

    @property
    def configuration_fingerprint(self):
        return digest({'base': super().configuration_fingerprint, 'revision': 'preparation-provider-v1',
                       'sourceSha256': self._source, 'manifestSha256': self._manifest})

    def _proof(self, record, proof):
        expected = {'schema': 1, 'evidenceKind': 'research-tokenizer-preparation-v1',
            'sourceSha256': self._source, 'manifestSha256': self._manifest, 'variantSha256': self._source,
            'leaseBindingSha256': digest(record['binding']),
            'processIdentitySha256': record['processPin']['identitySha256'], 'executionVerified': False}
        _require(type(proof) is dict and set(proof) == set(expected) | {'descriptorSha256'}
                 and type(proof['schema']) is int and proof['executionVerified'] is False
                 and all(proof[key] == value for key, value in expected.items())
                 and type(proof['descriptorSha256']) is str and re.fullmatch('[a-f0-9]{64}', proof['descriptorSha256']))
        return deepcopy(proof)

    def _before_launch(self, record, snapshot):
        _require(self.driver.configuration_fingerprint == self._source)
        self.driver.validate_spec(self.spec)
        proof = self._proof(record, self.driver(deepcopy(record)))
        _require(record.get('programVerification', proof) == proof)
        record['programVerification'] = proof

    def read_launch_proof(self, lease_id, owner):
        proof = super().read_launch_proof(lease_id, owner)
        with self._transaction() as conn:
            record = self._load(conn, lease_id, owner)
        return self._proof(record, proof)
