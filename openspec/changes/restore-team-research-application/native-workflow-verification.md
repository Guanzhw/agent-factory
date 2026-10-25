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

- The independent core identity fix removed the identity exception, but the child target still failed (18.630 s): the nested branch never reached evaluation. Installed Agno 3.1.0 `workflow.py:9126–9179` routes the paused inner executor then continues the outer step loop, skipping the remaining nested branch. The application will use flat top-level steps and native `StepOutput(stop=True)` for the stop decision. The exploratory core code fix was reverted in this application branch; its separate spec and original evidence remain. This avoids a second recovery mechanism or patching Agno.

## Flat consumer and review corrections

The final consumer uses only top-level native steps; the stop decision uses native `StepOutput(stop=True)`. The exploratory nested-identity core code was reverted before these runs. Historical failures above remain failures; they are not overwritten by the following changed-code validation.

| Check | Actual result |
| --- | --- |
| Flat immediate stop + actual child output/evaluation | 2 passed, 25.819 s, exit 0 |
| Actual completion transaction rollback + P3 original successor admission | 2 passed, 36.661 s, exit 0 |
| Actual paused consumer process SIGKILL and same-database restart | 1 passed, 23.558 s, exit 0 |
| Final portable protocol/service/migration/privacy cases | 13 passed, 1.858 s, exit 0 |
| Ruff / current-source Pyright / architecture | passed / 0 errors and warnings / 442 modules, 0 violations, 0 gaps |

Rollback assertions check the positively stopped original root remains nonterminal, its allocation remains BOUND, and no domain terminal/continuation is published after a controlled publication failure. Releasing that fixture fault lets the existing observer complete the same root and settle the original allocation once. The actual P3 case admits one successor allocation/root from one original event; the successor model receives the private original child observation and reaches its own decision. It does not create another experimental child unnecessarily.

The restart case gates only the fixture's original-wait observation, waits for a real paused parent and completed native child, kills the server process, then restarts with the same database/workspace/component. It verifies unchanged original root and child task/run IDs, a completed research decision, and idempotent start replay with no additional task. This is process recovery evidence with a synthetic model, not live model or remote GPU acceptance.

Independent review rejected automatic sharing of all child artifacts. That behavior is removed: the team receives curated conditions, operation/runtime facts and labelled agent analysis. The owner retains the original result/artifacts. A real SQLite private artifact canary proves Alice can read the bytes, Bob can read the terminal summary but cannot read the unselected artifact. Explicit curated artifact selection and full P7 team evidence access remain pending. A separate migration fixture now inserts rows before the first migration, demonstrates the old unique constraints by actual duplicate-write rejection, migrates, permits the new multiple associations, and preserves exact old IDs/content after reopening.

The rollback/P3 run emitted a psycopg unclosed-connection ResourceWarning. The TestClient fixture now explicitly disposes its owned root-lock connections before engine disposal; this is not a production timeout or assertion change. A temporary Pyright configuration initially used ignored absolute include paths; that check was terminated and is not counted as passing. The corrected relative includes restrict the successful check to this worktree's application and assembly sources.

Additional original local logs: `flat-stop-child-first.log`, `rollback-p3-first.log`, `hardrestart-first.log`, `portable-final.log` under `/tmp/research-native-workflow-evidence/`; the privacy/migration review correction log is `/tmp/research-rounds-review-fixes-behavior.log`. These outcomes do not stand in for the parent integration's complete applicable suite or exact-commit CI.

The coordinator subsequently found and stopped two stale Pyright parent/child groups from earlier temporary configurations, each using roughly one CPU. Their scene is retained at `/tmp/af-research-next-evidence/stale-pyright-processes.txt`. The local durations above are recorded execution times, not isolated performance measurements; functional assertions remain valid. This resource contention does not establish the cause of unrelated historical failures. Subsequent temporary static checks must use correct relative includes and an explicit bounded timeout.
