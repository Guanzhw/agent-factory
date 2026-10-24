"""Static research ownership over installed, exact original runtime bindings.

These hooks carry behavior, not service lookup. Native core services select the
original owner before calling them. Member-published application ids are not an
installation/authorization gate, and shared core adapters are never claimed.
"""
from .control_compatibility import ResearchControlHooks
from .factory_compatibility import ResearchTaskProjection
from .lifecycle_compatibility import ResearchObservation
from .research_runtime_hooks import ResearchRuntimeHooks


# Exact implementation sources, not user input or an adapter-id prefix test.
# Dynamic scientific suffixes remain exact (kind, adapter_id, revision) keys
# from the already-installed trusted registrations.
_RESEARCH_FACTORIES = frozenset({
    'agent_factory_research.autoresearch_profile',
    'agent_factory_research.autoresearch_scientific_child',
    'agent_factory_research.comparison_profile',
    'agent_factory_research.literature_synthesis_profile',
    'agent_factory_research.local_literature_profile',
    'agent_factory_research.local_orx_profile',
    'agent_factory_research.managed_orx_profile',
    'agent_factory_research.orx_experiment_tools',
    'agent_factory_research.orx_literature_tools',
    'agent_factory_research.orx_tools',
    'agent_factory_research.personal_command_profile',
    'agent_factory_research.pubmed_profile',
    'agent_factory_research.remote_scientific_profile',
    'agent_factory_research.research_runtime_profile',
    'agent_factory_research.synthesis_runtime',
})
_LEGACY_APPLICATIONS = (
    'research', 'orx-local-toy', 'public-literature-evidence-v2',
    'public-literature-host-v1', 'public-literature-synthesis-fixture-v1',
    'source-grounded-synthesis-fixture-v1', 'controlled-comparison-fixture-v1',
    'autoresearch-goal-session-v1', 'research-process-fixture-v1',
    'personal-agent-command-v1',
)
_RESEARCH_SYNTHETIC_TOOLS = frozenset({
    ('tool', 'native-literature-v1', '1'),
    ('tool', 'native-experiment-v1', '1'),
})


def research_binding_keys(bindings):
    """Read the installed trusted records, never classify a request's id string."""
    return tuple(sorted(key for key, entry in bindings._adapters.items()
                        if key in _RESEARCH_SYNTHETIC_TOOLS
                        or getattr(entry.factory, '__module__', None) in _RESEARCH_FACTORIES))


class ResearchApplicationHooks:
    waiting_control = staticmethod(ResearchTaskProjection.waiting_control)
    project_detail = staticmethod(ResearchTaskProjection.project_detail)
    summary_status = staticmethod(ResearchObservation.summary_status)
    observe_waits = staticmethod(ResearchObservation.observe_waits)
    effect_held = staticmethod(ResearchRuntimeHooks.effect_held)
    ended_reason = staticmethod(ResearchRuntimeHooks.ended_reason)
    cancel = staticmethod(ResearchRuntimeHooks.cancel)
    completed_launch = staticmethod(ResearchControlHooks.completed_launch)
    external_result = staticmethod(ResearchControlHooks.external_result)
    claim_external_result = staticmethod(ResearchControlHooks.claim_external_result)

    @staticmethod
    def approval_payload(commands, task, snapshot, original):
        return ResearchControlHooks.approval_payload(task, snapshot, original)

    @staticmethod
    def mark_cancel(store, task_id):
        ResearchObservation.mark_cancel(store, task_id)


def register_research_runtime(store, *, hooks=None):
    """Install once; duplicate owners and selector claims fail at registration."""
    return store.application_runtime.register('research', hooks if hooks is not None else ResearchApplicationHooks(),
        bindings=research_binding_keys(store.execution_bindings), legacy_applications=_LEGACY_APPLICATIONS,
        effects=('orx-experiment-launch-v1', 'autoresearch-session-v1',
                 'research-process-run-v1', 'comparison-report-v1'))
