# Verification — remove product demo modes

Base: `9454000e088ca6fba55621b8b2443ab55ffcc764`. This record is cumulative; final exact head, CI and review remain pending until explicitly updated.

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

Research evidence browser passed on desktop and mobile using the actual public OIDC/session boundary, PostgreSQL, native child and local CLI. It exercised goal revision during execution, negative results, owner/team delivery, private-project denial and withdrawn-source refusal. Mobile also executed two native association calls. Model responses came from a synthetic HTTP fixture, not a paid provider; no GPU was used. [Evidence and screenshots](evidence/research-browser/evidence.json) retain this distinction. Root inspected desktop platform entry and mobile owner delivery pixels. Temporary databases/listeners/workers were cleaned by the fixture.

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
