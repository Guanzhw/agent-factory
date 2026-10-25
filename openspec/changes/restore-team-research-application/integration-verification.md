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
