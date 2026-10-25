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

## Accepted ACK loss and actual controller SIGKILL

After independent review of the test implementation and orphan-agent cleanup,
exact source `a6552d23dc6fb789734ef59d1ed17c93e588fe97` ran the two new cases
once: **2 passed, 0 skipped, 33.152 seconds, exit 0**. The existing three cases
were not rerun or counted again. The outer timeout remained 240 seconds and
no per-case deadline changed. First-run log:
`/tmp/af-ssh-hard-restart-first.log` (local evidence, not a published artifact).

```sh
timeout 240 env \
  PYTHONPATH=platform:deployment:applications:platform/tests \
  FACTORY_TEST_DATABASE_URL=<existing-loopback-test-database-url> \
  /workspace/agent-factory-core-only/.venv/bin/python -m unittest -v \
  test_ssh_native_postgres.SSHNativePostgresTests.test_accepted_continuation_with_lost_ack_recovers_without_second_send \
  test_ssh_native_process.SSHNativeProcessTests.test_hard_kill_paused_controller_preserves_original_helper_and_run
```

The accepted-ACK case called the real original native `continue_run`, waited for
it to return, then injected a missing reply. Original command proof recovered
`decisionRecorded=true`, retained its fingerprint/binding/requirement, and could
not dispatch again. Service reconstruction and repeated reconciliation left
the actual send count and original process start count at one, with the actual
archived measurement delivered to the same native task. This differs from the
retained before-send UNKNOWN test; positive native evidence was not forced into
UNKNOWN.

The hard-restart case asserted the actual native job was PAUSED, killed its
controller process and verified exit code `-SIGKILL` (-9). It checked that the
original helper child retained its boot/PID/start/group identity, was still
RUNNING and not a zombie, and retained the same journal without stopped proof.
A newly started controller had a different PID and used the original database
and workspace. Completion retained the original task/run/plan/request,
operation/lease and typed inputs, one wait command and one actual continuation
send, one helper start and the actual output. These are executed assertions;
this log does not retain the numeric PIDs as a separate artifact.

Before the kill, the fixture recorded only its own SSH-agent birth and socket
directory metadata. Cleanup verified that identity and used a pidfd to terminate
the orphan agent, removed only its unchanged socket and empty directories, and
then performed normal new-controller teardown. No guardian or training process
was targeted by agent cleanup. All cleanup assertions passed. A subsequent
process check found no controlled SSH worker, `ssh-native-` process or
`ssh-agent -D`; a read-only PostgreSQL check found no remaining `af_test_%`
databases. The shared PostgreSQL server remained running; the heavy slot was
released.

This is explicit test-owned orphan cleanup after a bare-PID kill, **not** proof
of production automatic agent reclamation. Deployment supervisor/process-
namespace behavior, real external SSH/GPU and live providers remain separate
unverified boundaries. Local helper transport substitution remains unchanged.
