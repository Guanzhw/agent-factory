# Fixed research native Workflow implementation checkpoint

2026-10-25; cloud synthetic fixtures only. This is an incomplete implementation checkpoint, not P5/C01/D01 acceptance.

- `test_research_workflow`: 2 portable protocol cases passed.
- `test_research_rounds`: 10 portable service cases passed after the actual uppercase `PAUSED` observation contract was corrected (2.905 s). A restricted-network fixture startup stalled and was stopped; the explicit network-enabled portable run passed. That first run is not counted as passed.
- Actual `agent_factory_server.research.create_app`, an isolated PostgreSQL database, real native queue and fixed Workflow, synthetic model: immediate-stop case passed (1 case, 7.885 s). It created no child, retained the original not-met decision, and did not mutate the caller's Settings.
- First child case failed (37.503 s). The real child computed and archived a checksum; its original operation was closed/completed. The parent stayed paused because the application compared the native uppercase `PAUSED` status against lowercase `paused`. Fixed the comparison and portable contract; did not change timeout or assertion.
- Targeted child rerun after that fix failed (28.505 s). Original reconcile now resumes, but the core native step validator rejects `Original registered native step required`. The native Workflow then appears completed without a research decision, and the research acceptance test rejects the missing decision. Investigate exact nested Router/Steps original continuation identity before changing core authority checks. No scientific success is claimed from native completion.

- One bounded metadata-only diagnostic reproduced the continuation failure (41.784 s). The response and original executor run both carry declaration step ID `research_wait`; the original pending requirement carries its runtime UUID, with the same executor run/agent and exact `research_wait` name. Existing completed step results contain only context/decide. The core final matching check rejects this declaration/runtime-ID split. The core fix requires its own spec and foreign-identity regression; the application has not weakened the check.

Original local evidence (synthetic only): `/tmp/research-native-workflow-evidence/stop-first.log`, `child-first.log`, `child-after-status-fix.log`, `child-identity-diagnostic.log`; portable evidence `/tmp/research-rounds-portable-uppercase.log`. Each run completed cleanup of its TestClient, worker/scheduler and isolated database. No shared PostgreSQL data was removed.

The model is a deterministic protocol fixture; its observed tool result drives the fixture decision. No paid/live model, remote GPU, capacity, real provider identity, P7 team-value comparison or P8 independent reproduction has run. These remain NOT RUN/BLOCKED, not passes.
