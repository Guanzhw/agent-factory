# Verification

Spec de32456 was reviewed before implementation; compatibility/lock-order correction 11bd7e2 independently passed. The current ResearchRuns writer takes admission before its domain/content locks; completion callbacks run in the original admission transaction. AssistantEvents.emit now takes admission before its own event lock. No new execution controller or owner-proxy download was added.

- Existing content/events portable modules: 16/16, zero skips, 2.768s. New source cases plus these modules: 21/21, zero skips, 3.835s. An initial 29-pass run redundantly inherited existing test methods; the new test class was changed to inherit only the fixture, avoiding duplicate coverage.
- Independent test author ran real PG source/artifact tests: 3/3, zero skips, 20.950s, first run exit0. Real native Alice/Bob artifact, nested sources, generic HTTP body/list/artifact/replay/sharing and both withdrawal/read barrier orders passed. Existing event transaction/rollback/current-revocation regression: 1/1, 4.076s, exit0. Logs: /tmp/content-sources-pg-first.log and /tmp/content-sources-event-pg.log. Temporary workers/schedulers stopped normally.
- Ruff and diff checks pass. Targeted production Pyright uses this worktree's explicit platform path: zero errors/warnings. An exploratory check also included test files outside repository type-check scope and reported Pydantic dict-constructor/optional fixture-client typing diagnostics; runtime tests passed, no test assertions were relaxed.

P7/P8 actual consumers and final exact-head review/CI remain pending. These tests use synthetic identity/model fixtures and do not establish real model value, external identity or GPU acceptance.

## Integration checkpoint, 2026-10-25

Independent full-diff review passed through 606529f943c2c37044131eadb23efc67cd179ae1 and the documentation correction 0c065d2. Retarget bc776078f349b29c3d72999f145008fa4196c203 → 18921fc90d10a328fd7d55c38cdd96bb399c4ee2 retained the identical ten-file diff and independently passed. Exact fast [40209360880](https://github.com/Guanzhw/agent-factory/actions/runs/40209360880) succeeded; PR128 remains Draft.

P7 consumer review found a domain-before-admission lock inversion in project mutation and unnecessary duplicate rich-body storage. Those application changes are being corrected before final consumer acceptance; the core tests above do not discharge that application gate. Root combined the two core ports without conflicts and ran their portable modules together: 11 tests, zero skips, 0.836s. No new full or live-resource result is implied.
