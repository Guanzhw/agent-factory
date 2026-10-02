# Durable Factory event replay

`GET /api/factory/jobs/{id}/events?limit=100&cursor=...` is an owner-scoped,
current-read-authorized view of `af_events`. It is a Factory application stream;
`nativeCursor=false` explicitly distinguishes it from native Agno streams.

A task's persisted stream UUID survives API restart. An HMAC cursor is derived
from the trusted server signing key with a distinct domain; it binds owner,
task, stream, last row ID and task-relative sequence. Production replicas and
restores must retain their operator-managed signing key. Demo ephemeral keys
change after startup and require fresh login/replay.

Pages use one SQL snapshot for rows, high watermark and visible count. Other
tasks' global ID gaps are normal. PostgreSQL sequence allocation is not commit
order: a late lower-ID commit invalidates the recorded prefix. The next request
returns `409 EVENT_PREFIX_CHANGED`; clients replay from the beginning and
deduplicate persisted event IDs. This design does not invent an upstream durable
cursor or silently skip a late commit.

Limits are 1–1,000 rows, 1 MiB normalized response and 256 KiB inline event by
default. SQL applies payload bounds before JSON decoding. An oversized pending
event returns 413 and requires operator reconciliation; it is not silently
truncated. Each event has an intrinsic persisted-content hash independent of
derived sequence; a page hash includes the complete returned projection.

Job detail displays the latest 1,000 events in ascending order. Protected failure
status uses a SQL existence check over the full history, so display rollover
cannot turn failed application work into success. The UI can read history in
100-event pages, retry the same read after connection loss, restart replay after
prefix change, or return to current recent records. Reading replay creates no
task, continuation, cancellation or model call.

For a remote tree, the trusted owner-bound handoff relays the selected receiver
member's stream. Receiver cursors/sequences remain receiver-owned; origin and
receiver event positions are never merged. Public task IDs are mapped to the
scoped origin/child identifiers, projected content hashes are recomputed, and
receiver hashes remain explicit provenance. Foreign tree members/cursors are
masked with 404; tampering fails. The projected page also respects the byte cap.

Fifteen replay tests include five actual PostgreSQL/native HTTP cases: API restart,
large history, concurrent stream CAS, borrowed one-connection pool, owner/current
rights, and delayed lower-ID commit recovery. Two additional actual two-app
remote tests verify complete paging, digest provenance, current read-only rights
and child/cursor isolation. These are synthetic provider tests, not scientific or
external-host acceptance.
