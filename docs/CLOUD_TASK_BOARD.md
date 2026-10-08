# Native Agno reuse correction — active 2026-10-08

PR62 remains Draft and unmerged. Previous head `79133217bb019b067f7347ef4a2bece2a53283b6`
and its CI describe the superseded custom workflow implementation, not acceptance
of this correction. Main baseline `067354e0b95ceba7aa620216fe7a18715b179ac0` and
its independent completed-success CI37714925242 remain accepted.

Agno 3.1.0 Workflow/Step/Router/Condition/Parallel, WorkflowSession, requirements,
continue and durable queue own all workflow progress. The duplicate Factory DAG,
resume and progress service have been removed after native proof. Factory retains
immutable governance/input/component pins, shared budgets, external-operation
custody and thin command receipts. Actual ConvertD remains the user's local work.

| Owner | Exclusive scope | Current evidence / dependency |
|---|---|---|
| root | API/config/schema/native lifecycle and final integration | Serial PG; exact new-head CI and independent review required before authorized merge |
| factory_flow | remove old graph; operation contracts; real budget regression migration | 27 lightweight pass; 3 PG skipped locally (not PG acceptance) |
| go_policy | policy refs/model ledger; candidate read-only state wiring | 25 candidate checks pass; Ruff/Pyright clean |
| go_adapter | native bridge/control/registration unit tests | Thin command6 and registry17 pass; included in boundary50 pass |
| candidate_support_audit | input/UI and native handoff docs | Schema2 mock browser pass; docs updating |
| at10 | real native queue/restart and startup accounting fixtures | FactoryPG3 pass47.568s; startupPG3 pass40.538s, zero skips |
| candidate_final_review | independent reuse/correctness review | Function/active executor/schema integrity and identifier contract findings fixed; eligible for exact CI |
| ci_final_review | exact CI read-only observation | Historical b6 push failed old withdrawn-custody assertion; preserve new native regression |

Evidence retained: pure native proof3 passed4.266s. First Factory integration
attempt had2 pass/1 failure89.932s: the native external-wait helper was omitted
from approved tools. The fixture now approves it explicitly; replacement3 passed.
A subsequent command accidentally omitted the PG variable and skipped3; that is
not acceptance and was followed by the explicit database run above. New registration
integrity changes passed the nine-case mandatory gate in113.417s, zero skips.
The gate now requires10 cases, adding original owner/withdrawal/UNKNOWN custody.
First ten-case attempt had9 pass/1 fixture error98.392s: the denial correctly
returned409 but the test expected `detail` instead of Factory's `code/message`.
Corrected exact-code assertion passed the isolated new case13.566s. Final ten-case
gate passed177.103s, zero skips. Candidate gate9 passed101.137s, zero skips. Boundary54 passed0.635s, frontend217 passed with lint/typecheck/build,
Ruff/Pyright passed. npm audit found0 vulnerabilities; pip-audit found no known
vulnerabilities (local project is not on PyPI). Read-only cache errors were resolved
using workspace cache directories. The first corrected head `9a958a0` CI failed one stale mock assertion requiring
exactly one parent-plan read; native component validation now legitimately reads
child and parent plans. The fixture now returns each exact plan and checks owner,
ancestor validation and component mismatch rather than an implementation call count.
A further budget regression binds external wait call IDs to original native step IDs:
different child Agents cannot evade a second debit by reusing a local provider call ID.
Real SQL4 budget checks and native pause/restart/continue1 passed26.752s. Independent
review has no remaining blocker. AutoResearch11 is running serially; full regression
and replacement exact final CI remain pending. No live model/backend/data/deployment claims.

---

## Historical pre-correction phase (superseded below)

# Governed workflow agent extension — 2026-10-08

Base: PR60 exact `cd9522f9da1daec5c9ec69d5d43717b910da1740` (ten exact CI jobs
accepted twice). Branch: `feat/governed-workflow-agents-20261008`.
This phase implements generic workflow-agent boundaries, not real ConvertD
integration. Authorized GitHub lookup found no verified ConvertD repository/spec;
only supplied six-phase names, FAILURE_JSON/B routing, resume-from and parallel
join requirements inform a harmless representative fixture. No backend,
notification, new credential, externally exposed listener, paid call or deployment.
The user subsequently authorized normal merge into main after engineering checks,
and requested the already accepted baseline be synchronized first via PR61.
PR61 merged the accepted baseline into main at
`067354e0b95ceba7aa620216fe7a18715b179ac0` after explicit user confirmation
of the draft-to-ready step. Main CI37714925242 attempt1 passed all five jobs:
candidate9/9, AutoResearch11/11 (zero skips), full PG2281 tests (63 skips).
This is an independently completed baseline milestone; no protection bypass.
Current workflow edits remain separate in draft PR62. All 51 covered historical
stage PRs are resolved with exact ancestry evidence; independent #8/#41/#51 remain open.

| Owner | Exclusive files / interfaces | Acceptance / dependencies |
|---|---|---|
| root | Settings/main/store/native lifecycle/control/API glue, docs, final integration | Original task/approval/budget/cleanup preserved; exact CI final responsibility |
| go_policy | tool_policy_registry, plan_policy, material_governance + tests | New operator policies, exact adapters, withdrawal/version drift; legacy identity unchanged |
| go_adapter | workflow_contracts + tests | Bounded graph/runtime observation, original handles, read-only lookup |
| factory_flow | workflow_service/profile + tests | Durable intent/state/commands, waits, fanout/join, B routing, cancellation, no unknown replay |
| candidate_support_audit | input_schema, applications/composition + tests | Bounded schema and immutable inputs; old apps unchanged |
| ci_final_review | workflow/input UI, client/types/templates + tests | Server-authoritative stages, stale decision rejection, stable recovery commands |
| at10 | independent source/spec and correctness review | Synthetic labeling, failure-edge reachability, restart/unknown/concurrency review |

Required new acceptance: actual native agent/tool invocation with synthetic model
outputs explicitly labeled; persistent pause and same-run continuation; fresh
process restart over original DB; duplicate submission/event; lost ACK and
no redispatch; FAILURE_JSON-to-B; bounded parallel tasks and join; human decision
version/owner checks; cancellation retaining unknown custody; input/schema and
policy drift denial. Existing AutoResearch tests remain. Heavy local database
checks run serially. Implementation is integrated but final acceptance is pending.

Current evidence: frontend218 tests/build/typecheck/lint and actual browser with
mock API transport passed. Existing required AutoResearch native gate passed11/11
with zero skips in677.994s. npm/Python dependency audits report no known issues.
The first workflow native gate passed3/3, but later stricter recovery checks
exposed a race: ordinary adapter ConnectionError records protected tool failure
and cancels original custody before durable pause. Earlier reconcile HTTP500 had
no captured exact stack and is not claimed resolved merely by waiting.
A narrow typed unknown-acknowledgement contract now allows durable UNKNOWN
observation; generic failures/cancellation still propagate. Final four-case gate
adds a distinct service-exit-before-pause fault injection.
CI at178e998 failed on stale test mocks and readonly reconstruction missing the
workflow guard. Fixes preserve production validation, use a pure no-DDL guard,
and close SQLite handles before temporary fixture deletion. External native
wait completion now charges the original tool-call ID; actual ledger acceptance
is being verified independently. Service25 and lifecycle10 focused tests pass.
Candidate regression passed9/9 with zero skips in133.456s. Complete portable
suite passed2342 tests (435 expected environment skips) in208.663s, followed by
updated control15 and actual SQLite ledger3 checks with ResourceWarning treated
as an error. Independent core review found no blocker. The pre-pause exit gate
captured a GET snapshot500 from RunCancelledException; snapshot now retains
owner-readable custody with no execution actions, covered by regression tests.
Final four-case native/PostgreSQL rerun passed4/4 with zero skips in120.497s.
Ruff and Linux/Windows Pyright passed; changed-file credential-pattern scan found
zero matches. CI at bd7bb21 passed all PR portable/frontend jobs, but push
Windows failed one existing synthetic ORX concurrent-status test (COMMAND_FAILED;
original subprocess stderr was not captured). The same-head pass does not erase
that failure. The fixture now locks only shared JSON state I/O across processes;
a deterministic partial-publication regression proves the old reader's JSON
failure, and published corrupt state still fails closed without another launch.
No production retry/deadline is relaxed. Final exact CI and workflow merge remain
pending; PR62 records the immutable commit and terminal observations.

CI at ea23c6 passed all eight portable/frontend jobs but push native cancellation
revealed a real custody omission: API/delegation reads could mark the task
terminal while its workflow still held original operations, excluding it from
later lifecycle cleanup. Store terminal/admission, descendant accounting and
remote stop proofs now include workflow custody; user cascade cancellation
attempts cleanup of original workflow handles. Known paused waits remain
continuable while native-terminal held work reports UNKNOWN. Startup repairs
matching original accounting only, and first custody publication locks the task
row against terminal release. Metadata reads/transactions reuse Store connections.
Deterministic native cancellation now stops the observer and injects UNKNOWN
cancel ACK: task/disk/root capacity cannot release before positive original stop.
Four native scenarios passed4/4 zero skips in111.918s; three dedicated startup/
pool checks passed3/3 zero skips in58.476s, run serially. The mandatory gate now
includes all seven native/startup cases; discovery confirms seven. Updated
portable suite passed2358 tests (435 skips), followed by focused checks for the
latest transaction/paused-state changes. Independent source review found no
concrete lock inversion. Final exact CI and workflow merge remain pending.

Local handoff scope is explicit: the user owns real ConvertD development locally.
The existing workflow guide now includes a minimal definition/Settings assembly,
material and application publication, runtime/interaction schemas, recovery/cancel
contracts and runnable validation entry points. This follow-up changes docs only;
its successor commit must receive its own exact CI acceptance before merge.

See [workflow contracts and evidence limits](GOVERNED_WORKFLOW_AGENTS.md).

---

# Cloud integration task board

## Active remote scientific bootstrap implementation

Branch `feat/autoresearch-remote-scientific-bootstrap-20261007` builds on accepted
PR59 exact `e842b0ff37114efeddcf79e356fcc7c73706a76c`. Cloud retains ORX/Go
scientific decisions and credentials; one pinned receiver owns three bounded
scientific phases. Original baseline custody lives in a separate database and
workspace. The sealed real baseline is neither rerun nor rewritten. No new live
model request, listener, trust setup, credential persistence or deployment occurs.

| Owner | Exclusive scope | State / dependency |
|---|---|---|
| root | Core policy, placement, handoff, final acceptance and exact CI | Integrated; native acceptance passed; final exact-head CI pending |
| go_adapter | Sealed runtime pins, baseline context, concrete operator bindings | Implemented; 19 concrete bootstrap tests passed; external operator inputs still required |
| at10 | Fresh baseline reader, preparation separation, independent policy review | Implemented; 40 assembly/children checks plus independent custody and handoff regressions passed |
| candidate_support_audit | Evidence, receiver phases, bounded durable drive lifecycle | Implemented; no replay after UNKNOWN; fresh stop proof separated from retained artifact claims |
| go_policy | Origin journal, parent authority, shared debit, baseline proxy | Implemented; three actual PostgreSQL debit/receipt race cases passed |
| factory_flow | Operator CLI, remote coordinator, three-database native fixture | Implemented; three-database native fixture passed (655.732s) |
| independent review | Authorization, cleanup, catalogue identity, exact CI | Focused review active; final exact-head review pending |

The controlled fixture uses three isolated databases/apps: original preparation,
new receiver and cloud origin. It exercises real native queues, original process
receipts, checkpoint/evaluation services and ASGI handoff transport. GPU observations
and scientific payloads are synthetic. It injects one lost drive acknowledgment,
checks three metadata-only source children and bounded shared debits, reconstructs
the receiver service over original custody, and checks completed-task cleanup.
This does not prove cross-host transport, process restart or active-training cancel.

Integration fixes preserve immutable publication snapshot identity, native queue
identity (`id`), original lease custody during typed local lock contention, and
atomic first-native pin/receipt persistence. Network reads run outside journal
row locks. Terminal training checkpoint reads use a separate authenticated,
read-only custody proof; they do not reopen source execution authority. Retained
artifact claims cannot establish stop: fresh original native, lease and GPU proof
remain required. All scientific phase journals must close before successful
completion can release capacity.

Current local evidence: legacy remote handoff 24/24 actual PostgreSQL tests
(243.313s), remote bindings 10/10 (31.736s), local scientific native fixture
(287.143s), process runtime 9/9 (67.053s), and debit concurrency 3/3 (0.919s).
Frontend 203 tests/build and dependency audits passed. These earlier regressions
are supporting evidence, not substitutes for the current exact-head gate.
The final three-database native fixture passed in 655.732s with zero skips,
including all three original receipts, one lost drive acknowledgment, result read
before decision, receiver service reconstruction and completed-task cleanup.
Independent focused review passed 98 tests; Linux and Windows Pyright reported
zero errors; Ruff and diff whitespace checks passed. The required PostgreSQL
AutoResearch gate expects eleven tests with zero skips. Final exact CI is pending.

Initial exact head `be42e96` was rejected by CI: default unittest discovery could
not import the new baseline-context script, and the Windows assembly fixture
used a POSIX-only absolute path. Both are test-only corrections: explicit script
module setup and host-native synthetic absolute path. The same import failure
was reproduced locally (2273 tests, one error, 431 expected skips). Old CI runs
were canceled after diagnosis; replacement exact-head CI is required.

Replacement head `ba56543` passed all eight frontend/Python jobs, but both
required PostgreSQL gates exposed the same concurrent observation race: an older
GPU HELD snapshot returned after another observer persisted RECLAIMED/RELEASED.
The read now validates the response against its original request custody, then
rechecks current custody and preserves an already reclaimed original lease.
Other snapshots still undergo current-custody validation. GPU validators and
release-proof requirements are unchanged. Six deterministic tests using real process/GPU validators passed, including
corruption and identity rejection. The local full required gate is running;
replacement exact-head CI remains required.

Production identity, existing authorized bidirectional trust/connectivity, a real
GPU candidate, live literature retrieval and target-host capacity acceptance remain
external requirements. New controlled evidence must never relabel them as passed.

## Historical acceptance and earlier integration notes

Head `6ecea10` passed both required PostgreSQL gates but was rejected by Windows
Python: the real-time 200ms GET-retry fixture sometimes observed only one read.
The retry deadline test now deterministically expires the original real asyncio
timeout, checks exactly two reads and one mutation per route, and preserves the
original deadline. Its 21-case runtime suite passes; production timeouts are unchanged. Final replacement exact CI is required.

Exact head `22d710720eb5b1e5ebafa606979fd6780ab1450b` was rejected by both
PostgreSQL CI runs: the new fixture created input files using ambient umask, so
GitHub produced 0644 while staging correctly requires 0600. Local umask was 0077.
Explicit private fixture input creation and an umask regression now pass; the
required seven-case suite passed under umask 022 in 306.895 seconds, zero skips.
Production file-mode guards remain unchanged; replacement exact CI is pending.

## Current compact-candidate and scientific custody integration

Root continues beyond earlier draft checkpoints. Actual Go now chose and submitted
a compact public parameter candidate (12,361 tokens, three SETTLED calls, original
task terminal, effects DONE, original stop/reclaim). No experiment was authorized.
Scientific presets keep full source host-side and accept only the prior eleven
literal parameters, using the same full candidate validator.

The stronger native integration fixture identified two real wiring gaps now fixed:
preparation must verify retained baseline bytes rather than re-export a new
producer-bound file, and the evaluator service must be constructed after its
actual target is registered. The original producer's current policy/adapter
compatibility is retained; the research parent's preparation permission is read-only.

| Owner | Scope | Acceptance / dependency |
|---|---|---|
| root | Shared service, tool contract, lifecycle integration, final CI | Original six PG cases passed after read-only preparation change (102.658s); snapshot CAS/stop-only restore/revoked cleanup integrated; three-stage v14 passed (339.595s), including completed-custody registry reconstruction; required seven-case suite passed (324.218s, zero skips); final exact CI pending |
| at10 | Compact candidate builder; original preparation assembler/child; late evaluator binding | Compact inputs and per-parent/phase namespaces implemented; thirteen namespace/recovery light tests and Linux/Windows static checks passed; files frozen |
| factory_flow | Actual PG/native three-stage fixture | Source/environment/device seams explicit; v13 completed all three phases and reclaimed allocations, but final verification exceeded the fixture parent budget; v14 passed with an explicit synthetic 900/600-second envelope and completed-custody registry reconstruction; original process limits unchanged |
| candidate_final_review | Independent original custody, repeated-goal and recovery review | Original custody, revoked cleanup, directory replacement and transaction/retention separation reviewed; fixture recovery assertions reviewed as same-process completed-custody reconstruction; v14 terminal proof passed; not process-restart or live scientific acceptance |
| ci_final_review | Exact CI | Prior 8b head had eight successful non-PG jobs; PG runs stopped as superseded, never accepted |


