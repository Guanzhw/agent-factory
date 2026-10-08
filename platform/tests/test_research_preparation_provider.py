"""Pure proof hook validation, without process or GPU execution."""
from copy import deepcopy
import unittest
from unittest.mock import Mock

from agent_factory.research_preparation_provider import PreparationProvider
from agent_factory.store import digest


class PreparationProviderTests(unittest.TestCase):
    def test_strict_original_proof_and_reentry(self):
        provider = object.__new__(PreparationProvider)
        provider._source = 'a'*64; provider._manifest = 'b'*64
        provider.spec = Mock(); provider.driver = Mock()
        provider.driver.configuration_fingerprint = provider._source
        record = {'binding': {'id': 'lease'}, 'processPin': {'identitySha256': 'c'*64}}
        proof = {'schema': 1, 'evidenceKind': 'research-tokenizer-preparation-v1',
            'sourceSha256': 'a'*64, 'manifestSha256': 'b'*64, 'variantSha256': 'a'*64,
            'leaseBindingSha256': digest(record['binding']), 'processIdentitySha256': 'c'*64,
            'descriptorSha256': 'd'*64, 'executionVerified': False}
        provider.driver.return_value = proof
        provider._before_launch(record, {})
        provider._before_launch(record, {})
        self.assertEqual(record['programVerification'], proof)
        for field, value in [('schema', True), ('executionVerified', True), ('sourceSha256', 'e'*64),
                             ('leaseBindingSha256', 'e'*64), ('processIdentitySha256', 'e'*64),
                             ('descriptorSha256', 'invalid')]:
            changed = deepcopy(proof); changed[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                provider._proof(record, changed)
        provider.driver.return_value = {**proof, 'descriptorSha256': 'e'*64}
        with self.assertRaises(ValueError):
            provider._before_launch(record, {})
