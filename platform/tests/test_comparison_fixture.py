"""Pure fixed-evaluator contracts; these tests never start or execute a process."""
import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import unittest
from typing import Any, cast

from agent_factory.comparison_contract import fingerprint
from agent_factory.comparison_fixture import (CHOICES, REVISION, fixture_candidate, fixture_contract,
    fixture_limits, fixture_spec, input_manifest, validate_output)


def record(choice):
    manifest = input_manifest(choice)
    return {'schema': 1, 'fixtureRevision': REVISION, 'choice': choice,
        'datasetSha256': manifest['dataset']['sha256'], 'evaluatorSha256': manifest['evaluator']['sha256'],
        'sampleSetSha256': manifest['dataset']['sampleSetSha256'], 'sampleCount': 7, 'seed': 0,
        'metricId': 'mean_squared_error', 'unit': 'squared-target-units',
        'baseline': {'status': 'completed', 'value': 16.0, 'variantSha256': fingerprint(manifest['baselineFiles'])},
        'candidate': {'status': 'failed' if choice == 'failure-v1' else 'completed',
            'value': {'linear-v1': 0.0, 'constant-v1': 16.0, 'offset-v1': 25.0,
                      'failure-v1': None, 'long-running-v1': 0.0}[choice],
            'variantSha256': fingerprint(manifest['candidateFiles'])}}


class ComparisonFixtureTests(unittest.TestCase):
    def setUp(self):
        self.contract = fixture_contract('a' * 64, [{'id': 'reviewed-fixture', 'version': 1, 'sha256': 'b' * 64}])

    def test_all_reviewed_choices_recompute_expected_scores_without_execution_claim(self):
        expected = {'linear-v1': 'improved', 'constant-v1': 'unchanged', 'offset-v1': 'regressed',
                    'failure-v1': 'inconclusive', 'long-running-v1': 'improved'}
        for choice in CHOICES:
            raw = json.dumps(record(choice)).encode()
            result = validate_output(raw, self.contract, fixture_candidate(self.contract, choice), choice)
            self.assertEqual(result['assessment']['status'], expected[choice])
            self.assertFalse(result['assessment']['executionVerified'])
            self.assertFalse(result['assessment']['scientificConclusionVerified'])
            self.assertEqual(result['baseline']['resultSha256'], hashlib.sha256(raw).hexdigest())
            if choice == 'failure-v1':
                self.assertEqual(result['baseline']['status'], 'completed')
                self.assertEqual(result['candidate']['status'], 'failed')
                self.assertIsNone(result['candidate']['value'])
                self.assertIsNone(result['assessment']['improvement'])

    def test_fixed_spec_pins_source_and_choice_and_remains_within_argv_limit(self):
        for choice in CHOICES:
            spec = fixture_spec(str(Path('synthetic-python').absolute()), 'c' * 64, choice)
            self.assertEqual(spec.argv[:3], ('-I', '-S', '-c'))
            source = spec.argv[3]
            self.assertEqual(spec.argv[4], choice)
            self.assertEqual(spec.argv[5], source)
            self.assertEqual(hashlib.sha256(source.encode()).hexdigest(), input_manifest(choice)['evaluator']['sha256'])
            self.assertLessEqual(len(json.dumps(spec.argv).encode()), 8192)
            tree = ast.parse(source)  # Syntax/closed import surface only; no exec.
            terminal = tree.body[-1]
            self.assertIsInstance(terminal, ast.Raise)
            assert isinstance(terminal, ast.Raise) and isinstance(terminal.exc, ast.Call)
            self.assertEqual(ast.literal_eval(terminal.exc.args[0]), 0)
            imports = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
            self.assertEqual(imports, {'hashlib', 'json', 'sys', 'time'})
            self.assertFalse(any(isinstance(node, ast.ImportFrom) for node in ast.walk(tree)))
            self.assertFalse(any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id in {'exec', 'eval', 'open', '__import__'} for node in ast.walk(tree)))
        limits = fixture_limits()
        self.assertEqual((limits.cpu_seconds, limits.address_space_mb, limits.wall_seconds, limits.file_size_bytes), (1, 128, 5, 16384))

    def test_manifest_exact_schema_fixed_data_and_only_predictor_change(self):
        for choice in CHOICES:
            manifest = input_manifest(choice)
            self.assertEqual(set(manifest), {'schema', 'evidenceKind', 'choice', 'dataset', 'evaluator',
                'baselineFiles', 'allowedChanges', 'candidateFiles', 'metric', 'seed', 'resourceLimits'})
            self.assertEqual(manifest['evidenceKind'], 'synthetic_comparison_input')
            changed = {path for path in manifest['baselineFiles'] if manifest['baselineFiles'][path] != manifest['candidateFiles'][path]}
            self.assertLessEqual(changed, {'predictor.json'})
            self.assertEqual(manifest['dataset']['origin'], 'synthetic')
            self.assertEqual(manifest['resourceLimits'], self.contract['authority']['resourceLimits'])
        first = input_manifest('linear-v1')
        first['dataset']['sha256'] = 'd' * 64
        self.assertNotEqual(first, input_manifest('linear-v1'))

    def test_arbitrary_choice_and_modified_fixture_contract_rejected(self):
        for choice in ('../../outside', 'custom-provider', '', None):
            with self.assertRaises(ValueError):
                input_manifest(choice)
        for mutate in (lambda c: c['metric'].update(direction='maximize'),
                       lambda c: c.update(seed=1),
                       lambda c: c['authority']['resourceLimits'].update(wallSeconds=1)):
            modified = deepcopy(self.contract)
            mutate(modified)
            with self.assertRaises(ValueError):
                fixture_candidate(modified, 'linear-v1')
        wrong = fixture_candidate(self.contract, 'offset-v1')
        with self.assertRaises(ValueError):
            validate_output(json.dumps(record('linear-v1')).encode(), self.contract, wrong, 'linear-v1')

    def test_untrusted_output_cannot_change_hashes_scores_status_or_sample_set(self):
        proposed = fixture_candidate(self.contract, 'linear-v1')
        mutations = [lambda row: row.update(evaluatorSha256='d' * 64),
            lambda row: row.update(datasetSha256='d' * 64), lambda row: row.update(sampleSetSha256='d' * 64),
            lambda row: row.update(choice='constant-v1'), lambda row: row.update(sampleCount=6),
            lambda row: row.update(schema=True), lambda row: row.update(extra='injected'),
            lambda row: row['candidate'].update(value=-100.0), lambda row: row['baseline'].update(value=0.0),
            lambda row: row['candidate'].update(status='failed'), lambda row: row['candidate'].update(value=True),
            lambda row: row['candidate'].update(value=float('nan'))]
        for mutate in mutations:
            value = record('linear-v1')
            mutate(value)
            with self.assertRaisesRegex(ValueError, '^COMPARISON_FIXTURE_INVALID$'):
                validate_output(json.dumps(value).encode(), self.contract, proposed, 'linear-v1')

    def test_partial_duplicate_missing_and_oversized_output_are_not_results(self):
        proposed = fixture_candidate(self.contract, 'linear-v1')
        raw = json.dumps(record('linear-v1')).encode()
        for value in (b'', raw[:-1], raw + raw, b' ' * 16385, b'\xff', b'[' * 2000 + b']' * 2000,
                      b'{"schema":1,' + raw[1:], raw.decode()):
            with self.assertRaises(ValueError):
                validate_output(cast(Any, value), self.contract, proposed, 'linear-v1')


if __name__ == '__main__':
    unittest.main()
