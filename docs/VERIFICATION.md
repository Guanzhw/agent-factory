# Verification record

Verified locally on 2026-10-01 with Windows, Python 3.14.3, Node 26.5.1, Agno 3.1.0 and task-owned loopback PostgreSQL 17.11. This record keeps historical checkpoints; the latest verified stage is recorded at the end. Earlier foundation commit ba707a272c9d3fdfcbbe479f4278ee50bde3b703 remains historical evidence, not current acceptance.

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

Agno upstream revision is ab1d6007f09163c3adadbe06f998dc481b77a09a. ORX source is f336b121525d99364e2dee4fe90b2784894a54e6 (declares 0.2.13); installed 0.2.10 was not updated or treated as compatible. ORX contract tests execute controlled subprocess fixtures; no integrated literature/model task, paid model, autonomous scientific result, external provider execution, deployment or new external access was performed. A narrow actual public OpenAlex metadata lookup is recorded separately below.

Guarded schedule hard-process recovery and stale-lease takeover are now tested, with the native unconditional-release race explicitly retained as a limit. Native resource attachment has metadata evidence; Factory-to-Factory execution has actual two-app and loopback HTTP evidence. Production identity/model budget, captured actual ORX experiment outputs, real remote endpoints and hostile-code isolation remain open. See ACCEPTANCE.md and SECURITY.md.

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

## Governed materials, replay and autonomous cleanup checkpoint

The final complete staged suite passed **all 200 tests in 177.610 seconds** with
actual PostgreSQL enabled, official PG17.11 dump/restore binaries configured and
the exact ORX0.2.13 binary checks enabled. There were no skipped cases in this
invocation. Without those local opt-ins, ordinary CI explicitly skips the two
actual ORX binary checks and the backup/restore case; PostgreSQL cases run in the
separate CI service job. Ruff and Pyright passed with zero errors; frontend lint,
typecheck, thirteen HTTP client tests and production build passed. Official npm
registry audit found zero vulnerabilities.

New acceptance includes nineteen material governance cases, fifteen Factory
event replay cases, three active-compute authority-loss cases, three actual
twenty-user admission cases, one official PostgreSQL logical restore and eleven
main-wired lifecycle cleanup cases. Two added product tests relay receiver-owned
event pages and child cursors through actual separate native apps/databases.
The full run retains earlier hard-process native queue/schedule and real TCP
acknowledgement-loss checks.

Actual Edge material acceptance verified all six kinds, repeated clicks producing
one command, lost persisted acknowledgement retried with the exact original key,
author self-review refusal, independent current administrator publication,
immutable version history/archive/withdrawal and malformed policy fail-closed
recovery. Desktop/mobile screenshots were visually inspected; 390px documents
fit their viewport. Reviewer grants were only in the generated synthetic fixture.

Actual event UI read seven real server events with matching task IDs/sequences.
Controlled browser responses separately verified offline exact-cursor retry,
prefix-change409/from-start recovery, malformed/foreign-task rejection and
preservation of the last good page. Ten replay reads made no mutation. Normal
and recovery layouts at390px had no horizontal overflow. Controlled responses
are not substituted for native server replay tests.

The first observer integration regression exposed pre-ACK and completed-child
eligibility errors. They were fixed and covered by a real administrator-reviewed
healthy tree before/after native admission. Background cleanup preserves failure
reasons, keeps UNKNOWN/stale-running-ticket work held, and proves whole-tree stop
using public native APIs without owner/admin JWT impersonation. Timing assertions
now allow earlier legitimate autonomous cleanup while retaining positive native,
effect, group and quota evidence. Default running signals remain single-process.

Separately, one actual bounded pinned OpenResearchAdapter OpenAlex discovery
returned three public metadata records without credentials, a model call or
resource provisioning. This is narrow adapter retrieval proof, not an integrated
research/scientific/experiment workflow. See OPENRESEARCH.md for the result hash.

Staged publication scanning found no known credential/private-path/runtime-file
findings. Runtime state, screenshots/logs and temporary databases remain ignored.
Exact remote commit/CI verification is recorded in the draft PR after publication;
no merge, exposure, paid model, cloud provisioning or production grant is implied.

## Final remote cancellation publication checkpoint

The final complete backend suite passed **all 202 tests in 191.763 seconds**,
with actual PostgreSQL, official clean-stop dump/restore and exact ORX binary
opt-ins enabled; no cases were skipped. Complete Ruff and Pyright passed.
Frontend source was unchanged after its thirteen client tests, lint/typecheck,
production build and browser checks. The staged fix scan found no known
credential/private-path/runtime-file findings.

