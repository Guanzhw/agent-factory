"""Synthetic evaluator-shaped bytes cannot promote themselves to execution proof."""
from copy import deepcopy
import hashlib
import json
import unittest
from typing import Any

from agent_factory.research_evaluation import (evaluation_contract_fingerprint,
    validate_evaluation_contract, validate_evaluator_output)
from agent_factory.research_manifest import manifest_fingerprint
from test_research_manifest import example_manifest  # pyright: ignore[reportMissingImports]


def example_contract():
    def execution(prefix):
        return {'ownerId': 'alice', 'taskId': prefix + '-task', 'nativeRunId': prefix + '-run',
            'planId': prefix + '-plan', 'planFingerprint': 'a' * 64,
            'leaseId': prefix + '-lease', 'providerJobId': prefix + '-job'}
    return {'schema': 1, 'evidenceKind': 'offline_research_evaluation_contract',
        'comparisonManifest': example_manifest(),
        'training': {**execution('train'), 'variantSha256': 'b' * 64,
            'checkpoint': {'artifactId': 'checkpoint-artifact', 'sha256': 'c' * 64, 'sizeBytes': 100}},
        'evaluatorExecution': execution('evaluate')}


def output(contract, *, status='completed', value: Any = 1.25):
    return json.dumps({'schema': 1, 'evaluationContractSha256': evaluation_contract_fingerprint(contract),
        'status': status, 'metric': {'id': 'val_bpb', 'value': value}}, separators=(',', ':')).encode()


