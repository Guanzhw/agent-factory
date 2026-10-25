# Actual API browser: owner model / research schema incompatibility

Status: **FAIL, not completed acceptance**. Product code: `30699a37838dd3c59d0b02f361741e753e3a0b80`. `npm run build:research` exited 0. Browser uses that actual optional-research build and deployment, an isolated PostgreSQL database, development-selector HTTPS login, real cookie/CSRF and business HTTP. No Playwright request interception. Only provider transport and the registered local checksum tool are synthetic; no external provider or GPU was called.

## Completed before the failure

The browser followed platform home → AutoResearch → create project → save agreement → prepare private setup → explicit publish → use the returned exact application/connection references → save goal version 2 → confirm → explicit start. A personal model connection was created through actual core HTTP as a synthetic fixture prerequisite, not through the model-settings UI. The tool material was explicitly published through the existing governance service; the database did not contain a prebuilt research application.

Actual endpoint families used: `/api/factory/auth/*`, `/api/factory/session`, `/api/factory/personal-models`, `/api/factory/research/projects`, project `/goals`, `/confirm`, `/start`, `/experiments`, and `/api/factory/research/setup` draft/read/publish. These were served by the actual core/application deployment.

## Failure and distinguishing diagnostic

The native root workflow was admitted and ran. Its first model step failed with public code `PERSONAL_MODEL_REQUEST_FAILED`. Reading original `/experiments` returned a root task with status `failed`, `decision: null`, no experimental items, and an original terminal-record ID. This is **not** zero root dispatch: root admission/execution happened. There was no child experiment in the record and the synthetic model transport did not run.

A separate bounded diagnostic repeated the same journey with a transparent wrapper around `OwnerChatModel._body`: it called the original method, recorded only exception class, the boolean presence of response format and the known error code, then re-raised the original exception. It did not change results, configuration or transport. Recorded line:

```text
MODEL_BODY_DIAGNOSTIC ModelProviderError response_format_present=True code=PERSONAL_MODEL_UNSUPPORTED_FORMAT
```

The research workflow's `Agent(output_schema=Decision/Evaluation)` passes a response format, but the actual personal model adapter rejects it before invoking its transport. `_request` then reports the generic request failure. Fixed registered-model workflow tests do not cover this owner-model path. No product fix, assertion relaxation or replacement fixed model was applied by this browser task.

The two original runs without this wrapper failed at the same workflow step. The diagnostic supports a concrete compatibility defect, rather than attributing the failure to a browser timeout or resource contention. Model/GPU scientific acceptance remains NOTRUN; P7 research team-reading and peer-QA APIs remain NOTDONE.

## Retained local evidence

- `/tmp/af-live-integrated-build.log`: research build, exit 0.
- `/tmp/af-live-real-browser-select.log`: first product failure, exit 1; `/tmp/af-live-real-browser-select/demo/first-failure.png`, `failure-page.txt`, `errors.json`.
- `/tmp/af-live-real-browser-model-diagnostic.log`: synthetic transport exception instrumentation, no transport exception emitted; exit 1.
- `/tmp/af-live-real-browser-body-diagnostic.log`: exact format rejection diagnostic, exit 1.
- `/tmp/af-live-model-body-diagnostic.py`: transparent temporary diagnostic wrapper.

Earlier fixture-only failures are separately preserved: `/tmp/af-live-real-browser-first.log` (tool material must use exact registered declaration), `/tmp/af-live-real-browser-exact-tool.log` (formal UI logout is in the account menu), `/tmp/af-live-real-browser-account.log` (select label includes option text; changed the fixture locator to role plus label prefix). These are not product defects. No retry was represented as erasing an earlier result.

Raw logs were not copied to the public repository. This summary contains only synthetic, non-secret metadata. No HAR, token, cookie, authorization URL, key or credential value was saved. The final failure-page evidence reported no page errors or console errors.

## Cleanup and continuation

Each run exited its owned browser/server contexts and stopped native worker/scheduler. Each `IsolatedPostgres` context dropped only its generated `af_test_` database. After the diagnostic, a read-only catalog query found **zero `af_test_` databases**. The pre-existing `af-research-next-pg` container/volume was retained. No test server remains from these runs; PostgreSQL execution slot was released to the coordinator.

Continue after the owner-model compatibility repair with `scripts/accept_live_research_workbench.py`. Complete the remaining browser identity/history/owner-isolation assertions and production-local OIDC/mobile journey; the current failure is not a substitute for those results. The script intentionally fails until an actual research decision exists. The authoritative implementation must not be changed by the diagnostic wrapper.

## Text-output repair verification: second concrete blocker

On integrated code `81859a528e75a8031880166362e9e5e19aed5b40`, the same browser script created a fresh database and explicitly published the newly registered workflow pin. Frontend bytes were unchanged from the existing `30699a3` research build. The first model decision now succeeded and dispatched an actual native child. In the uninstrumented run, that child completed the local checksum tool and archived an artifact. The root workflow still failed later, with `decision: null`; the original failed root and completed child were both retained. `/tmp/af-live-real-browser-text-model.log` exited 1. The planned production-local/mobile scenario was NOTRUN because the desktop journey failed first.

A single transparent `_body` diagnostic then recorded `ValueError`, `response_format_present=False`, distinguishing this from the repaired format rejection. That run's failure cleanup also interrupted its child; do not substitute its failed child for the completed child in the first uninstrumented run. Its log is `/tmp/af-live-real-browser-text-body-diagnostic.log`, exit 1. The PostgreSQL slot was released after cleanup to the identity tests.

A focused portable experiment using actual Agno `Agent`, actual `OwnerChatModel`, and the actual `factory_wait_operations` tool confirmed the exact failure **without PostgreSQL or a provider call**:

```text
OwnerChatModel._body → encode_request → _tools → ValueError('MODEL_PROTOCOL_TOOL')
```

Agno's tool schema includes the local `external_execution: true` field inside `function`. The personal-model adapter passes that schema unchanged to the protocol codec, whose provider tool allowlist rejects this local runtime field. The diagnostic contains only the public tool declaration and frame locations: `/tmp/af-live-owner-wait-portable-diagnostic.txt`. No product code was edited here. The repair must preserve local external-wait semantics and the strict provider boundary rather than removing the native pause or accepting arbitrary provider fields. The browser remains **FAIL**, pending this second actual integration repair and the remaining journey assertions.
