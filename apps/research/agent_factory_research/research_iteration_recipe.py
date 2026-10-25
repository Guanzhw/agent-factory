"""Two reviewed toy byte sets; activity custody chooses promotion outside here.

The promoted baseline is the packaged candidate's exact bytes, never a supplied
path or source string. A matching hash alone does not authorize promotion: the
activity must first verify its previous source artifact and evaluation proof.
"""
from dataclasses import replace
import math

from .openresearch import OpenResearchError

from .orx_local import TaskLocalORXAdapter, TaskLocalORXProvider, _LEGACY_RECIPE

RECIPE_REVISION = '1'
SEED_IDENTITY = 'local-orx-toy-iterations-v1:seed'
PROMOTED_IDENTITY = 'local-orx-toy-iterations-v1:promoted'
PROMOTED_SOURCE_COMMIT = 'af497aa4d4e9c044af09401d1a2ff046453a108d'
PROMOTED_ARCHIVE_SHA256 = '4a48d26ce7fd7e95ae101ac44e64364b7ff54d3b282dc6d39441e3aac2ac8e17'
CANDIDATE_SHA256 = dict(_LEGACY_RECIPE.hashes)['candidate.py']


class IterationSeedORXAdapter(TaskLocalORXAdapter):
    transport_kind = 'pinned_openresearch_cli_local_toy_iterations_v1'
    _recipe = replace(_LEGACY_RECIPE, identity=SEED_IDENTITY)

    def evaluation_result(self):
        value = super().evaluation_result()
        if value is not None:
            scores = (value['baseline']['value'], value['candidate']['value'], value.get('improvement'))
            if (value.get('metric') != 'mean_squared_error'
                    or any(not isinstance(score, (int, float)) or isinstance(score, bool) or not math.isfinite(score) for score in scores)
                    or scores[2] != scores[0] - scores[1]):
                raise OpenResearchError('INVALID_OUTPUT', 'Iteration metric or improvement changed')
        return value


class IterationPromotedORXAdapter(IterationSeedORXAdapter):
    _recipe = replace(_LEGACY_RECIPE, identity=PROMOTED_IDENTITY,
        sources=tuple((name, 'candidate.py' if name == 'baseline.py' else source)
                      for name, source in _LEGACY_RECIPE.sources),
        hashes=tuple((name, CANDIDATE_SHA256 if name == 'baseline.py' else sha)
                     for name, sha in _LEGACY_RECIPE.hashes),
        commit=PROMOTED_SOURCE_COMMIT, archive_sha256=PROMOTED_ARCHIVE_SHA256, baseline_mse=0.0)


class IterationORXProvider(TaskLocalORXProvider):
    """Trusted activity assembly selects one fixed recipe; no user source input."""
    revision = RECIPE_REVISION

    def __init__(self, *, recipe, **kwargs):
        if recipe not in ('seed', 'promoted'):
            raise ValueError('RESEARCH_ITERATION_RECIPE_INVALID')
        self.adapter_type = IterationSeedORXAdapter if recipe == 'seed' else IterationPromotedORXAdapter
        super().__init__(**kwargs)
