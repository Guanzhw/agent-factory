# Guarded native scheduling

Agno 3.1.0 provides the persistent schedule clock and poller. Factory scheduling
adds admission checks around its public executor interface; Agno's durable queue
continues to own runs, sessions, pause/resume and execution recovery. No timer,
queue, agent loop or upstream fork is introduced here.

## Integration contract

`SchedulingService(settings, store, native_db, auth, bridge)` implements the
public `SchedulePoller` executor method
`execute(schedule, db, release_schedule=True)`. Call `initialize()` before serving
its API. The application owner starts/stops it once in the application lifespan
with `start()`/`stop()` or its `lifespan(app)` context manager. Keep AgentOS's
built-in `scheduler=False` to avoid a second poller. The default schedule polling
interval is 15 seconds; `settings.schedule_poll_seconds` can override it.

Expose only authenticated Factory wrappers. Pass the verified principal ID,
never a body-supplied owner. Deny external native `/schedules` routes, including
trigger; the stock executor cannot perform Factory task admission. Native
`/agents/factory-executor` routes also remain behind the trusted in-process
`NativeBridge`. Before enabling the feature, the application's routes and
lifespan must satisfy these constraints.

| Service operation | Input and authority |
| --- | --- |
| `create(owner, plan_id, name, cron, timezone="UTC")` | Current managed `components:write` and executor `run`; own ready, top-level immutable plan |
| `list(owner)`, `get(owner, id)`, `occurrences(owner, id)` | Current executor `run`; owner partition |
| `update(owner, id, cron, timezone="UTC")` | Current managed write/run; cannot change plan or owner |
| `set_enabled(owner, id, enabled)` | Current managed write/run; enabling repeats plan/policy checks |
| `await trigger(owner, id, request_id)` | Current managed write/run; scoped stable manual request key |
| `await cancel_occurrence(owner, id, occurrence_id)` | Current executor run; exact owned occurrence/task, existing cancellation tree |

The demo grants schedule-management permission to its manager persona. Runner
personas cannot create schedules. This is an explicit restricted initial
authority policy, not a grant inferred from model output. A schedule stores only
`planId` and `planHash`; callers cannot supply URLs, session state, owner IDs,
versions, raw agent configuration or credentials. Plan material/version snapshots
remain owned by the existing immutable plan store. Delegation-bound child plans
cannot be scheduled as independent roots.

## Admission and recovery

Native `ScheduleManager` persists schedules with Factory provenance and zero
native retries. Trusted definition hashes in `af_schedule_bindings` detect
unexpected native-row changes. Each automatic occurrence uses the persisted
owner, schedule ID and due timestamp; each manual occurrence uses the owner,
schedule ID and request ID. A changed definition with the same manual key returns
an explicit conflict.

Before submission, the executor reads CURRENT directory/grants, the immutable
plan, and CURRENT execution policy. `Store.reserve_task` enforces the existing
per-user and aggregate active-task budgets transactionally. Every new occurrence
gets a fresh task UUID/session and its own native queue run. A PostgreSQL advisory
lock serializes admission and schedule edits without blocking another async
handler. Native submission is bounded to 30 seconds.

`af_schedule_occurrences` persists the occurrence-to-task binding before native
submission. The existing bridge provides a task/subject-namespaced native
idempotency key. Duplicate or interrupted reservations inspect their exact native
ticket; they never submit again automatically. An unobserved acknowledgement
stays `unknown`, and its task retains capacity. Startup performs bounded ticket
reconciliation of uncertain receipts, not submission retries. Ambiguous native
tickets remain an error. A crash before the task binding remains an explicit
unknown receipt needing operator reconciliation.

Native `ScheduleRun` entries record **admission** status (`accepted`, `rejected`,
`unknown`) and link the native run/session immediately. Their `completed_at`
denotes completion of this admission attempt, not completion of the research
task. `occurrences()` includes the current actual queue snapshot. Use existing
Factory job inspection, answer/approval/resume and cancellation APIs for the
accepted task; do not infer task success from schedule acceptance.

Disabling a schedule prevents future admissions and does not cancel already
accepted jobs. Cancel an occurrence explicitly to preserve owned cancellation
and child-tree semantics. Cancellation acknowledgement does not prove that a
running external effect has stopped; the existing task/effect supervision remains
authoritative.

## Evidence and limitations

The source baseline is Agno tag 3.1.0, fixed commit
`ab1d6007f09163c3adadbe06f998dc481b77a09a`. Twelve relevant installed files were
byte-compared with this official commit in an isolated private proof environment.
The public seams are [SchedulePoller](https://github.com/agno-agi/agno/blob/ab1d6007f09163c3adadbe06f998dc481b77a09a/libs/agno/agno/scheduler/poller.py),
[ScheduleManager](https://github.com/agno-agi/agno/blob/ab1d6007f09163c3adadbe06f998dc481b77a09a/libs/agno/agno/scheduler/manager.py)
and [native schedule persistence](https://github.com/agno-agi/agno/blob/ab1d6007f09163c3adadbe06f998dc481b77a09a/libs/agno/agno/db/postgres/postgres.py).

Actual tests use isolated PostgreSQL 17.11, the native HTTP middleware, native
queue/worker and a deterministic provider. They exercise independent runs,
duplicate/conflicting manual keys, current revocation/disabled users, ownership,
real native acceptance followed by injected acknowledgement loss, quota refusal,
native paused-run cancellation, real poller due-claim admission, stored-payload
tampering and UNKNOWN capacity retention. Provider/transport fixtures are
synthetic; no live model or scientific research result is claimed.

A separate actual stock-scheduler hard-process-restart probe found its accepted
native queue run recovered and completed on attempt two, while its original
ScheduleRun remained `running` with no run/session ID. Stock executor cancellation
also left its accepted queue job running until an explicit owned native
cancellation reached a cooperative boundary. These findings motivate the binding
and cancellation guards; that probe is not proof of a hard restart of the full
Factory adapter. Full composed application hard-kill and multi-process lease
takeover acceptance remain to be run.

Native schedules use a 300-second stale-lock grace and coalesce missed cron times.
The adapter retains these native clock semantics, checks the claimed lease before
releasing it, and prevents duplicate task submission independently of clock
reclaim. It does not add catch-up replay, native lease renewal, a custom timer,
or an upstream lease-fencing fork. A direct administrative database change racing
the final native release is outside the supported wrapper boundary.

The current application execution policy admits bounded synthetic demo plans.
Production remains fail-closed until live adapter and temporary-plan policy
approval are implemented and reviewed. Schedule catalog quota, deletion/history
retention policy and user self-service scheduling beyond the manager are separate
unfinished product policies; active task quotas are enforced now. No worker
capacity or multi-host scheduling claim is made.

Run the public integration contracts against an explicitly disposable database:

```powershell
$env:FACTORY_TEST_DATABASE_URL = '<owned disposable PostgreSQL URL>'
$env:PYTHONPATH = 'platform'
uv run python -m unittest discover -s platform/tests -p test_scheduling_postgres.py -v
```
