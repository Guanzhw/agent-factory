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


## Material-driven application assembly and actual native bindings

Verified on 2026-10-02 on the same Windows/Agno3.1.0/PostgreSQL17.11 host.
The final complete backend suite passed **all 266 tests in 287.580 seconds**,
with actual PostgreSQL, official clean-stop dump/restore and exact ORX0.2.13 binary
opt-ins enabled; **no tests were skipped**. Ruff and Pyright passed with zero
errors. Frontend lint/typecheck, **21 client tests** and production build passed;
official npm audit found **zero vulnerabilities**. The final API-focused subset
also passed all23 cases after production evidence/status metadata was corrected.
CI's portable jobs explicitly skip unavailable PostgreSQL/ORX/restore fixtures;
its dedicated PostgreSQL job runs the actual native cases. Exact commit and both
CI runs are verified after publication and linked in the draft PR.

New backend coverage includes18 application/composition cases,12 connection cases,
13 execution-binding cases,10 runtime-binding governance cases,8 ORX callable
contracts and1 actual PostgreSQL/native ORX success case. A new approved six-kind
application executes actual native checksum without a core application-ID branch.
Concurrent native responses select separate Models/knowledge/owners; streamed
native metadata records the selected Model. Exact pin drift, unavailable factories,
retained callable identity, current authority loss during provider response and
owner connection handles are tested without a paid/live provider request.

Production-shaped preflight identifies one specific unavailable model revision
while healthy materials remain healthy, creates no task and constructs no factory.
Connection tests cover immutable owner metadata, scope narrowing, atomic repeated
bind/revoke, expiry, revision/handle rotation, task/owner mismatch, SQL role loss,
tamper and restart. One-slot pool tests exercise shared transactional reads and
native standalone admission/budget accounting; they do not certify every
multi-phase delegation/observer operation with a one-slot pool.

Actual supported Edge browser acceptance uses generated loopback native stores.
Alpha-to-Beta model selection and a tighter environment are sealed into a revised
plan; the actual native snapshot records `controlled-beta` and checksum bytes.
Double click makes one admission POST. Persisted revision/accept/bind responses
are intentionally lost; exact-key retries produce one successor/plan/reference.
Reload follows the authentic owner-scoped `revisedBy` chain with exact parent,
application/material refs and fingerprint, making **zero mutations**. Explicit
rejection then makes one POST. A revoked connection rejects admission409 without
increasing native ticket count. Separate current administrator approval passes;
author self-review returns403. Malformed application/registration and foreign-owner
responses disable actions; verified refresh recovers. Desktop and390px captures
are retained as ignored evidence; document width is390px. Reviewer roles exist
only in the generated fixture databases, which were removed after browser work.

The registered ORX tool uses the exact approved contract and narrow research read
capability. Its actual native test goes through separate exact material/application
reviews, trusted Alice connection, composition, queue, DONE effect and a hash-checked
artifact. The transport is explicitly `controlled_transport_fixture` and records
`configuredBinarySha256`; it does not claim CLI execution or live retrieval.
Callable tests cover replay/UNKNOWN, revoke/cancel/timeout and operator/plan/selected
environment time/output limits. ORX hard CPU/memory/PID containment and ORX experiment
launch/status/cancel are not wired or accepted. Earlier actual exact-source binary
preflight and narrow public metadata lookup remain separate evidence.

The first full266-case run exposed one real lifecycle race: a pending child read
became bound during guard checks, so a stale None native ID was misclassified as
authority revocation. An authentic pre-submit reservation plus one actual paused
native ticket reproduces the failure before the fix. Pending observations now use
metadata checks; acknowledged native work still requires its exact context. The
same deterministic case retains strict wrong-native-ID403, current SQL owner denial
and transactional material withdrawal denial. Remote product/lifecycle22 cases
passed in54.806 seconds before the final complete run. No observer delay, skipped
guard or changed cleanup/UNKNOWN capacity rule was used.

The second full run exposed a timing-dependent old policy test expectation:
withdrawal cleanup can finish before the approval POST, correctly returning409
instead of accepted continuation200. The corrected assertion preserves both
legitimate orderings, checks zero continuation calls after HTTP denial, records
actual protected denial, and retains zero compute/new effects/artifacts. All18
policy cases passed before the final complete run; production guards are unchanged.

