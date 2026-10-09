"""Disabled-by-default money management; historical SQL remains untouched."""
from fastapi import HTTPException


def require_available(settings, plan):
    spec = (plan.get('executionBindings') or {}).get('model') or {}
    from .go_development import MODEL_ADAPTER_IDS
    managed = spec.get('adapterId') in MODEL_ADAPTER_IDS.values()
    for price in getattr(settings, 'usage_pricing', ()):
        if (price.adapter_id, price.adapter_revision) == (spec.get('adapterId'), spec.get('revision')):
            managed |= price.local_model_type is None
    if managed and (not getattr(settings, 'fee_management_enabled', False) or not getattr(settings, 'platform_paid_models_enabled', False)):
        raise HTTPException(409, 'PLATFORM_PAID_MODEL_DISABLED: configure an owner BYOK model; managed hard-budget execution is unavailable')
    # These profiles call accounting at an external boundary themselves. They
    # cannot advertise or use hard budget custody without its actual ledger.
    if not getattr(settings, 'fee_management_enabled', False) and (plan.get('application') == 'autoresearch-goal-session-v1'
            or spec.get('adapterId') == 'managed-orx-pause-model-v1'):
        raise HTTPException(409, 'MANAGED_BUDGET_PROFILE_DISABLED')


def ledger_for_plan(store, plan):
    # BYOK never joins platform accounting, even on a legacy ledger-enabled host.
    from .byok_model import ADAPTER_ID
    spec = (plan.get('executionBindings') or {}).get('model') or {}
    return None if spec.get('adapterId') == ADAPTER_ID else getattr(store, 'usage_ledger', None)
