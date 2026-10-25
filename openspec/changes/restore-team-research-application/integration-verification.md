# P5–P8 backend integration checkpoint

This checkpoint records deterministic implementation and review, not real model research, external identity, remote GPU, deployment or capacity acceptance. Product/test tree b20efbb05c4c8acbc29721bd97f619427aa29e95 is the baseline for the next necessary combined full run. The final association/delivery UI is still under implementation in a separate branch; the previously reviewed workbench and QA UI are included here.

## Retained first failures

Combined full [40206239436](https://github.com/Guanzhw/agent-factory/actions/runs/40206239436), exact551f1bf, failed: PG2029/2fail/7error/5skip; Windows2029/7error/822skip. The seven lifecycle fixture errors were fixed by merged PR126 without production/assertion changes. Remote cancel fixture65ec5dd preserves PREPARED before observation, then exact CANCELLED_NO_DISPATCH/original identity/zero dispatch; its two PG targets passed9.884s and independent full review passed. Those results do not erase the original failed full.

Malicious QA was independently reproduced as the same native queue job attempting the entire Workflow twice. Protocol rejection alone did not fence the next attempt. Core5fe414c persists protected failure and existing cancellation atomically, admission before exact task/owner/run lock; no global retry or Agno modification.29 portable and4 PG passed, including forced attempt2 before observer with one HTTP, normal transient retry success, rollback and reopened Store. First new-test cleanup error remains in its verification record.

## Independent reviews

- Core rejection:551f1bf→5fe414c, foundation_review PASS.
- P7 associations:3e73b724→030016aec28b79966d4e486083baf1cc4da8e512, foundation_review PASS after correcting project lock order, direct original-record lookup, duplicate rich-body storage and visible-record assessment wording. Complete authority dependencies remain uncropped.
- P8:a3e083c full review plus corrections210810f and source tests ec9d555, pr104_independent_review PASS. Recipe invalid/missing values cannot be called complete; sourceIds and exported recordIds have separate purposes.
- Actual peer CLI test:7377298→bb8d8a3, pr104_independent_review PASS. Four actual PG tests passed92.059s on the recorded integration base: real CLI reproduction/continuation, withdrawal barriers, capture rollback, and peer input→original child→selected artifacts→revocation. First missing deployment import is preserved. These use synthetic model decisions.
- Root integration through53b6be0, pr104_independent_review PASS. rounds.results retains both original evidence capture and peer context; _publish retains source-bound artifacts with an explicit keyword. Core rejection patch is identical to its reviewed version.030016a thereafter changes only reviewed model instructions and its portable test; bb8d8a3 adds the reviewed PG test, not production code.

## Root checks

- Combined original CLI/content portable modules:11 passed,0 skipped,0.836s.
- Delivery/rounds portable after integration:17 passed,0 skipped,3.738s. The first restricted-environment process stalled without a result and was terminated (exit143); it is not a pass. The bounded invocation with environment network permission is recorded in /tmp/af-delivery-integration-portable.log.
- P7/P8 combined portable:27 passed,0 skipped,5.492s (/tmp/af-p7-p8-integration-portable.log).
- Ruff:passed. Architecture:480 modules,0 violations,0 coverage gaps.
- Whole production Pyright:0 errors/warnings. First invocation used the shared editable environment and reported10 unresolved current-worktree imports. A temporary config retained repository includes/basic mode/Python3.12, explicitly selected current platform/deployment/applications roots and the existing venv, then passed; the temporary config was removed. Both logs retained under /tmp/af-p7-p8-integration-pyright*.log. No type assertions or compiler diagnostics were weakened.

PR127 and128 are merged; maincd50b9ce348591b0014bbc7da53a0117790943cb [fast40211020781](https://github.com/Guanzhw/agent-factory/actions/runs/40211020781) succeeded. This does not cover the unmerged application combination. Final full, final UI/browser, exact PR heads and per-PR retarget reviews remain separate gates. C01–C04/D01–D03 require frozen real tasks, models/budgets, hardware, identity and tolerances; no paid provider or actual GPU was called.

## Completed full and final supplemental seams

Exact [full40211745245](https://github.com/Guanzhw/agent-factory/actions/runs/40211745245) at931f7c3dc9c92c2dbe17bdf468c2e66e93708050 completed SUCCESS in all seven jobs. PG:2073 tests,5 skips,0 failures/errors,1923.095s; all required groups passed19/5/102/16/10 with no skipped required cases. Windows Python:2073 tests,835 skips,0 failures/errors,304.332s. Independent core wheel installation/empty database/startup/shutdown, architecture/static checks and both frontend platforms passed. Synthetic/live labels in the PG summary remain modelLive=false, externalRemoteVerified=false, realCredentialsUsed=false.

That full predates the final evidence/association UI and three added acceptance cases. Production Python, dependency locks and workflow bytes are unchanged; do not claim the later head independently ran the earlier full. The final UI has its separate complete490-test check and two actual HTTP/PG/browser journeys. Screenshots, JSON, initial fixture failures and the minor historical status-metadata erratum are in [the UI verification](../connect-research-associations-and-delivery-workbench/verification.md). Its later driver lint failure CI40213434126 was fixed by removing unused names only; independent incremental review passed. No browser behavior was changed or rerun for that cleanup.

The missing seams were added after spec review: A06/A07 original cancelled UNKNOWN custody across hard restart; A04 actual two-endpoint native event cycle reaching budget refusal; A01 same-database removal followed by bare-core restart. Individually these passed27.594s,8.346s and14.488s. A01 retains its initial demo-mode fixture error and rejected over-strong oracle: positive original stop evidence permits failed execution settlement, but no fake research result or successor. Completely removed application declarations are not automatically reconstructed or finalized after reinstall.

All three new cases plus the existing successful research hard-restart case were then run together on integration4e0e794b381dee8e2517fa602a64bec58d749915:4 passed,0 skipped,65.334s,exit0. Command: `PYTHONPATH=platform:platform/tests:deployment:applications:applications/tests FACTORY_TEST_DATABASE_URL=<isolated-loopback-PG> timeout 180 <existing-venv>/bin/python -m unittest test_research_workflow_restart_postgres test_research_removal_postgres test_assistant_event_cycle_postgres -v`. Log:/tmp/af-final-acceptance-seams.log. This is supplemental execution, not a second2076-case full run. Collection finds2076 IDs with valid fast selection and executed=false; that collection is not another370 passing tests. Final Ruff passes after the driver cleanup.

Independent final reviews: A06/A07 931f7c3→2d7e816; A04 931f7c3→b024fe9; A01 931f7c3→7881c71; UI evidence2f1fb74→55e1419 and equivalent release0a5a1e4; driver cleanup0a5a1e4→f14bdae. All PASS. Existing assertions/deadlines were not weakened to chase green. Application removal follows the original positive-stop contract rather than adding perpetual holds or a new owner registry.

C01–C04/D01–D03, external identity and actual deployment/capacity remain BLOCKED/NOTRUN where real parameters or environments are absent. Historical MCP long-tail causality and lack of whole-suite speedup evidence remain limitations; this successful run does not prove those historical issues never recur.
