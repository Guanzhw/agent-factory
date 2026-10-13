"""Frozen synthetic research catalog and application definitions."""
from agent_factory.applications import ApplicationService
from agent_factory.application_schema import ApplicationDefinition, ApplicationDefinitionV2, ModeDefinition, ModeDefinitionV2
from agent_factory.material_governance import PinnedRef

SEEDS = [
    ("research-skill", "skill", "Evidence-led investigation", "Define a question, compare evidence, record provenance and uncertainty.", []),
    ("research-prompt", "prompt", "Auto-Research", "Investigate the user's bounded question. Label synthetic fixtures. Report evaluator and evidence provenance, never claim a real scientific result.", []),
    ("synthetic-knowledge", "knowledge", "Synthetic research corpus", "Two invented candidates; baseline=10 and candidate=8. Lower is better. This is a fixture, not literature.", []),
    ("literature-tool", "tool", "Literature fixture adapter", "literature_search", ["research:read"]),
    ("experiment-tool", "tool", "Bounded experiment", "run_experiment", ["experiment:synthetic"]),
    ("question-tool", "tool", "Clarify research scope", "ask_scope", ["question:ask"]),
    ("checksum-tool", "tool", "Checksum", "checksum", ["checksum:read"]),
    ("demo-model", "model", "Deterministic native tool model", "No network model calls. Agno owns the tool loop; deterministic model responses only.", []),
    ("local-environment", "environment", "Bounded local fixture", "Single-server synthetic tool environment; no arbitrary code, network, credentials or installation.", []),
]


LEGACY_DEMO = {
    "demo-model": ("model", "local-synthetic-model-v1"),
    "synthetic-knowledge": ("knowledge", "local-synthetic-knowledge-v1"),
    "local-environment": ("environment", "local-bounded-environment-v1"),
    "literature-tool": ("tool", "native-literature-v1"),
    "question-tool": ("tool", "native-ask-scope-v1"),
    "experiment-tool": ("tool", "native-experiment-v1"),
    "checksum-tool": ("tool", "native-checksum-v1"),
}

def demo_definitions(seeds):
    """Configuration fixtures are the only place application IDs choose defaults."""
    def mode(ids, tools, caps, *, ask=0):
        return ModeDefinition.model_validate({"materialRefs": [ApplicationService.pin(seeds[mid]) for mid in ids],
            "capabilities": caps, "toolOrder": tools, "config": {"askScopeBelowLength": ask}})
    common = ["demo-model", "local-environment"]
    research = [*common, "research-skill", "research-prompt", "synthetic-knowledge", "literature-tool", "question-tool"]
    literature = mode(research, ["literature_search", "ask_scope"], ["research:read", "question:ask"], ask=12)
    experiment = mode([*research, "experiment-tool"], ["literature_search", "ask_scope", "run_experiment"],
                      ["research:read", "question:ask", "experiment:synthetic"], ask=12)
    checksum = mode([*common, "checksum-tool"], ["checksum"], ["checksum:read"])
    return [ApplicationDefinition(id="research", name="Auto-Research", defaultForDiscovery=True,
                discoveryKeywords=["research", "investigate", "literature", "研究", "调研"], modes={"literature": literature, "experiment": experiment}).model_dump(exclude_none=True),
            ApplicationDefinition(id="checksum", name="Checksum", discoveryKeywords=["checksum", "sha256", "校验"],
                modes={"literature": checksum, "experiment": checksum}).model_dump(exclude_none=True)]


def demo_v2_definitions(seeds):
    """Additive neutral fixture; historical checksum v1 remains untouched."""
    return [ApplicationDefinitionV2(contractVersion=2, id="checksum-neutral", name="Checksum (neutral contract)",
        defaultMode="execute", modes={"execute": ModeDefinitionV2(
            materialRefs=[PinnedRef.model_validate(ApplicationService.pin(seeds[mid])) for mid in ("demo-model", "local-environment", "checksum-tool")],
            capabilities=["checksum:read"], toolOrder=["checksum"])}).model_dump(exclude_none=True)]


def all_demo_definitions(seeds):
    return [*demo_definitions(seeds), *demo_v2_definitions(seeds)]
