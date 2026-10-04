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
tickets remain an error. After a crash between reservation commit and occurrence linking, recovery reads
the exact original owner/request task and validates its plan/hash/fingerprint
before binding it. An occurrence with no authoritative reservation or native
ticket remains UNKNOWN; recovery never reserves or submits another task.

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
Factory adapter. Nine additional guarded application tests now exercise owned process hard-kill
before native submission, after queue commit and before occurrence linking. A
restarted native worker reaches its actual persisted question with the original
request/task/run/occurrence and one ticket. A native-poller due occurrence is
likewise killed/restarted. Unknown reservations retain capacity without replay.

Native schedules use a 300-second stale-lock grace and coalesce missed cron times.
The adapter retains these native clock semantics, checks the claimed lease before
releasing it, and prevents duplicate task submission independently of clock
reclaim. It does not add catch-up replay, native lease renewal, a custom timer,
or an upstream lease-fencing fork. Current lease identity is checked at admission entry and immediately before
native submission, preventing a stale claimant from admitting new work. Native
`release_schedule` still lacks a conditional lease-token API: a successor claim
can race the final read and unconditional release, even through public native
APIs. A regression exposes that release limitation while the immutable occurrence
fence retains exactly one task/ticket. Atomic lease release remains unresolved.
Keep one scheduler-active application process in the supported initial topology;
concurrent scheduler replicas require an upstream conditional-release API and
additional acceptance. The full default 300-second grace was not awaited.

The current application execution policy admits bounded synthetic demo plans.
Production defaults to current administrator plan review and remains fail-closed
until a live adapter, identity and model budget are configured and accepted. Schedule catalog quota, deletion/history
retention policy and user self-service scheduling beyond the manager are separate
unfinished product policies; active task quotas are enforced now. No worker
capacity or multi-host scheduling claim is made.

Run the public integration contracts against an explicitly disposable database:

```powershell
$env:FACTORY_TEST_DATABASE_URL = '<owned disposable PostgreSQL URL>'
$env:PYTHONPATH = 'platform'
uv run python -m unittest discover -s platform/tests -p test_scheduling_postgres.py -v
```

## User-facing schedule management continuation (2026-10-04)

The **计划任务** workspace now exposes owner-scoped list/detail, five-field cron
and IANA timezone preview, editing, pause/resume, occurrence history and links to
original tasks. A manager enters from an already approved immutable plan in the
existing composer; runner personas receive read-only controls. Backend permissions
remain authoritative at every write and every dispatch. New editor-created
schedules are persisted **paused**, with explicit separate enable. The editor has
no manual-trigger or external-notification action. Test fixtures may explicitly
use the existing owned trigger endpoint with far-future cron definitions.

`/api/factory/schedule-management` is a finite control-plane projection over the
same `SchedulingService`, public native schedule storage and poller. It is not
another scheduler or task executor. Legacy `/schedules` Factory wrappers remain
compatible. `metadata` declares current management authority and active-task
limits; `preview` is read-only and takes no client clock; `commands/{requestId}`
recovers an original owner command directly without scanning a partial list.
Schedule and occurrence lists expose bounded cursor pages, not full snapshots.
Raw native queue bodies, stored request payloads and errors are not projected into
the new UI contract. Actual task status remains separate from admission status.

Creation/edit/enable commands persist exact owner, semantic request key, immutable
plan hash, target native definition and revision intent **before** the native
write. The native ID is fixed in the creation intent. The public native DB create
primitive is used because `ScheduleManager.create` cannot accept a precommitted
ID or an initially paused state. Lost native acknowledgements never cause another
create or native write. GET recovery can repair only metadata for that exact
already-committed native row; if no authoritative native result exists, the command
remains UNKNOWN. It does not guess failure, adopt a same-name row or replay effects.

Editor CAS fingerprints include the stable definition, enabled state and monotonic
editor revision, excluding natural clock/lease advancement. Old pending snapshots
are re-read under the schedule lock before receipt repair so they cannot roll back
later revisions. Legacy edits and new dispatch are fenced while an editor command
is pending. Original occurrence history and cancellation instead retain the
original owner/immutable-plan/task/request custody; a lost clock-edit reply cannot
block cleanup of an already owned task. A pause acknowledgement still does not
cancel accepted tasks or prove an external effect has stopped.

The lock connection is separate from metadata and root-resource lock pools and
bounded to one connection with a short acquisition timeout. Contention returns a
finite busy conflict instead of blocking the event loop while it awaits native
HTTP. Metadata pool size one is part of targeted PostgreSQL acceptance.

