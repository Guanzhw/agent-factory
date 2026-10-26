# Verification — remove product demo modes

Base: `9454000e088ca6fba55621b8b2443ab55ffcc764`. This record is cumulative; final exact head, CI and review remain pending until explicitly updated.

## Current final-code validation: 1597fe8

Exact code head `1597fe8bbc29a2ba596db1e1f3878dd4da014c6c` passed
[full40233357540](https://github.com/Guanzhw/agent-factory/actions/runs/40233357540), all **7 jobs SUCCESS**.

| Check | Actual result |
|---|---|
| Combined core/application PostgreSQL discovery | 2068 total: 2063 passed, 5 skipped, zero failures/errors; 2022.780s. Required groups 102/16/10/19/5: all 152 passed, zero skipped. PG artifact `12615216185`. |
| Windows Python | 2068 total: 1228 passed, 840 skipped, zero failures/errors; 273.567s. |
| Frontend on both platforms | 487 tests in 52 files passed per platform. AST checker 11 passed. |
| CI Chromium | Configured and bind-loss desktop scenarios passed against the synthetic API; not real IdP authentication. Earlier actual local-OIDC browser evidence remains separate below. |
| Standalone installed core | Passed, including `demoSettingAbsent`, `publicUnconfiguredIdentityDenied` and synthetic external-bearer resource validation. No real external IdP/TLS/model/remote acceptance is inferred from this probe. |

Exact [fast40232215707](https://github.com/Guanzhw/agent-factory/actions/runs/40232215707)
also succeeded: 370 Python and 61 PostgreSQL cases (PG zero skips).
Foundation's independent cumulative review of base `9454000` → exact `1597fe8`
is PASS; see [review](review.md#final-code-cumulative-review-1597fe8).

This documentation-only follow-up changes no production source, tests, workflows
or lockfiles relative to 1597fe8. A new exact-head fast check and documentation
review are required before merge; no unchanged full rerun is needed. PR136 is
not yet merged, and no resulting-main validation is claimed.

Historical failures remain failures: old 624 full40228654327 ended with 2068
combined cases, 2057 passed/2 failures/4 errors/5 skips (2091.848s). Earlier
full/targeted failures remain below and in verification-testing.md. The final
full pass does not establish the causes of earlier MCP/storage timing failures,
nor does it demonstrate overall suite speedup.

### Local Windows handoff

Keep the local Windows instance stopped until its explicitly configured external
identity is ready; real organization authentication has not been accepted here.
After merge, update the stopped clone to the verified main commit and install
locked dependencies using the repository development instructions. Remove retired
demo/profile startup options from the launch configuration; do not replace them
with a test issuer or fixture mode. Public access without configured identity is
rejected. Existing demo databases are rejected before schema/identity migration;
this change does not delete, promote or clear their contents. Retain existing data
and obtain a separately scoped migration/deletion decision if needed. No local
update, data deletion or deployment was performed by this cloud validation.

## Implementation and independent corrections

- Specification committed first as `81dd35f`; explicit public/internal identity boundary clarified before its implementation in `4a3cfb3`.
- Frontend slice `b3a7ce3` removed persona login, runnable prototype/HTML/packaging and Chart.js. Initial complete Web check: 483 tests, zero skipped, build/types/lint and both audits passed. Independent reviewer found four live navigation cases deleted with a demo-named file; `6d102eb` restored their exact assertions, targeted4/4 and independent incremental review PASS. Final complete Web count requires another actual run.
- Backend auth `077f463`/`503baee` removed demo configuration/identity/seed/profile. Independent review rejected exposing valid internal HS256 credentials through the unconfigured public app. `2e0be62` added only a no-IdP outer rejection boundary, preserving the original internal bridge; independent review PASS. First portable authentication24/24 passed17.053s.
- Runtime slice `485563f` removes legacy demo bindings/adoption. Old bootstrap application/material records explicitly cannot authorize new execution; source pins, exact bindings, authority and original UNKNOWN custody remain. Independent full-slice review PASS.

## Actual PostgreSQL identity and preservation

`test_development_login_postgres`: first4 cases had2 passes/2fixture errors5.109s; replacing a frozen OIDC config reused its mappingproxy JWKS. Fixture correction supplies original raw public JWKS, without changing production verifier, assertions or deadlines. Final4/4 passed0skip12.828s at `ee22338`; independent incremental review PASS. These are PG/TestClient OIDC protocol cases, not Chromium. Cases include correct session lifecycle/current membership and no-IdP public internal-token rejection while internal bridge works. The isolated old demo DB is rejected with exact original table list/mode/canary unchanged; no real database was cleared or promoted.

## Chromium and installed standalone core

Browser first attempt failed before business steps because Playwright's expected bundled executable was absent. An explicit existing `/usr/bin/chromium` then reached real login but failed the empty-catalog assertion: the supplied dist was the research build, not core-only. Both original failures remain in local logs. No assertion or timeout changed. `a914590` accepts explicit browser executable and dist; a separate core-only build was used.

Actual desktop/mobile Chromium run passed using a test-directory HTTPS OIDC peer and the real public app: login, reload, logout, pending-flow retry, private/no-store, HttpOnly/Secure cookie and no horizontal overflow. Two authorization/code exchanges. Safe [JSON](evidence/core-browser/evidence.json) and six screenshots are retained; no token/cookie/private key is in the artifact. This is local synthetic OIDC, not organization IdP acceptance.

Independent wheel build/install/lifecycle passed first run. The installed package has no development_identity/development_tls/process_runtime_profile/go_development module and no Settings.demo field. Actual TCP HTTP verifies health and rejects internal bearer without IdP. A test-only external RSA token through the existing OIDC bridge over ASGI HTTPS verifies empty catalog and member/admin resource permissions; that part does not certify real network TLS. One actual native/store lifecycle shuts down cleanly; no research package/routes/tables/default apps are installed.

## Subsequent local checks

Full portable at `9f84216`: 2068 total, 1507 passed, 561 explicit skips, 179.243s, exit 0. The first full run had 7 failures and 12 errors; fixture corrections and original logs are retained in [testing migration evidence](verification-testing.md). Production Pyright returned zero errors/warnings; Python architecture check covered 480 modules with zero violations or coverage gaps. The first Pyright command used a misplaced temporary config and was stopped; it was not a product check result.

Final local `npm run check` at `8a573b4` passed: 52 files, 487 tests, zero skips, plus lint, types and core build; Vitest 21.52s. Log: `/tmp/af-no-demo-web-final.txt`. This includes the four restored navigation cases. Subsequent changes so far are documentation/test-fixture corrections; exact published-head CI remains required.

Research evidence browser passed on desktop and mobile using the actual public OIDC/session boundary, PostgreSQL, native child and local CLI. It exercised goal revision during execution, negative results, owner/team delivery, private-project denial and withdrawn-source refusal. Mobile also executed two native association calls. Model responses came from a synthetic HTTP fixture, not a paid provider; no GPU was used. [Report index and screenshots](evidence/research-browser/evidence.json) retain this distinction. Root inspected desktop platform entry and mobile owner delivery pixels. Temporary databases/listeners/workers were cleaned by the fixture.

First PG fast run at `2bb08fc`: 61 tests, zero skips, 12 failures and 22 errors, 177.619s, exit 1 (`/tmp/af-no-demo-pg-fast-first.log`). This is a failed check, not a release result. Diagnosis and targeted corrections are in progress; no assertion or production authentication relaxation is authorized by this failure.

## Remaining validation

PG corrections/full validation, final Web/CI and exact final-head independent review are not yet complete. First daily370 had369pass/1old fixture hash failure; details and replacements are in [testing migration evidence](verification-testing.md). No production IdP, paid model or GPU call is performed. Existing real and old demo data remain untouched. Separate audit found P5/D01 remote research execution is not wired, not merely awaiting real resources; it is tracked as a separate change, not hidden by this authentication work.

## Published-head update

At `ba08307`, [fast CI 40223992140](https://github.com/Guanzhw/agent-factory/actions/runs/40223992140)
succeeded. The older d6c8f62 full run ended FAIL (platform PG: 2068 cases,
2018 passed/36 failures/9 errors/5 skipped). The synthetic browser fixture
correction passed all 8 Chromium scenarios and independent review; PG fixture
corrections remain in progress. See [exact counts, first failure and review boundaries](verification-testing.md#published-ci-checkpoint--2026-10-25-head-ba08307).
This update supersedes pending fast-CI statements above, not the unresolved full
validation or historical MCP diagnosis.
