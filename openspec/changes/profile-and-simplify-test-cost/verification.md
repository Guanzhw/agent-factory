# Verification — in progress

## Frozen baseline

Commit `9a933aa8aadda1b80b216cf67f399974690c6fc6`; existing cloud checkout,4 CPU/16 GiB cgroup. Locked Python3.12.14/uv0.12.1/Node24.19.0 dependencies. PostgreSQL17.11 CI digest, dedicated2 CPU/1 GiB container and fresh local volume, loopback only. One heavy runner, no source edits during baseline, no real external provider.

Command: `uv run --no-sync python /workspace/scratch/suite-review-20261024/profile_suite.py --output /workspace/scratch/suite-review-20261024/baseline` with disposable `FACTORY_TEST_DATABASE_URL`.

2026-10-24 10:12:27 UTC start; driver3576.996s/exit1, original unittest3555.380s. **3198 run:3131 passed,1 failed,66 skipped. Seven required groups all passed with no required skips; overall acceptance remains false.** Exact discovery filtered3198 observed case rows; raw nested runner selftest events are not extra product cases.

Failure: `RemoteHandoffPostgresTests.test_13_forwarded_questions_local_children_scoped_reads_and_artifact_bytes`. Parent original native ticket remained `running` after answer, attempt2/max2. `locked_at` is refreshed by native heartbeat and cannot establish claim time. Original test and deadlines unchanged; root cause pending targeted diagnosis.

Prior takeover failures and later passes remain in `/workspace/scratch/cloud-takeover-20261024/`; neither later passes nor this baseline's MCP passes establish stability.

## Cost ranking

Case durations include setup/test/teardown/cleanup, but class/module fixtures are separate. Helper spans nest and must not be summed with case or wall time. External observer phase attribution for nested runner selftests is incomplete; original unittest summary is authoritative for failures/subtests.

| Module | Cases | Case seconds | Setup | Test | Teardown/cleanup |
|---|---:|---:|---:|---:|---:|
| `test_remote_scientific_integration` | 1 | 275.05 | 0.00 | 275.05 | 0.00 |
| `test_remote_process_runtime_postgres` | 11 | 253.27 | 117.21 | 124.24 | 11.82 |
| `test_personal_mcp_capacity_postgres` | 6 | 130.02 | 15.47 | 113.41 | 1.14 |
| `test_autoresearch_scientific_children_postgres` | 1 | 117.77 | 0.00 | 117.64 | 0.13 |
| `test_remote_handoff_postgres` | 26 | 111.75 | 0.10 | 103.23 | 8.40 |
| `test_governed_remote_process_postgres` | 9 | 108.11 | 1.53 | 98.97 | 7.60 |
| `test_remote_usage_process_postgres` | 8 | 101.17 | 1.37 | 92.79 | 7.00 |
| `test_research_inventory_scale` | 1 | 84.22 | 0.00 | 84.10 | 0.12 |
| `test_remote_execution_postgres` | 10 | 79.42 | 0.04 | 67.23 | 12.15 |
| `test_lifecycle_observer_postgres` | 14 | 72.88 | 0.59 | 69.16 | 3.13 |
| `test_personal_models_postgres` | 12 | 68.91 | 41.00 | 27.19 | 0.72 |
| `test_control_commands_remote` | 5 | 62.97 | 0.03 | 55.71 | 7.23 |

Across case phases:setup844.30s,test2493.12s,teardown68.20s,cleanup70.98s (approximate due observer caveats). 404 isolated-PG creations total43.53s; remote process server starts25 calls/124.24s; their11 containing pair starts117.20s are overlapping spans, not additional cost. Largest class fixtures: governed remote13.19s, remote usage10.96s, remote handoff9.54s.

## Value and scope decisions

- Retain remote scientific275.05s and local scientific117.77s: distinct remote receipt/shared-budget and local parent/child custody/reconstruction boundaries. No claim of real science/GPU/model validation.
- Retain original process UNKNOWN, delayed dispatch, lost cancel acknowledgement and both origin/receiver revocation paths; similar terminal assertions exercise distinct failure sources.
- Merge remote normal completion and same-request replay using the **same completed task**; baseline22.43s+18.82s, second fixture setup10.35s. Preserve every identity, single allocation/launch, artifact/hash and owner-isolation assertion.
- Reduce repeated full scans in84.22s real24204-file test. Preserve actual count, complete capture/staging, final-member corruption refusal and config bytes; move cheap replay bytes assertion to existing small driver case. Deletion-from-pristine and replay have independent small-tree counterparts.
- Do not restructure five pure SSH PG duplicates merely to save about1.19s, or broader model receipt tests based on counts. Prioritize meaningful avoidable work.
- MCP130.02s suite retains the original historical second-call path pending diagnosis; removing a failing step cannot count as fixing it.
- CI already executes full PG discovery once. Required gates reuse those results; Linux Python full is not duplicated. Windows is a distinct platform boundary. Do not claim PR96 changes as new savings.

