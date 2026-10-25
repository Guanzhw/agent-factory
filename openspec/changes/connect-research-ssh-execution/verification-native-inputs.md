# Native SSH inputs and private output integration

2026-10-25, exact source `13755c7941ea7dec84594e9b730ce561551adab9`.
First execution of the updated three-case fixture: **3 passed, 0 skipped,
95.656 seconds, exit 0**. The outer 240-second bound did not expire. No test
failure or rerun occurred in this three-case execution.

```sh
timeout 240 env \
  PYTHONPATH=platform:deployment:applications:platform/tests \
  FACTORY_TEST_DATABASE_URL=<existing-loopback-test-database-url> \
  /workspace/agent-factory-core-only/.venv/bin/python \
  -m unittest discover -s platform/tests -p test_ssh_native_postgres.py -v
```

The existing authorized PostgreSQL listener was `127.0.0.1:55439`. Each case
owned a randomly named isolated database; the fixture's normal context exit
drops only that database. No shared database or server was removed. Execution
used the authorized local-network tool permission for PostgreSQL and disposable
SSH agent sockets. The local log is `/tmp/af-ssh-native-inputs-first.log`; this
path is not presented as a published artifact.

## Actual observations

- Two native runs consume different schema-validated conditions. Their actual
  helper programs parse `--experiment-json` and its separate JSON argv entry,
  and emit the received values. Shell-like quoted text remains literal data.
- The first run pauses at its original wait; the controller is stopped and
  reconstructed after the model's later input selection changes. Its original
  task/run/operation and retained inputs remain unchanged. The second run has
  distinct identities and derived target reference. The actual start log has
  exactly one entry for each input set.
- The controlled model reads the actual wait function's archived private
  output, status, exit code and original artifact reference. It does not return
  a hard-coded completion result in lieu of reading the helper output.
- The original wait resumes once after controller reconstruction, with one
  original control receipt. Repeated lifecycle observation does not create
  another receipt or process.
- A deliberately unavailable continuation acknowledgement leaves the same
  command UNKNOWN and non-dispatchable across controller reconstruction. The
  original run remains paused, dispatch count stays one, and the controlled
  model receives no fabricated completed result.

## Scope and cleanup

This is real PostgreSQL, native queue, custody, actual local helper subprocess,
archival and controller reconstruction. Only the SSH subprocess transport is
substituted; enrollment probing is synthetic. No actual sshd connection, GPU,
external provider or live model was used here. These are two independently
started native agent tasks shaped like the execution children; this test does
not prove a Research parent delegated both children. The separate loopback
test proves a different network-mechanism segment, not this entire composition.

Worker/scheduler shutdown and fixture cleanup completed without errors. After
exit a process check found no `ssh-native-` or test-runner process. The serial
heavy-test window was released. Before this execution the no-database import
probe collected three tests and explicitly skipped all three; those skips were
never counted as behavioral passes. Test changes and this evidence still need
the author-independent review gate.
