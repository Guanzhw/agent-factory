# Storage cancellation: one bounded diagnostic experiment

Diagnostics are opt-in; ordinary test discovery uses `controlled_command_worker`
and does not copy diagnostic files. To observe this same test with the bounded
diagnostic worker, set an authorized disposable loopback `FACTORY_TEST_DATABASE_URL`
and run:

```sh
FACTORY_STORAGE_DIAGNOSTIC=1 PYTHONPATH=platform:deployment:platform/tests \
  uv run python -m unittest test_storage_process.StorageProcessTests -v
```

The original assertions and HTTP deadline are identical in both modes. Historical
results below remain observations of their original revisions.

The preserved first targeted failure (`/tmp/no-demo-full-failures-targeted-first.log`) is a 15-second HTTP read timeout at the original storage test's cancellation POST, before quarantine or injected process death. Its child log was removed by normal cleanup; no lock-deadlock claim is established.

Hypotheses: (1) synchronous root-lock connection acquisition blocks the event loop while the observer holds the single connection; (2) native cancellation awaits durable run/session writes; (3) repeated group/detail reads delay the response after cancellation has already committed.

One original test run will retain its original HTTP/test deadlines. A test-only child wrapper records cancellation phases, a bounded heartbeat, thread stacks and requested/actual asynchronous-task snapshots at 5 and 12 seconds. Independent PG samples report wait categories and blocker PIDs, plus original task/command state; SQL text, parameters, credentials and stack locals are excluded. Connection-acquisition start/end timings identify pool waits. Diagnostics are copied before the original fixture cleanup, including on failure; ordinary runtime entrypoints are unchanged.

Discriminating criteria: absent heartbeat plus a main-thread connection/SQL wait supports loop blocking; continuing heartbeat plus native cancel awaiting DB/session work supports the native path; completed cancellation with pending detail supports response projection. A passing run cannot close the historical failure without discriminating evidence. This is observation, not a timeout increase or a new retry.

Implementation and execution results are recorded separately after freezing the diagnostic fixture. Only root assigns the heavy-test slot.

## First instrumented run

The one authorized original test passed, 1/1 with zero skips in 13.498 seconds (exit 0). Command used the existing disposable PG fixture and `timeout 120`, retaining the test's original 15-second HTTP timeout. Log: `/tmp/af-storage-cancel-instrumented-first.log`; retained child evidence: `/tmp/af-storage-cancel-diagnostic-blg5tx4e`.

The cancellation HTTP phase completed in 0.395 seconds: submit 0.272s, cascade 0.103s, native cancellation 0.042s. Neither 5s nor 12s sampling fired; the stack file is empty. This run does not reproduce or close the historical 15s failure and supplies no affirmative evidence of a pool or event-loop stall. Original quarantine process exit, restart, read recovery and restore assertions also passed; owned subprocess/database cleanup completed.

Independent review identified that Python traceback.print_stack could include source lines/SQL literals if a sampling threshold fired. The run had already started when the finding arrived; no source was changed mid-run, and its empty stack file confirms no such output occurred. Commit 8362eb7 replaces that formatter with filename/line/function only. Ruff/diff checks passed; no second heavy run was made for this formatting-only correction.