Final post-fix actual Go diagnostic passed: public context plus final reply, three
SETTLED requests (8,877 tokens), both context/session effects DONE, zero held
provider tokens and exact original container stop/reclaim. Rejected decision
reserved no effect. Earlier UNKNOWNs remain. See `AUTORESEARCH_SESSION.md`.

## Active continuation after PR59 checkpoint

Historical PR59 head `ca9efb2ffaab1d2b716a844917e37c1eab5dd016` was **not accepted**:
Windows CI found three Linux-fixture portability errors. That head's push PostgreSQL job passed 2010 tests (63 platform skips), but the head remains rejected. Owned fixture fixes are
included in code checkpoint `a9eb50ab657d9e8e2253fdff1e101e8fa98af1d5`; final exact-head CI receipts belong to draft PR59. The first application remains
in implementation, and this draft is not a stopping condition.

| Owner | Exclusive current scope | Dependency / acceptance |
|---|---|---|
| root | Core API/config/lifecycle integration, original control commands, final checks | Implemented; six required PG cases passed; original UNKNOWN retained; final exact CI pending |
| at10 | New scientific child profiles and opt-in approved application modes | Implemented and light-tested; actual target baseline/config/receipts still missing |
| factory_flow | New durable scientific child orchestration service/tests | Implemented and light-tested; original candidate/call/plan pins and custody; real three-stage target acceptance pending |
| reviewer | New parent native session control module/tests | Implemented; native single-worker acceptance passed; 13 final controller regressions passed |
| candidate_support_audit | Two Linux runtime/bridge test files | Windows skips only Linux-only behavior; portable checks remain; 12 Linux tests pass |
| go_adapter | Go broker/session transport and diagnostics | Classified third diagnostic GET timeout; bounded GET-only retry implemented; historical UNKNOWN retained |

The first actual Go diagnostic settled one response and held the second UNKNOWN;
no real-provider context tool completed. The successful earlier harness/MCP test
used a **synthetic provider**. Two further independent public read-only diagnostics retained all original
UNKNOWN reservations. The third identified a 30-second ORX sessions GET timeout;
cleanup then interrupted broker request two. GET-only original-deadline retry and
explicit OpenCode title-disable fixes are now implemented. Actual native
single-worker pause/child/continuation passed (1 case, 33.984 seconds). The probe request ceiling is not a subscription limit. The fixed actual Go run
then completed a real context tool and final reply with all three requests
SETTLED. A denied out-of-stage decision left an UNKNOWN tool effect and an
incorrect completed projection. candidate_final_review fixed precondition
reservation and projection; reviewer added continuation guards and stop-only
cancellation before best-effort diagnostics. Original effects remain unchanged.
Scientific stages were not executed. All original UNKNOWN records remain.
The required PostgreSQL suite passed all six cases in 70.192 seconds, with no skips.
Local full Python discovery passed 2,062 cases (426 environment skips); final
AutoResearch focused discovery passed 106 cases (six PG-environment skips). Final
service/controller regressions passed 22/13 cases; the six required native PG
cases were repeated after those fixes and passed in 90.687 seconds with no skips; frontend 203 tests, lint,
typecheck, build, Ruff/Pyright and dependency audit (zero findings) passed.
The a9 code checkpoint then exposed one Windows assembly-fixture error: a pure
candidate derivation test invoked POSIX-only runtime-file observation. A fixed
synthetic runtime FilePin preserves the real derivation/architecture/manifest
assertions on Windows; production observation is unchanged. Root owns final
evidence and fresh exact CI integration.

## Initial PR59 checkpoint — superseded by active continuation above

Continue from PR58 exact `d8449295535111947006b62030263efffd161906` on
`feat/autoresearch-goal-session-20261007`. This phase replaces the claim that
operator-selected candidate execution is an autonomous research application.
Agno owns Factory tasks; the pinned ORX/OpenCode session owns research decisions.
No parallel Factory research model is introduced.

| Owner / exclusive scope | Dependency | Acceptance / blocker |
|---|---|---|
| root | Admission, shared configuration/lifecycle/API, App integration, docs, final checks and draft PR | Goal-only/default UI wired; original identities and UNKNOWN stop custody retained; frontend203 tests/build, Ruff/Pyright and audit pass; exact CI pending |
| go_adapter | Real ORX HTTP transport and session/MCP/ledger runtime | Actual upstream HTTP zero-model checks and real harness/MCP context wire with synthetic provider responses pass; one real Go diagnostic stopped after one settled and one UNKNOWN attempt; no real context/decision; no retry |
| candidate_support_audit | Isolated ORX/OpenCode container launcher and socket bridge | Actual network-none config/health/wrapper and context tool wire pass; positive original stop+container reclaim; 12 unit tests; no credentials |
| at10 | Governed model/tool profile and explicit scientific/operator preset bootstrap | 19 focused profile/preset/bootstrap tests pass; no automatic publication |
| factory_flow | New AutoResearch UI/state tests and separate PG acceptance tests | 7 UI tests pass; five actual PG/native cases pass, zero skips (47.283s); tool governance mismatch fixed |
| reviewer | Broker fixes and service lifecycle regressions | 24 broker + 12 service tests pass; no live calls |
| candidate_final_review | Independent read-only integration review | First review blockers addressed or retained as explicit unavailable prerequisites; final review pending |

**Remaining implementation and target evidence:** the existing candidate CLI
creates standalone preparation/training/evaluation tasks. It is deliberately not
invoked from the new research tool. A durable subordinate executor with shared
parent budgets, current authority, native approval/cancel and original custody
verification is still required; the scientific preset stays unavailable without
it. Actual target baseline/config/receipt bindings are also absent from this
cloud checkout. Callback interfaces are not evidence of completed integration.

The existing scientific runtime is unchanged. No GPU dispatch, paid fallback,
merge, deployment or personal 24-hour agent is authorized by this phase. Heavy
checks and real container probes run serially. Scratch paths are evidence only,
not reproducibility prerequisites. See [session handoff](AUTORESEARCH_SESSION.md).

## Ephemeral candidate database authentication — 2026-10-07

Local PR57 acceptance stopped before execution: its retained baseline config
names an expired or different database route. The successful baseline's temporary
auth file was removed. No local candidate stage or budget was consumed.

| Owner / exclusive scope | Dependency | Acceptance / blocker |
|---|---|---|
| root | CLI route, read-only original-lineage anchor, baseline/recovery integration, docs and draft PR | Explicit private-file override shared in memory; original config/journal identity unchanged; 82 focused tests, Ruff/Pyright, frontend196 tests/build and dependency audit pass; exact-head CI pending |
| toolchain_path_fix | Focused authentication tests | Twelve tests pass: one read, strict args, redaction, path rotation, unchanged identity and retained-input drift refusal |
| candidate_support_audit | Standalone real PostgreSQL integration | Native synthetic baseline records; real CLI/auth/DB reopen, removed auth file and replacement path, wrong DB/binding rejection; standalone case passed; combined nine required cases passed in 218.066s with zero skips |
| candidate_final_review | Independent read-only review | Final diff reviewed; no remaining blocker, 30 independent light tests passed |

The override is a connection route, not permission to create credentials or new
access. It is never persisted or included in identity hashes. Both original
training and evaluator chains must match before workspace/state writes. An exact
record clone has the same logical lineage; physical-server attestation is not
claimed. No installed runtime, old config or old auth pathname is modified.

## Bounded candidate/recovery implementation — 2026-10-07

External operator scripts continue PR56 without changing the installed scientific
runtime or replaying the accepted baseline. Synthetic acceptance and exact-head CI
completed on PR57; local target acceptance found the routing gap above. No GPU
run, candidate improvement, or target recovery acceptance is claimed.

| Owner / exclusive scope | Dependency | Acceptance / blocker |
|---|---|---|
| root | Shared state composition, integration, handoff, strict CI and draft PR | Integrated commands and handoff; draft PR57; exact c1a592aa95b9d592249e2aae292ebac1f47ffd39 CI passed twice |
| candidate_support_audit | Candidate assembly, original-provider reopening | Original preparation/training/evaluation provider fingerprints verified; no installed runtime changes |
| toolchain_path_fix | Single-candidate CLI and isolated CLI tests | One consumed attempt/stage, exact comparison identity, real baseline custody gate and advisory assessment |
| target_recovery_audit | Durable invocation journal and stop-only recovery | 19 focused tests pass including repeated cancellation; shared deadline persists across reopen, no replay |
| toolchain_path_review | Retained baseline original-custody validation | Original provider/native policy/checkpoint/output rechecked; substituted JSON score rejected |
| pr52_ci_monitor | Required native/PostgreSQL acceptance and independent journal/CLI review | Eight required cases executed serially with real local PostgreSQL; scientific fixture boundaries explicit; CI rejects every skip |

Heavy database tests remain serial. Numeric resource limits come from the retained
operator configuration; no example limits authorize a new target run.

## Bounded candidate/recovery preparation — 2026-10-07

Based on the completed baseline, [the next-step handoff](RESEARCH_CANDIDATE_RECOVERY_PLAN.md)
audits existing candidate/recovery APIs and supplies executable offline source
preparation plus strict-no-skip target smoke commands. No GPU work was started.

| Owner / scope | Dependency | Acceptance / blocker |
|---|---|---|
| root | Source audit integration, precise candidate, envelope/evidence and docs | Actual pinned MATRIX_LR0.04→0.036 derivation passes;30 targeted tests pass; package/runtime unchanged |
| candidate_support_audit | Read-only candidate/assembly/manifest audit | Driver/profile support exists; canonical CLI/bootstrap are baseline-only, so candidate operator wiring is a real gap |
| target_recovery_audit | Read-only original-identity recovery audit | Original observe/stop/reopen supported; no training resume or fresh-process controller restart CLI; no reproduced defect |
| parent / local owner | Review candidate and interruption definition; retain actual approved limits/receipts | No new department identity/provider needed; original approved numeric limits are private/local, not supplied in public summary; GPU lanes not launch-ready |

No runtime fix was warranted by this audit. Next wiring can be completed using
existing installed APIs without silently reinstalling the sealed runtime or
invalidating comparison identity. A future GPU interruption lane is separate from
the successful scientific comparison, bounded to one fresh attempt, not a campaign.
Personal-agent/24-hour direction remains deferred.

## First real local baseline COMPLETE — 2026-10-07 09:48 UTC

The local owner verified PR54 runner + sealed PR50 runtime: RTX 5070/SDPA/
microbatch1, counted training302.587995s after11warmup, full fixed evaluation
val_bpb1.6711944975804394. Both stages COMPLETED/exit0, audits PASS, all original
lease/allocation/GPU/native claims RELEASED; no residual process/claim artifacts.
See [first real local baseline acceptance](RESEARCH_BASELINE_ACCEPTANCE.md) for exact identities, digest provenance and remaining priorities.

| Owner / scope | Dependency | Acceptance / boundary |
|---|---|---|
| original local execution owner | Fixed source/data/tokenizer/evaluator and real target | Single successful attempt, zero retries; checkpoint and independent evaluation verified; unknown/missing ACKs preserved |
| root | Sanitized acceptance/handoff reconciliation, documentation draft PR | Documentation only; no cloud GPU, feature, merge, deployment or optimization campaign |
| independent reviewer | Existing roadmap/closure map and sanitized reported evidence | Review remaining original-plan items without reclassifying implemented flows as missing code |

Earlier failure, pending and UNKNOWN entries below are dated stage records, not
the current terminal status of this completed run. Older attempts remain intact.
Production identity, scientific-provider synthesis, candidate improvement,
remote-host enforcement and department capacity/operations remain unclosed.
Personal-agent/24-hour work stays deferred.

## Executed GPU baseline compiler PATH repair — 2026-10-07

Accepted PR50 installation/preflights reached actual Torch/GPU, then Inductor
failed before checkpoint/evaluation. Missing PATH reproduced with real GCC and
fixed at canonical runner environment owner; no guardian/schema/package changes.

| Owner / exclusive scope | Dependency | Acceptance / remaining boundary |
|---|---|---|
| root | Integration, source-only installation handoff, exact CI/draft PR | 32 targeted tests and static checks pass; exact CI recorded in PR; package stays PR50; no cloud GPU |
| toolchain_path_fix | Runner launch environment and isolated/compiler guardian regressions | RED missing ld; GREEN 12 focused tests; literal system PATH only |
| toolchain_path_review | Independent mechanism reproduction, trust/toolchain review | No blocker; GCC internals resolve internally, no speculative CUDA/host directories |
| original local worker | Original executed-attempt release chain, target smoke/preflights/new attempt | stoppedProof/cleanupConfirmed reported; GPU release UNKNOWN and full chain unverified, so new launch remains blocked |

Follow [the compiler-path handoff](RESEARCH_TOOLCHAIN_PATH_HANDOFF.md). Keep the
executed failed attempt immutable; never-dispatched release audit does not apply.
No training/checkpoint/evaluation success claimed by this patch or compiler tests.

## Never-dispatched minimal recovery gate — 2026-10-07

PR52 strict historical configuration reconstruction overconstrained the release
question. Runtime remains PR50; only standalone audit, read-only SQL and handoff
change. Original failure and ACKunknown remain unchanged.

| Owner / exclusive scope | Dependency | Acceptance / remaining boundary |
|---|---|---|
| root | Integration, runbooks, exact commit/CI and draft PR | Focused/static validation and exact CI recorded in PR; no target execution |
| never_dispatched_gate | Minimal release mode + synthetic tests | 17 focused tests pass; positive journal/compute/GPU gates retained |
| descendant_read_audit | Root-only queue SQL, provenance doc, disposable PG tests | 12 PG cases added; local PG unavailable, exact CI must execute |
| minimal_gate_review | Independent read-only review | No blocking finding; same-boot/root limitation explicit |
| original local worker | Exact original exports, release + queue checks, separate installation/new attempt | Target gates not run by cloud; no fabricated history or repeated release |

Follow [the corrected handoff](PR50_RELEASED_CUSTODY_HANDOFF.md). Historical
full-config checks are optional forensics; absence of never-executed training
artifacts is not a release blocker. Real missing stop/resource proof still blocks.

## Already-released custody and PR50 installation handoff — 2026-10-07

Runtime remains exact PR50 `997013114a8c533c84078d174b220e541ea19f9a`.
This delivery adds standalone read-only evidence verification and separate
installation tools; it does not change runtime code or historical repair pins.

| Owner / exclusive scope | Dependency | Acceptance / remaining boundary |
|---|---|---|
| root | Integration, original-state reconciliation docs and fixed continuation commands | Ruff/Pyright, npm check (196 tests)/audit, relative links and diff checks pass; runtime/historical tools unchanged |
| released_custody_audit | Standalone original released-custody consistency helper and tests | 11 synthetic tests pass, including existing runtime pure-validator cross-check; actual target export/provenance audit pending |
| pr50_install_handoff | Separate PR50 verifier, full-copy installer, public source manifest and tests | 8 tests pass; all603 exact Git source hashes and135 wheel payloads verified; actual target95-package installation not run |
| handoff_review | Independent read-only review and serial targeted validation | Both focused suites independently pass; no remaining review blocker |
| original local worker | Original evidence audit, new private installation and authorized new research attempt | Reported lease/provider RECLAIMED and GPU RELEASED; full identity still pending. Do not reset/replay unknown ACKs or recreate old service just to release again |

Follow [the fixed handoff](PR50_RELEASED_CUSTODY_HANDOFF.md). Preserve old
workspaces, claims, three new pyc files and receipts. Existing PR50 exact-head
runtime CI is distinct from these targeted delivery checks; no new scientific,
target installation or release acceptance is claimed by the cloud tools.

## Package data path compatibility — 2026-10-07

Target reports actual online install, full-copy and dependency check PASS: all95
versions and the original PR47 135 Factory source files match. Inventory/capture
then rejected legitimate setuptools data filenames containing spaces/parentheses.
DB preflight remains NOT RUN. This is a deterministic code defect, not a damaged
installation; no dependency downloads or environment rebuild are needed.

