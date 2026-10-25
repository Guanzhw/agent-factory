# Design

`ApplicationRuns.tool_results(owner, task_id, run_id)` checks membership and exact task ID/run ID after Store.task (which also accepts a run ID). Store.plan already verifies its immutable digest. No execution authorization or credentials are requested to read historical results.

The first consumer supports the ordinary Factory executor only: no nativeComponent or remoteHandoff. The original full materials and executionBindings.tools must identify exactly one tool, matching plan.tools and the material pin. The binding's adapter/revision/operationSha256 must match the persisted MemberToolOperations.by_adapter record, whose verified descriptor has transport=cli. Installed-only adapters and multiple tools are explicitly unsupported because effects do not persist per-call tool provenance. Never infer identity from the current registration, receipt count or JSON fields.

Return taskId/runId/planId, materialRef, binding adapterId/revision/toolName, operationRef and receipts. Only original-run personal-tool effects with DONE and completed outcome expose output. No connection/config/credential references, fingerprints, model messages or other effects leave this port. Receipt output is owner-only data, not a sharing grant. The port proves the selected operation and stored output, not actual argv, source commit or reproducibility.

Reuse existing bounded execution receipts and immutable plan validation; no new database table, retry or scanner. Tests cover owner/task/run mismatch, multiple tools with one receipt, unsupported provenance, unknown/failed effects and no execution/credential side effects. A real native consumer test belongs to the evidence integration before acceptance.
