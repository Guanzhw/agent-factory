"""Read original stopped scientific artifacts without renewing child execution."""
from .autoresearch_profile import APPLICATION_ID
from .autoresearch_scientific_child import PHASES, adapter_id, child_pin
from .execution_bindings import BindingContext
from .plan_policy import NativeMandateCompleted


def require_original_custody(store, owner, plan, context, *, stopped):
    try:
        store.require_plan_execution(owner, plan, run_context=context)
        return
    except NativeMandateCompleted as error:
        phase = str(plan.get('mode', '')).removeprefix('scientific-')
        if (not stopped or phase not in PHASES or plan.get('application') != APPLICATION_ID
                or not plan.get('delegation') or plan.get('remoteHandoff')
                or error.task_id != context.session_id or error.run_id != context.run_id):
            raise
        # The typed exception verified current ancestry but explicitly denied
        # execution. Validate current root approval and exact completed-child
        # custody independently, then finish the guards skipped by that denial.
        manifest = store.execution_bindings.recheck(plan, context)
        selected = [spec for spec in manifest['tools'] if spec['adapterId'] == adapter_id(phase, 'tool')]
        if len(selected) != 1:
            raise PermissionError('AUTORESEARCH_CUSTODY_BINDING_INVALID') from None
        child_pin(BindingContext(store.settings, store, plan, context, selected[0]), phase, custody=True)
        if store.material_governance is not None:
            store.material_governance.require_materials_current(plan)
        for guard in tuple(store.execution_guards.values()):
            guard(owner, plan, context, None)
