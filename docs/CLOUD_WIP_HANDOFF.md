# Semantic continuation correction — 2026-10-08

PR62 is still Draft. Head `47819a12755abbf3d75ca8dbfe77f23d2b9269df` is
**rejected for acceptance**, regardless of its eventual CI outcome. Real-browser
review found a completed queue row with three failed downstream steps and only
three of five expected operations. The earlier gate did not assert those results.
The stronger regression reproduced that failure before correction.

The correction preserves native runtime UUID lineage, validates missing native
continuation workflow context against the original ticket, supplies external
results through Agno RunRequirement, and requires fail-on-error step policies.
The strengthened serial native PostgreSQL gate passed all10 required cases in
107.224s, zero skips; boundary58 passed0.512s and Pyright reported0 errors.
Success now requires six successful leaf results and five once-only closed
operations. Candidate9 and AutoResearch11 previously passed serially, zero skips;
frontend217 plus lint/typecheck/build and dependency audits passed. The replacement
real browser traversed loopback React → Factory HTTP → PostgreSQL native queue,
passed the stronger five-operation/six-leaf assertions, and desktop/mobile
screenshots were manually reviewed. It used a synthetic model and SQLite backend,
not production identity or a domain backend. Exact new-head CI remains required.

The unified application developer guide and README entry ship with this foundation,
covering local authoring through reviewed publication. Real ConvertD remains the
user's local implementation. No live provider, production identity, scientific
data, deployment or target-machine acceptance is claimed.

---

# Current continuation — native Agno workflow correction (2026-10-08)

Active branch: `feat/governed-workflow-agents-20261008`, Draft PR62. Main baseline
`067354e0b95ceba7aa620216fe7a18715b179ac0` has independently successful CI37714925242.
Read the **top** of [CLOUD_TASK_BOARD.md](CLOUD_TASK_BOARD.md) and
[GOVERNED_WORKFLOW_AGENTS.md](GOVERNED_WORKFLOW_AGENTS.md) before historical text.

The pre-correction PR62 implementation duplicated Agno workflow progress and is
superseded. Current work uses native Agno Workflow/Step/Router/Condition/Parallel,
persistent requirements and original-run continuation. Factory adds governance,
immutable component/input pins, shared budgets, external-operation custody and
command receipts only. Old graph/profile/resume implementation is removed.
The operator must explicitly commit the reviewed implementation fingerprint;
function-name serialization alone is not a code integrity commitment.

Native proof and Factory PostgreSQL tests use public synthetic models and an inert
SQLite operation backend. These do not validate actual ConvertD, production
identity, live scientific sources, target-host capacity or backend safety. Real
ConvertD integration remains local user work. No live provider requests or
new costs were incurred for this correction. Final corrected-head CI and merge
are pending; prior-head CI must not be substituted. All earlier text is historical.

---

# Cloud WIP checkpoint handoff — 2026-10-02

## Active continuation — remote scientific bootstrap (2026-10-07)

Current branch: `feat/autoresearch-remote-scientific-bootstrap-20261007`, based on
PR59 `e842b0ff37114efeddcf79e356fcc7c73706a76c` (ten exact-head CI jobs accepted).
Earlier sections below are historical and do not describe current acceptance.
Read the top of `CLOUD_TASK_BOARD.md` and `AUTORESEARCH_REMOTE_OPERATOR.md` first.

The new cloud coordinator uses original delegated metadata children (no invented
native tickets), a pinned receiver, three scientific phases, durable once-only
drive intents, shared tool debits, original process/GPU custody, and a separately
sealed scientific runtime. The retained real baseline is not rerun or rewritten.
Controller/receiver bootstrap requires operator-reviewed matching publication
snapshots, explicit existing trust and private local configuration. Examples
are inert synthetic templates, not production credentials or run receipts.

Current validation is isolated and synthetic. The three-database native fixture
passed in 655.732s with zero skips. The eleven-case required PostgreSQL gate and
final exact-head CI remain pending. Production identity, authorized bidirectional connectivity, real
GPU candidate execution and live scientific literature remain separate acceptance
requirements. Do not infer them from mock constructors or local ASGI transport.


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

Latest continuation adds compact model-selected parameter candidates and retains
original preparation custody through a read-only verification child. Evaluator
construction is delayed until its exact target exists. The three-stage actual
native fixture passed in 339.595 seconds, including same-process completed-custody
registry reconstruction with unchanged original identities and no redispatch.
The required seven-case suite passed in 324.218 seconds with zero skips. Earlier eight-green/PG-pending
CI is superseded and is not final acceptance. Read the top of CLOUD_TASK_BOARD.md.

