# Local remote-process PostgreSQL admission diagnosis

## Scope and result

This closes the investigation of local PG08/10 failures retained with PR43
`2628e4be74f9c31def9208ea32b05405a54b79d6`. It does not mark those tests passed.
One serial diagnostic reproduction on the same existing task PostgreSQL service
failed both tests in 164.345 seconds, before their intended running-process
assertions. Original lease durations, authority checks, observers and production
code were unchanged. No model request, ML workload, GPU, new database container,
resource increase or target storage operation was used.

The new observations identify admission deadlines crossing before dispatch.
They do not prove that the earlier run, which lacked these observations, followed
an identical path, or that CI success explains the earlier failure.

## Environment established without credential disclosure

The test process was launched by `uv run --offline --no-sync python`; its outer
system-Python helper only constructed the private synthetic database environment.
The actual interpreter was CPython 3.12.14. Agno 3.1.0, SQLAlchemy 2.1.1,
psycopg 3.3.6, httpx 0.28.1, FastAPI 0.142.2 and uvicorn 0.54.0 matched `uv.lock`.
Fixture services used the test interpreter's base executable and its site-packages.

Read-only current measurements showed a 4-CPU/16-GiB execution cgroup and an
existing PostgreSQL container limited to 1 CPU/1 GiB. CI uses the same PostgreSQL
image without that explicit container cap. Current `oom`/`oom_kill` counters were
zero. These configuration differences are not proof of the cause of an individual
SQL/authority delay; no failure-time CPU, lock-wait or OOM cause was established.

## PG08: rejected before durable provider intent

The process wall limit of 0.3 seconds produces the existing `ceil` reservation of
1 second. The original lease deadline was `2026-10-06T14:18:09.994809+00:00`.

| Real observation (UTC) | Evidence |
|---|---|
| 14:18:09.907139 | Provider allocate entered, 87.670 ms before deadline |
| 14:18:09.909285 | Provider's first fresh authority callback entered, 85.524 ms before deadline |
| 14:18:12.538531 | Callback rejected with HTTP409 / `ADMISSION_WORK_ENDED`, after 2.629246 seconds and after the unchanged deadline |
| 14:18:12.684345 | The same allocation error propagated |
| 14:18:34.879825 | Timeout: no provider allocation row, zero launch-method calls, no custody; lease `UNKNOWN`, capacity held |

`ResourceManager` already performed an admission check before entering the
provider. The provider repeats fresh authority before its allocation insert.
That repeat crossed the original deadline and rejected before a provider row or
process existed. The resource manager conservatively stored UNKNOWN; subsequent
process inspection could not load a provider allocation. This explains the
reproduced missing-allocation exception and failure to reach RECLAIMED.

The callback's fixed rejection combines terminal/cancellation/expiry checks;
expiry is positively observed, but the later task cancellation snapshot does not
prove the task's exact cancellation state at callback time. No OS launch failure
is inferred.

This exposes an existing availability limitation: rejection before provider
intent can retain UNKNOWN capacity. Missing rows or zero launch counters alone
are not durable provider stop proof. A future repair would need an explicit,
identity-bound, durable no-effect result and replay/concurrency checks; this
investigation does not add an unsafe absence-based release rule.

## PG10: original PREPARED custody was never dispatched and safely reclaimed

The original 5-second lease deadline was `2026-10-06T14:19:40.535945+00:00`.
Four fresh provider callbacks returned before that deadline. The fifth entered
at `14:19:39.981241`, then rejected with `ADMISSION_WORK_ENDED` at
`14:19:41.195325` after 1.214084 seconds. The provider returned its durable
uncertain snapshot at `14:19:41.260250`.

At `14:19:42.786411`, the actual cancellation diagnostic recorded the original
runtime reason `LEASE_EXPIRED`, PREPARED custody, and task cancellation/terminal
both false. Final facts showed:

- The same lease RECLAIMED, execution CANCELLED, exit code null.
- Positive `never-dispatched` / all-stopped proof and capacity released.
- Original custody CANCELLED with no child or guardian pin.
- One call to the adapter's `launch` method; its authority gate prevented OS
  dispatch. This count is not a count of spawned processes.
- No read-disconnect fault had yet been installed.

The wait for RUNNING therefore failed because no RUNNING process existed.
This was neither a missed RUNNING poll nor interpreter exit125. The later
`PROCESS_EXECUTION_FAILED_WITH_STOP_PROOF` correctly preserved the unsuccessful
outcome. Deadline cancellation and reclaim behaved as designed.

## Evidence and boundaries

The new fixture records at most 128 in-memory allocation events plus a dropped
count. It adds no SQL to the dispatch callback. Original return values and raised
exception identities are preserved. Errors use finite categories and exact
allowlisted codes; arbitrary messages, credentials and configuration are excluded.
Timeout facts are gathered only after the original wait has failed. Read snapshots
are not an atomic historical view and in-memory events do not survive restart.

Private local evidence directory: `/workspace/scratch/local-pg-diagnosis-20261006`.
It contains the unchanged original log copy, diagnostic run, extracted bounded
observations and hashes. The original remains in the previous PR43 evidence
folder; its bytes were verified unchanged.

| Evidence | SHA-256 |
|---|---|
| Original local two-failure log (134.832s) | `e68fa1adeb60c2fe8edfbe66f34a3c593d16398e78d7f5fd531ed5b393159189` |
| Diagnostic two-failure log (164.345s) | `1f7da9bf8b00dcd7a40dc3d8a5906585ea1e68e5f919dd944ea1e287952cfe4f` |

Both local failures remain failures. Their running-phase prerequisites were not
met within the fixed local admission budgets. The latency's underlying resource
cause is unproven. No deadline enlargement, skipped assertion, fake timestamp,
production lifecycle change or blind repeat is used to convert this into a pass.
Independent review confirmed both observed mechanisms and these limits.

Validation: seven pure diagnostic tests passed; full non-PG Python suite
1662 = 1266 passed + 396 skipped in 164.905 seconds; repository Ruff and
configured-project Pyright passed. Exact-head Draft PR CI is recorded separately.
