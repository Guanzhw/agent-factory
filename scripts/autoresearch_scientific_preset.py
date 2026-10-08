"""Operator wiring for a pinned scientific project, with no execution at import.

The standalone candidate CLI creates independent native tasks and is deliberately
not called here. A subordinate executor and an original-custody result verifier
must be installed by the control plane. This module supplies neither authority
inheritance nor evidence attestation merely because a callback returned True.
"""
import asyncio
import inspect
from copy import deepcopy
from dataclasses import dataclass
import hashlib
from typing import Any, Awaitable, Callable, cast

from agent_factory.autoresearch import ResearchPreset
from agent_factory.research_assessment import assess_observations
from agent_factory.research_manifest import manifest_fingerprint, validate_manifest
from agent_factory.research_profile import verify_upstream_source
from agent_factory.research_training_adapter import build_training_bundle
from agent_factory.autoresearch_candidate_patch import build_candidate, parameter_context

ERROR = 'AUTORESEARCH_SCIENTIFIC_PRESET_INVALID'


def require(value):
    if not value:
        raise ValueError(ERROR)


@dataclass(frozen=True)
class OperatorScientificConfig:
    id: str
    name: str
    owner_id: str
    default_goal: str
    manifest: dict
    limits: dict
    # Trusted readers must reopen and authenticate original custody on each call.
    # Neither arbitrary user paths nor baseline stdout are accepted as readers.
    upstream_reader: Callable
    baseline_reader: Callable
    microbatch: int = 1
    review_owner: str | None = None
    blockers: tuple[str, ...] = ()


def make_preset(config: OperatorScientificConfig, *, runtime_factory,
                subordinate_executor: Callable[..., Awaitable[dict]] | None = None,
                result_verifier: Callable[..., Awaitable[dict]] | None = None):
    """Return an inert ResearchPreset; absent execution integration is unavailable.

    subordinate_executor(ctx,candidate,call_id,*,parent_guard) is async. It must
    durably bind subordinate tasks to original parent scope, reserve shared
    budgets before dispatch, guard every child admission/provider boundary, and
    propagate parent cancellation through existing native lifecycle/controllers.
    Front/back guard calls here do not replace those requirements.

    result_verifier(ctx,result) is async and must read existing original task,
    plan, lease, checkpoint and evaluator custody; it returns the public result
    with originalReferences. It must not promote supplied booleans to proof.
    Neither callback may create a replacement after an unknown acknowledgement.
    """
    require(type(config) is OperatorScientificConfig and callable(config.upstream_reader)
            and callable(config.baseline_reader) and callable(runtime_factory))
    manifest = validate_manifest(config.manifest)
    fingerprint = manifest_fingerprint(manifest)

    def upstream():
        files = config.upstream_reader()
        verify_upstream_source(files)
        return dict(files)

    async def baseline():
        # Legacy synchronous custody readers may run their own event loop. Run
        # them offloop; genuinely async readers are awaited on the current loop.
        # No observation or acceptance is cached across context/experiment calls.
        observation = await asyncio.to_thread(config.baseline_reader)
        if inspect.isawaitable(observation):
            observation = await observation
        assess_observations(observation, observation)
        require(observation['status'] == 'completed'
                and observation['comparisonIdentitySha256'] == fingerprint
                and observation['variantSha256'] == manifest['baselineSourceManifestSha256'])
        return deepcopy(observation)

    async def context_reader():
        files = await asyncio.to_thread(upstream)
        return {'schema': 1, 'evidenceKind': 'approved-scientific-project-context',
            'programMd': files['program.md'].decode('utf-8'),
            'trainSha256': hashlib.sha256(files['train.py']).hexdigest(),
            'candidateParameters': parameter_context(files['train.py'], microbatch=config.microbatch),
            'baselineObservation': await baseline(), 'comparisonManifestSha256': fingerprint,
            'scientificConclusionVerified': False}

    def candidate_builder(changes):
        files = upstream()
        return build_candidate(files['train.py'], changes, microbatch=config.microbatch)

    def candidate_validator(train_py):
        require(type(train_py) is str and 0 < len(train_py) <= 4 * 1024**2)
        raw = train_py.encode('utf-8')
        require(len(raw) <= 4 * 1024**2)
        files = upstream()
        receipt = build_training_bundle(files, {**files, 'train.py': raw}, microbatch=config.microbatch)['receipt']
        return {'schema': 1, 'trainSha256': hashlib.sha256(raw).hexdigest(),
            'adaptation': receipt, 'executionVerified': False, 'scientificConclusionVerified': False}

    async def experiment(ctx, candidate, call_id):
        if not callable(subordinate_executor) or not callable(result_verifier):
            raise ValueError(ERROR)
        require(type(call_id) is str and 1 <= len(call_id) <= 200 and type(candidate) is dict
                and set(candidate) == {'hypothesis', 'trainPy', 'validated'})
        require(candidate_validator(candidate['trainPy']) == candidate['validated'])
        await baseline()  # Original baseline still has readable, verified custody.
        def parent_guard():
            preset = ctx.store.autoresearch.current(ctx)
            require(preset.id == config.id and preset.owner_id == config.owner_id)
        parent_guard()
        result = await subordinate_executor(ctx, deepcopy(candidate), call_id, parent_guard=parent_guard)
        parent_guard()
        verified = await result_verifier(ctx, result)
        parent_guard()
        require(type(verified) is dict and verified.get('cleanupConfirmed') is True
                and verified.get('independentResult') is True
                and verified.get('scientificConclusionVerified') is False)
        references = verified.get('originalReferences')
        require(type(references) is dict and set(references) == {'training', 'evaluation', 'checkpoint'})
        references = cast(dict[str, Any], references)
        for phase in ('training', 'evaluation'):
            ref = references[phase]
            require(type(ref) is dict and set(ref) == {'taskId', 'nativeRunId', 'planId', 'leaseId', 'providerJobId'}
                    and all(type(v) is str and 0 < len(v) <= 200 for v in ref.values()))
        require(all(references['training'][key] != references['evaluation'][key]
                    for key in ('taskId', 'nativeRunId', 'leaseId', 'providerJobId')))
        checkpoint = references['checkpoint']
        require(type(checkpoint) is dict and set(checkpoint) == {'artifactId', 'sha256'}
                and type(checkpoint['artifactId']) is str and 0 < len(checkpoint['artifactId']) <= 200
                and type(checkpoint['sha256']) is str and len(checkpoint['sha256']) == 64
                and all(c in '0123456789abcdef' for c in checkpoint['sha256']))
        return deepcopy(verified)

    blockers = list(config.blockers)
    if not callable(subordinate_executor) or not callable(result_verifier):
        blockers.append('受管子实验的父任务权限、共享预算和原始评估凭据尚未接通。')
    return ResearchPreset(id=config.id, name=config.name, default_goal=config.default_goal,
        owner_id=config.owner_id, instructions='Read research_context before proposing an eleven-literal-only candidate.',
        manifest=manifest, limits=deepcopy(config.limits), runtime_factory=runtime_factory,
        context_reader=context_reader, candidate_validator=candidate_validator, candidate_builder=candidate_builder, experiment=experiment,
        review_owner=config.review_owner, blockers=tuple(blockers), external_session=True)