Public FR/AC/AT mapping is in ACCEPTANCE.md and operator/compatibility rules are in
MATERIAL_ASSEMBLY.md. Registered factories and owner connection lifecycle are now
implemented; real model/ORX scientific acceptance, provider credentials, production
identity/isolation, receiver-side connection mapping, sustained target throughput,
monitoring/retention and multi-replica scheduler recovery remain open. No paid API,
cloud provisioning, deployment exposure, production grant or merge was performed.

## Governed remote execution and receiver-local connection bindings

Verified on 2026-10-02 on Windows / Agno 3.1.0 / PostgreSQL 17.11. The complete
backend suite passed **319 tests in 447.161 seconds, no skips**, with disposable
PostgreSQL, official restore tools and exact-source ORX binary opt-ins. Ruff and
Pyright passed. Frontend lint/typecheck, **35 client tests** and production build
passed. Official npm audit reported **zero vulnerabilities**; the configured
mirror lacks an audit endpoint, so auditing used registry.npmjs.org without a
persistent configuration change. Exact remote commit/CI evidence is linked in
the draft PR after publication; portable CI skips explicitly unavailable fixtures.

The complete run initially exposed a Windows test teardown failure: the old
venv redirector PID could exit before the actual API worker released its log.
The existing five-case TCP fixture now launches real CPython with the pinned
venv import path and waits for its owned worker exit. Its focused five cases
passed in 10.983 seconds, then the complete 319 run passed. Runtime guards, assertions
and cleanup proof requirements were preserved.

New coverage comprises nine exact application snapshot-import cases, nine local
receiver-binding cases, fourteen actual/adversarial origin-HTTP authorization
cases, four compatibility-contract cases, eight bounded target transport cases
and nine actual two-process governed remote cases. Independent generated PG
databases share one loopback PostgreSQL server; they are not two physical hosts.
No in-process ASGI transport substitutes for the two-process acceptance boundary.

Process acceptance runs administrator-reviewed non-demo/non-synthetic plans
with explicitly controlled Models/connections. It tests legal, missing,
wrong-owner and rotated mappings; both current role withdrawals; origin process
outage and original receipt recovery; narrowed receiver-owned children and
scoped cancellation; receiver hard exit after native commit before HTTP ACK;
pre-review positive no-dispatch cancellation; and registered ORX discovery.
Each remote root has zero origin native tickets and one receiver root ticket;
separately delegated children own separate native tickets. Failure history,
UNKNOWN capacity, original manifests and SHA-checked artifact bytes are retained.
Current-origin HTTP is the actual authenticated Factory route, not a fixed-success
callback. Origin outage keeps receiver native facts readable and disables
execution/delegation actions; it does not manufacture stop or revocation proof.

Final artifact provenance acceptance reran all nine process cases against the
latest Store code: **9/9 passed in 89.459 seconds**. New remote artifacts identify
both source and effective model/environment adapter IDs/revisions, source/effective
execution-binding hashes and the immutable receiver proof hash. The effective
manifest digest is independently reconstructed from exact public proof entries.
Source manifests, artifact bytes and older stored metadata remain unchanged.
No handles, tokens or fixture control credentials appear in public provenance.

The registered remote ORX case creates an actual native DONE effect and
hash-checked discovery artifact labeled `controlled_transport_fixture`. It is
not integrated CLI experiment or live scientific acceptance. Exact-source binary
preflight remains separate from controlled discovery evidence. Production
identity issuance, TLS/host authorization, cross-host/replica isolation, sustained
target throughput and real provider/science acceptance remain pending. There is
no remote configuration in default startup, paid call, cloud allocation,
deployment exposure, production grant or merge.

Supported Edge browser acceptance used the actual loopback pair and latest
production frontend bundle. Separate source/receiver administrators reviewed the
exact plans. PREPARING showed a scoped proof, zero receiver tickets and no native
tool/replay/delegation controls. Wrong receiver-plan responses disabled actions;
offline reads recovered the original identity after explicit reconnect. Receiver
approval followed by a post-commit503 continuation ACK loss recovered the original
plan/target/request receipt, then native input. Explicit same-target replay kept
one receiver root ticket.

