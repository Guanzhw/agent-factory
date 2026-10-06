"""Pure synthetic protocol identity tests; no paths, devices or upstream imports."""
from copy import deepcopy
import hashlib
import json
import unittest
from unittest.mock import patch

from agent_factory import research_manifest as subject
from agent_factory.research_profile import SOURCE_SHA256, source_profile


def example_manifest():
    artifact = subject.artifact_identity(b'synthetic fixture only')
    profile_hash = hashlib.sha256(json.dumps(source_profile(), sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')).hexdigest()
    return {'schema': 1, 'evidenceKind': 'offline_research_experiment_manifest',
        'sourceProfileSha256': profile_hash, 'baselineSourceManifestSha256': '1' * 64,
        'protocol': {'revision': 'autoresearch-reviewed-v1', 'trainingBudgetSeconds': 300,
            'totalWallSeconds': 600, 'seed': 0, 'evaluationBudgetTokens': 20971520, 'sequenceLength': 2048},
        'dataset': {'revision': 'synthetic-data-v1', 'shards': [
            {'id': 'train-0', **artifact}, {'id': 'validation-0', **artifact}],
            'validationShardIds': ['validation-0'], 'sampleSetSha256': '2' * 64},
        'tokenizer': {'tokenizer': deepcopy(artifact), 'tokenBytes': deepcopy(artifact)},
        'environment': {'lockfileSha256': SOURCE_SHA256['uv.lock'],
            'installedInventory': deepcopy(artifact), 'runtimeKernel': deepcopy(artifact)},
        'device': {'identitySha256': '3' * 64, 'deviceCount': 1},
        'evaluator': {'code': deepcopy(artifact), 'configuration': deepcopy(artifact), 'metric': 'val_bpb', 'direction': 'minimize'},
        'initialCheckpoint': None,
        'artifactLimits': {'checkpointBytes': 1024, 'logBytes': 1024, 'resultBytes': 1024}}


class ResearchManifestTests(unittest.TestCase):
    def invalid(self, value):
        with self.assertRaisesRegex(ValueError, '^RESEARCH_MANIFEST_INVALID$'):
            subject.validate_manifest(value)

    def test_canonical_fingerprint_and_detached_data(self):
        value = example_manifest()
        checked = subject.validate_manifest(value)
        expected = hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')).hexdigest()
        self.assertEqual(subject.manifest_fingerprint(value), expected)
        self.assertTrue(subject.same_comparison_identity(value, dict(reversed(list(value.items())))))
        checked['dataset']['shards'][0]['sha256'] = '4' * 64
        self.assertNotEqual(checked, value)
        self.assertEqual(subject.manifest_fingerprint(value), expected)

    def test_every_mutable_identity_dimension_changes_comparison(self):
        value = example_manifest()
        for path, replacement in [
            (('baselineSourceManifestSha256',), '4' * 64), (('protocol', 'revision'), 'v2'),
            (('protocol', 'totalWallSeconds'), 601), (('protocol', 'seed'), 1),
            (('dataset', 'revision'), 'data-v2'), (('dataset', 'sampleSetSha256'), '4' * 64),
            (('tokenizer', 'tokenizer', 'sha256'), '4' * 64), (('tokenizer', 'tokenBytes', 'sha256'), '4' * 64),
            (('environment', 'installedInventory', 'sha256'), '4' * 64),
            (('environment', 'runtimeKernel', 'sha256'), '4' * 64), (('device', 'identitySha256'), '4' * 64),
            (('evaluator', 'code', 'sha256'), '4' * 64), (('evaluator', 'configuration', 'sha256'), '4' * 64),
            (('initialCheckpoint',), subject.artifact_identity(b'initial')),
            (('artifactLimits', 'resultBytes'), 1025),
        ]:
            changed = deepcopy(value)
            target = changed
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = replacement
            with self.subTest(path=path):
                self.assertFalse(subject.same_comparison_identity(value, changed))
        reordered = deepcopy(value)
        reordered['dataset']['shards'].reverse()
        self.assertFalse(subject.same_comparison_identity(value, reordered))
        changed = deepcopy(value)
        changed['dataset']['shards'][0]['sha256'] = '4' * 64
        self.assertFalse(subject.same_comparison_identity(value, changed))

    def test_pinned_protocol_and_unknown_fields_cannot_be_redefined(self):
        for path, replacement in [
            (('schema',), True), (('sourceProfileSha256',), '0' * 64),
            (('protocol', 'trainingBudgetSeconds'), 301), (('protocol', 'totalWallSeconds'), 300),
            (('protocol', 'evaluationBudgetTokens'), 1), (('protocol', 'sequenceLength'), 1024),
            (('environment', 'lockfileSha256'), '0' * 64), (('device', 'deviceCount'), 2),
            (('evaluator', 'metric'), 'loss'), (('evaluator', 'direction'), 'maximize'),
            (('dataset', 'revision'), '../data'), (('device', 'identitySha256'), 'hostname'),
        ]:
            value = example_manifest()
            target = value
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = replacement
            self.invalid(value)
        for name in ('candidateSourceSha256', 'outputCheckpoint', 'executionVerified', 'path'):
            self.invalid(example_manifest() | {name: 'untrusted'})
        for key in example_manifest():
            value = example_manifest()
            del value[key]
            self.invalid(value)

    def test_shard_membership_uniqueness_and_bounds(self):
        for ids in ([], ['missing'], ['validation-0', 'validation-0'], [True], 'validation-0'):
            value = example_manifest()
            value['dataset']['validationShardIds'] = ids
            self.invalid(value)
        for shards in ([], [True], [{'id': 'x', 'sha256': '0' * 64, 'sizeBytes': True}],
                       [{'id': 'x', 'sha256': '0' * 64, 'sizeBytes': 0}]):
            value = example_manifest()
            value['dataset']['shards'] = shards
            self.invalid(value)
        value = example_manifest()
        value['dataset']['shards'] *= 2
        self.invalid(value)
        value = example_manifest()
        value['dataset']['shards'] = [{'id': f's{i}', 'sha256': '0' * 64, 'sizeBytes': 2**40} for i in range(16)]
        value['dataset']['validationShardIds'] = ['s0']
        subject.validate_manifest(value)
        value['dataset']['shards'].append({'id': 'overflow', 'sha256': '0' * 64, 'sizeBytes': 1})
        self.invalid(value)
        value['dataset']['shards'] = [{'id': f's{i}', 'sha256': '0' * 64, 'sizeBytes': 1} for i in range(1024)]
        subject.validate_manifest(value)
        value['dataset']['shards'].append({'id': 'overflow', 'sha256': '0' * 64, 'sizeBytes': 1})
        self.invalid(value)

    def test_artifact_and_exact_type_limits(self):
        for value in (None, True, [], {'schema': 1}):
            self.invalid(value)
        for field, maximum in (('checkpointBytes', 2**40), ('logBytes', 64 * 1024**2), ('resultBytes', 1024**2)):
            for bad in (True, 0, maximum + 1, 1.0, '1'):
                value = example_manifest()
                value['artifactLimits'][field] = bad
                self.invalid(value)
        for size in (True, -1, 2**40 + 1):
            value = example_manifest()
            value['tokenizer']['tokenizer']['sizeBytes'] = size
            self.invalid(value)
        value = example_manifest()
        value['initialCheckpoint'] = {'sha256': '0' * 64, 'sizeBytes': 1025}
        self.invalid(value)
        value['initialCheckpoint']['sizeBytes'] = 1024
        subject.validate_manifest(value)
        for raw in (True, '', bytearray(b'x'), memoryview(b'x')):
            with self.assertRaisesRegex(ValueError, '^RESEARCH_MANIFEST_INVALID$'):
                subject.artifact_identity(raw)  # pyright: ignore[reportArgumentType]
        with patch.object(subject, 'MAX_INLINE_BYTES', 2):
            self.assertEqual(subject.artifact_identity(b'xx')['sha256'], hashlib.sha256(b'xx').hexdigest())
            with self.assertRaises(ValueError):
                subject.artifact_identity(b'xxx')


if __name__ == '__main__':
    unittest.main()
