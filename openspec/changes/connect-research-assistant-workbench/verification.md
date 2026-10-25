# Verification

## Scope and current result

Base `f2dd047`; specification was committed as `fa8c86c` before implementation, then extended for the observed late-write acknowledgement boundary before the hook repair. This is the UI consumer of `add-research-assistant-qa`; it does not implement a second message/answer store, budget, worker, authentication mechanism or provider selection policy.

Implemented: explicit owner identity, private QA draft → explicit publication → CAS operational allowance, actual personal model connection references, directed assistant directory, original question reading, whole-answer hiding after unavailable input dependencies, current-source reading and stable project assistant association. Existing platform/resources/auth/layout are retained. The UI states “操作额度受限，token/费用未计量”; no token/cost hard-limit claim is made.

The existing application command hook now deletes a saved command only when the active view actually receives its successful result. A success arriving after unmount does not navigate a different owner's screen and retains the original request for same-key recovery. The former behavior would erase the only local receipt recovery pointer before handling the result. The correction introduces no second retry/recovery controller.

## Executed checks

- `npm run check`: exit 0; **51 files / 480 tests passed, zero skipped**, including lint, TypeScript and core frontend build. Log `/tmp/af-qa-ui-full-first.txt`.
- Explicit `npm run build:research`: exit 0, `/tmp/af-qa-ui-research-build.txt`.
- `node scripts/check_web_architecture.mjs --config scripts/architecture-web.json`: exit 0, 101 modules, 0 violations, 0 coverage gaps (`/tmp/af-qa-ui-architecture.txt`).
- Full `npm audit --audit-level=moderate --registry=https://registry.npmjs.org` and production `--omit=dev`: both exit 0, 0 vulnerabilities; `/tmp/af-qa-ui-audit.txt`, `/tmp/af-qa-ui-audit-production.txt`. No dependency/lockfile change.
- Focused application/navigation run before the full run: 45 passed; `/tmp/af-qa-ui-targeted-fixed.txt`.

New behavior tests cover actual binding selection, no write before explicit creation, draft/publication separation, operational-only allowance, CAS input retention without automatic resubmission, explicit missing-model resource entry, directed peer selection, 408/remount with same request, success-after-owner-switch retention, acknowledged question followed by read failure, entire-answer revocation, late question/source responses after replacement, and focus revalidation. Navigation coverage preserves QA setup/question IDs through the existing resource entry and rejects invalid pointers. These use controlled transport responses and do not claim actual model or browser acceptance.

## First failures retained

The first affected-suite run reported 32 passed / 1 failed because the legacy creation test still asserted `assistantId` while the deliberate new UI contract submits `researchAssistantId`; the test fixture now supplies the real owner identity shape and checks the new field while preserving old endpoint data. See `evidence/legacy-association-first-failure.txt`.

The first new-question/settings run reported 19 passed / 4 failed. The new fixtures called `ApiError` with `(status, code, message)` rather than the actual `(message, status, code)` constructor; this made 408 classification and expected readable error text wrong. Correcting the fixture arguments resolved those failures. Assertions, production timeouts and recovery conditions were not weakened. See `evidence/qa-fixture-first-failure.txt`. Evidence log trailing whitespace is normalized only; error text, counts and assertions are retained.

## Still required

Author-independent complete base/head implementation review and any necessary fixes; serial real-API dual-user browser acceptance with the actual QA deployment, actual core state/queue and synthetic provider transport, including offline recipient and withdrawal. No browser, real model/GPU, external identity-provider, C03 quality, proactive association or whole-P7 completion is claimed by these frontend checks. Coordinator owns task checkbox completion, exact CI and integration/merge decisions.