Clock behavior is specified and tested in [SCHEDULE_CLOCK_CONTRACT.md](SCHEDULE_CLOCK_CONTRACT.md).
The preview shows UTC, local time and explicit UTC offset for the next three ticks.
It follows installed Agno/croniter/pytz semantics, including DST gap/fold behavior;
it is not a guarantee of actual admission. Missed ticks coalesce, with no catch-up
replay. Overlap remains allowed subject to current per-owner and aggregate active
task/storage admission, plus each immutable plan's existing execution/usage budget.
This is not a new cumulative daily/monthly spend cap or per-schedule no-overlap
policy. Paused/UNKNOWN tasks retain their normal active capacity until authoritative
lifecycle evidence releases it. Restarts reconcile original occurrences/tickets,
not replacement runs. Single active poller and the documented conditional-release
limitation remain unchanged.

The milestone uses explicit synthetic development fixtures, mock HTTPS login,
deterministic clock seams and isolated PostgreSQL/native runtime only. Its draft PR
records exact-head CI, targeted PostgreSQL and desktop/mobile evidence. It creates
no production schedules or notifications and accepts no new provider credentials,
financial commitment, host configuration, deployment or merge. Schedule deletion,
catalog quota/history retention, multi-poller lease fencing, cumulative recurring
spend policy and production identity/host acceptance remain separate work. Offline
[baseline/candidate contracts](BASELINE_CANDIDATE_CONTRACT.md) are validation-only;
no comparison execution or full scientific workflow is claimed.

History in this initial editor covers persisted occurrences, not a complete log of
all clock claims or refusals. Current-role/plan/pending/lease checks may reject
before occurrence persistence and remain internal audit only; lock acquisition can
fail before that audit boundary. An empty history does not prove no tick occurred.
Owner-visible finite pre-admission refusal diagnostics remain code work; this
milestone does not claim that every non-execution can be diagnosed from the UI.

| Requirement | Current milestone | Remaining code / external validation |
|---|---|---|
| Create/edit/list/pause/resume/history | Manager own approved plan, initially paused create, immutable plan pin, CAS, finite owner projections and actual UI | Production operating policy and account onboarding |
| Timezone/DST/missed runs | Five-field cron, IANA zone, UTC/local-offset preview; deterministic native clock comparisons; missed ticks coalesce | No catch-up/backfill feature; deployed clock/zone-data operations not certified |
| Overlap/per-owner limits | Concurrent occurrences allowed within current owner/global active quotas, storage admission and per-plan execution/usage budgets | Per-schedule no-overlap, cumulative daily/monthly spend caps and catalog quota |
| Identity/permission changes | Current authorization and plan/binding checks at each dispatch; pause/revoke race coverage | Production identity deployment and operator policy |
| Lost replies/stale edits/restart | Durable exact native ID/command, stable occurrence identity, original receipt reconciliation, CAS and no UNKNOWN replay | Administrative resolution of truly unknown control-plane writes; history retention/deletion policy |
| Cancellation with pending edits | Original plan/task/request custody remains available for explicit owned cancellation | External stop confirmation remains existing runtime-specific evidence |
| History and failure explanations | Persisted admission records, actual queue state, original task links; safe finite projection | Owner-visible pre-reservation denial diagnostics |
| Scheduler topology | One existing native poller, bounded separate advisory-lock pool; no second orchestrator | Atomic native conditional lease release and multi-poller acceptance |
| Baseline/candidate comparison | Strict offline declared-data/evaluator/change-scope contract, synthetic unit tests | Actual verified bytes, governed execution, result provenance and complete comparison/review UI |
| Scientific/host acceptance | Explicit synthetic mock-login and isolated native fixtures | Real scientific provider/domain validation, deployed IdP/TLS, target host and sustained capacity acceptance |

Initial full CI at `8ce321a` passed the PR run but the push run failed two existing
remote-process tests when their private facts endpoint returned HTTP 500. The
original service traceback was not retained, so the precise cause of those two
responses is not established. Separate deterministic reproduction identified a
fixture-only readiness race: the SQLite path exists before its initialization
commits. The fixture now reads only after the provider publishes its durable
journal identity and process pin; prior states remain UNKNOWN/held. Pinned read
failures remain HTTP 500 with finite safe diagnostics. The original two scenarios
passed targeted actual PostgreSQL revalidation (54.059s). This does not weaken
production custody checks or justify calling the failed head accepted; the draft
PR records fresh exact-head full CI after the fixture correction.
