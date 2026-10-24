# Final stability investigation and complete validation

This continues the existing test-cost work after the seven Draft deliveries. No new product feature, relaxed deadline, GC setting change, automatic merge, deployment or paid external model call is authorized or performed.

## Unresolved failures are different stages

| Failure | Established evidence | Missing evidence / not established |
|---|---|---|
| MCP replacement task native20s wait: HTTP-auth rejection, slow DELETE, credential failure and DELETE405 capacity cases | Original first failure released/restart proceeded in several preserved failures; some later traces instead fail first-task capacity and must remain separate | Original failing claim/slot/callback timeline and task/run IDs absent in older traceback summaries; no basis to assign later passing trace identities |
| MCP DELETE authorization2s | A second-task credential callback began promptly but returned late; lease validation was cancelled, so UNKNOWN is required. One first-task callback took6.826s while SQL cursor time totaled4.104s; pool acquisition was submillisecond | Client cursor wall does not alone distinguish PG work, process suspension or GIL. No evidence to classify every20s failure as DELETE |
| ORX concurrent-reservation entered.wait(5) | Failure is before first POST gate; old whole-case14.69s includes executor join. On assertion failure the release gate is not set, so a later worker can additionally wait its original5s | No original worker-start/future-exception snapshot; cannot attribute to DNS, PostgreSQL or dispatch bug |
| Remote handoff13 parent native15s completion | Original parent remained non-completed; attempt2 and heartbeat-updated locked_at also occur in passing traces | No original claimed/slot/earlier-owned-work timeline; attempt number alone does not prove replay or starvation |
| Pure loopback initial2s readiness in #102 full | [Original full40120435697](https://github.com/Guanzhw/agent-factory/actions/runs/40120435697) failed before cancellation/DELETE, not native/PG authorization | Original pending task exception, transport construction and HTTP method timeline were absent. Current fixture surfaces early failure and releases/joins its owned tasks |

A separate real gen2 pause1.418670s overlapped dual-loop lag1.326699/1.339067s while callback CPU0.098949s and SQL55/sum0.109270s were small. That passing probe's observer retained objects, so the magnitude cannot be assigned to uninstrumented historical failures. Current bounded scalar diagnostics avoid that retention. One earlier controlled fresh-query pair reduced authorization83→55SQL and credential189→133SQL, but both passed; less work is not historical root-cause proof.

The Node initial failure is already distinguished: synchronous child spawn EPERM in the restricted execution environment; same binary permitted execution passed10 tests. Do not classify the timing failures as the same environment error.

## Predeclared bounded experiments

