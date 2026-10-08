"""Offline contract data only: no evaluator or candidate execution."""
from copy import deepcopy
import unittest

from agent_factory.comparison_contract import compare_observations, fingerprint, validate_candidate, validate_contract


def contract():
    return {'schema': 1, 'evidenceKind': 'offline_comparison_contract',
        'dataset': {'path': 'data/synthetic.json', 'sha256': 'a' * 64, 'origin': 'synthetic', 'license': 'MIT',
                    'sampleSetSha256': 'b' * 64, 'sampleCount': 7},
        'evaluator': {'path': 'evaluator.py', 'sha256': 'c' * 64, 'protocolRevision': 'mse-v1'},
        'baselineFiles': {'data/synthetic.json': 'a' * 64, 'evaluator.py': 'c' * 64, 'predict.py': 'd' * 64},
        'allowedChanges': ['predict.py'], 'metric': {'id': 'mse', 'unit': 'squared-error', 'direction': 'minimize', 'minimumImprovement': 0.1},
        'seed': 17, 'authority': {'planFingerprint': 'e' * 64, 'capabilities': ['compute:local'],
            'resourceLimits': {'cpu': 1, 'memoryMb': 128, 'wallSeconds': 5, 'outputBytes': 65536}},
        'materialRefs': [{'id': 'reviewed-evaluation', 'version': 1, 'sha256': 'f' * 64}]}


def candidate(value):
    return {'schema': 1, 'contractSha256': fingerprint(value), 'authoritySha256': fingerprint(value['authority']),
            'files': {**value['baselineFiles'], 'predict.py': '1' * 64}}


def observation(value, files, score):
    return {'schema': 1, 'contractSha256': fingerprint(value), 'variantSha256': fingerprint(files),
        'datasetSha256': value['dataset']['sha256'], 'evaluatorSha256': value['evaluator']['sha256'],
        'sampleSetSha256': value['dataset']['sampleSetSha256'], 'sampleCount': value['dataset']['sampleCount'],
        'seed': value['seed'], 'metricId': value['metric']['id'], 'unit': value['metric']['unit'],
        'status': 'completed', 'value': score, 'resultSha256': '2' * 64}


class ComparisonContractTests(unittest.TestCase):
    def test_descriptive_direction_threshold_and_no_execution_claim(self):
        for direction, first, second, status in [('minimize', 16, 0, 'improved'), ('maximize', 16, 0, 'regressed'),
                ('minimize', 1, 1.05, 'unchanged'), ('maximize', 0, 16, 'improved')]:
            value = contract()
            value['metric']['direction'] = direction
            proposed = candidate(value)
            assessment = compare_observations(value, proposed,
                observation(value, value['baselineFiles'], first), observation(value, proposed['files'], second))
            self.assertEqual(assessment['status'], status)
            self.assertFalse(assessment['executionVerified'])
            self.assertFalse(assessment['scientificConclusionVerified'])

    def test_all_noncompleted_states_remain_inconclusive_never_zero(self):
        value = contract()
        proposed = candidate(value)
        for side in ('baseline', 'candidate'):
            for state in ('unknown', 'failed', 'cancelled'):
                baseline = observation(value, value['baselineFiles'], 16)
                changed = observation(value, proposed['files'], 0)
                target = baseline if side == 'baseline' else changed
                target.update(status=state, value=None, sampleCount=0)
                result = compare_observations(value, proposed, baseline, changed)
                self.assertEqual(result['status'], 'inconclusive')
                self.assertIsNone(result['improvement'])
                self.assertIn(side.upper() + '_' + state.upper(), result['reasons'])
                target['value'] = 0
                with self.assertRaises(ValueError):
                    compare_observations(value, proposed, baseline, changed)

    def test_data_evaluator_sample_order_units_seed_and_scope_must_match(self):
        value = contract()
        proposed = candidate(value)
        baseline = observation(value, value['baselineFiles'], 16)
        changes = {'datasetSha256': '3' * 64, 'evaluatorSha256': '3' * 64,
            'sampleSetSha256': '3' * 64, 'seed': 18, 'sampleCount': 6, 'metricId': 'accuracy',
            'unit': 'seconds', 'variantSha256': '3' * 64, 'contractSha256': '3' * 64}
        for key, item in changes.items():
            other = observation(value, proposed['files'], 0)
            other[key] = item
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, '^COMPARISON_CONTRACT_INVALID$'):
                compare_observations(value, proposed, baseline, other)

    def test_candidate_cannot_add_delete_replace_protected_files_or_expand_authority(self):
        value = contract()
        for mutate in (lambda p: p['files'].update({'network.py': '4' * 64}),
                       lambda p: p['files'].pop('predict.py'),
                       lambda p: p['files'].update({'evaluator.py': '4' * 64}),
                       lambda p: p['files'].update({'data/synthetic.json': '4' * 64}),
                       lambda p: p.update(authoritySha256='4' * 64),
                       lambda p: p.update(credential='must-never-be-a-contract-field')):
            proposed = candidate(value)
            mutate(proposed)
            with self.assertRaises(ValueError):
                validate_candidate(value, proposed)

    def test_contract_refuses_unknown_fields_paths_permissions_and_nonfinite_numbers(self):
        mutations = [lambda v: v.update(command='python evaluator.py'),
            lambda v: v['dataset'].update(origin='private'),
            lambda v: v['evaluator'].update(path='../outside.py'),
            lambda v: v.update(allowedChanges=['evaluator.py']),
            lambda v: v['authority']['capabilities'].append('compute:local'),
            lambda v: v['authority']['resourceLimits'].update(cpu=True),
            lambda v: v['metric'].update(minimumImprovement=float('nan')),
            lambda v: v['dataset'].update(sampleCount=True)]
        for mutate in mutations:
            value = contract()
            mutate(value)
            with self.assertRaises(ValueError):
                validate_contract(value)
        value = contract()
        proposed = candidate(value)
        for score in (True, float('nan'), float('inf'), 10**13):
            with self.assertRaises(ValueError):
                compare_observations(value, proposed, observation(value, value['baselineFiles'], 16),
                    observation(value, proposed['files'], score))

    def test_validated_values_do_not_alias_and_changed_review_pins_invalidate_candidate(self):
        value = contract()
        proposed = candidate(value)
        checked = validate_contract(value)
        checked['baselineFiles']['predict.py'] = '9' * 64
        self.assertEqual(value['baselineFiles']['predict.py'], 'd' * 64)
        copied = validate_candidate(value, proposed)
        copied['files']['predict.py'] = '9' * 64
        self.assertEqual(proposed['files']['predict.py'], '1' * 64)
        altered = deepcopy(value)
        altered['materialRefs'][0]['version'] = 2
        with self.assertRaises(ValueError):
            validate_candidate(altered, proposed)


if __name__ == '__main__':
    unittest.main()