Final post-fix actual Go diagnostic passed: public context plus final reply, three
SETTLED requests (8,877 tokens), both context/session effects DONE, zero held
provider tokens and exact original container stop/reclaim. Rejected decision
reserved no effect. Earlier UNKNOWNs remain. See `AUTORESEARCH_SESSION.md`.

## Active scientific integration after PR59 initial checkpoint

Coordinator continues on `feat/autoresearch-goal-session-20261007`; PR59 is draft,
not product completion. New same-parent scientific profiles/controller/assembler
and custody guards are implemented, with actual single-worker native pause →
controlled process child → same-parent continuation acceptance. Real target
three-stage scientific acceptance remains pending. See the current task board
and `AUTORESEARCH_SESSION.md`; do not treat prior callback-only blockers as the
latest code state.

Final native PG verification after UNKNOWN/controller fixes passed all six cases
in 90.687 seconds with no skips. The final exact CI head also includes the
Windows assembly fixture correction; see PR59 for its two-round terminal receipts.

Initial head ca9efb2 failed Windows fixture checks; its PostgreSQL push CI passed
2010 tests/63 platform skips. Final new-head CI is still required. A local full
run was interrupted after983 starts when superseded by this integration; it is
not a pass and its four observations were checked in isolated focused runs:the Go mock campaign
passed; the remote case completed in26.024 seconds under a bounded45-second
observation window, so only that test's prior15-second window was corrected.

Three independent public Go diagnostics retained one settled and one UNKNOWN
attempt each. The third classified a30-second ORX sessions GET transport timeout,
then secondary broker authority denial during cleanup. The original ledgers are
not reconciled to zero. Fixed GET-only polling retries share the original deadline;
OpenCode automatic title inference is explicitly disabled. Updated actual wire acceptance passed with two synthetic responses and no title
request. A subsequent actual Go run completed the original context tool and
final reply:three provider requests all SETTLED (2734/60,2884/145,3068/83).
An out-of-stage decision was denied but left an UNKNOWN tool effect. Its original
completed projection was incorrect. Its effect is retained; new pure preconditions
now run before reservation, and unresolved tools block completed projection and
native continuation. Stop-only cancellation precedes best-effort diagnostics. No scientific experiment or
independent result was produced. All original stop/reclaim proofs were retained.

## Goal-driven research session checkpoint — 2026-10-07

Current branch `feat/autoresearch-goal-session-20261007` continues PR58 exact
`d8449295535111947006b62030263efffd161906`. Read the
[session integration handoff](AUTORESEARCH_SESSION.md) and current task board
first. The scientific autonomous application is **not yet accepted**. Existing
candidate/baseline runners prove controlled execution and custody; their fixture
models do not prove autonomous hypothesis generation. Older current sections
below are historical.

## Current research custody checkpoint — 2026-10-06

Current integration branch: `coord/research-custody-runtime-20261006`, based on
accepted draft PR35 `767323e0f0983a1bf6e4056485c4b767bde2a436`. Continue from the
exact tested head and CI receipt in this branch's draft PR. See the
[research custody handoff](RESEARCH_CUSTODY_RUNTIME.md) and
[current task board](CLOUD_TASK_BOARD.md). This phase adds original native pause,
GPU lease release evidence, immutable experiment inputs and independent evaluator
custody. Its test driver is inert; actual GPU execution, checkpoint production and
scientific validation remain outstanding. Earlier entries below are historical.

## Current development checkpoint — 2026-10-04

Continue from the exact tested head recorded in the draft PR for branch
`coord/schedule-diagnostics-checkpoint-20261004`, based on accepted PR33
`e0f74ec330b4f11929be49b4d260acbe1747856f`. See the
[runnable handoff](DEVELOPMENT_IMPLEMENTATION_CHECKPOINT.md),
[current board](CLOUD_TASK_BOARD.md), [final scope audit](V03_FINAL_REQUIREMENT_AUDIT.md)
and [Git-reproducible browser fixture](SCHEDULE_DIAGNOSTICS_ACCEPTANCE.md).
The entries below preserve earlier handoff evidence and are not today's branch
or missing-code instructions. Reconstruct fixtures from checked-in tests/scripts;
do not assume any earlier scratch path or ephemeral database survives.

## Delivery review cleanup — 2026-10-03

