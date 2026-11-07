# Native research Skills and independent continuation

This branch starts from main `15e192b` after PR #177. It adds reusable research capabilities to Agno 3.1.0 rather than introducing another research runtime or a fixed experiment sequence.

## Implementation

- Agno `Skills` and `LocalSkills` load bundled research skills, the launch project's `.agents/skills`, and optional external `FACTORY_SKILL_PATHS`. Instructions, metadata, script source and reference reading use the native implementation. The small loader extension discovers nested resources, which the pinned loader otherwise omits.
- Native script execution uses synchronous `subprocess.run` with a default 30-second timeout. The adapter instead calls the existing cancellable research command function. Arguments, shebang interpreter flags, cwd, exit code, stdout/stderr and complete output files follow that existing path. There is no new command deadline or execution service.
- The default cwd is the session workspace. Explicit cwd can select an external skill directory using `source_path` returned with its instructions. Commands already run with the service account's host permissions; this is not an OS sandbox. Output logs stay in the session. Files created elsewhere are not automatically copied into chat downloads.
- Two bundled skills describe optional research iteration and evidence analysis. Their references discuss selecting useful checks and interpreting comparisons. Neither imposes phases, experiment IDs, a fixed number of attempts or a shared evaluator protocol.
- Research records accept observations and ordinary file/URL/result references. Analysis can be standalone or attached to an existing record without requiring a terminal record. Historical records remain readable.
- Unknown results stay unknown, with their original identities. They no longer stop every other tool or the next model call. Repeated original calls are not dispatched again. A genuinely ended native turn can permit independent new work without rewriting its unresolved effects. Automatic retries that could repeat side effects remain stopped; once the original native run ends, the user can start an independent turn. Stop is checked against the current transaction row, including a concurrent stop request.

No production deployment or WSP run was performed.

## Verification

The local full minimal suite passed **18/18 in 99.130 seconds** before the final external-cwd adjustment. The updated external Skills journey then passed in **48.150 seconds**: actual native instructions/reference/source access, a script with preserved `-O`, Chinese/space arguments, default and explicit cwd, exit 7 followed by a 31-second successful run, and a byte-correct browser download. The added step reads an ordinary asset from the skill's own directory. Final-head CI is recorded in the PR.

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

## Frontend integration handoff

The local frontend session `01a1b720-a561-7d40-af4c-4bcb7a835dfa` has uncommitted work. No local workspace or `web/` file was overwritten. Keep both branches and merge these shared files deliberately:

| File | Cloud change | Preserve from local frontend |
| --- | --- | --- |
| `applications/research/session_tools.py` | Optional research-record schemas; unknown facts returned instead of global stop; normal cwd handling in existing command path | Add actual tool arguments to the existing started/finished events. Cloud script execution reuses `research_run`, so these arguments identify the executed script and its parameters. |
| `applications/research/sessions.py` | `_refresh`, `_safe`, `_model_boundary`, `read`: distinguish an ended native turn from unknown effects; preserve current Stop and active children | Current-turn `messages[0].text` as goal. The cloud branch does not change `_start`. Do not label each tool successful merely because the turn ended. |
| `platform/agent_factory/runtime.py` | Reserve native Skills tool names when assembling personal tools | SSH native pre/post hooks carrying callId, arguments, outcome and output. These can coexist with the Skills name reservation. |

Additional wiring: `main.py` exposes the existing executor in application state; research installation assigns its native Skills instance in `public.py`. No new HTTP route, required frontend field or database table was introduced. Native skill reading is retained in Agno's run history; script execution emits the existing research command events. Frontend integration and acceptance of its uncommitted changes remain separate from this branch's backend verification.

Windows execution, actual remote SSH/MCP research, distributed cancellation and the local frontend's final combined experience remain unverified by this work.