class ResearchEvaluationTests(unittest.TestCase):
    def test_owner_identity_supports_unicode_and_email_without_normalization(self):
        for owner in ('alice@example.test', '研究用户', 'e\u0301', '\u00e9', 'a' * 200):
            contract = example_contract()
            contract['training']['ownerId'] = contract['evaluatorExecution']['ownerId'] = owner
            self.assertEqual(validate_evaluation_contract(contract)['training']['ownerId'], owner)
            self.assertFalse(validate_evaluator_output(contract, output(contract))['executionVerified'])
        for owner in ('', 'a' * 201, 'user\n', 'user\t', '\x00user', 'user\x7f', True):
            contract = example_contract()
            contract['training']['ownerId'] = contract['evaluatorExecution']['ownerId'] = owner
            with self.assertRaises(ValueError):
                validate_evaluation_contract(contract)
        contract = example_contract()
        contract['training']['ownerId'] = 'e\u0301'
        contract['evaluatorExecution']['ownerId'] = '\u00e9'
        with self.assertRaises(ValueError):
            validate_evaluation_contract(contract)
        contract = example_contract()
        contract['training']['taskId'] = '任务'
        with self.assertRaises(ValueError):
            validate_evaluation_contract(contract)

    def test_valid_output_binds_manifest_variant_and_actual_bytes_but_is_untrusted(self):
        contract = example_contract()
        raw = output(contract)
        receipt = validate_evaluator_output(contract, raw)
        self.assertEqual(receipt['observation'], {'schema': 1, 'status': 'completed',
            'comparisonIdentitySha256': manifest_fingerprint(contract['comparisonManifest']),
            'variantSha256': contract['training']['variantSha256'], 'valBpb': 1.25})
        self.assertEqual(receipt['rawSha256'], hashlib.sha256(raw).hexdigest())
        self.assertIs(receipt['executionVerified'], False)
        self.assertIs(receipt['scientificConclusionVerified'], False)
        # Identical bytes in training stdout cannot be authenticated by a parser.
        self.assertEqual(validate_evaluator_output(contract, bytes(raw)), receipt)
        self.assertNotIn('custodyVerified', receipt)

    def test_contract_fingerprint_is_canonical_detached_and_changes_with_checkpoint(self):
        contract = example_contract()
        saved = deepcopy(contract)
        checked = validate_evaluation_contract(contract)
        expected = hashlib.sha256(json.dumps(contract, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()
        self.assertEqual(evaluation_contract_fingerprint(contract), expected)
        self.assertEqual(evaluation_contract_fingerprint(dict(reversed(list(contract.items())))), expected)
        checked['training']['checkpoint']['sha256'] = 'd' * 64
        self.assertEqual(contract, saved)
        self.assertNotEqual(evaluation_contract_fingerprint(checked), expected)
        with self.assertRaises(ValueError):
            validate_evaluator_output(checked, output(contract))

    def test_distinct_native_identities_and_common_owner_are_required(self):
        for field in ('taskId', 'nativeRunId', 'leaseId', 'providerJobId'):
            contract = example_contract()
            contract['evaluatorExecution'][field] = contract['training'][field]
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_evaluation_contract(contract)
        contract = example_contract()
        contract['evaluatorExecution']['ownerId'] = 'bob'
        with self.assertRaises(ValueError):
            validate_evaluation_contract(contract)
        for field in ('taskId', 'nativeRunId', 'planId', 'planFingerprint', 'leaseId', 'providerJobId'):
            original = example_contract()
            changed = deepcopy(original)
            changed['evaluatorExecution'][field] = 'd' * 64 if field == 'planFingerprint' else 'other-' + field
            with self.subTest(changed=field), self.assertRaises(ValueError):
                validate_evaluator_output(changed, output(original))

    def test_contract_missing_extra_invalid_types_and_checkpoint_bounds(self):
        original = example_contract()
        invalid = []
        for field in original:
            value = deepcopy(original); del value[field]; invalid.append(value)
        for path, replacement in [(('schema',), True), (('extra',), 1),
                (('training', 'checkpoint', 'sizeBytes'), True), (('training', 'checkpoint', 'sizeBytes'), 0),
                (('training', 'checkpoint', 'sizeBytes'), 1025), (('training', 'checkpoint', 'sha256'), 'bad'),
                (('training', 'variantSha256'), 'A' * 64), (('evaluatorExecution', 'taskId'), '../escape'),
                (('evaluatorExecution', 'taskId'), 'a' * 201), (('comparisonManifest', 'protocol', 'seed'), True)]:
            value = deepcopy(original); target = value
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = replacement; invalid.append(value)
        for value in invalid:
            with self.assertRaisesRegex(ValueError, '^RESEARCH_EVALUATION_INVALID$'):
                validate_evaluation_contract(value)

    def test_noncompleted_has_no_metric_and_zero_crash_sentinel_is_rejected(self):
        contract = example_contract()
        for status in ('failed', 'cancelled', 'unknown'):
            self.assertIsNone(validate_evaluator_output(contract, output(contract, status=status, value=None))['observation']['valBpb'])
            with self.assertRaises(ValueError):
                validate_evaluator_output(contract, output(contract, status=status, value=0))
        for value in (0, -1, True, None, '1.25', float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                validate_evaluator_output(contract, output(contract, value=value))

    def test_strict_json_duplicates_encoding_extra_fields_and_bounded_bytes(self):
        contract = example_contract()
        raw = output(contract)
        bad = [b'', b'\xff', raw + b'garbage', b'[]', b'null',
            raw.replace(b'"schema":1', b'"schema":1,"schema":1'),
            raw.replace(b'"value":1.25', b'"value":1.25,"value":0'),
            raw.replace(b'"schema":1', b'"schema":true'),
            raw.replace(b'"val_bpb"', b'"candidate_stdout_val_bpb"'),
            raw[:-1] + b',"executionVerified":true}', b' ' * 1025,
            raw.replace(b'1.25', b'1e9999')]
        for value in bad:
            with self.assertRaisesRegex(ValueError, '^RESEARCH_EVALUATION_INVALID$'):
                validate_evaluator_output(contract, value)
        with self.assertRaises(ValueError):
            validate_evaluator_output(contract, raw.decode())  # type: ignore[arg-type]


if __name__ == '__main__':
    unittest.main()