Current review/integration order: **PR9 → PR10 → PR14 (checkpoint bridge) → PR11 → PR12 → PR13**.
See [delivery index](DELIVERY_INDEX.md) and [current acceptance](ACCEPTANCE.md#current-matrix).
The runtime `68b3dc7` passed both exact-head CI runs with two terminal observations;
older pending-CI and unregistered-Go notes below are historical. The current
coordinator owns documentation and the narrow completed-log scope correction
found by independent bridge review. Reviewer owns read-only review; test worker
owns its isolated regression file. Historical branches remain unchanged; all PRs
remain Draft. No live key/provider access or production selection is performed.


## Current Go product phase

Continue from exact completed `37f889e5cc157206868c60c00230bd3b8aef23a5`
([Draft PR12](https://github.com/Guanzhw/agent-factory/pull/12)) on
`coord/go-development-product-path-20261002`. The prior receiver-parent stage
passed unchanged 30-second business-bound actual recovery and two exact-SHA CI
observations; it is not being rewritten.

Current changes integrate exact Go models into an explicitly enabled development
profile, governed application/material selection and owner bindings, native queued
tool execution, actual controlled loopback SSE, receipt/artifact and durable usage.
Subscription mode is unconditionally denied before callbacks. No real key is read
in this phase. See [current profile](GO_DEVELOPMENT_PROFILE.md),
[board](CLOUD_TASK_BOARD.md) and [decisions](PRODUCTION_DECISIONS.md).

Local failures remain evidence: initial 6 setup failures revealed an application
capability declaration mismatch; corrected without widening schema. Next run
passed 5/6; quota revealed native queue replay outside model retry limits. A
Go-only durable protected failure now prevents further model admission, including
queue/restart replay after native 503 budget exhaustion. Final acceptance/CI is
recorded in the new draft PR; do not reuse historical test counts below.


## Resumed coordinator snapshot

The dedicated coordinator has resumed from exact checkpoint
`12c82a469e1172654ac7d57fc02ceeffb8db0bbf` on
`coord/at10-go-integration-20261002`, with sole integration ownership.
[Draft PR11](https://github.com/Guanzhw/agent-factory/pull/11) tracks current
acceptance and exact-SHA CI results. The older paused snapshot below is retained
as provenance; its credential and test status do not describe the new container.

The new environment's authorized credential presence/nonempty check was **true**.
No value, length or digest was exposed. No live Go call was made because
subscription-only billing remains unverified. Workers use mock transports only.
The pinned ORX binary was rebuilt from public source with an exact approved hash
match; PostgreSQL and runtime fixtures were recreated, not assumed to exist.

Integrated commits through `59fdcddef12edd44a3766f983bc8d41d69d3e0d3` add:

- Off-loop fresh authority checks with loop-local cancellation fences, loop-owned
  model construction and pause publication, and deterministic regression tests.
- Successful exact-binary version proof reuse; authority/hash checks remain fresh.
  ORX commands check operation authority after capacity acquisition before spawn.
- Go terminal/usage parsing hardening and one-request/one-ledger-attempt contracts.
- Fail-closed Windows capability checks retaining Linux no-follow/nonblocking
  flags, portable recovery mocks, and explicit non-Linux rejection coverage.
- Standalone SELECT autocommit with immediate connection release; explicit
  transactions and durable denial writes retain their semantics.
- Fixed-label timing and allowlisted lifecycle failure diagnostics.

Recorded validation: frontend 64 tests/build/lint/typecheck, offline backend 546
with 280 opt-in skips, latest focused 48 tests, Ruff/Pyright and dependency audit
passed. Actual local parent recovery, parent cancellation and child budget overrun
passed 3/3 in 370.921 seconds. Actual Chromium recovery issued one command POST
with no page errors. The resumed local child restart has also passed.

Receiver-parent remains **unaccepted**: the latest attempt failed after 94.946
seconds with inspect CancelledError at the native 60-second boundary. Diagnostic
cold-container construction took 31.710 seconds, within 43.904-second experiment
setup; parallel authority timing cannot be added directly. No deadline increase,
permission cache, origin-observer bypass, or native-row rewrite was used.

At this snapshot, remaining actual receiver/safety tests run serially within the
measured 4 CPU / 16 GiB environment; PostgreSQL CI is running. Windows/Ubuntu
Python and frontend jobs passed at `59fdcdd`. Consult PR11 for final results rather
than treating this intermediate snapshot as acceptance. Production identities,
real research/provider evidence and target-host capacity remain open gates.

### Subsequent PostgreSQL correction

The first full PostgreSQL CI exposed metadata-pool starvation under a one-slot
pool: a session root lock held its only connection while nested reads needed
another. Store now shares one separately bounded lock connection across all
DelegationService handles. Budget charging takes the same root lock before its
metadata transaction; reverse-order entry is rejected. Native/observer shutdown
precedes lock-pool disposal. Independent review covered both the starvation and
reverse-lock cycle. The metadata pool is not enlarged. A legitimate native
cancellation in the UNKNOWN fixture is accepted while unchanged-effect,
no-compute and retained-UNKNOWN assertions remain mandatory.

### Current acceptance boundary

The root-lock follow-up passed all 8 targeted PostgreSQL cases, including the
original CI failures and lifecycle case 11. Application closure now avoids
checking every unrelated catalog material before checking the complete selected
closure again; the final selected governance check still runs fresh every time.
Six new regressions cover transitive selection, revocation and malformed graphs.

Actual resumed receiver acceptance remains red. The 11-case matrix had 4 passes
and 7 preparation failures before safety fault injection. Local parent/browser
recovery passed again after the lock fix. Receiver parent still times out after
the selected-closure optimization. See CLOUD_TASK_BOARD.md and Draft PR11 for
precise run counts and final exact-head CI. A bare slim-image substitution was
rejected: it lacks ORX's required git/ps/kill dependencies. No image, resource
ceiling or native deadline was changed. Go remains entirely offline.

### Latest terminal-publication correction

CI at `2e68725` found a failure arriving between the observer's cleanup-request
and terminal-publication phases. Before publishing terminal, the observer now
rechecks strict binding/reason, records cancellation provenance and refreshes
positive-stop/failure facts. UNKNOWN/queued changes and check failures keep the
root unreclaimed. Five deterministic contracts reproduce the old defect; all
19 PostgreSQL lifecycle/lock cases passed in 43.985 seconds after the fix.

The real safety batch at `2e68725` passed 7/8 (1111.150 seconds); the remaining
receiver-overrun case failed before fault injection and has an earlier passing
run. Separate passing runs do not establish a combined green acceptance matrix.
Final corrected-head CI and receiver-parent reliability remain the gates. The
reported cloud disconnect did not block shell/Git or interrupt the active test.

## Preserved pre-resumption checkpoint

This is preservation of incomplete project work, not an acceptance release.
Parent instruction explicitly authorizes a separate WIP commit/push and then
pauses changes until a dedicated coordinator resumes. The commit containing this
document is the checkpoint; obtain its exact ID with `git rev-parse HEAD`.
Base: `4e1f29900080ad6004fd33f55580b9fe5ea75c37`, descended from the original
`6793a96c21be88f7145efc55a1312a06ab787628`. Do not reset to main or recreate work.
No merge, deployment, live provider call or production acceptance is implied.

## Ownership and saved implementation

Root is the sole integration writer. Both existing workers are completed and
frozen: `/root/go_adapter` delivered offline Go transport and then the separately
assigned approval-recovery bridge/API/control work; `/root/at10_review` completed
independent read-only review. Process inspection at preservation found no active
Python unittest, inference-tree worker or recovery-browser process. No worker
needs termination; retain test data, working tree and evidence.

Saved AT10 work includes persisted tree/receiver ownership and fresh authority
checks, ancestor/shared usage ceilings, original stopped-work proof, read-only
completed ORX receipts/logs without namespace wake, recovered-child reconciliation,
explicit `resume_approved` recovery with a separate durable receipt and Agno's
public queue CAS, frontend recovery controls, and synthetic actual-runtime tests.
The original approval is never silently dispatched again. Deadlines, UNKNOWN
holds and resource reservations remain in force. No native failed-row rewrite.

Go is an unregistered, billing-gated development adapter with bounded single
requests, buffered SSE, strict usage parsing and offline tests. See
[Go limits](OPENCODE_GO.md). Boolean-only `OPENCODE_GO` presence/nonempty check
at preservation: **false**. No credential value was printed or transferred and
no new live calls were made. Subscription-only billing verification, a proven
input-token guard, immutable pricing and real registration remain absent.

## Evidence and failure status

- Latest combined `test_inference_wait`, `test_approved_recovery`,
  `test_opencode_go`: **50 tests passed**, 0.133 seconds. Pyright: **0 errors,
  0 warnings**. These are focused checks, not full acceptance.
- Prior frontend check: 64 tests in 9 files plus lint/typecheck/build passed.
  No full backend regression or exact-checkpoint CI was completed for this WIP.
- Latest actual remote-parent test **FAILED**, 1 test in 94.036 seconds:
  `ActualReceiverParentInferenceTests.test_parent_inference_fault_preserves_acknowledged_child_work`.
  The receiver child reaches running, then queued/failed before launch approval.
  `orx_experiment_inspect` emits `tool_failed.errorType=CancelledError`.
  This is pre-recovery failure and does not prove the origin-forwarded repair.
- Earlier local parent/child recovery passed; receiver root/child restart and all
  eight receiver safety scenarios have passing runs across separate invocations.
  They do not establish a green combined final matrix. Local parent cancellation
  and child-overrun actual tests, the optional new browser helper and final full
  regression remain pending. See [scenario matrix](AT10_TREE_ACCEPTANCE.md).
- Independent final review and its 16 approval-recovery contracts passed; review
  is not a substitute for the failed remote-parent run or CI.

Cloud-local logs retained outside Git (do not publish raw generated configs):

| Path under `/workspace/scratch/orx-linux/` | Evidence |
|---|---|
| `at10-tree-origin-repair.log` | Latest failing origin-forwarded remote-parent test |
| `at10-tree-pyright.log` | Zero-error static check |
| `at10-tree-core-contracts.log` | 50 focused passes |
| `at10-tree-approved-recovery-first.log` | Local parent repair and source outage pass; remote parent failure |
| `at10-tree-parent-reconcile.log` | Earlier receiver-child pass, earlier parent failures |
| `at10-tree-evidence/` | Per-case synthetic identity/stop receipts and service logs |

The optional `FACTORY_AT10_TIMING=1` diagnostic remains in the test worker.
It records aggregate current-authority and CLI call time, not arguments/secrets.
One in-flight sample showed 80 authority calls taking about 19.7 seconds and one
CLI call about 3.43 seconds. Repeated synchronous authority checks/event-loop
contention is a hypothesis, not an established cause. Native execution has a
60-second bound; diagnose cancellation without enlarging it or caching authority.
Remove or formalize the temporary diagnostic only during resumed development.

## Preservation checks

The 31 changed/new source and documentation files were scanned for private-key
blocks, provider/GitHub/AWS key formats, literal JWTs and credential-bearing URLs;
no matches were found. Credential-related fixture code was checked for synthetic
values and runtime generation. This is a bounded pattern/manual scan, not a
claim that every possible secret format can be detected. Raw logs, generated
JWT/database configs, caches, environments and browser profiles are excluded.
`git diff --check` passed. No business-code fixes or new acceptance runs were
performed during checkpoint preservation.

## Environment and resumption

Workspace `/workspace/agent-factory`: Debian 13.6, Python 3.12.14, Agno 3.1.0,
Node 24.19.0/npm 11.9.0, Docker 28.4; cgroup allocation 4 CPU/16 GiB.
All 50 installed Python packages passed `uv pip check`; this is dependency
compatibility only. Set `UV_CACHE_DIR=/workspace/.cache/uv` because the default
home cache is read-only. PostgreSQL 17.11 fixture is loopback-only on 65432.
Pinned real ORX source is `f336b121525d99364e2dee4fe90b2784894a54e6` (CLI 0.2.13).
See [Linux setup](LINUX_ORX.md), [verification](VERIFICATION.md) and CI locks.
Existing local preparation files are in
`/workspace/scratch/agent-factory-cloud-prep/` (`reproduce.sh`, `test-env.sh`).
Do not copy local user data, real credentials or global configuration.

For focused checks:

```sh
PYTHONPATH=platform:platform/tests .venv/bin/python -m unittest \
  test_inference_wait test_approved_recovery test_opencode_go -v
.venv/bin/pyright
```

Actual tests require explicit owned ORX/PG fixture opt-in from the retained
`/workspace/scratch/orx-linux/env.sh`, sufficient workspace disk and serial heavy
execution. `/tmp` cannot satisfy the parent/child admission reservations.
Set `FACTORY_AT10_FIXTURE_ROOT=/workspace/scratch/orx-linux` and
`FACTORY_AT10_TREE_EVIDENCE_DIR=/workspace/scratch/orx-linux/at10-tree-evidence`.
Run the single failing class first after diagnosis. Optional browser execution
uses `FACTORY_AT10_BROWSER_PYTHON` pointing at the retained browser venv and
`PLAYWRIGHT_BROWSERS_PATH` at its owned browsers directory; not yet accepted.

Next coordinator should diagnose remote inspect cancellation, verify the explicit
origin-forwarded recovery and browser path, complete remaining actual cases and
full regression/audits, then obtain both exact-final-HEAD CI workflows green.
This WIP branch push does not update, merge or certify Draft PR10. Real-model
research, production identity/isolation, Windows coverage and target-host load
remain distinct gates. Resume only under the parent's next coordinator task.

### Final CI follow-up: cancellation in a read projection

Both CI runs at `9beef4a` finished with the same first failure: GET task detail
entered `delegation_scope` before cancellation, then its fresh binding check
observed cancellation and raised native `RunCancelledException`, leaking HTTP
500. The preview now returns denied availability with no modes; owner isolation,
execution guards, and asynchronous request cancellation remain unchanged.
The second reported subtest failure was role-state contamination, addressed by
unconditional role restoration in that test. Independent review passed. Final
commit and two-round exact-SHA CI evidence are maintained on Draft PR11.

Actual-runtime reruns at `9beef4a` without timing instrumentation: three tests,
391.023s, receiver-root recovery passed with original identity/one launch;
receiver-parent and receiver-overrun failed before fault injection in inspect.
A green CI result must not be represented as full AT10 or production acceptance.


### Receiver-parent continuation after c374293

New coordinator branch `coord/receiver-parent-recovery-20261002` preserves c374293
and PR11. Three worker scopes covered timing/fixture contracts, read-only full
acceptance/Go gaps, and independent authority/UNKNOWN/ledger review. Root owns
core integration and serial heavy tests.

The original 30s business recovery wait was not a test observation timeout.
Repeated tool-independent material/binding/application guards consumed its
window. Explicit guard declarations now skip only duplicates whose callable
actually succeeded within that same check (including replacement/ABA defense);
unknown guards and all later boundaries remain fresh. Connection preflight also
projects its already checked result without a duplicate current-binding query;
inspect/list/bind/revoke and resolve preserve their own fresh checks.

Actual receiver-parent passed with phase diagnostics in 203.020s and, after the
connection optimization, without instrumentation in 190.857s. Parent and child
completed with original native/ORX identities, one launch, origin repair and
idempotent duplicate receipt. The earlier failed stages remain documented in
AT10_TREE_ACCEPTANCE.md. Timing instrumentation records bounded fixed labels,
allowlisted denial codes and identity booleans; no credentials or raw arguments.
Combined safety, final SHA and two-round exact CI are recorded in this stage's
new draft PR. No merge/deployment or live Go request is authorized by this result.

Go remains an unregistered development adapter, with mock HTTP/usage tests.
Still missing: approved binding/profile, immutable pricing and request guard,
Go-through-native-to-real-PostgreSQL-ledger coverage, and account-specific
subscription-only billing proof. OPENCODE_GO presence/nonempty was already true;
workers never access it, no live calls or account changes were made. Production
identity/TLS, live research, selected mutable scientific workload, Windows actual
containment, and target-host capacity remain separate open acceptance gates.

### Lifecycle completion race follow-up

Do not treat `42341646` as green: PR CI passed, push CI failed the remote
shared-grant child completion assertion. A native-completion/authority-check
race can incorrectly cancel normal completed child work. The follow-up uses a
specific completed-self-mandate exception and strict fresh binding in the
observer; generic authority loss and unresolved effects keep their previous
semantics. Independent review passed. Actual safety at the preceding head was
8/8 passing (1149.785s); the targeted real PostgreSQL failure now passes
(39.976s). Final follow-up evidence and exact SHA are in draft PR12.

The final runtime at `ee0e5ca` additionally passed actual receiver-parent recovery
(199.900s), 14 real PostgreSQL lifecycle tests (43.740s), and 597 offline tests
(290 skips). Independent evidence review confirmed the original 30s wait,
identities, one launch, positive stop, retained UNKNOWN and duplicate receipts.
Its push CI passed; PR CI found a test expectation race: binding recheck correctly
raised native cancellation, but remote handoff test08 accepted only HTTP denial.
The follow-up makes both denial boundaries deterministic, verifies persistent
cancellation and no new tickets/effects/artifacts, and restores fixture roles
and observers in finally. No runtime source, deadline or budget changes follow
`ee0e5ca`; exact final CI remains linked from draft PR12.