| Owner / exclusive scope | Dependency | Acceptance |
|---|---|---|
| root | Shared observer path policy, verifier overlay identity, integration/docs/exact CI | 467 research tests (21 skipped), 14 verifier tests, Ruff/Pyright and npm check/audit pass; first Windows run exposed CRLF checkout of pinned observer, fixed with explicit LF; new exact CI pending |
| at10 | Cross-layer package-path regression only | Old regex RED; six tests GREEN through inventory/capture/manifest/observer, mutation and symlink fail closed |
| factory_flow | Standalone repair prepare/check helper and tests | 11 helper tests pass; actual offline Factory-wheel swap on synthetic95 fixture preserves all non-Factory bytes |
| reviewer | Independent security and deployment review | Final implementation approved: shared path boundary, exact wheel overlay, private backup and unchanged non-Factory bytes |
| original local worker | Target Factory-only update, fresh derived identity, DB preflight | Await reviewed fixed delivery; no duplicate cloud target executor |

The base PR47 source/wheel and historical evidence stay immutable. The explicit
repair identity records the sole observer payload replacement and both wheels;
base lock provenance is distinct from the patched installed payload. No changes
to manifest logical-ID validation, startup allowlists or nofollow/link checks.

## Full-copy installation compatibility — 2026-10-06

Known target ext4 reports FICLONE/ENOTSUP; free space permits independent copies.
The former CoW-only delivery was incompatible. Explicit full-copy installation
preserves all source/identity/runtime checks and old attempts; no target execution.

| Owner / exclusive scope | Dependency | Acceptance |
|---|---|---|
| root | Shell mode/budget/integration, documentation, exact CI | 23 local tests pass; static checks pass; previous b18 non-PG 8 jobs passed, remaining CI superseded; new exact CI pending |
| at10 | New bounded atomic copy helper and deterministic tests | 14 copy tests pass; no hardlink/reflink; late mutation and budget regressions covered |
| reviewer | Independent implementation and known-target compatibility review | Approved after closing final-hash mutation window |
| original local worker | Actual private install/identity/DB preflight | Await fixed reviewed tool commit; no cloud duplicate executor |

## Public PR47 installation handoff — 2026-10-06

Branch `coord/pr47-install-closure-delivery-20261006`, based on runtime
`6d6eb9f5fbd3ead921a82b1226edbe6f3d96c12f`. Delivery-only scripts, public manifest,
usage instructions and synthetic regression checks; no application/schema change.

| Owner / scope | Dependency | Acceptance |
|---|---|---|
| root | Public helper delivery, instructions, tests, draft PR | 9 synthetic tests pass; Ruff/Pyright/Bash checks pass; Windows CI exposed CRLF manifest drift, fixed with LF checkout attributes; exact CI pending; source pin remains PR47 |
| reviewer | Independent public diff/security/commit-boundary review | Approved; independently reran 9 tests |
| target operator | New private combined installation and database preflight | Not run by this delivery; target database policy remains unknown |

The previous MODULE_NOT_FOUND occurred before DSN reading because the installed
package was older than the entrypoint. Installation closure must pass before
retrying the existing database preflight. Preserve all old environments/attempts.
See [the portable handoff](PR47_INSTALL_HANDOFF.md); no private cloud paths needed.

## Control/canonical policy alignment and assembly diagnosis — 2026-10-06

Branch `coord/preparation-assembly-diagnosis-20261006`, based on exact PR46
`2112b4b0246542aa488b3e13def0dbaad1c67ad1` (10/10 CI, two terminal observations).
Target static preflight: 76 PASS / 0 BLOCKED / 2 NOT_CHECKED. Target is offline;
no second executor, environment replacement, credential access or local PG/GPU
work is performed. Actual failure root cause remains unconfirmed.

| Owner / exclusive scope | Dependency | Acceptance |
|---|---|---|
| root | Shared control/canonical policy, runtime diagnostic CLI, main stages, integration | Full non-PG1716:1320pass396skip88.313s; final focused21pass1PGskip; npm196/check/audit; Ruff/Pyright0; exact CI pending |
| at10 | Actual control-entry → real SQLite policy regressions, diagnostic boundary tests | Old wiring deterministically rejects; shared policy passes; assembly never enters lifespan |
| factory_flow | Read-only database compatibility helper/tests | 11 pure/SQLite tests pass; new isolated-schema PG test deferred to existing CI service |
| reviewer / independent_review | Independent lifecycle, credentials and policy review | Final approved, including isolated-schema PG acceptance test |

The concrete code defect is the prior control entrypoint's legacy policy contract
conflicting with canonical construction. That does not establish the target DB's
contents. First inspect it with the read-only database mode after reconnection;
retain all prior evidence. Assembly-only mode is explicitly non-read-only but
cannot submit work. Partial constructor failures rely on the short CLI exiting;
no positive cleanup or scientific acceptance is inferred.


## Preparation validation and read-only preflight — 2026-10-06

Branch `coord/preparation-preflight-repair-20261006`, based on PR45 exact
`58cb4fc01261d83d681e72cb522dbac965af47bc`. The actual local attempt stopped
at PREPARATION_ASSEMBLY / VALIDATION_REJECTED, with no submitted preparation,
training or evaluation. Root cause remains unknown; no environmental replacement
or relaxed validator is justified. Environment disconnect notice was checked:
actual workspace read/write/execute succeeded.

| Owner / exclusive scope | Dependency | Acceptance |
|---|---|---|
| root | Runner read-only CLI, assembly diagnostic hooks, integration, exact CI/handoff | Local full1695=1299pass396skip85.533s; npm196/check/audit pass; Ruff/Pyright0; exact CI pending |
| reviewer | Pure tokenizer preflight module and synthetic unit tests | 10 tests including 8192 and UTF8 BOM; independent review approved |
| at10 | Controlled full-vocabulary assembly and CLI regressions | 8192 total constructs; 8193 rejects; CLI no-write/no-DB regressions pass |
| factory_flow | Pure accumulated configuration diagnostics/tests | 7 tests; independent field checks and existing capture constraints |
| independent_review | Independent safety/lifecycle review | Final approved; no remaining blocker |
| go_policy | Exact-head push/PR CI, two terminal observations | Waiting final SHA |

The existing canonical schema remains authoritative. Pure preflight grants no
admission; database/application and runtime-only checks stay NOT_CHECKED. The
historical failed attempts and cleanup uncertainty are preserved.


## Canonical entry safe failure diagnostics — 2026-10-06

Branch `coord/canonical-safe-diagnostics-20261006`, based on PR44 exact
`3c76da2e6cf395bc6f9cfbc8666a62cee4148af6` (10/10 CI; two terminal observations).
The reported first real canonical attempt stopped after STARTED/STOPPED at exit2
without a preparation ACCEPTED record. Its root cause is unknown; baseline0 and
val_bpb null remain. Later empty tables do not rewrite cleanupConfirmed:false.

| Owner / exclusive scope | Dependency | Acceptance |
|---|---|---|
| root | Existing runner stage/type diagnostics, integration and local handoff | 19 focused tests pass; full non-PG1671=1275pass396skip84.624s; Ruff and runner Linux/Windows Pyright0; exact-head CI pending |
| at10 | Runner failure and redaction regression tests | 9 new diagnostic tests, including real execute mock boundaries and 512-byte bound; no credentials, PG, GPU or target execution |
| reviewer | Independent diagnostic safety and lifecycle review | Final safety/lifecycle/docs review approved; POSIX entry-test scope matches existing runner; pure classification cross-platform |

No credential contents/hashes are read by this investigation. The denied unused
password file remains untouched; no cleanup is authorized by this change. The
same canonical entry is used for the next local diagnostic attempt. Target
preparation, baseline and evaluation remain unverified.


## Local PG08/10 failure diagnosis — 2026-10-06

Branch `coord/local-pg-diagnosis-20261006`, based on PR43 exact
`2628e4be74f9c31def9208ea32b05405a54b79d6` (10/10 CI; two terminal observations).
Scope is the retained local failures only. CI success does not explain them.
No provider request, GPU/training, new database container or target storage work.

| Owner / exclusive scope | Dependency | Acceptance |
|---|---|---|
| root | Test timeout evidence, serial reproduction, lifecycle integration and final CI | One serial diagnostic run:2fail164.345s retained; full non-PG1662=1266pass396skip164.905s; Ruff/configured Pyright0; exact-head CI pending |
| at10 | Controlled process fixture diagnostics and isolated lightweight tests | Bounded in-memory allocation phases and finite provider/custody observations;7 pure tests passed; frozen |
| reviewer | Independent read-only environment and diagnostic review | Both admission-crossing mechanisms, evidence hashes and diagnostic tests reviewed; no blocker |

The original two-failure log is retained unchanged outside Git. New observations
use original lease identities/deadlines and real timestamps; authority callbacks
retain their return/exception behavior. No duration or lifecycle rule is changed.

Reproduction:08 crossed its original1s deadline before provider intent and retained
UNKNOWN capacity;10 crossed its original5s deadline before dispatch, then safely
reclaimed PREPARED custody with LEASE_EXPIRED/never-dispatched proof. Neither
entered the intended running-process phase. Original-run causality and the
underlying latency source remain unproven. See `LOCAL_PG_ADMISSION_DIAGNOSIS.md`
for timestamps, hashes and the explicit pre-intent UNKNOWN availability limitation.


## Bounded optimizer/compile probe — 2026-10-06

Branch `coord/research-compile-resource-probe-20261006`, based on accepted PR42
exact `4e0d3aceddc4e7a2fdbd88cbe1f1569ce865755f` (10/10 CI, two terminal observations).
Only an independent diagnostic and minimal control-environment plan are in scope.
No target cleanup, environment synchronization, isolation relaxation, database startup,
new access channel or three-stage execution occurs while the storage choice is pending.

| Owner / exclusive scope | Dependency | Acceptance |
|---|---|---|
| root | Integration, private-control plan, task board | After regression repair: full Python1655=1259pass396skip134.936s; Ruff0; production modules unchanged from project Pyright0; new script Linux/Windows Pyright0; exact-head CI pending; local PG08/10 failure retained below |
| at10 | New optimizer/compile probe and mock/stdlib tests only | Same pinned training adapter; two partial-accumulation updates and two eager forwards; source-only pins, startup gate and verified descendant stop implemented |
| go_adapter | Read-only control/research environment and network feasibility | Same-prefix/package gates confirmed; isolated control venv cannot substitute for combined runtime |
| reviewer | Independent probe, documentation and deadline-regression review |14 probe mock/stdlib tests pass7.403s; cause-specific PG assertion and new controlled-transport test reviewed; no remaining code-review blocker |

Actual target storage and dependency facts remain private. No full-copy fallback is
attempted before enough storage is established. Baseline0 / val_bpb null persists.
See `RESEARCH_OPTIMIZER_PREFLIGHT.md` for diagnostic limits and
`RESEARCH_CONTROL_ENVIRONMENT_PLAN.md` for the conditional private-control installation plan.
Actual compiler timing, full warmup/evaluation budgets and target installation remain unverified.

The first exact head `9d9bbe97d66ca5b36cc4e3d67676d1a0c8e8fa9f` reached
9/10 CI jobs, not acceptance. Push PostgreSQL recorded one existing read-disconnect
test failure: its actual 503 response boundary crossed the fixed lease deadline by
1.606 ms; PR PostgreSQL passed all1654 tests (1591pass63skip). Two terminal
observations106.653s apart preserve this failure. The regression repair separates
real HTTP/PG expiry or original-process-limit evidence from deterministic
unexpired-lease transport coverage; it does not change production lease durations.
Local targeted PG08/10 did not pass (2 failures,134.832s), both before the changed
assertions:08 lacked its provider allocation record;10 never observed RUNNING and
reported a non-successful execution with stop proof. These logs do not identify
an OS restriction or prove a dispatch bug. The runs are retained as failures;
no production change or repeated local PG run is inferred from those incomplete facts.

## Canonical local development bootstrap — 2026-10-06

Branch `coord/research-canonical-bootstrap-20261006` preserves PR40's frozen CI head.
No cloud Torch/GPU execution, production deployment or external identity setup.

| Owner / exclusive scope | Dependency | Acceptance |
|---|---|---|
| root | Versioned interpreter/observer limits, trusted assembly, integration | Complete profile13 and legacy50 pass; full Python1639=1243pass396skip94.521s; runner identity follow-up10pass; Ruff/Linux+Windows Pyright0; real assembled preparation PostgreSQL1 pass25.900s; target full scan pending |
| factory_flow | Preparation runtime, complete inventory, executable handoff docs | Source-only preparation native PG2 pass; inventory10 mock pass; handoff documented |
| at10 | Loopback bootstrap, native controller, three-stage runner | Bootstrap10/controller10 mock and native PG1 pass; runner/controller22 mock pass plus final runner10pass; original-process failure cleanup PG1 pass11.104s |
| go_adapter | Capability probe, captured inputs, assembly regression | Probe13/input9 pass; assembly4 constructor tests pass |
| reviewer | Strict CoW clone and independent assembly review | Clone17 pass; preparation review clear; assembly/stop-only review clear |
| independent_review | Inventory/profile review |13 pass; same-base, cwd and installed RECORD findings resolved |
| go_policy | PR40 exact b8b4ff0 CI |10/10 success, two terminal observations138.075s apart; each PG1507=1444pass63skip |

A deterministic orchestration model is labeled separately from actual provider
execution. Development code identities do not represent independent human review.
Shared-cache contents/permissions are never changed. CoW unavailability has no
full-copy or hardlink fallback. Reviewed target .pth profile is explicit; existing local PG tooling and actual
CoW capability remain factual inputs; missing assembly code continues here instead of being
presented as a user approval prerequisite.

## Cancellation before synthetic process dispatch — 2026-10-06

PR40 head `7a0a5a6ce6df0a75c813710fec4230dddfbf85f3` failed both PostgreSQL
jobs (8/10 jobs passed). Both exposed an environment-preflight cancellation after
effect reservation that retained UNKNOWN; one also exhausted active capacity.
Push: 1500 tests, 2 failures, 63 skips. PR: 1500 tests, 1 failure, 63 skips.

| Owner / exclusive scope | Dependency | Acceptance |
|---|---|---|
| root | tools lifecycle, native PG regression, integration | Original control-command PG8 pass; deterministic preflight PG1 pass; full Python1507=1116pass391skip107.886s; Ruff/Linux+Windows Pyright0 |
| go_adapter | New synthetic predispatch unit tests | Covers no-launch cancellation, ambiguous launch, stale exception proof, cleanup failure and no replay |
| independent_review / at10 | Read-only lifecycle review | Never-dispatched proof must come from this invocation before Popen; unknown launch retains capacity |
| go_policy | Exact-head CI evidence | Both failed terminal observations preserved; no blind rerun |

The repair does not alter generic binding cancellation or infer stop from a native
CANCELLED status. Only the current worker's positive pre-dispatch/cleanup evidence
settles its original effect. Startup-call errors without a returned handle remain
UNKNOWN. Target diagnostics remain independently deliverable from the prior head;
no target training or cloud GPU execution is claimed.

## Active uv0.11.7 target startup profile — 2026-10-06

Branch `coord/research-uv0117-profile-20261006`, based on PR39 exact
`87f7227fae1d4a39ba85db6f68d96061f9f4de3a`. PR39's corrected Linux/Windows
Python and frontend jobs passed; push PostgreSQL passed, PR PostgreSQL failed.
Final9/10 is not accepted. Full failing logs were unavailable (Transport closed /
HTTP403); no assertion or final count is inferred. The next phase preserves test
exit status and prints only the final400 PostgreSQL log lines for diagnosis.

| Owner / exclusive scope | Dependency | Acceptance |
|---|---|---|
| root | Documentation, notices, integration and serial validation/CI | Native PG5pass76.362s; full Python1495=1105pass390skip97.546s; Ruff/Linux+Windows Pyright0; no target execution |
| go_adapter | Observer profile selection and tests |16 pass; exact uv0.11.7/0.12.19 cfg+startup-byte pairing and both final coverage checks |
| at10 | Canonical capture CLI and tests |11 pass; private canonical output, same held config, finite missing-import errors |
| factory_flow | Path-free startup evidence probe and tests |9 pass; fixed files/config fields, no raw paths or argument echo |
| reviewer | Independent implementation review |36 focused tests pass, no remaining code blocker |
| independent_review | Actual inventory limits and CLI boundary review | No CLI blocker; complete target counts prove admission blocked; safety review recorded |
| go_policy | PR39 exact CI observer | Exact PR39 final9/10 confirmed; PostgreSQL PR job failed |

Official uv0.11.7 startup bytes differ from0.12.19 and now have a separate named
profile. Existing0.12.19 and schema1 behavior remain. The target worker reports
ordinary-FD plus logical argv0 restores venv prefix, and independent SDPA full/
half-window BF16 forward/backward plus tokenizer8192 checks passed. These are
relayed target observations, not Factory end-to-end or cloud GPU reproduction.
The generic local contract hash is not adopted as the canonical Factory contract.

