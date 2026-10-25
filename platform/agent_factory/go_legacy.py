"""Inert identifiers for persisted Go development plans.

Shared dispatch and admission may recognize these historical plans without
loading their campaign, provider, transport or accounting implementation.
Recognition never grants execution. The development profile is removed; these
identifiers remain for historical accounting and original-operation custody.
"""
from typing import Any


APPLICATION_ID = "go-development-checksum"
MODEL_ADAPTER_IDS = {
    "deepseek-flash": "go-development-deepseek-flash-v1",
    "deepseek-v4-flash": "go-development-deepseek-v4-flash-v1",
    "gpt-6-luna": "go-development-gpt-6-luna-v1",
}


def is_go_plan(plan: Any) -> bool:
    spec = (plan.get("executionBindings") or {}).get("model") or {}
    return plan.get("application") == APPLICATION_ID or spec.get("adapterId") in MODEL_ADAPTER_IDS.values()
