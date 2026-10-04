# Application recovery and aggregate contracts — 2026-10-04

Continuation of draft PR28 at `3afdef7c42556206910ad952b8816a5c1258f972`.
The stage PR records the exact final commit and independent terminal CI checks;
this file does not claim that an unobserved CI run passed.

## Delivered behavior

- Owner-scoped proposal history finds a committed proposal after its first reply
  is lost. Read-only recovery returns the original accepted immutable plan even
  after browser storage loss. Reading history never repeats acceptance or grants
  permission to execute withdrawn materials.
- Exact-plan review recovery distinguishes pending, denied, expired and effective
  decisions. Lost request acknowledgements reconcile through the original request
  key; owner/plan/policy checks and stale-response fencing remain mandatory.
- Explicit development mock login selects synthetic Alice, Bob and two managers
  through the existing PKCE and opaque SQL session mechanism. It has no production
  fallback. The [launcher](DEVELOPMENT_LOGIN.md) uses temporary local TLS keys.
- An opt-in [delegated aggregate backend](AGGREGATE_PROCESS_CONTRACTS.md) connects
  to existing native reservations, process custody, receiver receipts and UI.
  Positive group removal differs from present-tense limit readback. Unknown
  guardian observations retain custody; no uncertain kernel operation is replayed.
- [Deployment declaration validation](DEPLOYMENT_VALIDATION.md) reports missing
  selections with finite codes and never loads credentials or deploys a service.

## Validation and defects found by actual integration

The local Python suite ran **1119 tests in 60.294 seconds**, with **774 passed and
345 explicitly skipped** when the PostgreSQL test URL was absent. Separate new
PostgreSQL tests passed: proposal inbox/recovery **2 in 7.858 seconds** and
development identity/session isolation **2 in 4.692 seconds**. Their isolated
databases were cleaned. Full PostgreSQL coverage belongs to exact-head CI.

Frontend check includes lint, TypeScript, tests and production build. There are
**131 passing frontend tests**. Dependency audit found zero vulnerabilities.
Linux and Windows Pyright and Ruff are required before the stage commit.

Real Chromium over temporary HTTPS initially exposed a mock selector failure:
`no-referrer` caused form `Origin: null`. Only the selector document now uses
`strict-origin`; strict Origin/CSRF checks remain, and authorization query values
do not enter Referer. A causal browser probe confirmed Alice and cancellation
responses changed from 400 to 303. The complete desktop/mobile login suite then
passed normal login/logout, cancellation, abandoned/refreshed authorization,
lost-ACK logout with SQL revocation, repeated navigation and owner/role isolation,
with zero execution instances, page errors or horizontal overflow.

Actual recovery browsing also found a frontend response-shape mismatch:
`nativeToolConfirmationSeparate` belongs inside `policy`, while
`nativeToolConfirmationRequired` is top-level. The parser, types and regression
fixture now match the actual backend. A narrow proposal-list grid was corrected
after screenshot inspection. Failed runs remain diagnostic evidence, not passes.
The final desktop/mobile recovery rerun passed: create/accept/review POSTs each
occurred exactly once; after dropped replies and browser-storage loss, GET
recovered the original proposal, plan and review. Manager denial remained denied
on owner re-entry, Bob received 404, and there were zero duplicate mutation POSTs,
execution instances, page errors, unexpected console errors or horizontal overflow.
Six recovery screenshots and ten login screenshots were retained outside Git;
root and the browser worker inspected the layout and denied-state evidence.
All temporary services, browsers, TLS files and isolated databases were cleaned.

Independent review additionally found and corrected aggregate reservation
geometry, misleading post-removal readback and ambiguous guardian-death recovery.
Fake filesystem, SQLite and mocked full guardian control-flow tests verify
ordering, no replay and positive stop contracts. They do not exercise cgroups.

Initial CI at `c834ba6` exposed two Windows fixture failures: Linux-only affinity
and uname attributes needed explicit mocked creation, and a SQLite engine had to
be disposed before its temporary directory cleanup. The fixes only change tests;
22 targeted tests pass locally. That failed head is not accepted, and its
superseded workflows are cancelled in favor of the corrected exact-head runs.

The next CI head `5159742` passed all eight frontend/Python platform jobs, but
push PostgreSQL exposed an implicit static-file fixture dependency: the new
backend navigation test expected repo `dist/index.html`, which the PostgreSQL
job does not build. That run had 1119 tests, 1055 passed, 63 skipped and one
failure (1418.216 seconds). The test now supplies a temporary synthetic HTML
file through the real static route and asserts its marker, retaining every
session/CSRF/owner assertion. Two actual PostgreSQL cases pass in 4.606 seconds.
This backend document fixture does not substitute for the separate real React
browser acceptance. The failed head is not final acceptance.

## Remaining boundaries

No live provider/key calls, host/cgroup/security configuration changes, machine
provisioning, real identity onboarding, deployment or merge occurred. Linux is
selected, but actual delegated-host enforcement, receiver TLS/identity and target
capacity remain unaccepted. The process profile is deliberately bounded and
trusted; it is not a general scientific sandbox. Remaining whole-application
code gaps and external scientific acceptance are in the
[application audit](V03_APP_GAP_AUDIT.md) and
[scope reconciliation](V03_SCOPE_RECONCILIATION.md). This milestone is not a claim
that the complete v0.3 product or production deployment is finished.
