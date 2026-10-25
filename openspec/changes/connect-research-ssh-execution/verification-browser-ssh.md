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
