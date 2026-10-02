# Durable task control commands

`POST /api/factory/jobs/{task}/commands` accepts an owner-scoped `commandId` and
one exact decision: `answer` with requirement ID/version/answer, `approve` with
requirement ID/version/boolean, or `cancel`. The server stores the intent before
calling the native continuation or receiver. Responses contain references and
proof, never the answer text. The durable server record necessarily retains the
answer so an explicitly resumed, undispatched intent can use the original data.

The PostgreSQL primary key is `(owner_id, command_id)`. A fingerprint binds the
exact task, immutable plan, native run or remote placement/manifest/child,
requirement version and decision. A separate unique requirement slot prevents
two command IDs from choosing different decisions for one paused requirement.
Concurrent copies converge on one dispatch CAS. Reusing an ID for another task,
decision or binding returns a conflict; another owner cannot read the receipt.

Only `PREPARED` can cross the durable dispatch boundary. After `DISPATCHING`,
recovery never sends another continuation, even if the native requirement still
looks unchanged. An absent receipt is not proof of non-acceptance. `UNKNOWN`
therefore remains actionable uncertainty rather than a claim of exactly-once
execution. Explicit `/dispatch` is permitted only for an undispatched intent and
rechecks current authority and the exact requirement before dispatching.

Native continuation proof uses Agno 3.1's existing job payload and atomic native
continuation update: command ID/fingerprint in metadata plus the hash of the
actual updated tools, native run, session, owner and executor. This adds no
executor or replacement queue. Later native requirements cannot erase already
persisted decision evidence. Current execution status is observed separately;
a failed read does not retain a stale “execution continuing” claim.

Cancellation records the scoped cancel flag with its dispatch CAS. “Decision
recorded” does not mean “stopped”: stop confirmation requires the existing native,
descendant and resource lifecycle evidence. An already stopped task yields a
confirmed no-op without changing a completed task into a canceled task.

Remote commands retain both origin and receiver receipts. The receiver pins its
mapped owner, actual tree member, handoff, manifest and receiver binding proof to
the origin fingerprint. Read recovery only asks the receiver for that command.
A missing or mismatched receiver receipt remains unknown, with no remote POST
retry. Origin receipts do not substitute origin queue state for receiver proof.
A receiver intent not yet dispatched is not automatically resumed by the origin.

## Reading and acknowledging

- `GET /api/factory/jobs/{task}/commands/{command}` reads/reconciles one original
  receipt with read permission. Reconciliation may persist observed evidence;
  it cannot dispatch execution.
- `GET /api/factory/commands` lists this owner's outstanding commands, optionally
  filtered by `taskId`, with `limit` and `after` cursor pagination.
- `POST .../{command}/acknowledge` hides a known decision or rejection from the
  outstanding list. Cancellation requires positive stop confirmation. Records
  are retained; this endpoint does not delete evidence or perform execution.

The UI persists only owner/task/command references, requirement version and a
SHA-256 decision digest before sending a POST. No answer text, session token or
credential is put into localStorage. Full browser restart and account switching
recover the same references. Server receipts also recover when browser storage
has been cleared. A failed POST is followed only by receipt GET. The UI separately
shows decision recorded, execution continuing and stop confirmed. Same-owner
concurrent tabs can adopt the server's first accepted command for the exact same
decision. Legacy `/answer`, `/approve`, `/cancel` routes enter the same protocol;
clients omitting an ID receive a deterministic semantic compatibility ID.

## Reproducible bounded acceptance

With the existing isolated PostgreSQL test environment:

```sh
PYTHONPATH=platform:platform/tests .venv/bin/python -m unittest \
  test_control_commands test_control_commands_remote test_control_commands_process
npm run check
```

The process fixture is imported only by tests, never production startup. It exits
without cleanup after native commits and before Factory receipt persistence for
answer, both approval decisions and cancel; it also exits before dispatch and
after the dispatch CAS but before native delivery. Restarts reuse the same
isolated database and workspace. Assertions distinguish positive proof from
unknown and count continuation calls by original command ID.

For full Chromium close/relaunch, install Playwright in an isolated tooling
environment and run `scripts/accept_control_browser.py --output <owned-directory>`
with `platform/tests` on PYTHONPATH, the isolated test database and a built UI.
Four actual UI cases cover answer, approve, reject and cancel: the actual POST
commits, its response is discarded, same-page receipt reads are blocked, Chromium
exits, a fresh browser process recovers via GET, and Bob/Alice switching verifies
owner separation. This is a deterministic model fixture, not real research.

`scripts/accept_orx_process.py` reuses the pinned actual ORX binary and sealed toy:
actual approval/cancel HTTP responses are deliberately discarded by the caller,
Factory is SIGKILLed, and original command IDs recover after each restart. The
approval case retains the original detached-running-process check; final checks
require one native admission, one ORX run, matching original run IDs and positive
stop evidence. It does not rebuild the toolchain or claim remote/Windows runtime
acceptance. No paid model or compute is used.

Command retention, disk admission/monitoring, workload fairness, live-write
restore and remote actual ORX remain separate acceptance work.
