# Verification

## Complete serial comparison

Cloud checkout `/workspace/agent-factory-cloud-main`;4 CPU/16 GiB cgroup. Python3.12.14,uv0.12.1,Node24.19.0,npm11.9.0; frozen dependencies including Agno3.1.0/MCP2.3.0. Both runs use PostgreSQL17.11 CI digest, separate fresh volumes,2 CPU/1 GiB/pids256, loopback55432, fsync/synchronous_commit enabled. One heavy runner; source frozen within each run. Host caches not reset; no live provider.

Command for each: `uv run --no-sync python /workspace/scratch/suite-review-20261024/profile_suite.py --output /workspace/scratch/suite-review-20261024/{baseline,after}`, with disposable `FACTORY_TEST_DATABASE_URL`.

| Measurement | Exact code | Passed / failed / skipped | unittest seconds | Driver seconds / exit |
|---|---|---|---:|---|
| Before,10:12 UTC | `9a933aa8aadda1b80b216cf67f399974690c6fc6` |3131 /1 /66 (3198 total)|3555.380|3576.996 /1|
| After,11:39–12:43 UTC | `6f82b4abd2a3487dd756882766d3e313cb949fb9` |3139 /2 /66 (3207 total)|3807.505|3830.558 /1|

Both passed all seven required groups without skips:130/33/9/11/10/19/6 cases. **Neither complete run passed. Unittest/observer elapsed increased252.125s (complete driver increased253.562s); no suite-wide speedup or stability claim.** Same external observer SHA256 `f727282452ba52e345261bddf2b68bf9ff6bc601ef7681c82301e829d02a7688`; exact discovery IDs filter nested runner selftest events. Ten cheap regressions added, one remote case merged; counts are not the value metric.

The only subsequent code change is optional-profiler traceback formatting plus one deterministic regression, verified separately below; local complete comparison does not cover that later change. Exact final-commit CI must be recorded in the Draft PR and local delivery evidence.

## Cost and independent coverage

| Workload | Before seconds | After seconds | Decision |
|---|---:|---:|---|
| Remote scientific3 phases |275.05|306.74|Retain: original remote receipts and shared budget|
| Local scientific parent/children |117.77|131.12|Retain: distinct local custody/reconstruction|
| Entire remote process module |253.27|250.96|Retain distinct crash/revocation/UNKNOWN/deadline cases|
| MCP capacity module |130.02|172.43|Retain original second calls and UNKNOWN/restart paths; after includes failure|
| Remote handoff module |111.75|136.56|Retain scoped reads/HITL/child provenance; baseline includes failure|
| Governed remote module |108.11|125.87|Retain original-process authority boundaries|
| Remote usage module |101.17|124.12|Retain authoritative usage/uncertain acknowledgement boundaries|
| Remote completion + same-task replay |41.251|22.794|Merge replay into same completed-task journey;18.457s less observed work|
| Actual24204-file inventory case |84.221|41.705|Remove redundant repeated calls, preserve scale/corruption;42.516s less observed work|

The last two comparisons passed on both sides; observed combined reduction60.974s concerns those workloads only. A prior targeted four-case run also passed (remote23.718s,scale34.979s); it is not an independent statistical performance estimate. Unchanged cases varied substantially and failure outcomes changed.

Baseline case phases:setup844.30s,test2493.12s,teardown68.20s,cleanup70.98s.404 isolated-PG creations43.53s;25 process-server starts124.24s;11 containing pair starts117.20s overlap. Class fixtures are separate; helper spans must not be added to case totals. Async loop/executor closure is wall-only. Frozen observer has incomplete nested-run/subtest phase attribution and can truncate assertion traceback frames; original acceptance results/messages remain authoritative. The reusable profiler addresses these diagnostic issues separately.

Coverage mapping:

- `test_remote_process_runtime_postgres...test_02_completed_request_replay_preserves_released_process_identity` is merged into `test_01_governed_remote_process_original_identity_receipt_and_owner_isolation`. Every identity, single launch/allocation count, artifact/hash/provenance and owner404 assertion remains, using the same completed task. One two-database/two-process fixture removed, no mutable class fixture sharing.
- `test_research_inventory_scale...test_24204_files_observed_and_staged_without_truncation` retains24204 real files, count/tail, full capture and real driver success, then tail corruption refusal and unchanged config bytes. Four repeated observer/driver calls removed (not a claim of exactly four disk traversals). Existing small `test_research_local_driver` dynamic-ID replay now checks byte equality; pristine deletion detection remains in `test_research_package_paths`.
- Keep expensive delayed dispatch, lost cancel acknowledgement, origin/receiver revocation, native restart and20-user pressure because failures differ. Do not delete five SSH PG checks for only1.19s or broad model receipt coverage by count. Remote bindings setup35.79s/body.97s remains a future fixture candidate, without proof safe to share state.
- CI already runs full PG once and reuses its results for required groups. Windows remains a distinct platform. No workflow change or re-credit for PR96.

