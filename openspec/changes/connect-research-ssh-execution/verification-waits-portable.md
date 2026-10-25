# Ordinary Agent SSH wait hook: portable verification

Contract preceded implementation: `6c8c64d`, `2cc3d3b`, `b3601ad`; shared
helper contract source is `6c874b4`. This slice adds only the exact SSH binding
wait owner and its focused tests. Composition must explicitly inject the existing
`factory_api.commands` and register both launch/wait pins for `core-ssh-process`.
No lifecycle worker, custody table, control journal, or Research workflow is added.

First run: 7 tests, 6 passed and 1 errored, 0.246 seconds, exit 1.
`/tmp/af-ssh-waits-portable-first.log` preserves the original failure.
The fixture passed a reconstructed requirement alongside a live `run_response`;
Agno's run-response branch retained its original unresolved tools. The native
HTTP/queue boundary instead continues by original run ID and serialized tools.
The fixture was corrected to use a real SQLite Agent database and the original
run ID/session ID. No product assertion or timeout was relaxed.

After that fixture change: **7 passed, 0 skipped, 0.386 seconds, exit 0**.
Log: `/tmp/af-ssh-waits-portable-fixed.log`.

```sh
PYTHONPATH=platform:platform/tests:deployment timeout 120 \
  /workspace/agent-factory-research-next/.venv/bin/python \
  -m unittest test_ssh_operation_waits -v
```

Every test obtains a real ordinary Agno Agent external-execution requirement
through OwnerChatModel with synthetic HTTP. The continuation test reconstructs
the serialized result, resumes the persisted original run, and confirms the
second model request contains the actual synthetic operation result. The other
cases isolate custody/control ports to check foreign task/run/pin, unresolved
operation, original PREPARED/UNKNOWN command handling, and exclusion of Research
workflow/canceled child paths. These isolated port tests are not durable queue or
restart evidence. Ruff and whitespace checks pass.

Remaining: actual exact-owner installation, PostgreSQL/native queue restart and
lost-continuation-ACK proof, process integration, controlled SSH, and target D01
acceptance. No SSH daemon, PostgreSQL suite, real provider/GPU, or deployment was
started for this slice. Temporary SQLite databases and HTTP clients were closed
by test cleanup. Independent review is still required.

## Independent review: do not claim unrelated confirmations

Review found that registry fallback can select this task's SSH owner for an
ordinary confirmation tool. The hook now returns `None` for another tool or a
non-SSH task; strict approval/custody checks apply only to its selected wait.
Two regressions use the actual registry and ControlCommands approval preparation
for ordinary approve/decline, and verify the Research workflow is not claimed.
The first expanded run was 8 passed/1 fixture error (0.455s): the isolated store
omitted registry's existing `effects` read. Supplying the fixture's empty effects
list fixed that fixture; no product fallback was added.

Final expanded run: **9 passed, 0 skipped, 0.508 seconds, exit 0**.
First log `/tmp/af-ssh-waits-review-fix.log`; final log
`/tmp/af-ssh-waits-review-final.log`. No PG/SSH run occurred.
