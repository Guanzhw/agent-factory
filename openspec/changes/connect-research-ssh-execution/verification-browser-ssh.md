# SSH-specific browser checkpoint

The existing CLI browser journey does not cover the new SSH selectors or explicit execution consent. The 489 Web tests prove deterministic DOM interactions only. This narrow actual-API script reuses existing isolated PG/native resource setup and local HTTPS OIDC, with no new product mode or controller.

## First run

- Source `3b3f32b`; research Vite build passed. Chromium viewport 1487×1058.
- `PYTHONPATH=scripts:applications:applications/tests:platform:platform/tests:deployment /workspace/agent-factory-core-only/.venv/bin/python scripts/accept_research_ssh_ui.py --dist dist --output /tmp/af-research-ssh-ui-first`, existing synthetic `FACTORY_TEST_DATABASE_URL`, outer timeout 180 seconds.
- Exit 1. Actual login, prepare-only versus execution authorization, explicit button, dropped successful bind response, refresh and original receipt recovery passed. Exactly one bind request and zero tasks/helper starts were asserted before the screenshot.
- Failed at the SSH evidence-source selector: exact implicit-label lookup did not match the real select's accessible label including option text. [Original failure](evidence/browser-ssh-first/failure.txt), [actual page](evidence/browser-ssh-first/first-failure.png), [consent checkpoint](evidence/browser-ssh-first/ssh-execution-consent.png), [console](evidence/browser-ssh-first/browser-errors.json).
- Corrected fixture selectors to the existing browser suite's combobox/prefix-name convention and supplied required agreement budget fields. No product or timeout change. Final source/save/refresh and QA assertions remain NOT RUN to completion.
- Worker/scheduler stopped. Separate read-only cleanup check: matching helper/training/browser Python processes `[]`, `ssh-native-*` directories `[]`, isolated `af_test_%` databases `[]`. Shared PG retained; slot released.

## QA boundary

`test_research_qa_setup.py` asserts the exact published QA tools are `research_qa_context` and `research_qa_record`; `test_research_qa.py` asserts native `Agent.tools == []` and no provider tools field. The existing malicious-provider PG case asserts a returned `train` call fails, one model call only, no tool resolution/dispatch, and no delegation links. These are enforced boundaries, not prompt claims.

The narrow browser fixture additionally prepares/publishes QA while the real SSH adapters/materials are registered and asserts the same exact tool set excludes `LAUNCH_TOOL`. That new assertion has not yet been reached in this first run. No extra QA PG matrix is needed.

HTTP lost-response recovery is distinct from runtime UNKNOWN reconciliation, which remains covered separately. Synthetic local OIDC/resource credentials/probe are test prerequisites, not real identity, host, GPU or provider acceptance. No research task is started by this browser scenario.

## Second run — completed business checks, console classification failed

- Tested head `bb10f29ed4ed851ab918e38cc4fcbfdccf6192c1`, same command/deadline/viewport with output `/tmp/af-research-ssh-ui-second`; exit 1.
- All consent, original-receipt, source-kind clearing, exact selected-field save/reload, QA publication with SSH registered and zero-task/helper assertions completed. Final console assertion failed on the initial unauthenticated `/api/factory/session` HTTP 401; pageErrors remained empty. The script recognized only `/auth/session`, unlike the existing browser suite which recognizes both login session endpoints.
- [Original second failure](evidence/browser-ssh-second/failure.txt) and [console evidence](evidence/browser-ssh-second/browser-errors.json) retained. Corrected only known session HTTP 401 classification **before login**; post-login or other endpoint errors still fail. No product or timeout change. This run is not labelled PASS.

## Third run — PASS

- Actual checkout `b88499a8594d0b77a51623e36b99258d2c6b1985`; independently reviewed script `5ff71f8`, no application changes since the research build. Same command/180-second outer limit with output `/tmp/af-research-ssh-ui-third`.
- Exit 0; complete single desktop Chromium scenario at 1487×1058. [Result and console JSON](evidence/browser-ssh-third/evidence.json), [run log](evidence/browser-ssh-third/run.txt), [execution consent screenshot](evidence/browser-ssh-third/ssh-execution-consent.png), [SSH selection screenshot](evidence/browser-ssh-third/ssh-selected-evidence.png). Both earlier failures remain retained.
- Exactly one original execution bind request `00b2275d-1bb3-4419-8869-aba7098fd840` reached the real server; its successful response was dropped, refresh retained the request and lookup recovered its real receipt. No replayed mutation. Prepare-only initially did not authorize execution; explicit consent changed that fact without starting work.
- Source switching cleared incompatible selection; saved/reloaded project retained `ssh-process`, exact launch material pin and only metrics/source/run_recipe fields. Initial missing selection was visibly unconfigured; no default evidence was fabricated.
- Actual QA prepare/publish on the same host with SSH registered produced exactly `research_qa_context` and `research_qa_record`; SSH launch was absent. Tasks, delegation links and helper launches stayed zero.
- Page errors and unexpected console errors were empty. The initial unauthenticated `/api/factory/session` 401 is retained separately; post-login errors remain failures.
- Both local HTTPS servers, browser and fixture resources stopped. Additional read-only inspection found no matching helper/training/browser Python processes, no `ssh-native-*` directories and no isolated `af_test_%` databases. Shared PG retained and heavy slot released.
- This closes the newly introduced desktop SSH UI interactions, not mobile/device coverage, runtime UNKNOWN reconciliation, external identity/SSH/GPU or live-model autonomy. Native execution and selected team artifact authority are separately evidenced in [the native integration record](verification-research-native.md).
