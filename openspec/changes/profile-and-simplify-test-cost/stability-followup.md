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

Bounded experiments are complete. Frozen union complete verification remains pending; local raw logs supplement the versioned experiment sources and aggregate evidence below.

### Targeted outcomes (before final union)

- ORX fixed6case sequence passed, exit0; driver65.594s, observed cases24.892s (import/startup outside observer). Entered gate signaled in0.015516s, release wait0.001506s, future returned acknowledged; no initial failure reproduced. Do not assign historical5s failure to this timing.
- A separate deterministic **failure-path** probe injected a false entered-gate result only after the real worker reached POST. Before correction: original assertion remains1failure, worker release gate false and waits to its unchanged5s bound,5.099s body. After try/finally releases the owned gate before executor join: same1assertion failure remains, release wait returns true,0.107s body. This proves/fixes extra fixture cleanup waiting; it does **not** explain the historical initial gate delay. The normal original concurrency case and phase/snapshot calibrations subsequently12passed0.117s.
- MCP fixed13case sequence passed163.744s, driver174.634s, exit0; no retries and0 dropped events. This is not root-cause closure. [Scalar analysis](experiments/mcp-prefix-analysis.md) and [bounded timing data](experiments/mcp-prefix-analysis.json) preserve original synthetic operation identities. All 210 callbacks entered and finished; maximum callback queue12.499ms. Two CPU-active gen2 pauses1.934s/1.443s occurred during fixture startup, outside native claims/callbacks. Original claims, slots and callbacks ended before replacement generation startup. These observations exclude those overlaps for this run only; they do not establish historical causes. A395ms client cursor wall spike lacks backend wait evidence and must not be labelled a server lock or slow statement.
- Remote15s wait now emits bounded memory-only worker/await/thread diagnostics plus the last already-read task/ticket on failure. No new database/HTTP access, task scheduling, cancellation or recovery; no deadline change. Five pure calibrations cover redaction, bounds, no-I/O and retaining the original assertion. The original remote prefix is not repeated merely for another green run; final full provides the necessary changed-code observation point.

Reproducible experiment sources are versioned in [experiments/](experiments/). Use a disposable PG fixture and the selected checkout's locked environment; `mcp_prefix_probe.py --repo <checkout> --output <new.jsonl>` exclusively creates its output, and `orx_gate_probe.py --with-pg-predecessor` runs exactly six cases. The negative gate probe intentionally retains one assertion failure; `--expect-release false/true` checks before/after fixture cleanup, not product acceptance. No real provider credentials are needed or used.
