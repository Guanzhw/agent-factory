"""Native external-execution requirement; completion is owner-scoped custody proof."""
from agno.tools import tool


@tool(external_execution=True)
def factory_wait_operations(operationIds: list[str]) -> str:
    """Wait for original external operation IDs; never start or replace an operation."""
    raise RuntimeError('NATIVE_EXTERNAL_EXECUTION_REQUIRED')
