# Schedule clock and preview contract

This milestone adds a read-only preview to the existing Agno 3.1.0 scheduler.
It adds no timer, poller, queue, task admission path or catch-up executor. The
existing ownership, immutable plan, administrator review and resource budgets
remain authoritative; a preview does not reserve capacity or authorize a run.

## API seam

`preview_schedule(cron, timezone, *, now_epoch=None)` returns schema 1:

- `cron`: whitespace-normalized five-field expression (minute, hour, day of
  month, month, day of week).
- `timezone`: an installed IANA/pytz name, including `UTC` and named aliases.
  Numeric offsets such as `+08:00` are rejected.
- `previewedAtUtc`: the single captured preview clock, as an ISO UTC string.
- `nextRuns`: exactly three entries, each containing integer `epoch`, ISO UTC
  `utc`, ISO local `local` with explicit offset, and integer `utcOffsetSeconds`.
- `semantics`: fixed clock, missed, overlap and DST descriptions plus
  `previewOnly: true`. The clock label is `agno-3.1.0/croniter-6.2.4/pytz`.

The public API must not accept `now_epoch`; it is a deterministic operator/test
seam. Invalid cron/timezone, impossible next dates, invalid clock bounds and
nonmonotonic results return HTTP 422 `SCHEDULE_CLOCK_INVALID`. Input bounds are
256 ASCII characters for cron and 100 characters for timezone. Macros, six-field
seconds and seven-field years are rejected even though the underlying croniter
validator accepts some extended formats. Five-field croniter syntax otherwise
retains native behavior, including day-of-month/day-of-week matching semantics.
Existing persisted schedules are not rewritten by this helper.

## Native clock behavior

Installed `agno.scheduler.cron.compute_next_run` constructs a timezone-aware
base with pytz, creates a fresh croniter, takes its next datetime, then returns
`max(computed_epoch, int(time.time()) + 1)`. Passing an old `after_epoch` alone
therefore does **not** simulate an old clock: it can return the real current
second plus one rather than a cron-aligned historical time.

The preview captures its clock once and performs the same calculation for each
of the next three bases, constructing a fresh iterator each time. It never
patches process-global time. Deterministic tests patch native `time.time` only
inside the test, then compare every preview epoch against actual installed
`compute_next_run`. Reusing one iterator across previews would not faithfully
represent the repeated-hour behavior of successive native clock calls.

Observed and pinned by tests with the installed croniter/pytz versions:

| Expression / zone | Transition | Local occurrences |
| --- | --- | --- |
| `30 2 * * *`, `America/New_York` | Spring 2026 | March 8 is **03:00 -04:00**, then March 9 and 10 are 02:30 -04:00. The nonexistent 02:30 is shifted; this is not a promise to skip it or use 03:30. |
| `30 1 * * *`, `America/New_York` | Autumn 2026 | November 1 occurs at **01:30 -04:00** and again **01:30 -05:00**, one hour apart in UTC, before November 2 at 01:30 -05:00. |
| `0 9 * * MON-FRI`, `Asia/Kathmandu` | Ordinary weekdays | Local 09:00 corresponds to 03:15 UTC; offset is 20,700 seconds. |

These are version-specific native semantics, not a universal rule for every
IANA transition. Display both UTC and local offset so repeated wall-clock labels
are distinguishable. Runtime clock movement, downtime and editing/enabling a
schedule can make a previously displayed preview stale. The preview promises
neither exact dispatch timing nor a provider result; the poller normally checks
every 15 seconds and task execution follows admission and queue availability.

## Missed occurrences, overlap and disabling

The existing `SchedulingService._fire` releases a due schedule using native
`compute_next_run(cron, timezone)` from the current release time. After downtime,
a claimed overdue occurrence can be attempted once; missed intermediate cron
points are coalesced and are not replayed as catch-up tasks. Enabling likewise
recomputes the next future native time. The preview does not enumerate or submit
missed occurrences.

Different due occurrences may overlap: admission completion is separate from
the accepted research task's execution completion. Existing owner and global
active-task budgets still apply. This milestone does not add a skip-if-running,
queue-behind-previous or cancel-previous policy. Disabling prevents future
admissions; it does not stop already accepted tasks. Their cancellation uses
the existing exact owned occurrence/task lifecycle.

`docs/SCHEDULING.md` remains authoritative for the persisted occurrence fence,
UNKNOWN acknowledgement handling, native lease limitations and supported
single scheduler-active process topology. This clock preview does not resolve
the native unconditional-release race across scheduler replicas.

## Validation

`platform/tests/test_schedule_contract.py` contains seven deterministic lightweight
tests: actual native UTC/IANA parity, spring gap, autumn repeated hour, exclusive
minute boundary and single clock capture, native historical-clock guard,
strict input/impossible-date rejection, and declared no-catch-up/overlap semantics.
No PostgreSQL, live provider, timer or wall-clock waiting is involved in these
tests. They do not replace the existing actual scheduling integration suite.