## Evidence and pending validation

Raw local evidence: `/workspace/scratch/suite-review-20261024/`: `full-baseline.{json,log}`, `baseline/{summary,ranking,discovered-ids}.json`, `baseline/timings.jsonl`, `baseline-environment.json`. Observer hash recorded there; same frozen observer will be used for comparison.

Original-code deterministic callback probe:5 cases,2passed/3failed, exit1; queued cancellation and submit failure leave phantom unfinished callbacks; dequeued-before-wrapper cancellation can execute the callback later. Already-running custody and normal return/exception/context propagation pass. See `mcp-callback-before.{json,log}`. Historical PG attribution and repair validation remain pending.

No final after timings, full acceptance, PR or CI claim yet.

## Targeted diagnosis and implementation

- Callback original5-case deterministic run:3fail/2pass; same command after narrow start-gate fix5pass. No timeout changes. Already-started callbacks keep custody until real finally; abandoned-before-start workers cannot enter later. Submission failure closes an unstarted gate and propagates original exception. Existing MCP plus callback/profiler/runner regression61pass/0skip; Ruff/Pyright pass.
- Original two PG scenarios with observation:2pass/0skip,42.997s test time. Five DELETE authorization sequences each355 SQL statements; combined callback0.516–0.645s, queue0.00033–0.00305s, connection acquire0.00103–0.00122s. This run did not reproduce historical authorization-budget exhaustion and is not a performance benchmark. Historical2-second timeout mechanism remains; actual prior contention source unproven. Do not claim both historical failures fully closed or alter production deadlines/current-authority checks.
- Node24.19.0 permission-mode matrix:default minimal node:test passes; both sync spawn probes report EPERM; default full architecture runner produces original file-level failure. Direct diagnostic entry identifies9pass/1fail at real CLI stderr assertion. Approved same-version probes and standard architecture command pass10cases. Added explicit spawn error/signal assertions, retaining all CLI output/exit assertions; no skip or fallback. Post-edit verification pending.
- Remote handoff isolated original case passed25.079s. Wait phases parent-paused0.567s/child-paused0.526s/child-completed2.349s/parent-completed1.427s. This does not explain full failure. One original ordered predecessor subset is the next diagnostic, with unchanged15s deadline and failure-only bounded task/thread frame labels (no locals/payloads).

Changes are on isolated branch `chore/profile-test-cost-20261024`; original checkout/branches preserved. No push/PR yet.


Further targeted results: original six MCP capacity cases117.009s,6pass/0skip after fix, including historical two-call paths and UNKNOWN SDK-exit/restart refusal. Node post-edit approved standard10pass; default direct negative check9pass/1fail now explicitly reports EPERM. Remote ordered-prefix13pass/0skip, original deadlines unchanged; full-baseline failure remains unexplained rather than labelled fixed.

Independent review found no blocking callback/coverage/acceptance issue. It identified async runner startup/final loop+executor shutdown outside unittest case callbacks; documentation now keeps these costs in total wall only. Expanded profiler tests cover async awaited cleanup, module transition teardown subtraction, and module setup failure preserving required rejection;5 tests passed (clock fixture subsequently isolated to the profiler module to avoid affecting other observers; final5-case rerun passed).


Final pre-comparison gates: Ruff, Pyright0errors/0warnings, Python and Web architecture, OpenSpec validation passed. Fast collect-only validates3207 full IDs,230 Python/58 PG daily IDs,2919 manual-only, no cross-lane overlap; this is selection validation, not an execution claim. Independent core wheel installation/loopback lifespan/PG/native worker/empty app catalogs/clean shutdown passed. Full Web695pass, production/all npm audits0vulnerabilities, real Chromium configured+bind-loss2 synthetic-API scenarios passed.

Same frozen observer targeted pruning comparison: remote original01+02 total41.251s versus merged01 23.718s;24204-file case84.221s versus34.979s. Small driver replay and last-file deletion counterparts passed;4 targeted cases58.780s, no skips. These are single targeted observations, not final suite-wide speed claims. Work eliminated is a second two-database/two-service journey and four repeated observer/driver calls, not independent failure coverage.
