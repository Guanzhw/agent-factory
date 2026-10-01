# Verification record

Verified locally on 2026-10-01 with Windows, Python 3.14.3, Node 26.5.1, Agno 3.1.0 and task-owned loopback PostgreSQL 17.11. This record describes the synthetic implementation milestone. Earlier foundation commit ba707a272c9d3fdfcbbe479f4278ee50bde3b703 remains historical evidence, not current acceptance.

## Checks

- Frontend lint/typecheck, four HTTP client contract tests and production Vite build passed.
- Python Ruff and Pyright passed with zero errors.
- The complete opt-in suite exercises native runtime/auth, actual PostgreSQL API/queue/delegation/schedules, dependency preflight and narrow adapter contracts. All 80 tests passed locally in 37.950 seconds with PostgreSQL enabled. Exact commit CI is recorded in the draft PR after publication.
- Official npm registry audit found zero vulnerabilities. The user's configured mirror has no audit endpoint; the audit used a command-scoped official registry override without changing global configuration.
- CI is configured for frontend/Python on Windows and Ubuntu plus isolated PostgreSQL integration on Ubuntu. Actions, dependencies and PostgreSQL image are pinned. PostgreSQL fixtures create only randomly named loopback databases; intentional UNKNOWN facts are retained during each test and never discharged to make quota tests pass.

## Fail-closed evidence

Actual native Function tool pre-hooks must throw StopAgentRun. InputCheckError is appropriate for Agent input hooks but is swallowed by Function pre-hooks. Native regression verifies exhausted shared budget produces no unbudgeted artifact. Current SQL revocation, current policy withdrawal and persisted UNKNOWN effects were tested on actual approved native continuations: subprocess.Popen spies were never called; there were no new effects, compute_started events or artifacts. The direct registered experiment entrypoint also denies before compute. Application state is failed for denied authority/policy and unknown for an unresolved effect, regardless of a native loop's COMPLETED marker.

Independent child tickets preserve parent/root scope and shared counts. Reusing a child plan through standalone admission is denied, with factory task and native ticket counts unchanged. Cancellation settles the actual owned synthetic process tree before a CANCELLED effect is accepted. Rejected metadata with an acknowledged live native ticket cannot imply stopped or release capacity.

## Browser evidence

Supported Playwright CLI drove the actual loopback application, not screenshots of mocked data. Observed: login, owner-isolated Bob workspace, immutable preflight, double submission creating one ticket, native question restored after API restart and answered to completion, restored scoped experiment approval, actual evaluator values and hashed artifacts, approval followed by cancellation while compute was running, and confirmed cleanup/CANCELLED effect. Browser offline/online recovery and manager draft followed by separate publication passed. Desktop/mobile and final delegation checks are recorded with their local screenshots and final PR evidence.

One actual cancellation task was 506f5920-dbee-464f-a05b-847c6af4c3d5: compute_started, compute_stopped(cleanupComplete=true), compute_cancelled(cleanupComplete=true), application canceled and effect CANCELLED; no experiment_completed event. These identifiers belong only to disposable synthetic demo data. Browser logs contain expected unauthenticated-session and intentionally offline errors; those are not counted as unexplained product exceptions.

Screenshots/logs/SQL/runtime state remain ignored local artifacts. The committed project contains original code/docs and synthetic inputs only. Staged publication is scanned for known credential formats, private paths and prohibited runtime files.

## Limits

Agno upstream revision is ab1d6007f09163c3adadbe06f998dc481b77a09a. ORX source is f336b121525d99364e2dee4fe90b2784894a54e6 (declares 0.2.13); installed 0.2.10 was not updated or treated as compatible. ORX contract tests execute controlled subprocess fixtures; no actual literature search, paid model, autonomous scientific result, remote lifecycle/provider execution, deployment or new external access was performed.

Stock native queue hard-process recovery was tested; that does not establish full guarded scheduling adapter restart or concurrent stale-lease takeover. Actual remote adapter evidence covers metadata only; lifecycle recovery uses explicit synthetic transports. Production temporary-plan approval, identity provisioning, approved provider/model budget, exact ORX binary attestation, real remote endpoints and hostile-code isolation remain open. See ACCEPTANCE.md and SECURITY.md.