Custom direct/paused child modes came from the exact parent application, not
hardcoded research labels. A paused child answered through the UI and produced
a 171-byte native checksum artifact with authenticated byte/hash verification.
Root cancellation proved the owned receiver group stopped; native child COMPLETED
and its artifact remained historical evidence despite Factory cascade reclaim
intent. A second PREPARING task was canceled with one POST under double click,
positive CANCELLED_NO_DISPATCH/allStopped and null receiver task/run IDs, unchanged
receiver ticket count, and no native group/event calls. Desktop and 390px captures
are retained as ignored evidence; final document/scroll width was 390px.

The browser harness once created an unrelated controlled local task after reload
without restoring its remote-target selection. That task was explicitly canceled;
the remote replay claim comes from the later explicit same-target check, not that
mistaken submission. All fixture tasks were terminal before owned-service cleanup.
Only generated native fixture users/roles were used; credential-bearing browser
helpers were removed. There were no production grants or provider requests.

The two-process HTTP fixture now uses explicit finite connect/write/pool deadlines
of 3/5/3 seconds, a 75-second read deadline for instance submission and 30 seconds
for other reads. This allows the existing sequential 20-second prepare, dispatch
and detail phases to finish under loaded CI. The first PR run timed out in the
outer fixture before assertions; the same-source push workflow passed. No runtime
timeout, retry, state wait or admission/effect assertion changed. After correction,
all nine actual-process acceptance cases passed again in 85.518 seconds.

## WIP cloud handoff checkpoint — 2026-10-02

Local development scope is frozen for cloud handoff. The complete milestone is
**not accepted**. [CLOUD_HANDOFF.md](CLOUD_HANDOFF.md) lists exact continuation
commands, pinned versions, ORX build provenance and known blockers.

- Final frontend check: lint/typecheck/build and 51 tests pass; official npm
  production audit reports 0 vulnerabilities. Ruff passes and Pyright reports
  0 errors before the final preservation-only documentation update.
- Actual pinned Windows ORX adapter: 10 tests pass in 104.785 s. Actual Factory
  ORX suite: 8/9 pass in 159.632 s; connection-revocation cleanup observation
  failed. Final one-case recheck after fixing the persisted capabilities
  omission still fails in 54.789 s. It is unresolved, not waived.
- Real PostgreSQL ledger: 19 tests pass in 10.184 s. Actual two-service remote
  usage: 8 pass in 105.353 s. Final legacy remote handoff: 23 pass in 73.865 s;
  legacy remote child: 1 pass in 39.442 s. Explicit zero-price origin/receiver
  fixtures: 14 and 9 pass respectively.
- The first full local regression ran 364 tests in 677.116 s, with 2 failures,
  1 error and 19 explicit opt-in skips. It imported earlier test fixtures before
  their corrections: the stale missing-grant/dispatch-body cases were fixed and
  pass in the subsequent 23-case suite; the unpriced source-model fixture was
  fixed and passes in the subsequent 14-case suite. The **full final-source suite
  was not rerun**. These focused results are not a full-suite passing claim.
- Startup profile is unrun. The preserved Playwright 1.58.0/Edge harness passed
  syntax and static checks only; actual browser approvals/cancel/recovery/download
  acceptance is unrun. Factory/native durable queue hard-interruption recovery
  remains unimplemented acceptance; adapter-only worker recovery is distinct.
- Read-only source review found remaining terminal stop-proof/capacity release
  and imported remote ORX effective-pin cleanup gaps. See the handoff blockers.

No paid models/compute, credentials, production grants, merge or deployment were
used. Source scan/remote commit/CI status and owned-service stop evidence are
reported with the exact published checkpoint SHA. Raw local logs, databases,
private generated auth fixtures, upstream ZIP/binary and machine caches remain
ignored and are not transferred. OpenSession remains local.

## Cloud handoff: portable setup repair

