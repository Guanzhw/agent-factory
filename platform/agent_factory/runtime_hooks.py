"""Small trusted boundary for adapter-owned evidence and existing-work custody.

The immutable built-ins are selected by operator code, never application data.
Native Agno remains the execution owner. Hooks cannot grant admission, submit
work, or infer stop from elapsed time or a cancellation acknowledgement.
"""
from .research_runtime_hooks import ResearchRuntimeHooks


# Keep historical effect classification available before a Store exists, and
# for existing callers of store.effect_unresolved. New adapters extend this
# trusted list in code, not via material-supplied executable paths.
EVIDENCE_ADAPTERS = (ResearchRuntimeHooks,)


def effect_unresolved(effect):
    return (effect.get("status") not in {"DONE", "CANCELLED"}
            or any(adapter.effect_held(effect) for adapter in EVIDENCE_ADAPTERS))


def reconcile_runtime_capacity(store):
    for adapter in EVIDENCE_ADAPTERS:
        adapter.reconcile_capacity(store)


def runtime_custody_held(store, task_id):
    return any(service is not None and service.task_held(task_id)
               for service in (getattr(store, "process_runtime", None), getattr(store, "workflow", None)))


def native_ended_reason(store, task):
    for adapter in EVIDENCE_ADAPTERS:
        reason = adapter.ended_reason(store, task)
        if reason:
            return reason
    workflow = getattr(store, "workflow", None)
    if workflow is not None and workflow.task_held(task["id"]):
        return "native-ended-unfinished-workflow"
    return None


async def cancel_owned_runtime(store, task):
    for adapter in EVIDENCE_ADAPTERS:
        await adapter.cancel(store, task)
    workflow = getattr(store, "workflow", None)
    if workflow is not None:
        await workflow.cancel_task(task["owner_id"], task["id"])


def execution_classification(plan):
    """Execution classification is independent of the deployment/auth mode.

    A synthetic controller does not classify all of its external tools or
    artifacts as synthetic. Evidence is separately projected by its adapter.
    Unknown model bindings are deliberately not claimed to be verified/live.
    """
    binding = plan.get("executionBindings") or {}
    model = binding.get("model") or {}
    synthetic = model.get("adapterId") == "local-synthetic-model-v1"
    if not binding:
        synthetic = plan.get("syntheticFixture") is True  # historical demo pin
    component = plan.get("nativeComponent") or {}
    kind = "native-workflow" if component.get("kind") == "workflow" else "native-agent"
    return {"executionKind": "synthetic-controller" if synthetic else kind,
            "syntheticFixture": synthetic}


def runtime_policy_projection(plan):
    # Legacy API compatibility field; not an execution grant.
    return ResearchRuntimeHooks.policy_projection(plan)


def project_runtime_evidence(settings, store, task, plan, events, job):
    evidence, evaluation = {}, None
    for adapter in EVIDENCE_ADAPTERS:
        projected, observed = adapter.project(settings, store, task, plan, events, job)
        evidence.update(projected)
        if observed is not None:
            evaluation = observed
    return evidence, evaluation


async def project_runtime_requirement(store, task, requirement, version, status, job, actions):
    for adapter in EVIDENCE_ADAPTERS:
        if await adapter.requirement(store, task, requirement, version, status, job, actions):
            return True
    return False


async def project_runtime_recovery(commands, task, snapshot, requirements, job, actions):
    for adapter in EVIDENCE_ADAPTERS:
        await adapter.recovery(commands, task, snapshot, requirements, job, actions)
