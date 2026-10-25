# Verification

## Contract and implementation

Backend base `73772989537c25ad4a3e7a1c8a4eabd0e16f595c`; spec `e1ae7c4` preceded production edits. Actual API mapping verified against the combined backend: assistant associations uses the existing CAS configuration; core content returns source-bound rich publications; protected project/goals/experiments/rounds use the exact unions in design; Agreement.evidence and delivery create/list/read/download match the frozen P8 service. Later backend prompt wording changes do not change these UI contracts; integration remains coordinator-owned.

Implemented the three consumer groups without backend changes: explicit bounded association configuration and current-source details; protected projections and original goal/evidence preservation; current-authority manifest generation/read/download. The visible budget notice remains operational-only. Run records show actual source suitability assessments alongside original run IDs, not a synthetic claim that a source was useful. The ZIP reader uses same-origin credentials, expected owner, auth epoch and abort boundaries; it does not call the job-artifact API or claim independent SHA verification.

## Checks and first failures

- `npm run check`: exit 0, 52 files / 490 tests / zero skipped; lint, TypeScript and core build passed (`/tmp/af-evidence-ui-full-fixed.txt`). After that run, a small actual-source-assessment display/test was added and a required delivery-navigation callback was tightened; final TypeScript/research build passed separately; scoped evidence text wrapping is checked in the final build before review. The earlier full result is not mislabelled as running those later lines.
- Research build exit 0; architecture 105 reachable modules, zero violations/gaps. Targeted source-assessment test: 4 passed (`/tmp/af-evidence-ui-source-assessment.txt`).
- Full and production npm audits both exit 0, zero vulnerabilities. No dependency/lockfile change.
- First targeted run: 46 passed / 2 failed. Existing expected agreement lacked the intentional `evidence:null`; a numeric-input assertion selected the newly added maxRecipients control instead of the question count. Tests now assert the actual new payload and address the named question-count field. Error/counts preserved in `evidence/ui-first-failures.txt`.
- First complete check stopped at typecheck: optional API evidence (`undefined`) was incorrectly allowed in a controlled nullable editor callback. Narrowing the editor contract to actual selection or null fixed this; no assertion or timeout was weakened. See `evidence/web-first-type-failure.txt`.

New deterministic checks cover protected source shapes without missing-field crashes, old-body hiding, preservation of exact evidence through goal changes, explicit association activation versus old configurations, original delivery recovery after 408/remount, late owner/source responses, unavailable manifest and ZIP rejection/session switch. These synthetic frontend transports prove interactions only.

Final frozen-source `npm run check` after browser evidence commit `5f79c84`: exit 0, 52 files / 490 tests / zero skipped (22.25s Vitest), including final source-assessment/callback/CSS changes; lint, TypeScript and core build passed. See `evidence/web-final-check.txt`. This closes the earlier full-check coverage gap; no production code changed after `2f1fb74`.

## Real backend browser evidence

Production UI/backend snapshot: `2f1fb74db771d52e870d79fc72d2268148f95810` (base `7377298`). Author-independent complete base/head review passed with no required changes. The subsequent commit contains driver/evidence/documentation only. Backend prompt-only `030016a` was not part of this local browser snapshot; coordinator integration remains separate.

`scripts/accept_research_evidence_ui.py` runs Chromium against real loopback HTTPS, application/core HTTP, PostgreSQL, vault/personal model adapter, native root/child execution and an actual local CLI. Only model HTTP is synthetic. There is no business API interception. Run with the project Python environment, `PYTHONPATH=applications:applications/tests:platform:platform/tests:platform/tests/browser:deployment:scripts`, and arguments `--database-url <isolated-fixture-admin-url> --dist dist --output <new-directory> --mode demo|production-local`. Build with `npm run build:research` first. The URL must address a disposable-test-capable database; the fixture creates/drops its own isolated database and never deletes the shared container.

- Desktop (1487×1058), development identity selector: exit 0. See `evidence/browser-desktop.json` and desktop PNGs.
- Mobile (390×844), production auth mode with local synthetic OIDC: exit 0. See `evidence/browser-mobile.json` and mobile PNGs. This is not an external identity provider acceptance.
- Both: select real published setup and personal connections, explicitly publish, select exact evidence material/three fields, confirm goal v3, start original native execution, revise/confirm v4 while child is in flight, preserve original budget/evidence and original task IDs. The actual CLI succeeds with metric 3 below target 4; the controlled model records `not_met`, not technical failure or scientific success. Both original root and child reach actual native `completed` in the original 45-second bound.
- Owner creates actual manifest with no missing selected evidence; Bob reads the team manifest and downloads the three-role ZIP. Private project read is denied. Unselected private canary is absent. Revoking the owner's source hides the manifest and denies download (404). Refresh, platform return and logout/relogin use the real browser session.
- Mobile additionally: real local OIDC/CSRF HTTP prepares both assistants as an explicit fixture prerequisite, not a claim of browser-form coverage. A real prior team publication is created through the content service. New actual research publications trigger native association executions (two synthetic model calls); UI reads the actual association and original core source. Revoking the prior source hides the entire association, protects project/goals/experiments and rejects the dependent manifest. No research-specific duplicate source API is involved.
- Both runs record zero unexpected console errors and page errors. The initial driver classified deliberate 404 console entries correctly but mistakenly wrote their metadata `status` as 401. Original JSON is retained unchanged; `apiResponses` and explicit download assertions retain the actual 404. The committed driver corrects only that metadata expression; the corrected expression has not been browser-rerun, and does not change assertions or product behavior.

First failures remain visible:

1. Desktop selector failure: the script addressed a nested textarea by an unmatched exact label. This delayed release of the controlled child barrier; its timeout surfaced honestly as a personal-model failure. Fixed only the script's accessible textbox selector.
2. Desktop barrier failure: a synchronous synthetic transport blocked the server event loop while waiting for UI revision. Moved the fixture wait to `asyncio.to_thread`, preserving the same 30-second bound; no product timeout changed.
3. Desktop logout failure: the script navigated before logout completed. Waited for the login button's existing enabled state before navigating. No production change.
4. Mobile prerequisite failure: an internal native token is not a production external bearer credential. Replaced that invalid fixture authentication with actual local OIDC browser login and session/CSRF requests. Product auth was not weakened.

The four failure logs, both successful run logs and safe response-path/status evidence are committed alongside screenshots. No cookies, tokens, request authorization headers, HAR or real credentials are stored. Python/browser/server/native worker and isolated DB cleanup is managed by fixture context managers; the pre-existing shared PG container remains running. A read-only `pg_database` query after both successful runs confirmed both owned database names absent.

## Remaining acceptance

The new driver/evidence and screenshots require independent review, and coordinator integration requires exact CI. Earlier P7 private offline QA evidence is separate; these new scenarios do not repeat or expand its claims. No real provider/GPU, independent scientific reproducibility, actual target-machine capacity or C02/C03/C04 quality acceptance is claimed. Task boxes remain coordinator-owned.
