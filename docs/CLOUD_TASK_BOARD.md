# Cloud integration task board

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