## Failures: confirmed repair versus unresolved observations

1. **Queued MCP callback custody defect confirmed and fixed.** Same deterministic five-case probe: original3fail/2pass, repaired5pass. Cancellation/submission failure before worker entry left a phantom unfinished callback; a shared start/abandon gate now prevents later entry and acknowledges never-started work. A callback already running retains custody until its actual finally. Tests preserve ContextVar, value/exception identity and dequeued-before-wrapper behavior. No production deadline changes.
2. **Historical MCP authorization-budget exhaustion remains unclassified.** Original takeover credential failure occurred in the second successful call (authRejected,36/36 callbacks); slow-delete failure had27/28 callbacks finished. Two-case trace passed:355SQL per DELETE across current-authority checks, callbacks.516–.645s. Recorded takeover commands had no overlapping heavy checks; only short GitHub reads/dry-run. No evidence to blame them, remove guards or claim latency fixed.
3. **After-run MCP DELETE405 failure is a different observed stage:** first failed operation released and restart completed; the new task failed to reach native queue terminal state within original20s. It did not reach the later capacity assertion, so historical auth timeout is not established. One original-case diagnostic passed25.500s/zero skips: all25/36/36 callbacks finished, no authorizationRejected, DELETE callback sums.655–.749s, observed loop maximum lag130ms/36ms. This successful diagnostic cannot explain the full failure or prove stability; no repeat-to-green.
4. **After-run ORX double-click case:** original `entered.wait(5)` returned false before the first POST gate. A suspected auto-release overlap bug is not the observed assertion and was not implemented as its fix. One original unchanged diagnostic passed: worker create.034s, gate reached, second resultack_unknown, first acknowledged, one POST. No swallowed production exception observed. Historical pre-POST delay/early failure remains unknown; original5s limits and assertions unchanged.
5. **Baseline remote handoff13:** original parent remained running after answer. Native heartbeat updates `locked_at`, so it does not establish claim time. Isolated original1case and ordered13-case prefix passed; full after also passed. Cause remains unresolved; original15s deadlines unchanged.
6. **Node environment restriction identified:** minimal node:test works, default sync-child probes returnEPERM; default architecture test9pass/1fail. Approved same binary standard10pass. Added spawn error/signal diagnostics, no fallback/skip/assertion weakening. Post-edit default negative probe explicitly reportsEPERM and approved10pass.
7. **Optional profiler traceback defect confirmed and fixed after measurement.** Wrappers lacking unittest's framework marker hid the actual assertion frame. Added `__unittest` marker and a regression checking actual user frame/source while required acceptance still rejects. Before6cases:5pass/1fail; after6pass. Frozen external observer was not changed retroactively.

## Other applicable validation

Exact argv,cwd,UTC,duration and exit code are in task-local `<label>.json`, raw output in matching `.log`:

- `targeted-mcp-profiler`:61pass/0skip; `mcp-capacity-after`:original6pass/0skip; `pruned-targeted-profile`:4pass/0skip. All exit0, earlier than complete after failures.
- `profiler-group-smoke`:original execution_invariants6pass/0skip; `profiler-traceback-before/after`:expected negative then6pass.
- Ruff; Pyright0errors/0warnings; Python/Web architecture; OpenSpec validation:exit0.
- `core-install`:real isolated core wheel/newvenv/emptycwd/-I, PG/native worker start, application absence and clean shutdown,acceptedtrue,exit0.
- `web-check`:60files/695tests,build/typecheck,exit0. Both npm audits0vulnerabilities. `browser-smoke`:two actual Chromium scenarios with synthetic APIs,exit0.
- `final-fast-python`:final231pass/0skip,32.671s,exit0; discovery3208.
- Pre-final collection3207 IDs:230fast Python/58fast PG/2919manual-only; collect-only is not execution. Later traceback regression adds one cheap Python case.
- Independent code review found no blocking callback/pruning issue; acceptance failures and traceback correction explicitly recorded. Public added-line credential-pattern scan is supplementary, not exhaustive.

## Evidence and boundaries

`/workspace/scratch/suite-review-20261024/`: `full-{baseline,after}.{json,log}`, `{baseline,after}/{summary,ranking,discovered-ids}.json`, timingsJSONL, `comparison.json`, `case-costs.csv`, environment snapshots, callback/Node/remote/MCP/ORX diagnostic records and `REPORT.md`. Earlier failures remain `/workspace/scratch/cloud-takeover-20261024/` unchanged. Full local runs were not repeated to obtain green.

Branch `chore/profile-test-cost-20261024`; original checkout/branches preserved. Both owned PG containers/volumes were removed after inventory showed only four foundation databases. Scoped process scan found no live owned fixture server;70 global zombie entries remain, without inferred ownership or a blanket clean-process claim. Publication/exact-CI status is recorded in delivery evidence/PR. No production or target-machine acceptance, real science/model/provider call, merge or deployment is claimed. Unresolved timing failures remain follow-up limitations; they are not excused as environment failures without evidence.
