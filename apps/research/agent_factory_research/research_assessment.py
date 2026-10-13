"""Offline val_bpb advice from supplied observations, never execution proof.

Fingerprints bind the supplied records, not their truth or external provenance.
This module performs no I/O and cannot publish, execute, keep, or roll back code.
"""
import hashlib
from fractions import Fraction
import json
import math
import re
from typing import Any


_ERROR = 'RESEARCH_OBSERVATION_INVALID'
_FIELDS = frozenset({'schema', 'status', 'comparisonIdentitySha256', 'variantSha256', 'valBpb'})
_STATUSES = frozenset({'completed', 'failed', 'cancelled', 'unknown'})


def _observation(value: Any) -> dict[str, Any]:
    if type(value) is not dict or any(type(key) is not str for key in value) or set(value) != _FIELDS:
        raise ValueError(_ERROR)
    if type(value['schema']) is not int or value['schema'] != 1:
        raise ValueError(_ERROR)
    status = value['status']
    if type(status) is not str or status not in _STATUSES:
        raise ValueError(_ERROR)
    for name in ('comparisonIdentitySha256', 'variantSha256'):
        fingerprint = value[name]
        if type(fingerprint) is not str or re.fullmatch(r'[a-f0-9]{64}', fingerprint) is None:
            raise ValueError(_ERROR)
    metric = value['valBpb']
    if status == 'completed':
        try:
            valid = type(metric) in {int, float} and math.isfinite(metric) and metric > 0
        except (OverflowError, ValueError):
            valid = False
        if not valid:
            raise ValueError(_ERROR)
    elif metric is not None:
        raise ValueError(_ERROR)
    # Only validated immutable primitive values enter the receipt's digest.
    return dict(value)


def _fingerprint(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def assess_observations(baseline: Any, candidate: Any) -> dict[str, Any]:
    """Recommend lower positive val_bpb only within the same comparison identity.

    Invalid observations raise a fixed ValueError. Valid incomplete or mismatched
    observations are inconclusive. A tie recommends rollback. ``deltaValBpb`` is
    candidate minus baseline; negative means lower. No recommendation is an
    authorization, scientific conclusion, execution attestation, or mutation.
    """
    original, proposed = _observation(baseline), _observation(candidate)
    reasons = [side.upper() + '_' + observation['status'].upper()
        for side, observation in (('baseline', original), ('candidate', proposed))
        if observation['status'] != 'completed']
    if original['comparisonIdentitySha256'] != proposed['comparisonIdentitySha256']:
        reasons.append('COMPARISON_IDENTITY_MISMATCH')
    delta = None
    recommendation = 'inconclusive'
    if not reasons:
        before, after = original['valBpb'], proposed['valBpb']
        # Preserve integer/float boundary differences instead of rounding the
        # integer to a float before subtraction (e.g. 2**53+1 versus 2**53.0).
        difference = Fraction(after) - Fraction(before)
        delta = difference.numerator if difference.denominator == 1 else float(difference)
        recommendation = 'recommend_keep' if after < before else 'recommend_rollback'
    return {
        'schema': 1,
        'evidenceKind': 'offline_research_assessment',
        'recommendation': recommendation,
        'baselineObservationSha256': _fingerprint(original),
        'candidateObservationSha256': _fingerprint(proposed),
        'deltaValBpb': delta,
        'reasons': reasons,
        'advisoryOnly': True,
        'executionVerified': False,
        'scientificConclusionVerified': False,
    }
