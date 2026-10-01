# Verification record

Verified locally on 2026-10-01 with Windows, Python 3.14.3, Node 26.5.1, Agno 3.1.0 and task-owned loopback PostgreSQL 17.11. This record describes the synthetic implementation milestone. Earlier foundation commit ba707a272c9d3fdfcbbe479f4278ee50bde3b703 remains historical evidence, not current acceptance.

## Checks

- Frontend lint/typecheck, eight HTTP client contract tests and production Vite build passed.
- Python Ruff and Pyright passed with zero errors.
- The complete opt-in suite exercises native runtime/auth, actual PostgreSQL API/queue/delegation/schedules, dependency preflight and narrow adapter contracts. The initial stage passed 80 tests. The expanded stage passed all 89 tests with PostgreSQL enabled, including five real TCP acceptance cases and four actual native cancellation-contract regressions. Exact commit CI is recorded in the draft PR after publication.
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

Stock native queue hard-process recovery was tested; that does not establish full guarded scheduling adapter restart or concurrent stale-lease takeover. Actual remote adapter evidence covers metadata only; lifecycle recovery uses explicit synthetic transports. Final production policy selection, identity provisioning, approved provider/model budget, exact ORX binary attestation, real remote endpoints and hostile-code isolation remain open. See ACCEPTANCE.md and SECURITY.md.

## Backend contract extension

See [actual backend contracts](BACKEND_CONTRACTS.md) for the mapped subset of independent draft PR #8, committed-ACK-loss and process-restart acceptance, native cancellation Query compatibility and remaining complete v0.3 boundaries. The actual browser ACK-loss recovery task was 72964902-5a49-4c6e-a85d-4d4b94fd2413: one POST, one receipt GET, one native acceptance, one artifact and explicitly synthetic evidence. Exact-head CI is recorded with each draft update.

## Configurable plan-review checkpoint

The complete staged backend suite passed all 107 tests with actual PostgreSQL enabled in 59.058 seconds, including 18 new plan-policy cases. This invocation loaded only tracked/staged test modules and excluded an independent remote adapter still under development. Ruff and Pyright passed; frontend lint/typecheck, eight client tests and production build passed.

The real isolated browser owner/admin workflow refused self-approval (403) and unreviewed admission (409), retained one review after repeated submission, then completed one native execution with one POST and one artifact. A second workflow denied a plan, kept execution disabled with zero tasks, explicitly created a new review and recovered after administrator approval. Desktop review scope was visually inspected; its initially narrow grid was corrected and rechecked. Administrator and owner 390px pages stayed within viewport width. Prior evidence is retained when current authority is withdrawn. See [plan policy](PLAN_POLICY.md) for tested configuration, expiry and ancestor boundaries.

This checkpoint adds configurable approval with a conservative production default; it does not authorize a live provider or production identities. Exact remote SHA/CI is verified after each publication and recorded in the draft PR.

## Remote placement and guarded schedule restart checkpoint

The complete staged suite passed 146 tests in 111.443 seconds with actual
PostgreSQL enabled (144 passed; two explicit ORX-binary opt-in tests skipped).
It excludes a separately developed material governance module not yet wired at
this checkpoint. The two optional tests were then run against the exact isolated
ORX 0.2.13 build and both passed in 0.157 seconds. Ruff and Pyright passed;
frontend lint/typecheck, ten HTTP client tests and production build passed.

New coverage comprises twenty adapter and eight main-wired product remote tests,
plus nine real guarded schedule interruption/recovery cases. ASGI transports are
controlled; native database, queue, authentication, questions/approvals and fixed
experiment process cleanup are actual. Read-only identity downgrade retains fact
inspection and rejects new execution. The scheduler tests explicitly expose the
native unconditional lease-release race; they do not certify atomic lease release
or multiple scheduler replicas. Full default 300-second grace was not awaited.

Supported browser acceptance used two actual loopback HTTP servers and separate
PostgreSQL stores. The remote root and one child were paused at native questions;
repeated clicks produced one child POST, and root cancellation finished with
allStopped=true, unknown=false. Stale answer version returned 409. A separate
selected remote goal produced one task, one dispatch boundary and one artifact;
downloaded bytes and receipt SHA-256 matched. Bob saw zero jobs/targets and the
foreign task returned 404. The 390px page document width was exactly 390px.
Desktop/mobile screenshots were visually inspected and remain ignored evidence.
Synthetic model/literature labels remained visible throughout.

Public safe build provenance is in ORX_BUILD_PROVENANCE.json. An actual bounded
ORX local status lookup timed out, so no successful real project/experiment or
research workflow is claimed. The checkpoint scan found no credential, private
path or runtime-file findings. Exact remote commit and CI are checked separately
after publication and recorded in the draft PR.
