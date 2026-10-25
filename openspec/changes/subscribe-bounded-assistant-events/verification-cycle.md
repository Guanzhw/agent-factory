# A04 two-endpoint cycle verification

Base: `931f7c3`; spec-first commit: `cc76c27`.

Existing PostgreSQL cases proved one receiver wake-up and direct allocation
exhaustion; portable cases proved depth refusal. They did not execute a native
queue cycle between two endpoints. The new isolated case fills that specific gap.

`test_assistant_event_cycle_postgres.AssistantEventCyclePostgresTests.test_two_native_receivers_cycle_until_original_scope_refuses_third_admission`
uses the existing synthetic application, two member-owned endpoints and one
explicit one-round scope per receiver. A test-only application completion owner
is installed before the service lifecycle starts. After actual native completion
and settlement it publishes a minimal synthetic result and emits a peer event
with the original delivery/task lineage. No admission, queue, model, settlement,
or background event loop is mocked. The callback is a deterministic synthetic
consumer, not evidence of autonomous scientific or team-value decisions.

Observed first run:

- Two original native jobs completed, one for each member; both tasks terminal.
- Each original scope has exactly one SETTLED allocation bound to its original task.
- Events share one root with actual depths 0, 1, 2.
- Third delivery is rejected with `LOCAL_BUDGET_EXHAUSTED` and no allocation.
- All events scanned; three further real delivery batches return `(0, 0)`.
- Task/run/allocation identities and consumed rounds remain unchanged.

Command (isolated loopback PostgreSQL; no external credentials/provider):

```sh
PYTHONPATH=platform:platform/tests:applications:applications/tests:deployment \
  timeout 90 /workspace/agent-factory-research-next/.venv/bin/python \
  -m unittest test_assistant_event_cycle_postgres -v
```

`FACTORY_TEST_DATABASE_URL` was set to the existing synthetic loopback fixture.
Exit 0; **1 passed, 0 skipped, 8.346 seconds**. Raw first-run log:
`/tmp/af-event-cycle-first.log`. Fixture shutdown logged native queue and scheduler
stopped; its registered cleanups closed the isolated database/workspace.

Ruff and `git diff --check` passed. No full-suite rerun, real model/GPU, deployment,
or capacity result is claimed. Independent exact-diff review remains required.
