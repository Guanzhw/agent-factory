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

## Remaining acceptance

Author-independent full base/head review, any necessary corrections, real-API dual-user browser/PG verification and coordinator exact CI remain required. No real provider/GPU, scientific reproducibility or C02/C03/C04 quality acceptance is claimed. The planned browser uses actual backend/core/native/CLI and only synthetic model HTTP, never intercepted business APIs. Task boxes remain coordinator-owned.
