# Native research Skills and independent continuation

This branch starts from main `15e192b` after PR #177. It adds reusable research capabilities to Agno 3.1.0 rather than introducing another research runtime or a fixed experiment sequence.

## Implementation

- Agno `Skills` and `LocalSkills` load bundled research skills, the launch project's `.agents/skills`, and optional external `FACTORY_SKILL_PATHS`. Instructions, metadata, script source and reference reading use the native implementation. The small loader extension discovers nested resources, which the pinned loader otherwise omits.
- Native script execution uses synchronous `subprocess.run` with a default 30-second timeout. The adapter instead calls the existing cancellable research command function. Arguments, shebang interpreter flags, cwd, exit code, stdout/stderr and complete output files follow that existing path. There is no new command deadline or execution service.
- The default cwd is the session workspace. Explicit cwd can select an external skill directory using `source_path` returned with its instructions. Commands already run with the service account's host permissions; this is not an OS sandbox. Output logs stay in the session. Files created elsewhere are not automatically copied into chat downloads.
- Two bundled skills describe optional research iteration and evidence analysis. Their references discuss selecting useful checks and interpreting comparisons. Neither imposes phases, experiment IDs, a fixed number of attempts or a shared evaluator protocol.
- Research records accept observations and ordinary file/URL/result references. Analysis can be standalone or attached to an existing record without requiring a terminal record. Historical records remain readable.
- Unknown results stay unknown, with their original identities. They no longer stop every other tool or the next model call. Repeated original calls are not dispatched again. A genuinely ended native turn can permit independent new work without rewriting its unresolved effects. Automatic retries that could repeat side effects remain stopped; once the original native run ends, the user can start an independent turn. Stop is checked against the current transaction row, including a concurrent stop request.

Including the file-list follow-up, source totals **20,155 physical lines across 140 files**, including tests. Production changes are +276/-181 (net +95) and minimal regressions +445/-3 relative to main. No production deployment or WSP run was performed.

## Verification

The local full minimal suite passed **18/18 in 99.130 seconds** before the final external-cwd adjustment. The updated external Skills journey then passed in **48.150 seconds**: actual native instructions/reference/source access, a script with preserved `-O`, Chinese/space arguments, default and explicit cwd, exit 7 followed by a 31-second successful run, and a byte-correct browser download. The added step reads an ordinary asset from the skill's own directory. On implementation commit `bf8ad58`, CI passed all 18 cases in **71.741 seconds**; frontend/backend checks and CodeQL also passed. The PR records checks for later documentation-only commits.

The suite uses real PostgreSQL, Agno queue, HTTP model adaptation, Chromium and local processes. Its model server is scripted. Unknown-response integration injects one adapter error, then checks independent file operations and a new turn while the original database effect remains UNKNOWN and the adapter call count remains one. Stop tests verify actual process PIDs before and after cancellation. Focused session snapshots cover queue retry and a concurrently recorded Stop. These are different kinds of evidence, not a claim that every service was exercised remotely.

Ruff and Pyright passed; Pyright retains six Windows-only import warnings in this Linux environment. Frontend lint/types/build passed with the existing CSS/bundle warnings. A wheel build included both bundled SKILL.md files and their references. Independent review found and resolved lost shebang flags and a Stop observation race.

## Live model: synthetic curve capability exercise

Configured provider: **OpenCode Go**, `https://opencode.ai/zen/go/v1`, OpenAI-compatible Chat Completions adapter. Requested model: **`deepseek-v4.1-flash`**. This used the authorized subscription, not the scripted test model. The provider's internal deployment is not independently identified by this configuration.

Task: use a task-specific external skill and its ordinary evaluator script to investigate 61 synthetic curve measurements (45 train, 16 validation). The Agent selected candidates, fitted them, ran the evaluator, interpreted results, adjusted candidates, wrote `report.md`, and saved a standalone `research_assess` analysis with file references. No experiment ID was supplied as a prerequisite. Runtime: **437.6 seconds**, completed with no recorded failure.

The Agent compared degrees 0–9, then tried robust and regularized variants and coefficient rounding selected using train-only cross-validation. Independent recomputation from the retained data and coefficient files gives:

| Candidate | Validation RMSE |
| --- | ---: |
| Zero baseline | 3.2821840866 |
| OLS quadratic | 0.0222474645 |
| Selected rounded quadratic | 0.0204336822 |

This proves a live model/tool/research-record loop on a small synthetic problem. It is **not complete research acceptance**, a scientific-quality certification, a WSP result, or proof of remote compute capabilities. The model's interpretation and uncertainty claims require ordinary scientific review. Evidence is retained outside the repository under `/workspace/agent-factory-cleanup/native-skills-live/`.

## Live model: repository search investigation

The same OpenCode Go / `deepseek-v4.1-flash` configuration completed a separate investigation in **2,580.7 seconds**, with **116 parent tool executions** and a completed model-driven child audit. The task studied literal-search correctness and performance against 78 actual production Python files (816,691 bytes); independent hashes match the source, which the experiment did not modify. Replicated corpora and a concatenated large file were additional synthetic workloads, not independent datasets.

