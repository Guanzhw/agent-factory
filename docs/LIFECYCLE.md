# Trusted lifecycle cleanup observation

The application starts a bounded Factory observer after all native database and
queue-worker startup, and stops it before their drain. It observes existing work
every 500 ms, at most 24 root groups per tick, rotating across roots so old UNKNOWN
groups cannot starve later observations. It neither submits, resumes, retries,
claims a ticket nor creates another scheduler/model loop.

Confirmed protected failure, native failure/cancellation or current authority loss
requests cleanup of that existing task and descendants. Current grants, plan
policy, governed materials and remote origin/receiver guards are checked.
Cleanup can proceed after ordinary run permission is revoked: it creates no new
work, mints no owner/admin JWT and grants no access. Before native cancellation,
the observer requires the exact persisted owner, task/session, native run,
executor, original admission key and immutable plan/envelope binding. Missing or
mismatched binding remains uncertain and cannot authorize another process's stop.

Queued/paused cleanup uses the public native `QueueWorker.acancel_queued`; running
intent uses public `Agent.acancel_run`. Actual bounded compute honors cancellation
and checks current authority itself every 250 ms. The observer records its cleanup
reason; an application failure remains a failure after cleanup, while explicit
user cancellation remains cancellation.

Native execution eligibility and observation are different boundaries. A child
reservation before its native acknowledgement remains uncertain; it is not
revoked merely because no ticket exists yet. Its validated root review/ancestry
and current guards still apply. An exact completed ticket does not renew an
execution grant; unfinished descendants are checked independently. A completed
child with active descendants cannot make the group stopped or admit new work.

Capacity is released only after positive native terminal ticket evidence, known
DONE/CANCELLED effects and every descendant's known stop. A persisted CANCELLED
run output alongside a still-running queue ticket is insufficient. Missing ACK,
UNKNOWN effect, incomplete descendant binding or unavailable authorization store
retains capacity. Remote-origin metadata has no local native ticket; it cannot
be mistaken for locally stopped execution.

Eleven actual PostgreSQL/native tests cover paused/queued/running cleanup without
UI detail polling, role revocation, no impersonation, exact-binding negatives,
UNKNOWN preservation, stale ticket disagreement, historical failure beyond the
display window, bounded rotation and real reviewed delegation before/after native
admission. The healthy-tree regression includes a completed child with a paused
grandchild and exact inherited administrator review.

Default native running cancellation signals are in-memory and reach this single
application process. They do not establish cross-replica or external-host cleanup.
Those deployments require approved native coordination and authoritative remote
stop receipts; no signal acknowledgement alone is stop proof. Monitoring/export
of observer error counters remains operational follow-up; no full production
availability/load guarantee is claimed.
