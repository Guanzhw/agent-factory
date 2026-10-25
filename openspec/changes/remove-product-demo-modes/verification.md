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

## Remaining validation

Full portable/PG and final Web/CI, research browser journeys and exact final-head independent review are not yet complete. First daily370 had369pass/1old fixture hash failure; details and replacements are in [testing migration evidence](verification-testing.md). No production IdP, paid model or GPU call is performed. Existing real and old demo data remain untouched. Separate audit found P5/D01 remote research execution is not wired, not merely awaiting real resources; it is tracked as a separate change, not hidden by this authentication work.