Cloud ownership starts from `cbe590695f6b03aca6de9c6993a811f74990d6c9`,
not the earlier baseline. Debian 13.6, Python 3.12.14 and Node 24.19.0 were
observed in a container limited to 4 CPU / 16 GiB (not the production target).
The Windows Job Object DLL attributes are explicitly typed for portable static
checking; Windows subprocess constants are looked up only inside the existing
Windows-only execution profile. Linux still cannot execute that profile.

The lock now uses official PyPI and files.pythonhosted.org URLs with every
version and artifact hash preserved. `uv sync --frozen --refresh` succeeded
against those URLs. Linux Pyright reports zero errors after reproducing the
13 handoff errors. The handoff's backup-tool variable is corrected to the
actual `FACTORY_PG_BIN`; no startup behavior is changed.

Before taking the WIP, the earlier `6793a96` passed nine actual loopback
TCP/two-process cases plus the official PostgreSQL 17.11 dump/restore case:
10 tests in 140.897 seconds, no skips. That result belongs to the old baseline
and must not be attributed to this WIP or Windows ORX acceptance.

## Cloud ORX cleanup contract repair

Portable PostgreSQL regressions reproduce a cleanup defect: the public
`Store.effects()` projection omits the launch fingerprint, so using that
projection to authorize cleanup rejects even an exact originally admitted
launch. Cleanup now reads the task/run-bound private fingerprint directly.
A real native ticket plus controlled experiment metadata proves revoked
connections permit only exact historical cleanup, and a changed launch hash
still fails closed. This is not Windows process-stop acceptance.

Every terminal ORX effect now requires `stopEvidence.allStopped=true`, including
done/failed outcomes. Admission, group/delegation, HTTP status, remote stop
statements and the lifecycle observer also keep historical terminal effects
without that proof held. Startup re-holds pre-fix task rows without rewriting
immutable effect fingerprints or inventing a native outcome. Positive reclaim
observations refresh the effect's stop proof, preserving original result facts.

Receiver cleanup selects its original effective specification from the exact
immutable root/child proof, rather than resolving a source-side connection pin
or requiring current run permission. Artifact provenance reads the same
historical manifest; it does not acquire an execution handle. Current execution
mapping and connection checks remain separate and still deny revoked access.

Three focused PostgreSQL/native metadata regressions passed (5.205 seconds).
An additional post-revocation artifact-persistence assertion passed separately
(1.662 seconds). The complete cloud suite and exact-commit CI are run separately;
these focused passes alone are not complete ORX or production acceptance.

The Windows-only actual ORX adapter/Factory suites, real orphan/supervisor stop,
Factory-queue hard-interruption recovery, startup/resume and actual browser
workflow remain unverified in this Linux environment. In particular, correcting
the reproducible fingerprint defect does not establish that the previously
failing Windows revocation case now passes. No new binary hash is approved and
the platform guard remains unchanged. No paid provider, production access,
external service or deployment is enabled.

## Cloud full regression and approval-race assertion

The cloud PostgreSQL run covering the cleanup changes completed 368 tests in
792.675 seconds: 350 passed and 18 explicit ORX skips, with no failures/errors.
The skips are ten actual Windows adapter tests, two exact-binary preflight tests
and six actual Windows Factory tests. All 19 ledger and eight remote-usage cases
ran. An additional final assertion for post-revocation historical artifact
provenance was checked separately after the full run had loaded its test module.

CI for `a4665c2885767b24db12175b687fc4c3773925c0` passed both frontend and
both Python platform jobs, but its PostgreSQL job exposed a pre-existing live
observer race in the plan-policy test: HTTP 409 can come from the API before the
bridge call, or from the real native route after one bridge call. The old test
incorrectly inferred zero bridge calls from every 409. No compute/effect or
artifact evidence indicated resumed execution.

The corrected test retains the no-compute/no-new-effect/no-new-artifact and
protected-denial assertions. A second deterministic case runs the real observer
after the API's waiting-approval read and before native continuation, requiring
one attempted bridge call, native HTTP 409 and unchanged execution evidence.
Both cases passed in 6.754 seconds. This follow-up changes tests/documentation
only; production authorization and continuation code are unchanged. Exact-head
CI remains the separate final validation source.
