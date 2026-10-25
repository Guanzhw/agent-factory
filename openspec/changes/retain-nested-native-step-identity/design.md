# Design

The observed response and original `step_executor_runs` both use `research_wait`; the original requirement uses a UUID but the same `step_name`, `executor_id` and `executor_run_id`. Completed step results do not yet contain the waiting node. This is an identity representation mismatch, not missing authorization.

Keep `_root` and persisted original child checks unchanged. A requirement must match name, executor ID and executor run. Its step ID must either match the response ID (existing behavior), or the response ID must equal this exact registered step's declaration ID. The latter never accepts an arbitrary supplied ID, foreign executor, wrong name or other session/run. Keep `factory_native_step_id` equal to the actual original executor's ID for subsequent `WorkflowDecisionModel` correlation; do not rewrite persisted native state.

First add a regression reproducing different requirement/executor step IDs and foreign identity mutations; verify it fails before the change. Run the existing native workflow tests, then rerun the actual nested child consumer once after the repair. Preserve the initial failure and diagnostic; a synthetic regression alone is not proof of native continuation.
