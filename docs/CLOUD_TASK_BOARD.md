# Cloud integration task board

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
