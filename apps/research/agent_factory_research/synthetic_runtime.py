"""Explicit synthetic research factories; never installed by the bare core."""
from typing import Any
from agent_factory.execution_bindings import BindingContext, EnvironmentLimits, ExecutionBindings, KnowledgeContext
from agent_factory.go_legacy import is_go_plan
from agent_factory.usage_ledger import PricingRevision
from .bootstrap_catalog import SEEDS, LEGACY_DEMO

class ResearchExecutionBindings(ExecutionBindings):
    def recheck(self, plan, context=None):
        manifest = super().recheck(plan, context)
        from .synthesis_runtime import validate_plan_source
        from .comparison_workflow import validate_plan
        validate_plan_source(self.store, plan)
        validate_plan(self.store, plan)
        if is_go_plan(plan):
            from agent_factory.go_development import preflight_plan
            preflight_plan(self.settings, plan, self.connections, context)
        return manifest


def default_bindings(settings: Any, store: Any, connections: Any = None) -> ExecutionBindings:
    from .demo_model import DemoModel
    from .tools import build_tools
    registry = ResearchExecutionBindings(settings, store, connections, legacy_materials=SEEDS, legacy_bindings=LEGACY_DEMO)
    def empty(config):
        if config:
            raise ValueError("Adapter accepts no material configuration")
    registry.register("model", "local-synthetic-model-v1", "1", lambda context: DemoModel(), demo_only=True, validator=empty)
    for adapter, name, permission, demo_only in (
        ("native-literature-v1", "literature_search", "research:read", True),
        ("native-ask-scope-v1", "ask_scope", "question:ask", False),
        ("native-experiment-v1", "run_experiment", "experiment:synthetic", True),
        ("native-checksum-v1", "checksum", "checksum:read", False)):
        registry.register("tool", adapter, "1", lambda context, selected=name: build_tools(context.settings, context.store)[selected],
            tool_name=name, permissions=(permission,), demo_only=demo_only, validator=empty)
    def knowledge(context):
        ref = context.spec["materialRef"]
        material = next(item for item in context.plan["materials"] if all(item[key] == ref[key] for key in ref))
        return KnowledgeContext(material["content"], {"evidenceKind": "synthetic", "source": "approved-material-content"})
    registry.register("knowledge", "local-synthetic-knowledge-v1", "1", knowledge, demo_only=True, validator=empty)
    keys = {"runtimeId", "timeoutSeconds", "outputBytes", "memoryBytes", "processLimit", "cpuPercent"}
    def environment(context):
        config = context.spec["config"]
        if set(config) - keys:
            raise ValueError("Unknown bounded environment configuration")
        return EnvironmentLimits(runtime_id=config.get("runtimeId", "local-python-bounded-v1"),
            timeout_seconds=config.get("timeoutSeconds", context.settings.experiment_timeout_seconds),
            output_bytes=config.get("outputBytes", context.settings.experiment_output_bytes),
            memory_bytes=config.get("memoryBytes", 256 * 1024 * 1024), process_limit=config.get("processLimit", 4), cpu_percent=config.get("cpuPercent", 10))
    def validate_environment(config):
        if set(config) - keys:
            raise ValueError("Unknown bounded environment configuration")
        environment(BindingContext(settings, store, {}, None, {"config": config}))
    registry.register("environment", "local-bounded-environment-v1", "1", environment, validator=validate_environment)
    return registry


def default_zero_prices():
    from .demo_model import DemoModel
    values = [PricingRevision("local-synthetic-model-v1", "1", "local-synthetic", "factory-synthetic-v1",
        "zero-local-v1", local_model_type=DemoModel)]
    try:
        from .orx_experiment_tools import LocalORXWorkflowModel
    except ImportError:
        return tuple(values)
    values.append(PricingRevision("local-orx-workflow-model-v1", "1", "local-deterministic",
        "factory-local-orx-workflow-v1", "zero-local-v1", local_model_type=LocalORXWorkflowModel))
    from .orx_literature_tools import LiteratureEvidenceModel, MODEL_ID
    values.append(PricingRevision(MODEL_ID, "1", "local-deterministic",
        "factory-literature-evidence-v1", "zero-local-v1", local_model_type=LiteratureEvidenceModel))
    return tuple(values)
