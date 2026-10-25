# Research SSH native integration

## First run — failed, retained

- Tested checkout: `83e020ffc6b2165cb2a5e858c05fa452019247ec`.
- One isolated PostgreSQL/native test, outer process limit 180 seconds; existing per-stage 30-second wait unchanged.
- Command: `PYTHONPATH=applications:applications/tests:platform:platform/tests:deployment /workspace/agent-factory-core-only/.venv/bin/python -m unittest test_research_ssh_native_postgres.ResearchSSHNativePostgresTests.test_setup_to_original_ssh_child_and_selected_team_evidence -v`, with the existing synthetic `FACTORY_TEST_DATABASE_URL`.
- Exit 1; 1 test in 35.567 seconds, 1 failure, no skips.
- Actual setup publish, project agreement and native root/child admission occurred. Root run `cf9790d2-61b2-41a3-ab7d-9f6695c4ca26`, child run `a908d1c8-fc3e-4cda-bc3d-53bf4b18fb35`.
- Child synthetic provider failed before helper launch: `PERSONAL_MODEL_REQUEST_FAILED`. The original stage assertion failed `Timed out: actual helper training start`.
- Cause found by inspecting the current reused fixture: `SSHSequenceModel` now requires `(inputs, observed)`; this consumer still called its old no-argument constructor. Corrected that fixture call only. No production behavior, timeout or acceptance assertion changed.
- Worker and scheduler stopped; registered fixture cleanup ran, including isolated database/directory cleanup. PG slot released. No automatic rerun.
- [Original first-run output](evidence/research-native-first-failure.txt) is retained. The helper transport/model are synthetic; this is not actual sshd, GPU, external host or live-model acceptance.

The existing wait port supplies `output.text`; the model fixture parses that actual child-visible output and the root compares the original child result. Neither a constant outcome nor direct artifact/database injection substitutes for that chain. Full Research SSH acceptance remains **NOT PASSED** until the corrected fixture runs.

## Second run — fixture access error, retained

- Tested checkout: `0af89edbb6974e667b11c2676484fde6ef14c704`; same command and original deadlines.
- Exit 1; 1 test in 14.290 seconds, 1 error, no skips.
- Actual setup/publish/project/root/child reached helper start. Root run `05843b96-a554-44c8-93a6-0f21cdd77731`, child run `54d9df62-415c-4f0b-b7f9-cf38fba58c15`.
- Fixture then accessed nonexistent `ResearchRounds.runs`; the real read-only port is `ResearchRounds.legacy.runs`. Corrected the two fixture reads (original child identity and original SSH output). No product changes or acceptance relaxation.
- [Second failure output](evidence/research-native-second-failure.txt) retained. Cleanup released the helper barrier and stopped worker/scheduler, then registered isolated resource cleanup ran. PG slot released; no automatic rerun.
- Complete terminal/evidence/share/withdrawal assertions remain **NOT PASSED**.

## Third run — passed after independent fixture review

- Exact tested head: `9a048ca9a07e625c54a65acf5b493b9e8adc6fab`; complete fixture independently reviewed before this run. Same command, original 30-second stage deadlines and 180-second outer process limit.
- Exit 0; **1 test passed in 25.758 seconds, zero skips**. [Original successful output](evidence/research-native-third-pass.txt). The two earlier failed runs remain above and were not overwritten.
- Actual setup/private draft/explicit publish, confirmed project agreement, native root delegation, original SSH helper launch/wait/resume and terminal publication completed. Root run `583e856d-0b54-4846-a3c2-f521aafadf7d`; child run `15ceb345-726a-4554-84a4-58a51bee7d0d`. The test asserted unchanged original run identities and exactly one process start.
- Child model fixture read actual bounded, valid UTF-8 JSON stdout from the real wait result; root read the original delegated child result. Measured value 3 versus target 4 produced `not_met`, with both native tasks completed. Scientific negative result is distinct from process failure.
- The actual delivery ZIP contained exactly the three selected roles: metrics, source and run recipe, with original operation provenance. The private stdout canary appeared only in owner-private output, not in the manifest or selected team ZIP. Bob read/download succeeded before source withdrawal and both returned 404 afterward.
- Normal fixture cleanup completed. A separate read-only post-run check found no matching helper/training/test Python processes, no `ssh-native-*` temporary directories and no `af_test_%` databases. PG slot released; the existing shared PG container remains.
- Scope: actual PostgreSQL, setup/governance, vault/connection authorization, native queue, custody, local helper subprocess, selected artifacts, sharing and withdrawal; **synthetic model HTTP and local transport only**. This does not establish external sshd/host, real provider autonomy, GPU training, hardware capacity, browser acceptance or scientific reproducibility by another member.
