# Schedule rejection diagnostics

This read-only journal distinguishes a retained pre-occurrence rejection from an
empty occurrence history. It does not prove that a clock never fired: observation
is best effort, expired rows are hidden, and unsupported/manual API validation
failures before `_fire` are not native trigger attempts.

`SchedulingService._fire` selects a finite reason at the actual guard boundary:
clock contention, authorization, claim identity, trusted binding, paused clock,
changed definition, or immutable-plan checks. Unexpected check failures use
`CHECK_UNAVAILABLE`; exception details are never copied. Recording stops before
the occurrence INSERT is attempted, including uncertain INSERT failures. Later
admission outcomes remain in the original occurrence/task/native-run journals.
Existing task, occurrence, request and native run IDs are unchanged.

`af_schedule_diagnostics` contains opaque ID, trusted schedule/owner binding,
finite reason/source and first observation time. UUID deduplication binds owner,
schedule, original due/manual key and reason without persisting that raw key.
Repeated observations do not update timestamps or counters. Different guards can
produce different records for the same due time. An unbound or foreign claimed
owner cannot create a record. There is no exception, credential, payload, plan
body, other owner's metadata, automatic retry or execution action in this table.

At most100 records are retained per schedule. Records older than30 days are
excluded on every read; physical cleanup runs opportunistically on the next
observation for that schedule, so dormant expired rows can remain on disk until
then. Writes atomically deduplicate and prune under a distinct nonblocking
transaction lock. A separate one-connection pool has10ms checkout,1s connect,
100ms statement and50ms row-lock timeouts. Async callers offload synchronous I/O
and wait at most1.5s. Failure or contention can omit a diagnostic; it cannot alter
the original denial or release a native lease that the admission lock never held.
The await timeout does not terminate an already running thread: a bounded
diagnostic-only write can finish later. It cannot create any task or occurrence.

`GET /api/factory/schedule-management/diagnostic-schedules` lists only original
owner bindings. `GET /api/factory/schedule-management/{id}/diagnostics` checks the
same owner and immutable historical plan. Both require the current executor
**read** permission, independently of **run** or clock-edit permissions. A pending
edit does not fence history; fully revoked read permission still denies access.
Neither GET repairs editor state nor writes/deletes any record. Pages contain at
most20 rows, use owner/schedule-scoped ID cursors, and explicitly are not snapshots.
An expired or foreign cursor is404. Concurrent insertion/retention can change
pages; refresh starts from the first page without replay.

The Chinese panel has its own catalog/selector so a failed editor/run-authority
read does not hide diagnostics. Owner/schedule epochs discard stale responses;
only finite validated projections render. The UI states the retention and empty
history limits and exposes no trigger/retry action in the diagnostic section.