The complete target inventory is not admitted by existing count/tree/JSON and
single-link gates. Additional executable startup files also require review.
No private inventory/capacity measurements are published here. Bounds and safety
checks are not silently relaxed. See `RESEARCH_TARGET_ADMISSION.md` for bounded
snapshot/isolation resource choices and control-plane/preparation requirements.

The integrated provider constructor now accepts the exact UV spec as well as the
legacy spec; subclasses remain rejected. The native UV PG regression exercises
real task/native/lease IDs, original checkpoint storage, prefix/argv0, full spec
fingerprint and recovered original-process cleanup. Its synthetic verifier now
matches the real driver's idempotent sealed-input recheck for both fresh-authority
callbacks. Device evidence remains explicitly mocked.

Parallel follow-up scopes: at10 fixed SDPA TorchVersion acceptance (15 mock/pure
checks); go_adapter produced the fixed eager-model diagnostic (independent review
includes interruption cleanup;14 mock tests passed); root retains integration/CI ownership.
Publication scan20files/diffcheck passed. New exact-head CI remains pending. The
separate preparation-store primitive stays in an isolated WIP worktree and is not
claimed as an executable bootstrap. Baseline0, val_bpb null. No global uv update,
dependency install, new local worker, merge or deployment.

Checkpoint reservation follow-up: independent controlled review reproduced a
revocation window after retention lock acquisition. Reservation now holds the
retention fence outside the metadata transaction, then takes admission, task and
hold locks; authority is rechecked after waiting and before directory/chmod/return.
Even a non-growing hold update must return exactly its original row. PlanPolicy
execution reads borrow the current metadata connection to preserve size-one pool
operation. Thirty focused checkpoint/policy tests pass. Updated native PG5 passes83.889s,
including actual policy with a size-one metadata pool; full Python1500 passes
1110/390skipped97.014s; Ruff/Linux+Windows Pyright0. Fresh exact-head CI is pending.
A full-suite test falsely matched HTTP403 in ordinary timestamp microseconds;
its diagnostic-field assertions now use a fixed timestamp containing403, while
retaining sensitive-text exclusion, persisted equality and no-retry checks. The earlier PR40 head's eight successful jobs
are superseded, not final acceptance. No actual target impact is inferred from
the controlled reproducer.

## Active bounded SDPA compatibility diagnostic — 2026-10-06

Base PR38 exact `63c0be99ee4da310492dbbed855bcc4badb6d453` passed all ten
push/PR jobs (37433117998/37433124232). Root double terminal observations were
96.801 seconds apart; independent observations were107.499 seconds apart.
Final PostgreSQL logs could not be downloaded (`Transport closed`), so their
exact test counts remain unverified. No merge or deployment occurred.

The designated target worker reports uv0.11.7/Python3.12.13/Torch2.9.1cu128,
64 frozen dependencies and all11 data/7 kernel assets verified. Its original
FA3 compatibility run failed after5.6 seconds with no kernel image for sm120;
tokenizer, training and evaluation have not run. This is operator-reported
target evidence, not a cloud reproduction. Preserve that original failure
separately from the adapted SDPA baseline.

| Owner / exclusive scope | Dependency | Acceptance |
|---|---|---|
| root | Integration, public launch/parameter contract, serial checks and exact CI | Corrected probe10 pass1.600s, Ruff/Pyright0; new branch `coord/research-sdpa-probe-20261006`, final commit/CI pending |
| factory_flow | `scripts/probe_research_sdpa.py` and focused tests | Seven fixed GPU cases, ten mock/pure tests passed; no actual Torch/GPU execution in cloud |
| go_adapter | Read-only baseline and SDPA contract review | Fixed entry/config/eleven-parameter contract verified unchanged from PR37 |
| reviewer | Independent probe resource/semantic review | Corrected ten mock/pure tests pass1.528s; BF16 quantization issue fixed, D128 nonzero gradient case added, CRLF fixture fix verified; no remaining code blocker |

Target uv0.11.7 is not the reviewed uv0.12.19 startup profile supported by PR38.
Ordinary-path independent compatibility diagnostics do not establish Factory
launch acceptance. Do not upgrade global uv or change version metadata to make
the environment pass. No new local task or source-toolchain build is requested.

The initial probe commit `85e161448a90623c5ec39afda5bd2bb12c81f5cf` failed
both Windows Python jobs: mock success tests read CRLF-converted checkout bytes,
which correctly failed the exact adapter-source pin. The tests now use an
explicit canonical binary fixture and separately assert CRLF rejection; the
actual probe and expected adapter hash remain unchanged. Superseded workflows
37437734399/37437819107 were canceled, not counted as acceptance. Final acceptance
requires fresh exact-head workflows.

## Active pinned uv research launch — 2026-10-06

Base draft PR37 exact `6fd3646ff74a2ab8b7c625461a6f5738fef15079` passed
all ten push/PR jobs; root/independent double observations were105s/115s apart.
Complete final PG logs were unavailable despite successful job conclusions, so
their exact counts remain unclaimed. PR37 proves offline adapter behavior only.

Branch `coord/research-uv-launch-20261006`, draft PR38. Initial public probe
commit `7d30aec38014a2a7b89aaafb6f3dc9925dc8e54f` lets the existing target
executor report exact startup facts; it is not the final integration head.

| Owner / exclusive files | Dependency | Acceptance |
|---|---|---|
| root | Shared spec/guardian/provider/driver/manifest integration, serial checks and final CI | Python1440=1051pass389skip120.223s; PG4pass84.196s; static/frontend/audit passed; final commit/CI pending |
| at10 | Interpreter identity module and filesystem/manifest tests | Interpreter23 and manifest5 passed; namespace and link normalization review fixes closed |
| go_adapter | Environment observer and tests |13 passed; pinned default uv startup profile, installed/upstream lock distinction |
| factory_flow | New uv guardian tests |11 passed; actual prefix success/failure, original stop/restart/cancel, gate-late denial |
| go_policy | Read-only target probe, tests and uv documentation | Probe12 passed; original-argv diagnostics and exact launch recipes documented |
| reviewer | Core lifecycle and observer independent review | Blocking namespace finding fixed and independently reproduced as denied |
| independent_review | Interpreter boundary review; probe review | Interpreter23/probe12 independently passed; link dotdot and trailing slash findings closed |

Only declared bounded interpreter links are supported by the new contract;
ordinary path components and final files retain no-follow checks. Canonical
contract bytes bind project/venv/interpreter roots, config/lock/inventory/package
identities and original custody. The fixed startup prelude rejects base-prefix
fallback before entering the research script. Target CPython3.12.13 previously
reported FD fallback, while a cloud3.12.14 diagnostic retained venv with logical
argv0: these are distinct observations, not interchangeable acceptance.

The first interpreter copy-only guardian fixture failed Python stdlib discovery;
the self-authored fixture now explicitly supplies its existing stdlib layout.
No target environment was modified to make that test pass. The fixed prelude
also has an actual negative test: wrong prefix exits126 before the entrypoint,
while original process stop proof remains valid. Initial probe-only workflows
37431030250/37431103113 were canceled as superseded, not claimed final green.

No new local task, ML installation, upstream execution or GPU experiment runs
in this cloud stage. The local SDPA adaptation and eleven bounded assignments
(approved microbatch overrides both variants) do not support full architecture
search. Real target startup and GPU/numerical evidence remain pending.

## Active local research execution adapter — 2026-10-06

Base accepted draft PR36 exact `0e05b19b84770e22d9bcc79a5df6990130079b84`;
branch `coord/research-local-adapter-20261006`. PR36's final two exact-head
workflows passed all ten jobs, each PG1292=1229 passed/63 skipped; root and
independent observations were more than90 seconds apart. Earlier pending notes
below describe the pre-CI checkpoint.

| Owner / exclusive scope | Dependency | State / acceptance |
|---|---|---|
| root | Shared process hooks/types, evidence storage import, evaluator integration, serial PG/full checks, PR/CI | Frozen: Python1384=995pass389skip94.509s; corrected PG17pass124.505s; frontend196/build, Ruff/Linux+Windows Pyright/audit0; commit/exact CI pending |
| go_adapter | Training source adaptation, lazy Torch runtime, static environment observer and tests | Frozen: training/runtime11 and environment9 pass; no ML imports/execution |
| at10 | Checkpoint format/FD helpers; research guardian extension; actual controlled PG lifecycle | Frozen: checkpoint11, guardian6+ordinary12; PG4pass52.036s including distinct evaluator and size-one metadata pool |
| factory_flow | Local provider/device observer, checkpoint-store tests | Frozen: provider9, device7, checkpoint-store10; portable mocked capability and missing-capability denial covered |
| go_policy | Immutable staging, trusted local driver, uv handoff documentation | Frozen: staging10 and driver12 pass, including real standard-library stale-bytecode regression |
| reviewer + independent_review | Independent source, scientific boundary, lock/custody review | All reported code blockers closed; separate28 and20 light checks passed; actual uv/GPU compatibility remains unverified |

The initial PG31 run exposed a shared retention-lock pool timeout and an old
race between outer lease cancellation and the guardian-deadline test oracle.
Retention now uses its own bounded, fast-failing connection pool; the test
isolates the two deadlines without changing production limits. Corrected PG17
passes include concurrent async fences, metadata pool1, original-run checkpoint
import, independent evaluator byte consumption, acknowledgement loss and revoke.
All local heavy tests ran serially. Isolated databases and guardians were checked
absent after cleanup; no UNKNOWN execution was counted as successful.

Draft PR37's first head `52251bad2357e96b77734c4ff985cb77a9a6419c` failed
both Windows Python jobs: a mocked device-observer fixture used a POSIX-only
absolute path. Workflows37426056733/37426123008 were canceled as superseded;
their successful Linux/frontend jobs are not final acceptance. The test fixture
and mocked OS capability are now portable; seven targeted tests pass, including
denial before opening/spawning when no-follow support is absent. Production path
and no-follow checks are unchanged. Final acceptance requires both new exact-head
workflows.

The cloud stage executes only controlled tests. No downloaded upstream/community
code, ML dependencies, GPU training or dataset downloads are executed here.
Separately authorized target work remains with the designated local executor;
this coordinator does not start a competing local task. Windows and WSL Python
environment management uses uv, independent project environments and reviewed
locks, preserving existing environments and caches.

The local baseline explicitly changes attention implementation, microbatch,
checkpoint export, safe tokenizer input and fixed independent evaluation. It is
not an unchanged upstream benchmark. The default uv interpreter symlink and
pinned-FD launch/venv discovery are not yet compatible with the strict regular
interpreter observer. That route remains blocked pending reviewed support and
actual target evidence; no static check establishes GPU/numerical validity.

## Active research custody and native wait — 2026-10-06

Base accepted PR35 `767323e0f0983a1bf6e4056485c4b767bde2a436`;
branch `coord/research-custody-runtime-20261006`. Both exact-head CI workflows
passed all ten jobs; both actual PG1236=1173 passed/63 skipped. Coordinator and
independent reviewer each observed success twice more than90 seconds apart.

| Owner / exclusive scope | Dependencies | State / acceptance |
|---|---|---|
| root | resources/process runtime/native tool/control integration; shared APIs/docs | Frozen: full Python1292=908pass384skip66.258s; PG19pass143.568s including aggregate budget rejection; frontend196/build, Ruff/Linux+Windows Pyright/audit0; exact-head CI pending |
| factory_flow | GPU custody helper/tests, inert controlled driver, custody handoff | Frozen; strict GPU proof/UNKNOWN retention and driver contract documented |
| go_adapter | manifest/profile and trusted evaluator service with unit tests | Frozen; approved knowledge manifest plus variant pins, original checkpoint and distinct evaluator custody |
| at10 | evaluator parser/tests and new native PostgreSQL lifecycle tests | Frozen: ten actual PG/native cases passed, including revocation/routing/continuation ACK faults; inert GPU driver only |
| reviewer | Read-only independent lifecycle/code/CI review | Final source/test and aggregate budget review clear; 32 independent light tests passed; exact-head CI pending |

All local heavy tests finished serially; isolated test databases were cleaned. The initial full-suite mock-interface failure was fixed with autospec, preserving GPU admission guards. The superseded initial-head CI was canceled for the aggregate budget correction; final exact-head hosted CI remains pending. Actual dependency installation,
training data download, native GPU kernel execution, training and new persistent
connections remain outside this phase. Controlled fixtures cannot establish
physical GPU isolation or scientific validation. Only generic code/tests and
public provenance may be published; no local operational/identifying metadata.


## Active autoresearch contracts — 2026-10-06

Base accepted PR34 `7509e26d8d16374c2fdc94ed2cec88aa13fb9e71`;
branch `coord/autoresearch-contracts-20261006`. Selected upstream is
`karpathy/autoresearch`, commit `228791fb499afffb54b46200aca536f79142f117`.
ORX and existing synthetic profiles remain unchanged. This phase implements inert
contracts; it does not authorize or claim GPU execution.

| Owner / exclusive scope | Dependency | State / acceptance |
|---|---|---|
| root | Source pin/profile, shared task board, integration/commit/CI | Static six-file pin verified; 16 new tests, Ruff/Linux+Windows Pyright and frontend196/check/audit0 pass; full Python1236=862pass374skip80.234s; commit/exact CI pending |
| go_adapter | research_candidate.py and its unit tests | Frozen: byte-bound train.py-only validation, five tests pass |
| at10 | research_assessment.py and its unit tests | Frozen: advisory same-identity comparison, eight tests pass |
| factory_flow | AUTORESEARCH_INTEGRATION.md only | Frozen: provenance, GPU readiness, milestones and code gaps documented |
| reviewer | Read-only independent review | Pure contracts independently reviewed, no blockers; source success-test/native60s documentation suggestions incorporated |

Local full Python regression completed; no heavy local lane remains running. No upstream code/dependency execution,
training, new credentials, paid resources, merge or deployment. Parent owns local
GPU preflight; Windows RTX5070 observed, WSL readiness/data/kernel provenance and
connection plan remain pending. Official code uses mutable dataset main and
runtime kernel resolution: repository commit alone does not freeze those inputs.


## Active schedule diagnostics and development checkpoint — 2026-10-04

Base accepted PR33 exact `e0f74ec330b4f11929be49b4d260acbe1747856f`;
branch `coord/schedule-diagnostics-checkpoint-20261004`. PR33 push/PR ten jobs
passed, both actual PG1200 total/1137 passed/63 skipped; root and independent
reviewer each checked twice more than90 seconds apart. Earlier milestone rows
below remain historical, including their then-pending gates.

| Owner / exclusive scope | Dependency | State / acceptance |
|---|---|---|
| root | Diagnostic persistence/guards/read APIs/shared UI integration/tool contract/docs/commit/CI | Frozen/independent review clear; fullPython1220=846pass374skip57.787s, frontend196/build/audit, Ruff/Linux+Windows Pyright passed; exact-head CI pending |
| at10 | New diagnostic PG/native tests only | Frozen:9 actual PG/native cases validated, including read-only permission, pending fence, real lock/pool and original error preservation; cleanup complete |
| independent_review | New diagnostic UI/state/tests only | Eight tests, lint/typecheck passed; frozen for root integration |
| go_policy | New diagnostic browser acceptance script only | Frozen: desktop/mobile four native denials, GET-only reads/reload/Bob404/zero tasks. New checked-in disposable runner independently repeated PASS; cleanup complete |
| go_adapter | Development launcher + new controlled workflow profile/tests | Frozen: actual combined native source/snapshot/synthesis/comparison and bootstrap/revocation/restart passed; shipped CLI twice HTTPS+Chromium mock-login+same3app pins, both exit0; cleanup complete |
| factory_flow | New final requirements audit document only | Frozen: final code/test audit reconciled with actual diagnostic/startup evidence; two input-dependent scientific/non-toy CODE boundaries retained |
| reviewer | Independent read-only safety/requirements/CI review | Final frozen code/UI/runner/docs approved; independent exact-head CI observation pending |

Diagnostic records contain finite reason/source/time fields and opaque IDs only.
They never reserve, execute, replay or release tasks; reads require current read
permission and original ownership independently of editor fences. Retention is
30 days/100 records per schedule, with best-effort observation explicitly shown.
No new external provider, key, account, host change, merge or deployment.
All heavy local lanes completed serially; none remain active. Original fixture
failures (role-assignment ordering, browser cookie restoration, runner event loop)
remain in evidence; fixes did not relax production authority. Final SHA, draft PR
and twice-observed CI results will be recorded in the PR acceptance receipt.


## Active controlled comparison workflow — 2026-10-04

