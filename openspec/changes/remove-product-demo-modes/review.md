# Independent integration review

Reviewer: cloud agent `pr104_independent_review`, not an implementation author of the product slices.

- Base: `9454000e088ca6fba55621b8b2443ab55ffcc764`
- Reviewed head: `c87428773eb96f23468ae7ab5e34c41b4d6c0d48`
- Conclusion: code review PASS; validation gate remains open.

The reviewer inspected the full 212-file change inventory, all product code differences and packaging boundaries, reusing earlier independent frontend, authentication and fixture reviews and checking representative permission, budget, original-request and protocol assertions. No new product blocker was found. Demo/mock configuration, persona/cookie login, bundled IdP, seed/adoption and implicit binding fallback are removed. The unconfigured public identity boundary rejects internal tokens; old demo databases are rejected before schema/identity migration. Product source does not import the test fixtures. Existing data is neither deleted nor promoted.

Earlier required corrections were implemented and independently rechecked: restore four real navigation tests removed with a demo-named file; reject internal tokens at the unconfigured public boundary; supply raw public JWKS when replacing frozen test OIDC configuration. The review does not replace actual verification.

The first PG fast run still failed at the reviewed head (61 tests, 12 failures, 22 errors). Four uncommitted fixture corrections were excluded from this review and require incremental review. Necessary PostgreSQL checks and exact published-head CI remain required before merge. Organization IdP and remote GPU execution are not established by this review.

## Subsequent independent incremental reviews

The original full-diff review above remains tied to its own head. Subsequent
reviews reported by the coordinator add these exact boundaries:

| Base | Head | Scope | Conclusion |
|---|---|---|---|
| `c87428773eb96f23468ae7ab5e34c41b4d6c0d48` | `3247127c037e5524658746a31e044e3b716924d0` | Fixture corrections after the initial review | PASS |
| `3247127c037e5524658746a31e044e3b716924d0` | `d6c8f620322eb4fe246c300000da93b53a2d4163` | Bounded test-local diagnostics | PASS |
| `b622e4a1c339f8a1f009dce9655f45eedf9aa643` | `ba083074df8e1f049174f39b654315bd1ef5e8df` | Personal-tool browser fixture configured-session/CSRF correction | PASS |

These are code-review conclusions, not a full-suite PASS. The exact fast run at
ba08307 succeeded, while the earlier d6c8f62 full run failed. Subsequent PG
fixture edits require their own affected-diff review and validation; see the
[CI checkpoint](verification-testing.md#published-ci-checkpoint--2026-10-25-head-ba08307).

## Final cumulative review before necessary full validation

Independent reviewer `/root/pr104_independent_review` reviewed base
`9454000e088ca6fba55621b8b2443ab55ffcc764` through
`1ebd15b754e5f22e1dce98fdd79b2fddc852a04a`: **PASS**, 219 files.
The reviewer reused the original complete product review and checked the full
37-file increment from c874287: tests, browser fixture, documentation and evidence
only, with no SSH implementation mixed into this change. Current-member denial,
empty OIDC directory, binding rejection, budget and UNKNOWN assertions remain.
Diagnostic wrappers preserve original calls and deadlines; stack output excludes
source lines and locals; GC observation does not change collection policy.

The earlier diagnostic source-line finding at d345014 was corrected by 8362eb7
and independently re-reviewed PASS. Foundation review also passed the passive
GC/watchdog correction a0112b0. The final cumulative diff check passed.
This conclusion permits continuing the Draft and necessary exact-head CI, not
claiming a successful full run. Original full failures, two later MCP timeouts
and the storage cancellation timeout remain recorded; isolated diagnostic passes
do not close their historical causes.

## Final-code cumulative review: 1597fe8

Independent `foundation_review`: exact base
`9454000e088ca6fba55621b8b2443ab55ffcc764` → head
`1597fe8bbc29a2ba596db1e1f3878dd4da014c6c`, **PASS**.
The exact full40233357540 subsequently completed all seven jobs successfully;
counts and boundaries are in [verification](verification.md#current-final-code-validation-1597fe8).
This supersedes earlier pending-full status without erasing earlier rejected
reviews, failures or unresolved historical timing causes.

The present follow-up is documentation only: production/tests/workflows/lockfiles
are unchanged from tested 1597fe8. Its documentation diff and new exact fast CI
remain to be reviewed before merge. PR136 remains unmerged; no future main SHA
or result is assumed.
