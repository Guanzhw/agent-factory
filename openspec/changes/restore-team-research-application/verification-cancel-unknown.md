# A06/A07 original research cancellation and UNKNOWN confirmation

Base: `931f7c3dc9c92c2dbe17bdf468c2e66e93708050`. Spec-first commit: `3b9db1a`. This follow-up changes only the existing restart test fixture and adds one consumer test. No product implementation, recovery policy, timeout or scientific success criterion changed.

The existing `test_original_paused_research_survives_process_death_without_new_child` verifies successful resume of a real native Research Workflow/child. It does not exercise cancellation while original custody remains UNKNOWN. The new continuous case fills this distinct A06/A07 boundary without a new recovery mechanism or a cross-product fault matrix.

The real subprocess fixture publishes and runs the selected research application on isolated PostgreSQL. Its native parent pauses and its actual native child executes. A persisted test-only marker makes the existing delegated operation observer withhold original stop confirmation: it retains the original operation/handle and returns UNKNOWN/allStopped=false. The child has actually completed. This deliberately tests unavailable stop confirmation, **not** a claim that a real remote effect remains running. The marker survives hard process termination and same-database restart. No task terminal fields are fabricated.

After ending the project and sending the public original-root cancellation command, the test asserts:

- root/child task IDs, native run IDs and custody operation/handle remain the originals, with exactly two tasks;
- cancellation requested is distinct from terminal completion; workflow custody, disk and the original 32-tool-call allocation stay held;
- no domain terminal or terminal publication appears before positive original stop evidence;
- after hard restart and an actual observer pass, the same identities and holds remain, with no replacement dispatch;
- removing the marker exposes the actual original child stop evidence: root becomes cancelled, custody closes, holds settle, and a single terminal record appears with no scientific success decision;
- the project stays cancelled, there is one round and no continuations; two further actual observer passes retain the same terminal record/body and exact scope statement without new tasks.

Command (synthetic PostgreSQL URL supplied only to the runner):

```sh
FACTORY_TEST_DATABASE_URL=<isolated synthetic PG server> \
PYTHONPATH=platform:applications:deployment:platform/tests:applications/tests \
timeout 150 /workspace/agent-factory-research-next/.venv/bin/python -X faulthandler \
  -m unittest test_research_workflow_restart_postgres.ResearchWorkflowRestartTests.test_cancel_unknown_keeps_original_research_across_restart_until_stop_confirmed -v
```

First execution: **1 passed, 0 skipped, 27.594 seconds, exit 0**, `/tmp/research-cancel-unknown-first.log`. The existing per-condition 30-second and startup 40-second bounds were retained. Fixture shutdown and isolated database cleanup returned normally; the shared PG server was preserved and the serialized test slot released. Ruff, whitespace and strict OpenSpec checks passed.

This is real native execution, persisted custody, process restart and PostgreSQL evidence with a synthetic model and controlled stop-confirmation fault. It does not close real-model C/D, GPU, remote host or live external account acceptance. The existing successful-restart case was not rerun in this targeted slot; the final applicable combined suite must include it.
