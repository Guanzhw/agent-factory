# Storage cancellation: one bounded diagnostic experiment

The preserved first targeted failure (`/tmp/no-demo-full-failures-targeted-first.log`) is a 15-second HTTP read timeout at the original storage test's cancellation POST, before quarantine or injected process death. Its child log was removed by normal cleanup; no lock-deadlock claim is established.

Hypotheses: (1) synchronous root-lock connection acquisition blocks the event loop while the observer holds the single connection; (2) native cancellation awaits durable run/session writes; (3) repeated group/detail reads delay the response after cancellation has already committed.

One original test run will retain its original HTTP/test deadlines. A test-only child wrapper records cancellation phases, a bounded heartbeat, thread stacks and requested/actual asynchronous-task snapshots at 5 and 12 seconds. Independent PG samples report wait categories and blocker PIDs, plus original task/command state; SQL text, parameters, credentials and stack locals are excluded. Connection-acquisition start/end timings identify pool waits. Diagnostics are copied before the original fixture cleanup, including on failure; ordinary runtime entrypoints are unchanged.

Discriminating criteria: absent heartbeat plus a main-thread connection/SQL wait supports loop blocking; continuing heartbeat plus native cancel awaiting DB/session work supports the native path; completed cancellation with pending detail supports response projection. A passing run cannot close the historical failure without discriminating evidence. This is observation, not a timeout increase or a new retry.

Implementation and execution results are recorded separately after freezing the diagnostic fixture. Only root assigns the heavy-test slot.