Base PR32 accepted exact `0a12409f4739b6cfcaa34e9be24037a0907bec6c`; branch
`coord/comparison-workflow-20261004`. PR32 push/PR 10 jobs passed; both actual PG
1171 total / 1108 passed / 63 skipped; coordinator and independent reviewer each
observed twice at >90s intervals. Prior failed-head evidence remains in PR32.

The approved next milestone connects the existing offline contract to one native
task and one bounded paired-evaluator process. Inputs are operator-installed
synthetic development data and finite candidate configurations, approved through
existing material/application/plan governance. No arbitrary code, new scheduler,
external account, paid call, production experiment, host change, merge or deployment.

| Owner / exclusive scope | Dependencies | Status / acceptance |
|---|---|---|
| root: core comparison service/read custody/main/guard/shared UI/docs | Frozen fixture/profile/UI contracts | Integrated; frontend188/lint/type/build and audit pass; Linux/Windows Pyright clean. NativePG7 pass55.837s; final local Python1200=837pass363skip52.362s; desktop/mobile four scenarios pass. Exact-head CI pending |
| go_adapter: comparison_fixture + pure tests | Existing strict comparison contract/process spec | Frozen: 6 tests, Ruff/Pyright pass; no actual execution claimed |
| factory_flow: comparison_profile + pure tests | Fixture manifest/existing governance/runtime | Frozen: 7 tests, Ruff/Pyright pass; separate publication and plan approval |
| independent_review: ComparisonPanel/state/UI tests | Root API contract | Frozen: 10 tests/lint/typecheck pass; strict mode/raw-hash consistency; browser pending |
| at10: comparison PG test/fixture | Integrated root core | Frozen: 7 actual PG/native cases pass55.837s, resources cleaned and heavy lane released |
| go_policy: comparison browser script | Built UI and PG fixture | Frozen: desktop/mobile success and candidate-failure four scenarios pass; two lost acknowledgements per scenario recover original IDs with one POST each; bytes/SHA/Bob404/page+console0; 8 screenshots reviewed; cleanup complete |
| reviewer: independent read-only code/evidence review | Integrated changes | No remaining code blocker; coroutine-to-thread cancellation finding fixed with 2 tests/3 interleavings; independently reran UI10. Four browser scenarios/8 screenshots independently reviewed; no blocker. Exact-head CI pending |

All worker files are frozen and heavy local fixtures cleaned. Final shared process-output flag access was adjusted for Windows static compatibility after browser startup; Linux semantics are unchanged, and 9 output/cancellation tests plus the final full local suite pass.

One process evaluates the approved pair as one effect; pure internal arithmetic
creates no second external effect. The final immutable plan pins all input bytes;
the derived comparison contract refers to the final plan fingerprint, avoiding
circular self-hashes. Offline assessment verification flags remain false; only the
outer verified native evidence may establish controlled execution, never scientific
validity. Whole-project remaining-code/external-validation map due before closing.


## Accepted schedule management journey — 2026-10-04

Base accepted draft PR31 exact `d81d455eeaacd258f60a536f9d247b5ee1cecb11`;
branch `coord/schedule-management-journey-20261004`. Requirements checked against
`V03_APP_GAP_AUDIT.md` and `SCHEDULING.md`: native poller/admission/recovery already
exist; remaining application gap is owner-visible editing/list/pause/resume/history.
Manager-only writes retain own approved immutable plans and current dispatch rights.
New creations start paused. Explicit synthetic mock-login fixtures only; no actual
production schedules, notifications, provider credentials, paid calls, host changes,
merge or deployment. Root grants one heavy local lane at a time.

| Owner / exclusive scope | Dependencies | Status / acceptance |
|---|---|---|
| root: scheduling core/editor journal/API/main and shared frontend integration/docs | Frozen worker contracts | Integrated durable native-write receipts, paused create, CAS revisions, finite owner projections, exact-command GET recovery and bounded independent lock pool. Frontend178/static/audit pass; final local Python1171=815pass356skip57.484s; actual desktop/mobile final pass. Initial8ce321a PR CI allpass; pushPG two old remote fixture facts500 failures. Fixture publication-readiness race deterministically reproduced/fixed without swallowing pinned errors; original04/09 actualPG2pass54.059s. Exact0a12409 push/PR all10success, PG1108pass63skip each; root/reviewer double terminal97s/125s. Original500 precise cause not proven. |
| factory_flow: schedule_contract helper/unit tests/clock doc | Installed native Agno clock | Frozen; 7 light tests pass, actual fixed-clock native comparison incl. DST gap/fold, coalesce/no catch-up and allowed budgeted overlap. |
| independent_review: new schedule panel/state/frontend tests | Root management API and preview contract | Frozen; 11 frontend tests pass. Chinese editor/list/history, current-action guards, lost-ACK exact-command recovery, opaque owner pointers and strict receipts. |
| at10: new schedule management PG tests | Integrated core/API | Frozen; 5 actual PG cases pass (initial4 14.011s, added cancellation4.514s), plus targeted exact receipt/pending/ABA regressions. Metadata pool1, paused native cancellation and owner fences verified; fixtures cleaned. |
| go_policy: new schedule browser script/scratch runner | Built UI/mock HTTPS + PG | Frozen; final manager+independent reviewer desktop/mobile PASS: create1 lostACK GET recovery, edit/enable/pause/history, fixture original trigger1, native artifacts/Bob404, page/console0, 8 screenshots; cleanup complete. |
| go_adapter: offline comparison contract/tests/doc | Existing plan/ORX boundaries | Frozen; 6 pure tests pass. Exact data/evaluator/sample/change/authority pins; no execution and no full comparison claim. |
| reviewer: read-only independent review | Shared implementation and final evidence | Lock/ACK/CAS/old-pending rollback and cleanup-fence findings fixed and regression tested. Code/11 UI tests and final browser/screens/doc matrix independently reviewed. InitialCI remote fixture failure disclosed; readiness fix independently reviewed; exact0a12409 accepted after separate double-terminal and both actualPG log checks. |

Native missed ticks coalesce; no backfill. Overlap is allowed subject to current
owner/global admission and existing task budgets, not a new periodic cost budget.
Pause blocks future admissions, not accepted tasks. UNKNOWN retains original task
capacity and never automatically replays. Single active native poller remains the
supported topology; conditional native lease release/replica acceptance remain open.


## Active verified-source controlled synthesis journey — 2026-10-04

Base accepted draft PR30, exact `d4f5e6c0f64cc49e44561629ba6dc1e909661387`;
branch `coord/source-grounded-synthesis-journey-20261004`. Root owns shared API,
configuration, policy/schema/lifecycle integration and publication. Explicit mock
login and controlled synthesis only; no Go/provider credentials or live scientific
calls, new accounts, paid services, host changes, production schedules, merge or deployment.

| Owner / exclusive scope | Dependency | Acceptance / state |
|---|---|---|
| root: shared composition/snapshot pins, policy/main/API/store wiring, app integration/CSS/docs | Frozen source/runtime/UI contracts | Integrated immutable sourceSnapshotRef and same native plan/review/run path; frontend167/static/audit clean; local Python1151=800pass351skip58.703s; desktop/mobile final pass; draft PR31 exact d81d455 push37220288533/PR37220329603 all10 jobs pass; each PG1088pass63skip. Root/reviewer dual terminal observations97.090241s/125.049434s. |
| factory_flow: new synthesis_sources + unit tests | Existing verified literature artifacts | Frozen; 9 source + 6 configuration tests pass, owner/custody/hash/stale/restart/idempotency and baseline policy fingerprint compatibility. |
| go_adapter: new synthesis_runtime + unit tests | Root extracted existing saver; source service | Frozen; 11 tests pass. Static adapters resolve plan snapshot; verified report projection reuses saver; no per-request publication/registry mutation. |
| independent_review: new SynthesisJourney/state/report UI and tests | Owner snapshot APIs; root Composer bridge | Frozen; 11 tests pass. Selection/provenance/limits/recovery + controlled output inspection; no new execution flow. |
| at10: new synthesis_journey_postgres tests | Integrated API and runtime | Four real PG/native cases pass across initial run + corrected fixture rerun; legacy synthesis profile2 pass. Cancel/revoke at actual model boundary, no report; source drift/missing/owner/restart covered. Lane released. |
| go_policy: new accept_synthesis_journey_browser script + scratch runner | Built UI, mock HTTPS/PG/source runtime | Frozen; final desktop/mobile actual mock HTTPS/PG/native journey passes. Snapshot/proposal lost ACK read recovery, exactly one source + synthesis per viewport, verified downloads/Bob404, page/console0/no overflow; fixtures cleaned. Completed-only mount fixes premature preview409. |
| reviewer: independent read-only contracts/security/acceptance review | Combined changes | Backend and frontend reviewed, 28 Python + 23 frontend independently pass; stable ref/sealed plan correction verified; code/browser/exact CI independently verified, two terminal observations125.049434s apart; no blocking issue. |

Heavy local tests run serially only after root grants the lane. Baseline/candidate
execution comparison shares unresolved evaluator/dataset/approved-change and native
review contracts; a pure validator would not complete that user workflow. Keep it
explicitly remaining, alongside schedule management, rather than claiming those
workflows from synthetic component tests.

## Active approved-template material-to-task journey — 2026-10-04

Base accepted draft PR29, exact `57a3f2f1c44b0dc151752162a4a1a6db5354e9db`;
branch `coord/material-template-user-journey-20261004`. Priority is the existing
material-library / application authoring / Auto-Research journey. Reuse native
services, current independent publication and plan review; no new orchestration.

| Owner / exclusive scope | Dependencies | Acceptance / state |
|---|---|---|
| root: ApplicationGovernance, shared API/types/CSS, integration, requirement matrix/publication | Frozen editor/picker contracts | Integrated guided editing, exact receipt checks and uncertain-save lock; frontend154/static/audit clean; local Python1121=774pass347skip60.182s; draft PR30 published; initial PR CI exposed old OIDC fixture clock race, fixed without production auth changes; final exact push37216580187 and PR37216583963 all10 jobs pass; root/reviewer two terminal observations >90s apart; actual PG logs1058pass63skip. |
| factory_flow: new applicationTemplateState + tests | Existing ApplicationDefinition schema | Frozen; immutable lossless edits and advanced-only boundary; 10 tests pass. |
| go_adapter: new MaterialPicker/materialCatalogState + tests | Existing approved material catalog | Frozen; exact-pin picker, missing/dependency evidence; 6 tests pass, no inferred authority. |
| independent_review: new ApplicationTemplateEditor | Pure template helpers and picker props | Frozen; Chinese guided forms, exact slots and preserved connection scope; 4 render tests pass. |
| at10: new material_template_journey_postgres tests | Existing application/composition/native fixture | Frozen; 2 PostgreSQL cases pass in 7.548s: independent review, new-ID native execution, withdrawal/revocation/hash/owner guards; fixture cleaned. |
| go_policy: new accept_material_template_browser script + scratch runner | Root built UI, mock login, disposable PG | Frozen; actual desktop/mobile native/lost-ACK journeys pass, artifact integrity/Bob isolation and exactly-one task verified; mobile wrapping fixed; fixtures cleaned. |
| reviewer: independent read-only requirement/security/CI review | Combined implementation | AC16.1/3/4/6 reviewed; receipt guard finding fixed, independent 23 frontend tests pass; final browser and exact CI evidence independently checked; no remaining code blocker; draft PR30 accepted at d4f5e6c. |

One heavy local lane, explicitly granted by root. No Go/provider credentials,
paid services, host changes, real accounts, provisioning, merge or deployment.
CLI GitHub auth is expired; use existing authorized connector publication when
supported, never extract/renew credentials. Retain local commits if push is blocked.

## Active aggregate contracts and application recovery — 2026-10-04

