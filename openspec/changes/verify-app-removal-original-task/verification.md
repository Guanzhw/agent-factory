# A01 same-database app removal — failing acceptance evidence

Base: `931f7c3`. Only specification and test fixtures changed. No production fix, no paid model or GPU.

The actual Research service created an original native workflow, paused on its original delegated operation, with a completed child and a bound budget allocation. After killing that process, the fixture started a separate bare-core process against the same isolated database/workspace. That process imported neither Research nor deployment and had no registered application owners, workflows, or configured runtime adapters.

## Executions

- First run: exit 1, 1 failure, 20.792 seconds. Fixture incorrectly changed `demo=True` to `demo=False` during restart. The existing bootstrap guard correctly rejected that mode change. Log: `/tmp/research-removal-first.log`.
- After keeping the original authentication mode: exit 1, 1 failure, 15.646 seconds. Original task/run/operation identities and the two task IDs were preserved. Initially the root remained paused, nonterminal and held. The actual lifecycle observer then positively cancelled the native root, closed the delegated operation as failed, made the task terminal/failed, and settled its scope. This fails the proposed retained-UNKNOWN/holds assertion. Log: `/tmp/research-removal-mode-fix.log`; bounded synthetic state is committed in `evidence/same-database-first-observation.json`.
- Ruff and `git diff --check`: pass. Strict OpenSpec validation passed for the initial specification.

The failure does not demonstrate redispatch or a false native completion: the observed native state is cancelled. It exposes the distinction between missing hooks for a still-declared owner and complete removal of all owner declarations. `ApplicationRuntimeRegistry.finalization_context` can preserve the former, but returns no application completion responsibility for the latter. The generic scope finalizer then settles a positively stopped group. Product changes or adjustment of the requested acceptance boundary require coordinator judgment; neither was silently applied here.

The health/routes/resource assertions after this failed assertion were not reached and are NOT RUN, not passed. Both fixture processes terminated, the isolated database context cleaned up, and the PostgreSQL slot was released. No existing user database or archive was modified. This case remains FAIL pending disposition and independent review.