The first publication CI exposed a real remote cancellation classification race:
origin intent was visible before receiver request delivery and was treated as a
generic authority failure. An exact trusted owner/task/manifest cancellation
signal now preserves cancellation through receiver guards, lifecycle observation,
active compute and native hooks. Genuine revocation/expiry retains failure
provenance. Factory-only HTTP route boundaries return409 for cancellation during
later native rechecks; native worker guards retain the native stop signal.

Thirty-two focused actual native remote tests passed, including forced delivery
windows for paused descendants/active compute, wrong owner/task/manifest signals
rejected403 without touching either native run or capacity, and four late public
admission/continuation/delegation checks rejected409 without new effects.
Read-only downgraded owners retain exact facts while positive cleanup converges;
new execution remains denied. Eleven observer regressions also passed. Earlier
failed publication logs remain ignored local diagnostic evidence. Exact final
remote SHA and its CI are checked after publication and recorded in the draft PR.

## Deterministic metadata and cleanup phases

A subsequent Linux CI exposed a timing-dependent old delegation assertion: the observer could cancel a failed child between its failure check and a new delegation request. The metadata/ticket-disagreement test now pauses only its generated fixture observer for the before-cleanup assertions, then invokes that same wired observer and proves positive native/group stop. It retains exact failure denial, no native submit/new task/link, no effects/artifacts and no capacity release before stop. The two acceptance phases also exposed missing background cleanup for a rejected Factory admission with an exactly acknowledged native ticket. An explicit admission-rejection cleanup cause now preserves failure provenance and stops that owned tree; uncertainty and mismatched bindings retain capacity.

## Admission rejection publication checkpoint

After the metadata/cleanup fix, the complete backend suite passed **all 204
tests in 183.924 seconds** with actual PostgreSQL, official clean-stop
dump/restore and exact ORX binary opt-ins enabled, with no skips. Complete Ruff
and Pyright passed. Frontend code was unchanged from its thirteen client tests,
lint/typecheck, production build and actual browser acceptance. The reviewed
publication patch contained only project source, synthetic tests and documentation;
the staged scan found no known credentials, private paths or runtime files.

The deterministic rejection test retains the pre-cleanup denial and mismatched
binding negative, then invokes the wired observer to establish positive native,
effect and descendant stop. It also checks failure provenance, unchanged effects
and artifacts, and no new native submission/task/link. Exact remote commit and
both CI runs are verified after publication and recorded in the draft PR.

One earlier complete run failed the active remote experiment cancellation check.
Persisted diagnostics showed accepted admission and no prior failure: cancellation
arrived between the trusted callback's first task read and its later target
execution recheck. That later check must preserve the exact owner/task/manifest
cancellation signal as well. Deterministic tests force this second read window;
arbitrary denials and earlier genuine failures retain their failure provenance.
A separate public paused-HITL case injects a clearly labeled prior protected
failure at the second-check boundary and proves denial without continuation or
new effects/artifacts. Policy-withdrawal acceptance first waits for actual native
denial/cleanup evidence, then cancels and strictly retains the failed outcome.
Those negatives exposed a receipt-projection defect: stopped canceled native
work unconditionally replaced the Factory group failure with canceled. Receiver
receipts now preserve full-history parent/descendant failure facts after positive
stop; clean user cancellation remains canceled. Origin and frontend read the
same retained outcome. No authority or stop-proof requirement was relaxed.
Receiver read reconciliation no longer re-accepts an already-bound native run;
repeated reads preserve terminal/admission decisions and reject a different
observed native ID. The shared binding transition is also idempotent for the
original run. A first late acknowledgement after rejection retains rejection
and holds capacity until positive stop; execution-only resolution denies that
rejected root before continuation or protected effects. Actual native acceptance
covers both same-binding reads and this late-binding cleanup boundary.

After the Windows execution transport recovered, all staged/unstaged changes were
preserved in a private patch snapshot. The outstanding first-ACK status refresh
passed a deterministic actual native queue test: the generated fixture worker is
stopped until the committed ticket is found, so no input hook can bind it first.
The same first receipt returns accepted/queued with the exact native ID, holds
capacity and has no effects/artifacts; starting the real worker then pauses it,
and repeated dispatch still has exactly one native submission. Frontend lint,
typecheck, thirteen client tests and build were rerun successfully; npm audit
found zero vulnerabilities. The local services bind only to loopback.