Base [PR28](https://github.com/Guanzhw/agent-factory/pull/28), exact
`3afdef7c42556206910ad952b8816a5c1258f972`; branch
`coord/aggregate-contracts-app-workflows-20261004`. Evidence-based final-gap audit
precedes consolidated acceptance. Existing receiver attachment is required and
implemented; optional machine/cloud provisioning is not added to this stage.
Linux is selected. Container/runtime and delegated-subtree details remain inputs.
The department IdP is not supplied; explicitly development-only mock login supports
current work while production identity remains fail-closed.

| Owner / exclusive scope | Dependency | State / acceptance |
|---|---|---|
| root: shared process custody/guardian/provider/receipt/capability/API wiring and final docs | Frozen backend and recovery contracts | Integrated; full local Python1119=774pass345skip60.294s, frontend131/static/audit clean; exact-head CI pending. No actual cgroup/host/security writes, credential access, deploy or merge. |
| go_adapter: new delegated_cgroup + delegated_cgroup_fs and unit contracts | Explicit operator-selected delegated subtree | Implemented descriptor/boot/inode pins, aggregate cpu/memory/pids controls, original-group stop/release; 12 fake tests pass, no kernel acceptance. 3 mocked full-guardian ordering/drift tests pass. |
| go_policy: new deployment_validation module/CLI/tests/doc | Existing identity/runtime/public configuration | Config validator 10 tests pass; development mock login/ephemeral TLS launcher added, 2 real PG cases pass4.692s. Real browser Origin failure diagnosed/fixed without weakening the guard; full desktop/mobile login rerun passes. |
| factory_flow: V03_APP_GAP_AUDIT + new composition_inbox backend/UI/tests | Existing immutable proposals/plans | 8 SQLite + 7 frontend + 2 PG/HTTP tests pass (PG7.858s); actual interrupted-ACK desktop/mobile recovery passes, no duplicate mutations/instances/errors/overflow. |
| independent_review: PlanReviews + new planReviewState/tests | Existing owner review list plus exact plan filter | Review recovery and aggregate UI implemented; 35 focused frontend tests pass. Current scope docs reconciled; historical evidence retained. |
| at10: new aggregate process contract tests | Root/backend frozen interface | 11 fake/SQLite contract tests pass; original bindings, no replay, positive group proof and guardian uncertainty covered. Native reservation ceil and original-lease resume regression passes. |
| reviewer: independent read-only scope/security/acceptance review | Combined changes | Scope corrections landed; aggregate budget/readback/guardian-absence findings fixed, 46 independent light tests pass; final code review and exact CI verification pending. |

Current environment has a read-only cgroup mount. Contract and fake-filesystem
success cannot certify kernel aggregate enforcement. Actual delegated-host tests
remain blocked by target/facility inputs and are reported separately from code.
Heavy tests stay serial, one local lane; no new grants/accounts/paid services.

## Active remote process / isolation capability integration — 2026-10-04

Base PR27 `2e66b50fdd3ef27ca8b36b2f27b39a287d7df8eb`; branch
`coord/remote-process-isolation-20261004`. Reuse Factory handoff, current HTTP
authority, receiver binding proofs and receiver-local process/shared-pool custody.
Do not create a second remote submission or provider transport abstraction.

| Owner / exclusive scope | Dependency | Acceptance / state |
|---|---|---|
| root: shared authority/effective bindings/handoff receipt/provider integration/docs | Existing native handoff lifecycle | Integrated verified effective target, original root process evidence, UNKNOWN origin retention and fail-closed isolation requirements; local full1058=717pass341skip53.654s, frontend106/static/audit clean; exact CI pending at commit time; initial Windows fixture-path errors corrected without production changes or skipped assertions. |
| factory_flow: remote_process_evidence + pure tests | Root receipt schema1/root-only scope | Frozen; eight pure tests pass, strict original root identity/pool/limit monotonic evidence. |
| go_policy: controlled_remote_process_worker fixture | Existing governed handoff/profile and source mapping | Frozen; separate task-owned processes and temporary synthetic auth; actual cancel/503 boundary diagnostics preserve original fixed deadlines. |
| at10: remote_process_runtime_postgres tests/helper | Frozen worker/root contracts | Initial ten cases: eight pass; strengthened UNKNOWN case passes, final expiry/disconnect two pass57.397s after causal assertion fixes. Complete matrix reruns in exact CI; same physical host. |
| go_adapter: isolation_capabilities + pure tests | Read-only current environment evidence | Frozen ten tests pass; cgroup v2 read-only/no user delegation; aggregate unsupported and required scopes fail closed, cleanup remains available. |
| independent_review: RemoteProcessEvidence/remoteProcessEvidenceState/tests + RemoteHandoff UI | Validated root-only receipt | Frozen; eight new UI tests; real PG/HTTP desktop/mobile normal and UNKNOWN browser acceptance passes69.678s, zero writes/errors/extra launches. |
| reviewer: read-only independent security review | Combined changes | Independent34 light tests pass; no production blocker. Final causal-test/browser evidence review passed; independent exact CI verification pending. |

No Go/key access, permanent credentials, paid provisioning, deployment, host/cgroup/
network/security changes or merge. Existing docker daemon is not proven unprivileged
task authority and is not used for enforcement. Real aggregate isolation requires
operator-delegated controllers or a separately authorized backend; independent
remote code continues. Final exact-head CI and deployment input gaps remain pending.

## Active native process / shared-lease integration — 2026-10-04

Base PR26 `ce0c06f21ced442344f46b36587297f2518100e9`; branch
`coord/process-lease-runtime-20261004`. Root retains sole integration ownership.
Only task-owned bounded cooperative Linux workloads; no live Go credential reads,
provider calls, privileged/cgroup/host changes, provisioning, merge or deployment.

| Owner / exclusive scope | Dependencies | Acceptance / state |
|---|---|---|
| root: schema/resources/runtime/lifecycle/API/docs | Original native identity, pools and process custody | Integrated; final local1028=697pass+331skip, frontend98/static/audit clean; exact CI pending at commit time. |
| factory_flow: process_provider + isolated tests | Root af_process_runs/allocation schema | Frozen14 mock tests pass; durable intent, original restart custody, no replay, outcome preservation and late dispatch fence independently reviewed. |
| go_adapter: process_enforcement/guardian + tests | Existing Linux adapter | Boot/PID/start/group, immutable journal pins and positive stop receipts; final12 actual tests passed2.685s. |
| go_policy: process_runtime_profile + tests | Governed bindings/runtime contract | Explicit operator-only target/profile; six light tests passed; no default production selection. |
| at10: process_runtime_postgres tests | Frozen provider/core | Nine PG cases validated: initial8pass, corrected original-receipt read case pass9.241s; strengthened native-terminal UNKNOWN hold pass13.207s. Exact CI will run all together. |
| independent_review: lease UI + browser acceptance script | Owner-only API and execution outcomes | Ten frontend checks passed; actual PG/native/process desktop/mobile normal release and controlled UNKNOWN held passed, four screenshots inspected. |
| reviewer: independent read-only review | Combined implementation | All three findings fixed; final38 independent light tests pass; no remaining blocker; exact CI review pending. |

Required evidence: original task/run/plan/lease/process identity through restart,
no duplicate after lost launch/stop replies, UNKNOWN capacity retention, revocation,
cancel/expiry, shared-pool contention, positive matching release and separately
reported execution outcome. Per-process/per-file limits and cooperative process-group
custody do not certify aggregate quotas, hostile-code isolation or target-host capacity.

## Active browser authentication and process enforcement — 2026-10-04

Base PR25 `a61898a5b92e1584e4adf7cf35bcdcc14b3948b5`; branch
`coord/browser-auth-isolation-20261004`. Root owns shared auth/schema/lifecycle.
Only synthetic IdP/users and task-owned processes/files. No real OAuth registration,
new account access, host/cgroup/network/security changes, purchases or deployment.

| Owner / exclusive scope | Dependency | Acceptance / state |
|---|---|---|
| root: browser_auth, auth/config/main/store, docs | Existing native SQL authority | Integrated; full local986=664pass+322skip, frontend88; exact final CI pending at commit time. |
| go_policy: browser_oidc + verifier tests | Pinned public configuration | 9 offline tests passed; independent ID-token semantics, bounded retry0 exchange. |
| factory_flow: App/api/browserAuth + frontend tests | Root auth endpoints | 31 targeted tests passed; Chinese login/retry/logout, memory-only CSRF, stale-session response rejection. |
| at10: fake IdP, browser PG tests and browser QA script | Shared core and UI | 4 real PG cases passed7.659s; desktop/mobile HTTPS fixture QA passed, stable six screenshots inspected. |
| go_adapter: process enforcement adapter/guardian/tests | Existing nonprivileged Linux facilities | 7 actual process tests passed2.265s plus async-guard regression; final8 cases pass in full suite. Per-process limits and cooperative group fencing only. |
| independent_review: browser boundary tests | Root core | 19 tests passed, including delayed callback/logout beyond initial state TTL and GC. |
| reviewer: read-only independent security review | Combined implementation | Identified logout race, private caching and async authority misuse; all fixed. Final evidence review and exact CI pending. |

Acceptance: exact pinned OIDC code/PKCE/state/nonce; browser binding; no token replay
or session fixation; current SQL users/grants and owner isolation; durable logout
and restart; CSRF and interrupted navigation; desktop/mobile browser behavior.
Resource acceptance requires measured CPU/AS/file-size/wall enforcement and
original-process custody. No aggregate quota, hostile-code/network sandbox,
production IdP or32/64 and54/192 host-capacity claim. Heavy local tests serialize.

## Active resource and identity milestone — 2026-10-04

Base PR24 `d7221e451e7f61c3b9d711788bf17486d6cb5f82`; branch
`coord/resource-identity-integration-20261004`. Root owns shared API/schema/lifecycle
and dependency integration. No production identities, OAuth grants, credentials,
permissions, host security/network changes or deployments are provisioned.

| Owner / exclusive files | Dependency | Acceptance / state |
|---|---|---|
| root: resources/main/config/store/resource API/dependencies/docs | Existing Agno/PG abstractions | Integrated; local945 total=627pass+318skip, frontend78/static passed. Final exact CI pending at commit time. |
| factory_flow: local_compute + local compute tests | Root allocation journal schema | Actual workspace backend accepted: 13 light +3 native/PG/FS tests passed; review fixes include PG locking, serialized effects and cancellation fence. Admission-only, not kernel quotas. |
| at10: capacity and identity tests | Root pools; go_policy verifier | 14 pool light tests and4 production-mode identity PG tests passed, including governed native queue/checksum/receipt/ledger. |
| go_adapter: resource PG tests | Root pool service | Three pool PG tests (23.007s), admin-maintenance PG (6.680s) and6 guarded-dispatch light tests passed. |
| go_policy: oidc_identity + verifier tests | Pinned PyJWT crypto extra | 12 offline RSA/ASGI tests passed; pinned identity, real-ASGI HTTPS requirement, SQL503 separation, no auto-provision/discovery. |
| independent_review: resource_maintenance + tests | Root effect CAS and operator admin authorization | 16 stop-only tests passed, including keyset pagination past active prefixes; no uncertain effect replay. |
| reviewer: independent read-only review | Frozen code and actual evidence | All identified blockers corrected; independent54 offline tests passed. Exact-head CI review pending; first Windows Pyright failure identified and corrected before new-head CI. |

Acceptance requires cross-owner/ref CPU/memory/disk/slot accounting, no oversale,
persistent UNKNOWN holds, original lease identity through restart, positive release,
current revocation and cancellation, actual filesystem and PostgreSQL integration,
and strict external access-token validation delegated to existing SQL authorization.
Target32/64 and54/192 profiles remain unmeasured. Browser OAuth login/session/logout,
remote machine provisioning and OS quota enforcement remain distinct further work.


## Active continuation after PR23 — 2026-10-04

Base a5173379ce7f119fdcf3540239fd82cb19ff86ab; branch coord/luna-scientific-contracts-20261004.
User authorizes a reviewed new bounded Luna investigation under the existing subscription;
no per-call permission gate, no old UNKNOWN replay/release, no guessed historical cause.

| Owner / scope | Dependency | Acceptance / state |
|---|---|---|
| go_policy: Go diagnostics/revision tests | Existing rejection/campaign contracts | Frozen: 52 diagnostics-related checks; six revision checks; native PG revision2 test passed. |
| factory_flow: bounded PubMed acquisition | Managed egress/fixed public query | Frozen: 12 offline tests; real host HTTP retrieval yielded two public abstracts. Real-result desktop/mobile and download-hash browser checks passed. |
| at10: governed PubMed profile | Fetcher/root projection | Frozen: five native PG scenarios passed, including revoke/cancel/UNKNOWN and empty failure evidence. |
| independent_review: source-bound synthesis | Trusted source projection | Frozen: eight immutable context/citation checks passed; no live scientific model. |
| go_adapter: synthesis profile | Root explicit tool contracts/source context | Frozen: offline + native PG tests passed; root native fixture with actual retrieved sources completed. |
| reviewer: read-only independent verification | Frozen integrations | Luna semantics/checksum, source chain, ledger and safety reviewed; exact CI pending. |
| root: shared API/schema, caps, live owner, evidence/PR/CI | Handbacks/serialized PG lane | Luna revision2 completed (2 SETTLED/4332 tokens/held0); retrieval and fixture synthesis completed. Local874=567pass+307skip/frontend78/static/audit passed. Final exact CI pending. |

PR23 completed code/CI stage, not full-product acceptance: both exact runs and all ten
jobs succeeded twice; each PG828total=765passed+63skipped. Its Luna ordinal14 UNKNOWN
and all prior histories remain immutable. New source retrieval is an explicit host
adapter, never a silent Linux fallback. Scientific synthesis needs a separately
selected provider/model/usage/price/owner-binding contract; independent offline code
continues without that input. No merge/deploy, paid fallback or host security change.

## Active milestone — public coding research, 2026-10-04

Current branch `coord/public-coding-research-20261004`, based on PR22 exact
`914de54a18ee3ccda772f578a217f7df6594c805`. PR21/22 are completed stages,
not whole-product acceptance. All older ownership/gates below are historical.
The user authorized ongoing subscription-only Go coding-development tests;
root alone owns credentials. No new payment, production provider, merge or deployment.

| Owner / exclusive scope | Dependencies | Acceptance / state |
|---|---|---|
| factory_flow: public_code_knowledge and isolated native/runner tests | Fixed MIT source pins, existing governance | Both protocols passed actual Factory/Agno/PG with mocked HTTP; 8 KiB bound, two settlements, no holds, cited persisted answer. Three runner checks and failed-retrieval PG diagnostic case passed. |
| go_policy: public_code_fetch and scope reconciliation | Fixed source schema | Eight offline fetch checks and static checks passed; root actual fetch verified both pinned full/excerpt hashes. Scope map delivered. |
| independent_review: read-only review | Frozen worker files and root diff | Source integrity/transport review passed; wrapper bounded-read fix and future diagnostic integration reviewed. |
| root: shared integration, runner, live evidence, board, PR/exact CI | Worker handback and serialized PG lane | Live DeepSeek accepted; Luna RESPONSES_INCOMPLETE/UNKNOWN, campaign stopped without retry. Local 828 total/528 passed/300 skipped; frontend78/static/audit passed; exact CI pending. |

Selected acceptance: a genuine coding question about this client's proxy/CA,
destination, redirect and retry behavior, answered from two reviewed immutable
public sources with explicit citations. This is a development example, not an
invented production research question. Root verifies real HTTP acquisition,
native execution, checksum artifact, settled ledger and answer semantics.
Historical UNKNOWNs and the old zero-source PubMed failure remain unchanged.
Current host PubMed diagnostic returned HTTP200/one source ID; container transport
and the historical failure cause remain unverified. No host security settings changed.

PR22 CI accounting correction: each PostgreSQL suite **805 total = 742 passed +
63 skipped**, zero failures/errors. Ubuntu default suite **805 total = 506 passed +
299 skipped**; Windows **805 total = 391 passed + 414 skipped**.


## Delivery review cleanup — 2026-10-03

Current review/integration order: **PR9 → PR10 → PR14 (checkpoint bridge) → PR11 → PR12 → PR13**.
See [delivery index](DELIVERY_INDEX.md) and [current acceptance](ACCEPTANCE.md#current-matrix).
The runtime `68b3dc7` passed both exact-head CI runs with two terminal observations;
older pending-CI and unregistered-Go notes below are historical. The current
coordinator owns documentation and the narrow completed-log scope correction
found by independent bridge review. Reviewer owns read-only review; test worker
owns its isolated regression file. Historical branches remain unchanged; all PRs
remain Draft. No live key/provider access or production selection is performed.


## Current Go product integration ownership

Base: `37f889e5cc157206868c60c00230bd3b8aef23a5` (Draft PR12), branch
`coord/go-development-product-path-20261002`. Sole coordinator writer; no merge/deploy.

| Work | Owner / exclusive files | Dependencies | State |
|---|---|---|---|
| Explicit profile/material contract | `/root/at10`: go_development.py, test_go_development_profile.py | Existing governance and exact bindings | Frozen; 10 light tests passed; safe transport exact-type allowlist |
| Product HTTP/native/ledger tests | `/root/go_adapter`: go_http_fixture.py, test_go_product_postgres.py | Root registration/guard/transport integration | Frozen; all 7 actual HTTP/PostgreSQL cases passed in 43.926s |
| Independent security/retry review | `/root/reviewer`: read-only | Complete diff and measured queue behavior | Final Go-only queue replay fix reviewed; no blockers |
| Production decisions | `/root/production_decisions`: read-only | Current identity/research implementation | Delivered; PRODUCTION_DECISIONS.md preserves minimum non-secret inputs |
| Core, evidence and delivery | `/root`: all shared interfaces, dispatcher, safe transport, pricing, docs/PR/CI | Worker handback | 38 light tests passed. First PG run failed application scope setup; second passed 5/6 and exposed queue-level quota replay. Durable Go-only stop added; 7-case rerun passed in 43.926s. Frontend64, Ruff/Pyright and npm audit (zero vulnerabilities) passed. Exact CI pending. |
| Live subscription gate | Root only, no key access this phase | Account-specific no-extra-charge proof and persistent request cap | Hard blocked before callbacks; live requests zero |

Heavy tests remain serial on the existing bounded fixture. No worker accesses
credentials. [Product profile](GO_DEVELOPMENT_PROFILE.md) and
[production decision list](PRODUCTION_DECISIONS.md) define current boundaries.
Earlier ownership/status sections below are historical.


Updated 2026-10-02. Dedicated coordinator resumed with sole integration ownership
from exact checkpoint `12c82a469e1172654ac7d57fc02ceeffb8db0bbf` on
`coord/at10-go-integration-20261002`. Previous workers and local Factory are stopped.
No merge or deployment. New container fixtures are being rebuilt from public pins;
old scratch paths are not evidence in this container.

## Active ownership (supersedes preserved rows below)

| Work | Owner / exclusive scope | Dependencies | Acceptance / state |
|---|---|---|---|
| AT10 deterministic diagnosis | `/root/at10`; inference_tree_worker, test_actual_inference_tree, new isolated tests | Pinned checkpoint; root-owned core integration | Deterministic loop/cancellation regressions green; fixture diagnostics delivered; actual receiver tree remains blocked by native 60-second timeout |
| Go offline hardening | `/root/go_adapter`; opencode_go.py, test_opencode_go.py, OPENCODE_GO.md | Mock transport only | 24 Go tests plus async/cancellation and version-proof tests green; independent review passed; offline only |
| Independent review | `/root/reviewer`; read-only | Worker and root diffs | Independent review found and resolved early usage, thread cancellation, native-response publication and callback compatibility issues; final matrix still pending; lock-after-capacity ORX authority review passed |
| Core and acceptance | `/root`; all shared APIs/schema/lifecycle, fixture, board, commits/PR | Worker handback and serial runtime fixture | Frontend64 and offline backend546 (280 opt-in skips) passed; pinned ORX rebuilt exactly; local parent/browser recovery and both delegated stop tests passed (3/3); receiver-parent still times out; root-lock PostgreSQL fix passed all 8 targeted cases; resumed real matrix 4/11 passed and 7 preparation failures; final exact-SHA CI pending |
| Go live gate | `/root` only | Account-specific proof balance fallback disabled | Current credential nonempty boolean true; billing remains unverified, no live call authorized through gate |

Pure offline work is parallel; heavy build/runtime tests remain bounded and serial.
Workers never read credentials; root alone checks the authorized variable.

## Preserved checkpoint status

| Work | Owner / file ownership | Dependencies | Acceptance | State / blocker |
|---|---|---|---|---|
| Linux AT10 delegation / receiver | `/root`; existing inference_wait, model_dispatch, lifecycle_observer, remote_handoff, usage_ledger; new inference_tree_worker/test_actual_inference_tree | Accepted standalone pause; native Agno queue and current-origin protocol | Real owned ORX, independent service/PG restart, same native/ORX identity, one launch; cancellation/revocation/overrun/drift/expiry and retained UNKNOWN | In progress. Child restart passed; Completed-receipt reads now bypass CLI/namespace wake, with original source/current authority/terminal proof; receiver restart reached completed in the active real rerun. Hard-crashed child effects now reconcile after parent recovery, but Agno may restore its prior launch confirmation while the original durable approval is already acknowledged; replaying that receipt intentionally does not dispatch again. The explicit separate queue-only recovery protocol now completes local parent/child. Origin-forwarded remote parent latest run FAILED during child inspect (CancelledError); no native rows are rewritten. First safety batch 6/8; isolated rerun passed receiver overrun (7 distinct cases passed). Origin outage also passed (all 8 safety scenarios have actual passing runs); prior setup timeouts remain documented. No deadline enlargement |
| Go development adapter | `/root/go_adapter`; NEW opencode_go.py, test_opencode_go.py, OPENCODE_GO.md only | Official Go API/catalog; existing httpx/Agno. No core edits | Offline chat/responses/tool-stream/usage/error contracts, own user agent, stable session, bounded requests/no retries, fail-closed billing gate | Worker delivered three files; 18 offline tests plus Ruff/Pyright passed. Found and fixed nested dispatcher double-attempt risk; eight guarded invocation subcases prove one request/attempt. Frozen for integration; no credentials/live inference. Real registration still gated. |
| Resume recorded approval | `/root/go_adapter` reused after Go freeze; control_commands.py, native_bridge.py, factory_api.py recovery sections, NEW test_approved_recovery.py | Exact original acknowledged approval, paused native run/ticket, verified DONE ORX result; public Agno queue-only CAS | One explicit repair receipt/leg per original approval, no HTTP detached fallback/no relaunch, current authority/source/budget, duplicate/UNKNOWN read-only reconciliation | Delivered; 16 light contracts, Ruff/Pyright and independent final review passed. Local actual parent/child repair passed. Root frontend64 tests passed; origin-forwarded actual repair blocked by child inspect cancellation |
| Independent AT10 review | `/root/at10_review`; read-only | Current AT10 diff / native implementation / tests | Concrete owner/authority/race/restart findings and honest coverage verdict | Review completed; 10/10 cheap contracts passed. Concrete fix: native child completed is insufficient; require original ORX terminal + allStopped before evidence-only observation. Review rounds fixed completed-child proof, namespace wake, nonregular logs, cancellation classification and stale repair receipt state. Final independent code review passed, actual/CI gates remain. No writes or credential access |
| Final integration / CI | `/root` | Worker result plus review findings and local acceptance | Full regression, audits, Draft PR10 update, exact-head push AND PR CI success, clean tree | Paused after independent WIP preservation; acceptance and exact-head CI remain pending |
| Limited Go live development check | `/root` only | Adapter checkpoint, injected credential, verified subscription-only billing path | At most three short requests/model, zero retry, <=60s/request, synthetic/public coding input, no tool loop | Blocked: current process credential presence/nonempty check is false; no verified request-level subscription-only switch. No account changes or credential transfer |

## Coordination rules

One writer per listed file. Workers do not commit, push or update PR10; root
reviews and integrates. Root retains shared schema/model-dispatch/ledger and final integration. The explicitly
assigned approval-recovery API/bridge/control sections belong solely to the reused
worker until handback; root does not edit those files concurrently. Pure offline development/review may run concurrently. Heavy PostgreSQL/ORX
acceptance is queued for the actual 4 CPU / 16 GiB host; never create duplicate
runtimes merely to increase concurrency. Test fixtures preserve existing resource
admission, deadlines and UNKNOWN holds. Only task-owned, positively stopped
containers may be removed; source artifacts and test evidence are retained.

No worker reads credentials. Only root may inspect the specifically authorized
Go variable (presence/nonempty boolean only), and only root may make future
explicitly bounded model requests after both credential and billing gates pass.
Production provider/identity/host decisions remain independent. No new paid
compute, subscription-external charges, OAuth, persistent credentials, production
access, network/security bypass, merge or deployment is authorized.

## PostgreSQL CI follow-up

The full PostgreSQL job at `ca12534` ran 550 tests in 1308.788 seconds and
exposed a one-slot metadata pool timeout plus an overstrict UNKNOWN native-state
assertion. The coordinator owns the corrective integration: a Store-shared root
lock pool bounded to one connection, root-before-metadata ordering for budget
charges, explicit reverse-order refusal, and disposal after worker drain. This
adds at most one lock connection per Store and conservatively serializes its
root-lock phases. It does not enlarge the metadata test pool or relax UNKNOWN
resource holds. Five PostgreSQL lock contracts accompany the change; final
results and exact-SHA CI are recorded in Draft PR11.

## Final validation snapshot

The root-lock correction passed five lock contracts plus the formerly failing
application/UNKNOWN cases and lifecycle case 11: 8 tests in 33.994 seconds. Full
offline regression at that stage passed 562 tests (289 explicit opt-in skips).
A further selected-closure optimization avoids duplicate governance traversal
of unrelated catalog rows; it preserves every fresh selected/transitive material
check and has six deterministic regressions plus application/governance coverage.

The resumed 11-case real matrix at `d72a857` took 1358.896 seconds: 4 passed
(local child restart, receiver child restart, origin cancel, receiver overrun);
7 failed during preparation, before the requested safety fault was injected.
Six were native inspect timeouts; one was origin-authority transport timeout
after an initial timeout/retry. They are not seven safety assertions passing.
The original three local parent/stop cases passed, including real Chromium
recovery. At `e0ce609`, local parent/browser recovery passed again while receiver
root and parent remained red (3 cases, 424.478 seconds). The selected-closure
receiver-parent rerun also failed at inspect (98.289 seconds). Full-profile cold
container setup remains a measured bottleneck on this 4 CPU/16 GiB Docker-vfs
host. No timeout, authority check or UNKNOWN hold was relaxed. Bare Python slim
was investigated but rejected because ORX also needs git, ps and external kill;
no runtime image was changed. Final exact-head CI is reported on Draft PR11.

## Terminal-publication race follow-up

Exact-head CI at `2e68725` exposed lifecycle case 01: a protected failure could
arrive after the cleanup-request phase, while the next phase published a stopped
root as terminal without recording its cancellation cause. Terminal publication
now repeats the strict binding/reason check, records required cleanup provenance,
and refreshes positive-stop/failure facts. Changed UNKNOWN/queued facts or check
errors retain capacity; normal completed work remains uncanceled. Five new
deterministic contracts fail against the old implementation and pass with the
fix. All 14 real PostgreSQL lifecycle cases plus five lock cases passed together:
19 tests in 43.985 seconds. Independent review passed.

The final safety batch at `2e68725` passed 7/8 in 1111.150 seconds. Receiver
overrun failed in inspect preparation before its fault was injected; it passed
in the earlier resumed matrix. All eight safety scenarios now have current
container passing evidence across separate runs, but this is not a green combined
run. Remaining receiver-parent reliability and final corrected-SHA CI are open.
Shell and Git were rechecked after a reported cloud disconnect at 20:33 UTC:
both remained available; the existing PostgreSQL process was preserved without
starting duplicate tests.

## Cancellation during a readable delegation preview

The corrected lifecycle head `9beef4a` completed both exact-head CI runs with
573 tests and two reported subtest failures (63 opt-in skips). The first was a
read race: current cancellation arose inside the fresh delegation preview's
binding check and escaped as `RunCancelledException`, returning HTTP 500 from
GET task details. The second subtest inherited the first scenario's revoked
origin role. The read-only preview now denies creation with empty modes for
native cancellation, while request cancellation and all execution guards retain
their existing behavior. Two deterministic regressions cover the projection;
the real process test restores its role in `finally` without changing assertions
or deadlines. Independent review passed. Final exact-head results are in PR11.

The uninstrumented actual-runtime batch at `9beef4a` ran three cases in 391.023s:
receiver-root pause/restart/recovery passed; receiver-parent recovery and receiver
overrun failed in inspect preparation before the intended fault. This is separate
from earlier timing artifacts and does not establish complete AT10 acceptance.

## Receiver-parent recovery continuation (after c374293)

New review branch: `coord/receiver-parent-recovery-20261002`, based on the preserved
exact checkpoint `c374293bd93ec4759f235a340ca264978d9747b3` (both
push/PR CI passed; actual receiver-parent recovery remains unaccepted).

| Work | Owner / exclusive scope | Dependency | Acceptance / state |
|---|---|---|---|
| Recovery stage diagnostics and deterministic fixture contracts | `/root/at10`; inference_tree_worker.py, test_actual_inference_tree.py, new test_at10_recovery_timing files | Existing failure logs; root owns shared core | Delivered: bounded secret-free phase/lock/identity evidence and transparent wrapper contracts; root runs actual acceptance |
| Full acceptance and Go integration gap audit | `/root/go_adapter`; read-only | Current source, PR11 evidence | Complete: Go remains unregistered; pricing/binding and real PG-ledger integration missing; no secret/live access |
| Authority / UNKNOWN / ledger review | `/root/reviewer`; read-only | Core recovery and observer paths | Complete for guard-scope change: ABA replacement regression fixed; actual successful-check identities only; no cross-call cache |
| Shared recovery implementation and final integration | `/root`; core, documentation, actual runs, commit/PR/CI | Worker evidence and review | In progress; heavy tests serial; exact final CI follows actual acceptance |

The 30-second bound is persisted production control metadata created by
`inference_wait.prepare_pause`, capped by original external-work timeouts. It is
not the fixture's 60/90-second observation polling limit and must not be widened
to pass the test. Separate evidence must distinguish service reconstruction,
read projections, fresh authority, lock wait/hold, and native continuation.


Recovery follow-up outcome: diagnostic receiver-parent passed in 203.020s;
final uninstrumented receiver-parent passed in 190.857s. Original 30s deadline,
native/ORX identity, single launch, explicit origin repair receipt, duplicate
receipt idempotency and parent/child completion were verified. Root integrated
same-call declared guard deduplication (including ABA protection) and pure
connection preflight projection; 13 real PostgreSQL connection tests passed in
30.336s. Independent review passed. Diagnostic wrapper failures and the
intermediate uninstrumented inspect timeout remain in AT10_TREE_ACCEPTANCE.md.
Final combined safety/CI results are recorded in the stage draft PR so that a
new documentation-only commit cannot silently invalidate its exact-head checks.

### Normal child completion versus authority loss

The first continuation head `42341646` passed PR CI but failed push CI: the
remote shared-grant child reached native completion with settled usage, while
lifecycle observation classified it as `current-authority-ended`. A stale
running snapshot followed by a fresh completed self-mandate reproduces that
classification deterministically; the original CI log did not retain the caught
exception, so the precise exception in that run remains an inference.

Root owns the narrow integration fix in plan policy and lifecycle observation;
`/root/at10` owns deterministic regression tests, `/root/reviewer` independently
reviews authority and UNKNOWN behavior, and `/root/go_adapter` verifies exact CI.
Execution still denies completed mandates. Only a typed same-task completion
reason, after ancestor checks, permits strict fresh terminal reclassification.
Ordinary authority denials remain failures; missing/mismatched/nonterminal proof
holds capacity. The failing real PostgreSQL scenario now passes in 39.976s.
The preceding head's complete actual receiver safety matrix passed all 8 tests
in 1149.785s. Final-head runtime and CI evidence follows in draft PR12.

Final-core runtime verification at `ee0e5ca` passed: uninstrumented actual
receiver-parent 1/1 in 199.900s; original 30s wait, identities, single launch,
UNKNOWN retention and duplicate receipt checks independently verified. Offline
597 tests passed (290 skips); real PostgreSQL lifecycle 14/14 passed (43.740s).
Push CI passed 597 tests (63 skips), but PR CI exposed a fixture-only exception
race in remote handoff test08: real binding recheck correctly raised native
`RunCancelledException` after cancellation, while the test accepted HTTP denial
only. `/root/at10` owns its deterministic two-boundary regression; `/root/reviewer`
reviews the denial and no-new-effect assertions. Root retains integration and
exact CI ownership. The follow-up changes tests/documentation only; runtime
source remains exactly the verified `ee0e5ca` version. Final CI is recorded in PR12.


## Bounded Go live validation — 2026-10-03 (in progress)

Base: `d760b8af63c6692d0119c5386d7a7481076f61bc`, PR13 exact-head CI
37081501616 passed all five jobs, with two terminal observations 90.069s apart.
Branch: `coord/go-bounded-live-validation-20261003`.

| Owner | Exclusive scope | Dependency | Acceptance / state |
| --- | --- | --- | --- |
| root | Core adapter/profile/queue/usage integration, live runner, real credential, final commit/CI | Independent review and offline product acceptance | In progress; no live dispatch yet |
| go_adapter | go_live.py, gate and transport tests | Root adapter integration | Gate 14 offline tests passed; observer admission fix in progress |
| at10 | test_go_live_product_postgres.py | Gate and adapter | Offline full native product validation in progress |
| reviewer | Read-only integration/security review | Final integrated code | Found observer INFLIGHT and cleanup-accounting blockers; fixes underway |

User attests Use balance and Auto-reload OFF and authorizes bounded genuine
coding development requests. This is account-setting attestation, not measured
invoice proof. Root alone owns credentials; workers use synthetic mocks only.
Fixed order: deepseek-v4-flash then gpt-6-luna; each at most one smoke and two
product requests, zero SDK/queue retries, 60s HTTP deadline. Any unknown outcome,
auth/quota failure, model mismatch or usage anomaly stops the whole campaign.
No model fallback, recharge, new credential, merge or deployment is authorized.


Bounded stage execution update: all worker files integrated; independent review
reports no remaining blocker. Observer/cleanup accounting regressions fixed.
Native PG six-mock-request acceptance passed in 8.176s; full offline suite
648/298 skips passed in 42.787s. The real campaign reserved one DeepSeek smoke
attempt and stopped UNKNOWN (no confirmed model/usage); Luna has zero attempts.
No retry/reset. Root owns remaining commit, draft PR and exact CI. Live compatibility
and billing remain unverified; details in GO_LIVE_VALIDATION.md.

Post-disconnect root verification found persisted SQLite/JSON identical, STOPPED,
DeepSeek1/Luna0 and no live process; no new live attempts. AT10 worker fixed only
the unrelated ORX concurrency fixture's two legitimate schedules; 16 focused
tests passed and independent reviewer approved. No core lifecycle change.

Final integrated offline run: 650 tests / 298 skips passed in 45.461s; existing
actual HTTP/PG Go cases 7/7 passed in 46.958s. Ruff/Pyright and web checks pass.


## Safe Go diagnostics continuation — 2026-10-03

Base `45eeb6b88046a40f8743e01e69d10353be386499` (PR15, all ten exact CI jobs
passed, two terminal observations 106.515s apart). New branch:
`coord/go-safe-diagnostics-20261003`. **Offline only; no new real request.**

| Owner | Exclusive scope | Dependency | Acceptance / blockers |
| --- | --- | --- | --- |
| root | Campaign integration, API/schema boundary, model-selection provenance, docs, final commit/CI | Worker interfaces and independent review | In progress |
| go_adapter | Provider diagnostic phases, safe exception/header normalization, focused tests | campaign.record_event | In progress; no secret access |
| at10 | New append-only diagnostic journal, runner events/exact-model selection, crash tests | safe_diagnostic | In progress; no secret access |
| reviewer | Independent read-only disclosure/crash/replay/alias review | Integrated implementation | Design constraints delivered |

Historical smoke evidence and its one UNKNOWN slot are immutable for this work.
A separate manifest snapshots the three existing evidence files outside Git;
workers do not access them. New diagnostics cannot backfill the lost HTTP facts.
The original user name `deepseek-flash` was not proven equivalent to the selected
versioned model; root will document this selection discrepancy and require explicit
exact-version selection for any future operator campaign.


Diagnostics stage integrated/frozen: provider worker, runner/journal worker and
root campaign boundary complete. Independent review no blockers, 82 targeted
tests passed. Full offline682/298skips passed44.056s; native PG six-mock-request
path passed9.191s; Ruff/Pyright pass. Root verified all three old evidence files'
bytes+mtime unchanged. No additional real request. Final commit/draft PR/exact CI
remain root-owned; recorded in PR to avoid invalidating the verified head.

First diagnostics CI found Windows Pyright rejects three direct POSIX flag
references. AT10 worker fixed guarded lookup with unchanged fail-closed platform
checks; five journal tests and Windows-target Pyright pass. Root requested
cancellation of superseded runs37105481904/37105520150 to avoid duplicate heavy
work, then advances PR16 to the corrected head for fresh exact CI.

Windows typechecking passed at679537e, then the ORX test fixture's shared JSONL
reader reported malformed JSON during concurrent subprocess execution. Exact bad
bytes were not saved; shared-append interleaving is an inference. AT10 replaced
only fixture logging with independently published complete JSON records, preserving
strict parsing, actual subprocesses, once-launch assertions and deadlines.18tests
passed4.216s and reviewer approved. Root cancelled superseded CI and revalidates
all tests on the next final head; no production diagnostic or lifecycle change.

Final integrated offline684/298skips passed46.341s; Windows-target Pyright and
Ruff pass. Root alone owns final push/PR16 exact CI and terminal evidence.

## Exact DeepSeek single-smoke continuation — 2026-10-03

Base PR16 `f85b02bf7343b7b67c3b3643c922fb9a69ed22ae`, all ten CI jobs passed;
root terminal observations 98.163s apart. Branch
`coord/go-exact-single-smoke-20261003`.

| Owner | Exclusive scope | Dependency | Acceptance / blockers |
| --- | --- | --- | --- |
| root | New source-bound cross-campaign budget, integration, docs, sole live credential access | Review and synthetic validation | Six budget/history/concurrency/crash tests pass; live not yet run |
| go_adapter | Exact deepseek-flash protocol and safe returned model preservation | Official public catalog/source | In progress; mocks only |
| at10 | Dedicated one-attempt runner and runner tests | GoSingleSmokeCampaign | In progress; mocks only |
| reviewer | Independent budget/replay/disclosure review | Integrated files | In progress; no live or secret access |

Current authorization is exactly one new independent short `deepseek-flash`
smoke, with historical UNKNOWN permanently retained: DeepSeek total at most two
for this step, original overall cap three. No Luna, native product execution,
account changes, automatic replay, alias substitution or price equivalence.
The fixed source-derived budget path prevents new campaign/evidence names from
resetting the count. Reopening is inspection-only. Safe results and CI evidence
will be reported in the continuation PR; old evidence stays unchanged.

Implementation and independent review complete. Root ran exactly one new smoke:
`aa945eb2-fdf5-432e-8237-c1c9f09c7bb9`, exact `deepseek-flash`, UNKNOWN after
ConnectError at DISPATCH_STARTED (07:56:11.638040 UTC), no response headers,
actual model or usage. Cumulative DeepSeek2/Luna0, both DeepSeek slots retained.
Live stopped; no retries/native execution/Luna. Old three evidence files remain
unchanged. Core7 + runner8 tests passed; independent44 passed; full704/298skips
passed52.616s plus final6alias tests passed. Ruff/Windows Pyright pass. Final
draft PR/CI evidence remains root-owned. See GO_EXACT_SINGLE_SMOKE.md.

## Managed Go egress compatibility — 2026-10-03

Base PR17 `4fc83fbe8bddf5e14a7f62d80f82d150de8d6aff`: ten exact CI jobs
passed, coordinator terminal observations 108.977s apart. Branch
`coord/go-managed-egress-20261003`. Inference remains forbidden in this stage;
both UNKNOWN tickets and DeepSeek2/Luna0 counts are retained.

| Owner | Exclusive scope | Dependency | Acceptance / blockers |
| --- | --- | --- | --- |
| root | Adapter integration, docs, sole one unauthenticated GET, final CI | Worker tests and independent review | In progress |
| go_adapter | Shared fixed-origin HTTP client, environment proxy/CA and offline tests | Existing HTTPX controls | In progress; synthetic env only |
| at10 | One-shot public GET diagnostic script, finite cause/errno and offline tests | Shared client | In progress; no real env/key/network |
| reviewer | Independent TLS/proxy/NO_PROXY/redirect/redaction review | Integrated frozen files | In progress |

Application compatibility only: honor the environment's existing proxy and CA,
preserve TLS verification, fixed official host and zero retries, and never change
host settings or fall back to another route after failure/denial. After offline
tests/review, root may perform exactly one unauthenticated ten-second bounded GET
to the public models endpoint; no credential read, inference, or automatic probe
retry is authorized. Safe outcome and exact CI will be recorded in the draft PR.

Integrated/reviewed: 22focused tests passed; full727/298skips passed53.323s;
native Factory/PostgreSQL synthetic path passed7.097s. Ruff/WindowsPyright pass.
Root performed exactly one no-auth GET at08:29:24UTC through existing managed
egress: HTTP200 in282ms. No key read, body retention, inference or second probe.
Seven budget/history/evidence files unchanged, both UNKNOWN retained, DeepSeek2/
Luna0. This proves public endpoint reachability only. Root owns final draft PR
and exact CI evidence; no merge or deployment.

First managed-egress head CI found the Windows EAI_NONAME/EAI_NODATA numeric
alias overwrote the canonical label. Root fixes fixed-order first-name mapping
with a simulated Windows alias regression; sixcause tests/Ruff/WindowsPyright
pass. Superseded CI cancelled, corrected exact CI follows. No probe rerun.

## Final authorized DeepSeek smoke — 2026-10-03

Base `e90de8a9a7ec69e00b5be896a6888216efcc3997`; branch
`coord/go-final-single-smoke-20261003`. User authorizes exactly one new
`deepseek-flash` synthetic coding request after managed-egress acceptance.
The two historical UNKNOWNs remain occupied; cumulative DeepSeek cap is three,
Luna remains zero. No product tool roundtrip, retries, PAYG fallback or deployment.

| Owner | Scope | Dependency | Acceptance |
|---|---|---|---|
| root | Adapter integration, final runner/tests, sole credential access and live dispatch | Durable gate and independent review | Offline validation in progress; no live call yet |
| go_adapter | Final authorization gate and deterministic tests | Existing original persistent budget | In progress; mock-only, no secrets |
| reviewer | Read-only gate/runner/client review | Final files | In progress; no live access |

Final authority must be consumed atomically in the original budget, preserve
both historical tickets, and never grant dispatch when reopening. Existing
controlled proxy/CA, verified TLS, fixed official endpoint, retry zero,
60-second timeout and 64-token output cap remain unchanged.

Outcome: independent reviewer passed 42 offline tests with no blocker; root
executed exactly one final request. HTTP 200/event-stream was followed by a
protocol error before STREAM_COMPLETED/PARSED. Returned model, finish and usage
are unknown; new ticket c2c80f9d-6d4c-4571-86e8-28e8f5d0851a is UNKNOWN.
DeepSeek 3/3, Luna 0; all live execution stopped. Old two UNKNOWN records and
historical evidence remain unchanged. No retry/product/Luna is authorized.
See GO_FINAL_SINGLE_SMOKE.md for timestamps and scope. Final exact-head CI is
tracked in the draft PR; no merge or deployment.

### Offline diagnosis follow-up

All live/external diagnostic requests are prohibited. Root owns documentation,
integration and immutable-evidence verification; go_adapter owns only
`test_go_stream_diagnosis.py` synthetic fixtures; reviewer independently reviews
signatures; at10 reads exact-head GitHub CI. No runtime behavior or assertion is
changed without a demonstrated defect. Initial PR19 head `329236cc` has passing
frontend and Linux/Windows Python jobs; Postgres jobs are pending.

Retained evidence has no exception chain or per-guard rejection code. Stage and
finite error signatures distinguish common direct read/truncation, JSON decoding
and EOF-without-terminal paths from the observed explicit feed rejection, but
several feed guards remain indistinguishable. Root cause is unconfirmed; all
three UNKNOWNs and DeepSeek 3/Luna 0 accounting remain immutable.

Offline follow-up implementation complete: 11 exact-model synthetic signature
tests, independent review 11+25 passed, full local 748 tests/298 skips passed in
49.443s, Ruff/Windows Pyright passed. Runtime unchanged; no evidenced live root
cause or assertion relaxation. Original and final exact CI outcomes are recorded
in PR19. All nine protected files retain bytes and mtimes.

## Safe rejection categories — bounded offline step

Base `b905d9ea66e1adcebb858283dc2233f247a75103`; branch
`coord/go-rejection-diagnostics-20261003`. No live model/public diagnostic calls,
new billing batch, environment/account/security change, merge or deployment.

| Owner | Exclusive scope | Dependency | Acceptance |
|---|---|---|---|
| root | go_diagnostics.py, docs, integration, full checks and exact CI | Finite shared code/chain contract | In progress |
| go_adapter | opencode_go.py throw-site annotations, test_go_rejection_sites.py | annotate_go_error helper | In progress, mocks only |
| at10 | test_go_rejection_redaction.py | Safe diagnostics API | 10 focused tests passed, frozen |
| reviewer | Independent read-only review | Frozen implementation/tests | Pending |

Only future errors gain bounded diagnostic metadata. All three UNKNOWN tickets,
DeepSeek 3/Luna 0 counts and historical evidence remain unchanged. Actual throw
sites assign stable enum codes; no message-based inference or historical backfill.

Implementation/review complete: actual throw-site categories and safe bounded
causal metadata integrated; all 18 stream guards covered. Final focused16 tests
passed, full764/298 skipped passed in44.627s, Ruff/WindowsPyright passed; independent
review approved. Ordinary exception metadata is read at record time to retain
raise-attached causes; wrappers retain sanitized bounded snapshots. Final exact
CI pending in draft PR. No historical writes or new live calls.

## Ongoing authorized Go project integration — 2026-10-04

Branch `coord/go-project-integration-20261004`, based on PR20 exact
`bcede60aa6b911969d4200d83eda4ad5f2b574ab`. The user superseded artificial
three-call and per-batch approval gates with ongoing project subscription use.
Balance fallback and auto-reload are confirmed off; no new payment, fallback,
account change or credential provisioning is authorized. Historical sections
above describe their original stages, not current admission policy.

| Owner | Exclusive scope | Dependency | Acceptance |
|---|---|---|---|
| root | Core adapter/schema/lifecycle integration, real credential, live runners, docs, final CI | Reviewed project policy and offline tests | In progress |
| go_policy | Project policy/repetition tests; nominal pricing regression file | Existing cumulative lineage | Policy9 and repeated-usage10 passed; pricing tests in progress |
| factory_flow | Workflow runner initial delivery, nominal UI initial delivery, now isolated Postgres workflow test | Exact alias registration and nominal tariff | Runner4 and UI9 passed; native mocked workflow pending |
| independent_review | Independent policy/stream/pricing review; narrow plan-summary display fix | Frozen root integration | Policy and stream approved; pricing accepted with UI fix pending |

Executor usable; OPENCODE_GO presence/nonempty **true** only. Root owns all
real-key access, workers use synthetic credentials. Original three UNKNOWN
tickets are preserved in place. New first DeepSeek request received HTTP200
and failed STREAM_USAGE_REPEATED, retaining a fourth UNKNOWN. Identical valid
repeated counters are now idempotent; conflicting or malformed repeats still
fail, with DONE and EOF required. A reviewed protocol-stop acknowledgement is
append-only. Subsequent DeepSeek smoke settled 56/69/125 tokens; Luna settled
31/69/100. Cumulative attempts DeepSeek5/Luna1; four UNKNOWN and two SETTLED.
No provider invoice is verified. Internal nominal reservations are explicitly
marked as such in persisted tariff metadata and UI. Actual Factory/Agno
tool/receipt/artifact/ledger execution is the next acceptance gate.

Native product outcome: both exact models passed real Agno/PostgreSQL with
mocked wire protocol, then actual authorized subscription execution. DeepSeek
1,454 tokens / Luna931, each2SETTLED, nativeattempt1, noholds, artifactverified.
Cumulative DeepSeek7/Luna3;4UNKNOWN/6SETTLED; ACTIVE. Originalrows/sessions/
17eventprefix/sevenimmutablefiles verified unchanged. Root fullchecks and
exact-head draftPR CI in progress. Next AutoResearch slice selected from audit:
owner-scoped literature evidence projection/UI and standalone report provenance.

## Literature evidence visibility — 2026-10-04

Branch `coord/literature-evidence-visibility-20261004`, based on Go stage PR21
exact `38b4014692713060a2e1bd269d6dbfb1287bbf05`. No new provider calls or
retrieval requests in this stage. Production identities/research providers remain
separate; existing source failures are not reclassified as live success.

| Owner | Exclusive scope | Dependency | Acceptance |
|---|---|---|---|
| root | Owner-scoped persisted projection, Factory API, App integration, PG/browser/full checks, final PR | Existing literature artifact/manifest contract | In progress |
| factory_flow | Standalone report provenance and tests; independent projection review/regressions | Existing report ZIP | 10 report and 8 projection tests passed; reviewed corruption fixes |
| independent_review | Chinese evidence panel/state validator/tests | Bounded optional literatureEvidence projection | In progress |
| go_policy | Read-only PR21 exact-head CI monitor | Push and PR workflows | 8/10 passed, PostgreSQL pending |

Projection reads only persisted owner-scoped artifacts: hashes, ZIP member bounds,
manifest, owner/plan provenance and bounded source fields are checked. It never
performs retrieval. Mixed controlled/public sources are labeled controlled;
no-sources and invalid evidence cannot appear ready. Standalone Markdown carries
its own provenance, missing text, failure and hash-scope explanations. Initial
PG run retained an escaped fixed error-code regression; known enum codes now
render as copyable inline code while untrusted fields remain escaped.

Literature stage local outcomes: report10/projection8/frontend78 tests passed;
PG4/1liveopt-in skip passed39.919s; fullPython805/299skip passed46.112s;
Ruff/Pyright passed. Browsercontrolledfixtures prove desktop/mobile no-sources,
failure/provenance labels and scoped links, zero page errors/writes. Narrowed
Vite proxy fixes demonstrated `/api.ts` source interception. Finalreview/PR
exact-head CI pending; no new external retrieval or provider calls.

Final independent literature review approved with no blockers. All implementation
lanes are frozen; root owns commit/push/draft PR and exact-head CI. Earlier local
corrupt-ZIP/report-integrity findings are resolved with regression coverage.

Final browser follow-up: source-present mobile hash expansion initially overflowed;
scoped wrapping fixes it and rerun passed. Initial PR22 head fb6e5f3 workflows
37187033930/37187049147 were canceled as superseded, not claimed green. Root
will verify only the new final head; backend unchanged from passing805 suite.

## Complete-inventory prelaunch consistency — 2026-10-07

Branch `coord/full-inventory-observer-20261007`, base PR49
`fdbc109a6ca59f10b9e985c18890cea6a958ea38`. Target report:24204 sealed
files, custody PREPARED, no launch receipt/training config/evaluation. Training
has NOT started; PROCESS_SUBMITTED is allocation acknowledgement, not spawn.
The16384 observation cap is a confirmed static compatibility bug, not a proven
sole cause of that attempt. Original target run remains on original pins,
retry0, awaiting normal cancel/cleanup receipt. Recovery is authorized after positive
original capacity/GPU release; OS idleness alone is insufficient.

| Owner | Exclusive scope | Dependency | Acceptance |
|---|---|---|---|
| root | Prelaunch diagnostics/lifecycle integration, task board, docs, final checks/commit/draft PR/exact CI | Original custody and cancellation receipts | In progress |
| at10 | Environment observer bounded deduplicated observations and focused tests | Existing complete inventory profile | Observer27 and document13 focused tests passed; frozen |
| factory_flow | New real24204-file inventory→observer→config-write regression | Observer repair and unchanged driver | Real24204-file full driver/config path passed89.184s; frozen |
| reviewer | Independent read-only cross-layer limit and final review | Worker/root patches | Independent final review passed; no blockers |

Heavy tests remain serial/bounded. No target DB, secret, ML/GPU execution,
inflight pin replacement, merge or deployment in this stage.

Prelaunch diagnostics worker `go_adapter` owns only new regression tests:4 light
tests passed,2 PostgreSQL variants prepared for exact CI. Original PREPARED
SQLite custody, persisted diagnostic/reopen/no-replay, owner projection and
normal never-dispatched cancel/reclaim covered with zero Popen/device calls.

Updated target report: original canonical exited2/retry0 without Torch dispatch,
300s training or evaluation. Original journal is CANCELLED/never-dispatched,
stoppedProof:true/capacityHeld:false; framework RECLAIMED/GPU RELEASED remains
unconfirmed UNKNOWN. Three new pyc files changed sealed namespace; old file
contents unchanged. Guardian lacks -B (confirmed future-write defect), but its
role in those files is not established. at10 now owns narrow guardian-bytecode
fix/regression; reviewer owns original-custody read-only recovery runbook.

Local integration validation:1777 tests/1378 passed/399 conditional skips in
155.066s before the final guardian-only addition; guardian2+generic12 passed
2.824s afterward. Ruff/Pyright0; frontend196tests and audit0 vulnerabilities.
Offline wheel built with135 exact source payloads. First full run's sole stale
PR49-current-source equality test was corrected to preserve the historical pin
and reject the new runtime under old one-file repair mode;14 focused passed.
Independent review approved main patch and that historical-pin regression.
Exact final-head CI, including both PG diagnostic cases, remains pending.

Final controller followup: validated prelaunch rejection now stops polling
immediately and enters original cleanup instead of waiting the3600s lease.
15controller tests passed, including initial/late rejection and unavailable
release proofs retaining cleanupConfirmed:false. Superseded3fa4ec43 CI had
8successful jobs; both remaining PG workflows cancelled before final push.
New exact-head CI is the only final acceptance source.
