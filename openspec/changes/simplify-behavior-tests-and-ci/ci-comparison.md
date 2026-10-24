# PR96 CI measurement and coverage

Before: [full run 40078129086](https://github.com/Guanzhw/agent-factory/actions/runs/40078129086) at `3e206920b8ea86598fca35d3cedcd80dfbdf160d`: **failure**, preserving the Windows baseline failure and error.

After: [full run 40079197408](https://github.com/Guanzhw/agent-factory/actions/runs/40079197408) at `13f36d25fe4c7552c507875dab4a75d566c438ab`: **success**. [Same-SHA PR fast run 40079170515](https://github.com/Guanzhw/agent-factory/actions/runs/40079170515) also passed.

These are one-run observations from standard GitHub-hosted Ubuntu/Windows VMs. Code, dependencies and cache states changed. They establish actual coverage and observed runtime, not a causal speed benchmark or billed cost.

## Actual outcomes

| Suite | Before | After |
|---|---|---|
|Linux ordinary Python|3201 executed;2620 passed;581 skipped;0 failed/errors;205.837s|Full ordinary invocation removed; static/type/architecture checks passed|
|Windows full Python|3201 executed;1978 passed;1221 skipped;1 failure+1 error;217.033s|3198 executed;1977 passed;1221 skipped;0 failed/errors;198.652s|
|Linux full PostgreSQL|3201 executed;3135 passed;66 skipped;0 failed/errors;2449.930s|3198 executed;3132 passed;66 skipped;0 failed/errors;2349.101s|
|Frontend on each OS|61 files;699 passed|60 files;695 passed|
|Independent core real install/Uvicorn/PostgreSQL smoke|accepted;clean shutdown|accepted;clean shutdown|
|Real Chromium short smoke|not in workflow|2 scenarios passed: configured and bind-loss; synthetic API interception|
|Official registry audits|not independent workflow gates|Production and full audits each 0 vulnerabilities|

The baseline Windows failure was the isolated core import of `pywintypes`; the error was the real member MCP invocation returning `PERSONAL_TOOL_OUTCOME_UNKNOWN`. Both exact test IDs passed in the final Windows job. Core distribution setup still creates real file/directory symlinks without a fallback, and its wheel and isolated all-module-import checks passed on Windows. Its PG lifespan test remains explicitly skipped on Windows.

## Coverage reconciliation

The baseline ordinary Linux log contains all 3201 unique test IDs and statuses. Of 2620 actual successes, seven intentionally removed diagnostics IDs are recorded in the cleanup mapping. **All 2613 retained baseline successes actually passed in the final PostgreSQL invocation**: missing IDs 0; retained IDs changed to skip/failure 0. All four new IDs actually passed:

- `test_actual_retrieval_boundary.RetrievalSerializationTests.test_same_task_retrieval_waits_and_subsequent_call_runs`
- `test_pubmed_retrieval.PubMedTests.test_non_fixture_transport_is_rejected`
- `test_retrieval_diagnostics.RetrievalDiagnosticsTests.test_native_exit_and_signal_codes_preserved_when_command_result_exists`
- `test_retrieval_diagnostics.RetrievalDiagnosticsTests.test_unclassified_adapter_failure_does_not_copy_message_or_guess_transport`

The real PostgreSQL provenance case `test_literature_postgres.FailedLiteraturePostgresTests.test_native_review_queue_sources_report_and_owner_download` passed.

The final complete PG log reconciles 3198 unique IDs = 3132 successes + 66 explicit skips. The baseline workflow emitted periodic tails and its last 400 lines, leaving 316 unique successful IDs visible; its complete PG per-ID set is unavailable. The comparison therefore uses complete baseline ordinary-success IDs against complete final PG successes, with explicit deletion mapping. Previous local 3140/61 figures are not substituted for these GitHub runs.

| Required group | Before passed/required | After passed/required | After required not-passed/skipped |
|---|---:|---:|---:|
|owner_byok_default_off|130/130|130/130|0|
|platform_application_boundaries|33/33|33/33|0|
|research_candidate_postgres|9/9|9/9|0|
|autoresearch_native_fixture|11/11|11/11|0|
|workflow_native_fixture|10/10|10/10|0|
|department_self_service|19/19|19/19|0|
|execution_invariants|6/6|6/6|0|

Every required group has `notPassed=[]`; both PG summaries have `accepted=true`. Groups overlap and must not be added as unique tests. Optional ORX/container/public-service, dump/restore, PG-bin and SSH prerequisites retain explicit skip reasons and are not claimed as validated.

## Observed elapsed time

| Job | Before seconds | After seconds | Change seconds |
|---|---:|---:|---:|
|Select CI mode|4|4|0|
|Linux Python|244|40|-204|
|Windows Python|316|271|-45|
|Linux frontend|37|79|+42|
|Windows frontend|77|69|-8|
|PostgreSQL|2534|2408|-126|
|CI summary|5|5|0|

All jobs summed: **3217s to 2876s**, or **53.6167 to 47.9333 raw job-runtime minutes**; observed difference -341s (-5.6833 minutes). This is measurement, not billing. Workflow start to final summary completion: **2553s to 2427s** (42m33s to 40m27s); PG remains the critical path.

| Component | Before seconds | After seconds |
|---|---:|---:|
|Linux npm install|3|5|
|Windows npm install|13|12|
|Linux complete npm check|24|32|
|Windows complete npm check|42|34|
|Linux Python dependency sync|2|2|
|Windows Python dependency sync|5|5|
|Linux pyright|14|19|
|Windows pyright|24|23|
|Linux Python architecture|7|11|
|Windows Python architecture|11|10|
|PG container initialization|15|13|
|PG uv setup/cache restore|26|2|
|PG dependency sync|2|1|
|PG independent core build/install/start/stop|11|11|
|Full PG enclosing step|2474|2372|
|Linux full ordinary discovery/execution step|214|0 (removed)|
|Windows full discovery/execution step|232|214|
|Linux browser tooling and matching Chromium install|not present|20|
|Linux real Chromium smoke|not present|7|
|Linux explicit production/full audits|not present|0/1|
|Linux/Windows Vitest reported duration|12.88/21.39|16.75/16.32|
|Linux/Windows Vite reported build duration|1.38/1.84|1.86/1.49|

Discovery is not separately instrumented in the baseline. Enclosing test-step time includes startup, discovery, output and teardown; subtracting unittest runtime does not isolate discovery. API step timestamps have one-second resolution.

Ubuntu image was `ubuntu-24.04` version `20261012.334.1`; Windows image was `windows-2025-vs2026` version `20261021.278.1` in both runs. Node was 24.21.0 (Linux)/24.22.1 (Windows), Python 3.12.15 (Linux)/3.12.10 (Windows), uv 0.12.1. Linux npm cache changed hit to miss; Windows npm cache missed in both. PG uv cache hit in both with different lock-derived keys. PostgreSQL 17.11 pulled the same pinned digest in both. No CI image/registry failure or retry was observed in these PG jobs; the 26s to 2s uv setup/cache difference and other VM/cache variation are not attributed to test cleanup.

Raw GitHub job logs, full downloadable workflow ZIPs, run/jobs API JSON with all job/step start/end timestamps, per-ID statuses with source log lines, the deletion mapping, SHA256 receipts and coverage comparison are retained in the baseline/final validation receipts. Public evidence is accessible through the run links above.