1. **ORX gate, one six-case sequence only.** Include the original adjacent actual-PG predecessor and the four preceding project cases, then the original concurrent-reservation case. Original bodies and5s gates unchanged. Record submit/worker-enter, future outcome type, gate entry/return, failure-time bounded thread frames and executor/cleanup end. Prediction: late worker start differs from immediate failed future; a release wait after failed entry explains cleanup extension without explaining the first failure. Outer180s watchdog is inconclusive, not a pass. No automatic retry.
2. **MCP, one fixed historical12-case prefix plus one initial-loopback case.** First and second native generations, exact claim owner (`locked_by`, not worker object's `worker_id`), callback queue/thread/CPU/SQL/await, pool, HTTP methods, loop heartbeat/GC and pre-teardown stacks. No secret/header/body/SQL parameters. A queued callback with responsive loops differs from slow in-thread SQL; simultaneous loop/GC pauses differ from a first-generation owner retaining a slot. A green run is inconclusive about old failures. Maximum13 cases, no retry loop.
3. Remote parent prefix is conditional on whether new lifecycle evidence can distinguish retained predecessor work; do not rerun an already-passing prefix just to collect another green result.

A calibration defect was reproduced before measurement: native claim snapshots read `worker_id`, while persisted native rows carry `locked_by`. The unchanged expected original owner fails before the test-only correction and passes afterwards with all six phase calibrations. This improves evidence, not runtime behavior or historical failure classification.

## Necessary final complete coverage

Only #98 exact5799403 has a current full success. Current#97 975488b, #99 42820a4, #100 f4ce910, #101 b4ce397, #102 ab24b72 and #103 74103b4 all changed after their last full run. Fast/targeted success does not replace complete verification of those changes.

Use one **validation-only union branch**, `verify/final-stack-20261024`, from#101 plus#102/#100/latest#103/latest#97 (includes#98/#99). Do not merge this branch into main or treat it as a combined feature-review PR. Preserve each existing Draft. Resolve task-board histories by preserving both; union selectors and keep pure traversal in the Python lane rather than duplicating it in PG. Automatically merged FactoryAPI and current ownership/resource bindings require review.

The final frozen union commit will receive complete Linux/PG discovery with all required groups, Windows compatibility discovery, both Web checks, core install/start/stop and applicable architecture/type/audit/browser checks. Publish exact commit/run/results below. This verifies the union, **not six standalone exact-head full successes**. Original failures/cancelled runs remain failures/cancelled. Targeted investigations happen before this integrated verification point; subsequent failures require a specific diagnosis rather than blind rerun.

## Results

Bounded experiments are complete. Frozen union complete verification passed; local raw logs supplement the versioned experiment sources and aggregate evidence below.

### Targeted outcomes (before final union)

- ORX fixed6case sequence passed, exit0; driver65.594s, observed cases24.892s (import/startup outside observer). Entered gate signaled in0.015516s, release wait0.001506s, future returned acknowledged; no initial failure reproduced. Do not assign historical5s failure to this timing.
- A separate deterministic **failure-path** probe injected a false entered-gate result only after the real worker reached POST. Before correction: original assertion remains1failure, worker release gate false and waits to its unchanged5s bound,5.099s body. After try/finally releases the owned gate before executor join: same1assertion failure remains, release wait returns true,0.107s body. This proves/fixes extra fixture cleanup waiting; it does **not** explain the historical initial gate delay. The normal original concurrency case and phase/snapshot calibrations subsequently12passed0.117s.
- MCP fixed13case sequence passed163.744s, driver174.634s, exit0; no retries and0 dropped events. This is not root-cause closure. [Scalar analysis](experiments/mcp-prefix-analysis.md) and [bounded timing data](experiments/mcp-prefix-analysis.json) preserve original synthetic operation identities. All 210 callbacks entered and finished; maximum callback queue12.499ms. Two CPU-active gen2 pauses1.934s/1.443s occurred during fixture startup, outside native claims/callbacks. Original claims, slots and callbacks ended before replacement generation startup. These observations exclude those overlaps for this run only; they do not establish historical causes. A395ms client cursor wall spike lacks backend wait evidence and must not be labelled a server lock or slow statement.
- Remote15s wait now emits bounded memory-only worker/await/thread diagnostics plus the last already-read task/ticket on failure. No new database/HTTP access, task scheduling, cancellation or recovery; no deadline change. Five pure calibrations cover redaction, bounds, no-I/O and retaining the original assertion. The original remote prefix is not repeated merely for another green run; final full provides the necessary changed-code observation point.

Reproducible experiment sources are versioned in [experiments/](experiments/). Use a disposable PG fixture and the selected checkout's locked environment; `mcp_prefix_probe.py --repo <checkout> --output <new.jsonl>` exclusively creates its output, and `orx_gate_probe.py --with-pg-predecessor` runs exactly six cases. The negative gate probe intentionally retains one assertion failure; `--expect-release false/true` checks before/after fixture cleanup, not product acceptance. No real provider credentials are needed or used.

### Frozen complete-validation point

Validation-only commit [`8de058a9639d3baf8f98e36f60be94cdd31d2f7c`](https://github.com/Guanzhw/agent-factory/commit/8de058a9639d3baf8f98e36f60be94cdd31d2f7c) contains the seven Draft source heads plus this investigation's test-only correction. [Full run40129163038](https://github.com/Guanzhw/agent-factory/actions/runs/40129163038) was dispatched once using `gh workflow run ci.yml --ref verify/final-stack-20261024`; all seven jobs reached success. No integration PR or main merge was created.

| Draft | Source head in union | Previous full evidence and remaining gap before union |
|---|---|---|
|#97|975488b2cf3aedeb34265619dc30dbbefc307521|965350f full40112603820 failed; latest observer/read-path corrections needed complete validation|
|#98|579940331648e2ef99340af872292aa1065dcd4b|Exact full40101966363 passed|
|#99|42820a43262cc513a1433078976f461add1cdab7|1d2bbb7 full40116074034 failed; remaining graph fixtures corrected|
|#100|f4ce910835fb9f399b8039cdeb96d84f2f40d291|a011ff8 full40118326022 failed; receiver-finalizing fixture corrected|
|#101|b4ce397af506ad3cf70f39155ed6c82c9eba92ee|d1ec7e9 full40123407895 failed; observer isolation and checkout bytes corrected|
|#102|ab24b72a88b505ecd917ec78a1b8a7230dbce845|05bda51 full40120435697 failed; Windows fixture paths corrected, readiness diagnostics added, historical timing cause unclosed|
|#103|0d157ff5558a3a3fe4af2418a90c793aed2bfca8|7fe8d90 full40110374707 passed; subsequent fresh authority reads, fixture ownership and current diagnostics needed complete validation|

Independent semantic review checked the union's FactoryAPI merge, remote supported-contract addition, native operation/account identity binding and guardian reaper; no concrete blocker found. CI-selector union preserves both features and class-scopes PG bulk-governance selection so its pure traversal tests remain in the Python lane. Independent diagnostic review approved original assertion/deadline preservation and bounded memory-only snapshots.

Union preflight `ruff check platform apps/research deployment scripts`, `pyright`, and `python scripts/check_architecture.py --config scripts/architecture-python.json` exited0 in45.333s: Ruff passed, Pyright0errors/0warnings, architecture785modules/0violations/0coverage gaps. OpenSpec strict exited0. An attempted `check_python.py --help` does not support help and started discovery/execution; it was stopped after9.398s (exit-15), recorded as **aborted, not a validation pass**, and is not the final full run. No timeout or assertion was altered to accommodate it.

Owned local PG `af-history-targeted` was stopped after experiments, retaining its state; Docker reported `exited`,2CPU/1GiB/pids256 limits. No other database/container was stopped. Full CI uses its own isolated service.

### Existing-trace critical-path analysis (no extra run)

[Replacement operation timeline](experiments/mcp-replacement-critical-path.md) separates intentional two-call workload from runtime validation cost. The two passing MCP invocations lasted6.455s/7.116s. Serial fresh authority→credential→authority chains precede individual HTTP sends; callback intervals cover~99% of invocation wall, with concurrent monitor overlap. Each invocation executed2659/2714 successful client SQL cursors. HTTP response-header intervals total only68/84ms, but do not include complete response streams. The replacement echo server has no intentional sleep.

This identifies substantial repeated freshness work on the observed critical path; it does not prove a removable duplicate, a PostgreSQL lock, or historical timeout causality. The second DELETE preparation took~1.205s within its existing2s budget; no failed deadline occurred. No guard was cached, removed or weakened.

At the frozen union, Windows complete discovery passed3517 tests in250.295s:2228passed/1289explicitly skipped, zero failures/errors. Both Web jobs passed728tests each plus10AST-checker tests; Linux audit production/all0vulnerabilities and configured/bind-loss Chromium smoke passed. Linux/Windows Ruff, Pyright and architecture steps passed. PG full subsequently passed as recorded below.

The #103 exact source0d157ff fast run[40129100361](https://github.com/Guanzhw/agent-factory/actions/runs/40129100361) passed:Python271/0skip24.539s andPG59/0skip153.476s; required groups all passed. This is fast acceptance, separate from combined full.

Read-only call-graph review found no proven-safe deletion of fresh authorization guards: original execution plan, execution bindings, current stored material/tool and account/vault checks have distinct inputs and timing. A narrower credential-row projection could avoid fetching unused ciphertext during authorization, but would not reduce query count and has no measured timing benefit. It was not implemented as a purported timeout fix.

Local execution resources were cgroup4CPU (`400000 100000`) and16GiB (`17179869184`), Python3.12.14, uv0.12.19, Node24.19.0. The isolated union used its own frozen/offline `.venv`. CI independently uses workflow-pinned uv0.12.1 and Python3.12/Node24; hosted runner results are not target32core/64GB or54core/192GB capacity acceptance. No paid models, production credentials or external scientific-provider acceptance were exercised.

At20:47UTC the local `gh run watch` command exited1 because its GitHub API credential returnedHTTP401, **not because CI failed**. The already-used authorized GitHub connector still reported the original PG job in progress. No new OAuth/login, credential extraction or test restart was performed. Subsequent CI status uses that existing read-only connector; this does not establish CLI push/write access.

### Final terminal result and remaining limits

**Full run40129163038 succeeded at exact union8de058a.** [Machine-readable results and all71 PG skip reasons](experiments/final-validation-summary.json) retain job IDs and required-group outcomes. PostgreSQL:3517run,3446passed,71skipped,0failures/errors,1815.409s. All seven required groups passed, with no skipped required case. Windows:3517run,2228passed,1289skipped,0failures/errors,250.295s. Both Web jobs:728tests plus10AST-checker tests each. Linux production/all dependency audits:0vulnerabilities; configured/bind-loss Chromium smoke passed. Independent core wheel installation, startup, native worker, application absence and clean shutdown all passed.

The71 PG skips are explicit opt-in actual ORX/Chromium/retrieval/literature/SSH and dump/restore acceptance, not successful executions. Required-group counts are130/33/9/11/10/19/6. The prior local real ORX evidence remains scoped to its recorded commits and scenarios; this CI does not upgrade fixture results to live providers or production capacity acceptance. Expected negative-path exceptions in the raw log are not failed unittest outcomes.

This is one necessary validation of final combined code, with no repeat attempt. It does not demonstrate an overall speedup: the earlier same-condition local before/after remained3555.380s versus3807.505s, both with failures; this hosted run has different code, environment and coverage. Historical MCP/native20s, pure readiness2s, original ORX gate5s and remote parent15s failures remain unclosed. Current probes identify fresh-validation cost and exclude specific queue/owner/GC overlaps **only for this observed passing run**. They cannot recover absent historical thread/backend timelines. No further unchanged prefix rerun is justified as root-cause proof.

Independent review approved the concrete fixture/diagnostic fixes. Local temporary PG is stopped, the read-only CI watcher exited after credential failure, and all observed CI jobs completed their cleanup. Seven feature Drafts remain separate; no main merge, auto-merge, deployment or paid call occurred.
