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