The Agent wrote its own evaluator, compared traversal and byte-prefilter candidates, corrected real script failures, and delegated adversarial checking. Its child found a permission-error regression: an optimized traversal could return empty success where the baseline raises `PermissionError`. The parent resumed automatically and produced candidate D, retaining original traversal and only adding the prefilter. It wrote a report and ordinary research records. These experimental candidates were not adopted into product code.

Independent replay covered 187 candidate/case comparisons; D passed all 49 of its comparisons. A separately constructed permission counterexample reproduced the earlier candidates' empty-success regression and confirmed D matches the baseline. After the model and collection processes stopped, independent warm-cache timing used equally represented, randomly shuffled implementation-order permutations, with 120 samples per query/implementation:

| Query | Baseline median | D median | Baseline / D |
| --- | ---: | ---: | ---: |
| Absent token | 5.293 ms | 2.038 ms | 2.60× |
| `research_search` | 5.189 ms | 2.319 ms | 2.24× |
| `workspace` | 5.566 ms | 3.133 ms | 1.78× |
| `def ` | 7.612 ms | 7.729 ms | 0.985× |
| `e` | 24.074 ms | 25.020 ms | 0.962× |

Sparse queries benefit; dense queries do not show a useful gain. These are local search microbenchmarks, not cold-cache measurements or application throughput claims. This run demonstrates autonomous investigation, failure recovery, child review and revision on real repository data; it does not establish general scientific validity or remote research readiness.

Evidence is retained at `/workspace/agent-factory-cleanup/native-skills-repo-research/`: native parent/child history, session, report and candidate files, plus `independent-verification.json` with raw timing samples. The driver's final recursive archive failed on deliberately adversarial deep directories after the research completed. A separate collector retained ordinary files and special-file metadata. The saved screenshot shows the completed page's tool area; it is not evidence of final-report download. Only this run's disposable database was deleted after confirming native `COMPLETED`.

A separate minimal real HTTP/PostgreSQL check reproduced a delivery gap: an unreadable child directory makes the entire file list return 503, although direct download of root `report.md` returns 200 and matches all 23,757 bytes. Restoring permissions and creating 1,100 nested directories still gives a successful list and download; the archiver failure therefore does not imply an API recursion failure. `file-delivery-verification.json` records this. The follow-up fixes this by returning `{files, errors}`: accessible files remain available and each read failure includes its workspace-relative path and operating-system reason. `SessionFiles.tsx` displays these warnings beside the usable list. The existing browser journey now checks actual directory permission failure, a byte-identical download while the warning is visible, and warning removal plus restored contents after permissions recover and the user refreshes. The extended real HTTP/PostgreSQL/Chromium journey passed in 25.217 seconds; its screenshot is retained at `/tmp/factory-partial-files.png`. Ruff, Pyright and frontend lint/types/build passed; independent code review found no blockers. This is a non-root POSIX check, not Windows permission validation.

## Frontend integration handoff

The local frontend session `01a1b720-a561-7d40-af4c-4bcb7a835dfa` has uncommitted work. No local workspace was overwritten. The cloud branch now changes only `web/apps/research/SessionFiles.tsx` for the file-list follow-up; integrate that contract with the local rewrite. Keep both branches and merge these shared files deliberately:

| File | Cloud change | Preserve from local frontend |
| --- | --- | --- |
| `applications/research/session_routes.py` and `web/apps/research/SessionFiles.tsx` | Files response is now `{files: [{path, size}], errors: [{path, message}]}`; render accessible files and each unreadable-path warning; refresh replaces both | Carry this response shape and warning behavior into the local files UI; download URL is unchanged. |
| `applications/research/session_tools.py` | Optional research-record schemas; unknown facts returned instead of global stop; normal cwd handling in existing command path | Add actual tool arguments to the existing started/finished events. Cloud script execution reuses `research_run`, so these arguments identify the executed script and its parameters. |
| `applications/research/sessions.py` | `_refresh`, `_safe`, `_model_boundary`, `read`: distinguish an ended native turn from unknown effects; preserve current Stop and active children | Current-turn `messages[0].text` as goal. The cloud branch does not change `_start`. Do not label each tool successful merely because the turn ended. |
| `platform/agent_factory/runtime.py` | Reserve native Skills tool names when assembling personal tools | SSH native pre/post hooks carrying callId, arguments, outcome and output. These can coexist with the Skills name reservation. |

Additional wiring: `main.py` exposes the existing executor in application state; research installation assigns its native Skills instance in `public.py`. No new HTTP route or database table was introduced. The existing files response changes as described above, so deploy/integrate its backend and frontend together. Native skill reading is retained in Agno's run history; script execution emits the existing research command events. The existing API may label a native child wait `waiting_approval`; `research_wait_child` is automatically resumed from the child result, not a request for human approval. Preserve the existing frontend child-aware waiting display. Frontend integration and acceptance of its uncommitted changes remain separate from this branch's backend verification.

Windows execution, actual remote SSH/MCP research, distributed cancellation and the local frontend's final combined experience remain unverified by this work.
