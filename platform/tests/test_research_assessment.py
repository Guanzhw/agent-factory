"""Pure supplied-record assessment: no provider, process, database or repository mutation."""
from copy import deepcopy
import hashlib
import json
import math
import unittest
from typing import Any

from agent_factory.research_assessment import assess_observations


def observation(value: Any = 1.5, *, status='completed', identity='a' * 64, variant='b' * 64):
    return {'schema': 1, 'status': status, 'comparisonIdentitySha256': identity,
        'variantSha256': variant, 'valBpb': value}


class ResearchAssessmentTests(unittest.TestCase):
    def test_same_identity_lower_only_recommends_keep(self):
        for value, expected, delta in ((1.0, 'recommend_keep', -.5),
                (1.5, 'recommend_rollback', 0), (2, 'recommend_rollback', .5)):
            with self.subTest(value=value):
                result = assess_observations(observation(), observation(value, variant='c' * 64))
                self.assertEqual(result['recommendation'], expected)
                self.assertEqual(result['deltaValBpb'], delta)
                self.assertEqual(result['reasons'], [])
                self.assertIs(result['advisoryOnly'], True)
                self.assertIs(result['executionVerified'], False)
                self.assertIs(result['scientificConclusionVerified'], False)

    def test_identity_mismatch_is_not_an_improvement(self):
        result = assess_observations(observation(9), observation(1, identity='d' * 64))
        self.assertEqual(result['recommendation'], 'inconclusive')
        self.assertIsNone(result['deltaValBpb'])
        self.assertEqual(result['reasons'], ['COMPARISON_IDENTITY_MISMATCH'])

    def test_all_incomplete_states_and_both_sides_are_inconclusive(self):
        for side in ('baseline', 'candidate'):
            for status in ('failed', 'cancelled', 'unknown'):
                with self.subTest(side=side, status=status):
                    inputs = {'baseline': observation(4), 'candidate': observation(1)}
                    inputs[side] = observation(None, status=status)
                    result = assess_observations(**inputs)
                    self.assertEqual(result['recommendation'], 'inconclusive')
                    self.assertEqual(result['reasons'], [side.upper() + '_' + status.upper()])
                    self.assertIsNone(result['deltaValBpb'])
        result = assess_observations(observation(None, status='unknown'),
            observation(None, status='failed', identity='c' * 64))
        self.assertEqual(result['reasons'], ['BASELINE_UNKNOWN', 'CANDIDATE_FAILED', 'COMPARISON_IDENTITY_MISMATCH'])

    def test_zero_crash_sentinel_and_invalid_metrics_are_rejected(self):
        for metric in (0, -0.0, -1, None, True, False, math.nan, math.inf, -math.inf,
                '1.0', [], {}, 10**400):
            for side in (0, 1):
                with self.subTest(metric_type=type(metric).__name__, side=side):
                    inputs = [observation(), observation()]
                    inputs[side]['valBpb'] = metric
                    with self.assertRaisesRegex(ValueError, '^RESEARCH_OBSERVATION_INVALID$'):
                        assess_observations(*inputs)
        for status in ('failed', 'cancelled', 'unknown'):
            for metric in (0, 1, math.nan, False):
                with self.subTest(status=status, metric=metric):
                    with self.assertRaises(ValueError):
                        assess_observations(observation(), observation(metric, status=status))

    def test_exact_schema_types_and_digest_shapes_required(self):
        bad = []
        for key in observation():
            value = observation()
            del value[key]
            bad.append(value)
        for changes in ({'schema': True}, {'schema': 1.0}, {'schema': 2}, {'status': []},
                {'status': 'COMPLETED'}, {'status': None}, {'extra': 'untrusted'},
                {'comparisonIdentitySha256': 'A' * 64}, {'comparisonIdentitySha256': 'a' * 63},
                {'variantSha256': 'g' * 64}, {'variantSha256': 1}, {'variantSha256': 'b' * 64 + '\n'}):
            bad.append({**observation(), **changes})
        bad.extend((None, [], 'untrusted observation'))
        for value in bad:
            with self.subTest(value_type=type(value).__name__):
                with self.assertRaisesRegex(ValueError, '^RESEARCH_OBSERVATION_INVALID$'):
                    assess_observations(observation(), value)

    def test_fingerprints_bind_actual_records_and_are_order_independent(self):
        baseline, candidate = observation(), observation(1, variant='c' * 64)
        saved = deepcopy((baseline, candidate))
        result = assess_observations(baseline, candidate)
        for side, value in (('baseline', baseline), ('candidate', candidate)):
            expected = hashlib.sha256(json.dumps(value, sort_keys=True,
                separators=(',', ':'), allow_nan=False).encode()).hexdigest()
            self.assertEqual(result[side + 'ObservationSha256'], expected)
        reversed_keys = dict(reversed(list(candidate.items())))
        self.assertEqual(assess_observations(baseline, reversed_keys), result)
        self.assertEqual((baseline, candidate), saved)
        candidate['valBpb'] = 2
        changed = assess_observations(baseline, candidate)
        self.assertNotEqual(changed['candidateObservationSha256'], result['candidateObservationSha256'])
        self.assertEqual(changed['recommendation'], 'recommend_rollback')
        candidate['variantSha256'] = 'd' * 64
        self.assertNotEqual(assess_observations(baseline, candidate)['candidateObservationSha256'],
            changed['candidateObservationSha256'])
        self.assertIs(changed['executionVerified'], False, 'A new digest is not authenticity proof')

    def test_plain_primitives_only_and_small_positive_metric_is_valid(self):
        class IntLike(int):
            pass
        class DictLike(dict):
            pass
        for value in (DictLike(observation()), observation(IntLike(1))):
            with self.assertRaises(ValueError):
                assess_observations(observation(), value)
        result = assess_observations(observation(1), observation(5e-324))
        self.assertEqual(result['recommendation'], 'recommend_keep')
        self.assertTrue(math.isfinite(result['deltaValBpb']))

    def test_mixed_integer_float_boundary_does_not_round_away_improvement(self):
        result = assess_observations(observation(2**53 + 1), observation(float(2**53)))
        self.assertEqual(result['recommendation'], 'recommend_keep')
        self.assertEqual(result['deltaValBpb'], -1)


if __name__ == '__main__':
    unittest.main()
