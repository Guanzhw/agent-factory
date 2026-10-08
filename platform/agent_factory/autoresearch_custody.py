"""Read original stopped scientific artifacts without renewing child execution."""
from fastapi import HTTPException

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
    except (HTTPException, PermissionError) as error:
        if (not stopped or not plan.get('remoteHandoff') or plan.get('mode') != 'remote-scientific-training'
                or plan.get('application') != APPLICATION_ID
                or isinstance(error, HTTPException) and error.status_code not in {403, 404, 409}):
            raise
        receiver = getattr(store, 'remote_scientific_receiver', None)
        if receiver is None:
            raise PermissionError('AUTORESEARCH_CUSTODY_BINDING_INVALID')
        receiver.require_completed_custody(owner, plan, context)
        # The distinct source custody proof replaces only the remote execution
        # guard. Local review, bindings, material currency and every other guard
        # remain mandatory. No native admission or tool call consumes this path.
        store.require_current_policy()
        store.auth.require(owner, 'run')
        store.plan_policy.require_execution(owner, plan, run_context=context)
        store.execution_bindings.recheck(plan, context)
        if store.material_governance is not None:
            store.material_governance.require_materials_current(plan)
        for name, guard in tuple(store.execution_guards.items()):
            if name != 'remote_receiver':
                guard(owner, plan, context, None)
