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

Author-independent complete base/head implementation review and any necessary fixes remain required. The actual backend browser work below supplements the deterministic frontend checks. No real model/GPU, external identity-provider, C03 quality, proactive association or whole-P7 completion is claimed. Coordinator owns task checkbox completion, exact CI and integration/merge decisions.

## Actual backend browser acceptance (product frozen at 48fabd7)

`scripts/accept_research_assistant_ui.py` uses the actual research deployment, owner model adapter/vault, PostgreSQL, native queue and HTTP APIs without browser interception. The only model implementation substitute is controlled ChatCompletions HTTP transport. Desktop uses the development identity selector; 390px mobile uses a local HTTPS synthetic OIDC issuer and real callback/code exchange. Neither proves an external production identity provider or model quality.

The browser explicitly creates Bob's stable assistant, saves a private QA draft, publishes its precise version, enters finite operational allowances, observes a real CAS 409 caused by a concurrent fixture configuration, retains entered values, reads the new revision and explicitly confirms revision 2. No task/model call occurs before a question. Bob logs out; Alice selects Bob in the actual directory, asks privately, receives the original native task receipt and answer with both actual input record IDs. One input is cited by the controlled answer; both are tracked as dependencies. Browser source opening, resource roundtrip, URL refresh and logout/relogin preserve the original question. Withdrawing the **uncited** second record hides the entire derived answer and all dependency buttons on reread. Each completed scenario checks one controlled model call, one recipient task, zero sender tasks, zero training dispatches and zero delegation links. Untrusted source text asks for training but does not receive that capability.

- Desktop completed every scenario assertion in the combined run, then the following mobile scenario failed on a script-only drawer interaction. Desktop screenshots are persisted; that run's initial aggregate writer did not persist the completed desktop result before the later mobile failure, so no missing structured desktop result is claimed. The script now persists each mode separately before subsequent modes.
- Mobile reran only after correcting the interaction, **exit 0**, result [browser-production-local.json](evidence/browser-production-local.json). Page errors and unexpected console errors are empty. Expected unauthenticated-session 401 and deliberately induced CAS 409 remain classified and recorded.
- Product source/build remained frozen throughout; no assertions or production timeouts changed. Source/browser runtime acceptance is tied to `48fabd75768e48aabf90afb64d487c71cf1dd22a`, not the later evidence-only commit.
- Actual model connection creation is a core HTTP fixture prerequisite, not acceptance of the model settings form. Team evidence creation/withdrawal uses the actual content service fixture, not acceptance of research publication UI. Late owner/question response suppression is covered by deterministic frontend tests, not artificially delayed browser APIs. This does not claim autonomous scientific reasoning, GPU, quality or proactive association acceptance.

### Browser first failures and exact corrections

1. [Selector failure](evidence/browser-selector-first-failure.txt): exact label lookup for the nested model `<select>` did not include its option text in the accessible name. Actual candidate/API were present. Script now uses the actual combobox name prefix.
2. [Revision observation failure](evidence/browser-revision-first-failure.txt): the fixture waited for an already-present “saved configuration” heading before reading the new revision. The safe failure screenshot showed revision 2 after the assertion. Script now waits for the exact visible revision 2, preserving the assertion itself.
3. [Mobile drawer failure](evidence/browser-mobile-dialog-first-failure.txt): returning to the original-question route correctly opens the drawer. The script redundantly clicked the background opener, which was intercepted. It now asserts that the existing drawer is visible, without force clicking. Desktop was not rerun for this mobile-only correction.

First-failure response metadata and logs are retained alongside final screenshots. No cookie, token, authorization URL query, HAR or credential values are included. Final cleanup confirmed **zero `af_test_` databases remaining**; each loopback server/native worker/browser/scratch TLS directory ended through its fixture. The existing shared PG container remains intact.

Screenshots: [desktop configuration](evidence/assistant-configured-desktop.png), [desktop answer/source](evidence/private-answer-source-desktop.png), [desktop withdrawal](evidence/withdrawn-answer-desktop.png), [mobile configuration](evidence/assistant-configured-mobile.png), [mobile answer/source](evidence/private-answer-source-mobile.png), [mobile withdrawal](evidence/withdrawn-answer-mobile.png). Actual desktop and mobile answer/source images were inspected.
