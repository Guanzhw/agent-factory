# A01 same-database app removal — reviewed contract passes

Current result: **1/1 PASS, 0 skipped, 14.488 seconds, exit 0** after independent review corrected the new oracle to the existing positive-stop contract. No production change. Earlier failures below remain evidence, not overwritten passes.

Base: `931f7c3`. Only specification and test fixtures changed. No production fix, no paid model or GPU.

The actual Research service created an original native workflow, paused on its original delegated operation, with a completed child and a bound budget allocation. After killing that process, the fixture started a separate bare-core process against the same isolated database/workspace. That process imported neither Research nor deployment and had no registered application owners, workflows, or configured runtime adapters.

## Executions

- First run: exit 1, 1 failure, 20.792 seconds. Fixture incorrectly changed `demo=True` to `demo=False` during restart. The existing bootstrap guard correctly rejected that mode change. Log: `/tmp/research-removal-first.log`.
- After keeping the original authentication mode: exit 1, 1 failure, 15.646 seconds. Original task/run/operation identities and the two task IDs were preserved. Initially the root remained paused, nonterminal and held. The actual lifecycle observer then positively cancelled the native root, closed the delegated operation as failed, made the task terminal/failed, and settled its scope. This fails the proposed retained-UNKNOWN/holds assertion. Log: `/tmp/research-removal-mode-fix.log`; bounded synthetic state is committed in `evidence/same-database-first-observation.json`.
- Ruff and `git diff --check`: pass. Strict OpenSpec validation passed for the initial specification.

The failure does not demonstrate redispatch or a false native completion: the observed native state is cancelled. It exposes the distinction between missing hooks for a still-declared owner and complete removal of all owner declarations. `ApplicationRuntimeRegistry.finalization_context` can preserve the former, but returns no application completion responsibility for the latter. The generic scope finalizer then settles a positively stopped group. Product changes or adjustment of the requested acceptance boundary require coordinator judgment; neither was silently applied here.

In that failed execution, health/routes/resource assertions were not reached. Both fixture processes terminated, the isolated database context cleaned up, and the PostgreSQL slot was released. No existing user database or archive was modified.

## Independent disposition and final verification

Two independent reviewers found the retained-UNKNOWN assertion after positive native stop exceeded the existing A01/D02 and `owned-native-finalization` contract. Missing hooks for a declared owner differ from removing all declarations. The revised spec (`cf81e90`) allows failed/SETTLED only after positive original root/child/custody stop evidence. It still forbids new tasks, scientific success, or invented application finalization. The fixture disables only the observer background poller through the existing test injection port and explicitly calls its real observer, making the before/after phases deterministic.

Command: `FACTORY_TEST_DATABASE_URL=<isolated loopback fixture> PYTHONPATH=platform:platform/tests:deployment:applications:applications/tests timeout 150 <venv>/bin/python -m unittest test_research_removal_postgres.ResearchRemovalPostgresTests.test_original_task_stops_without_replay_or_research_completion_after_app_removal -v`.

Result: **1 test passed, zero skipped, 14.488 seconds, exit 0**. Log: `/tmp/research-removal-reviewed-oracle.log`. The existing AuthorityCheck field-shadow warning remains visible. The final fixture executes all health/resource/no-app assertions. Original identity and task count are unchanged; unknown-phase holds remain BOUND; actual cancelled root and stopped child produce FAILED/allStopped custody and SETTLED allocation. Every row of research rounds/projects, assistant events and curated content is unchanged, including decision, terminalRecord, terminal and project ending. Bounded identity/state evidence: `evidence/reviewed-contract-pass.json`.

Ruff, diff whitespace checks and revised strict OpenSpec validation pass. Temporary processes and the isolated database were cleaned up; PG slot released. This proves core mechanics with a synthetic model, not production identity, real model research or GPU behavior. Complete removal of owner declarations does not promise automatic business terminal/outbox repair on reinstall; no research completion is claimed. Final exact diff review remains required.
