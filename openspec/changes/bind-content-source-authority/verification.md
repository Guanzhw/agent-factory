# Verification

Spec de32456 was reviewed before implementation; compatibility/lock-order correction 11bd7e2 independently passed. The current ResearchRuns writer takes admission before its domain/content locks; completion callbacks run in the original admission transaction. AssistantEvents.emit now takes admission before its own event lock. No new execution controller or owner-proxy download was added.

- Existing content/events portable modules: 16/16, zero skips, 2.768s. New source cases plus these modules: 21/21, zero skips, 3.835s. An initial 29-pass run redundantly inherited existing test methods; the new test class was changed to inherit only the fixture, avoiding duplicate coverage.
- Independent test author ran real PG source/artifact tests: 3/3, zero skips, 20.950s, first run exit0. Real native Alice/Bob artifact, nested sources, generic HTTP body/list/artifact/replay/sharing and both withdrawal/read barrier orders passed. Existing event transaction/rollback/current-revocation regression: 1/1, 4.076s, exit0. Logs: /tmp/content-sources-pg-first.log and /tmp/content-sources-event-pg.log. Temporary workers/schedulers stopped normally.
- Ruff and diff checks pass. Targeted production Pyright uses this worktree's explicit platform path: zero errors/warnings. An exploratory check also included test files outside repository type-check scope and reported Pydantic dict-constructor/optional fixture-client typing diagnostics; runtime tests passed, no test assertions were relaxed.

P7/P8 actual consumers and final exact-head review/CI remain pending. These tests use synthetic identity/model fixtures and do not establish real model value, external identity or GPU acceptance.
