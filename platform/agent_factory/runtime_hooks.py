"""Small trusted boundary for adapter-owned evidence and existing-work custody.

The deployment supplies trusted callbacks, never application data.
Native Agno remains the execution owner. Hooks cannot grant admission, submit
work, or infer stop from elapsed time or a cancellation acknowledgement.
"""
def effect_unresolved(effect, store=None):
    registry = getattr(store, 'application_runtime', None)
    held = registry.effect_held if registry is not None else None
    return (effect.get("status") not in {"DONE", "CANCELLED"}
            or bool(held is not None and held(effect)))


def runtime_custody_held(store, task_id):
    registry = getattr(store, 'application_runtime', None)
    if registry and registry.task_held(store.task(task_id)):
        return True
    return any(service is not None and service.task_held(task_id)
               for service in (getattr(store, "process_runtime", None), getattr(store, "workflow", None)))


def native_ended_reason(store, task):
    registry = getattr(store, 'application_runtime', None)
    observe = registry.ended_reason if registry is not None else None
    reason = observe(task) if observe is not None else None
    if reason:
        return reason
    workflow = getattr(store, "workflow", None)
    if workflow is not None and workflow.task_held(task["id"]):
        return "native-ended-unfinished-workflow"
    return None


async def cancel_owned_runtime(store, task):
    registry = getattr(store, 'application_runtime', None)
    cancel = registry.cancel if registry is not None else None
    if cancel is not None:
        await cancel(task)
    # Keep the existing outer cleanup ordering: ambiguous application cleanup
    # propagates before the core workflow continuation is considered.
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
