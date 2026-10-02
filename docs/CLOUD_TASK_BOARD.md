# Cloud integration task board

Updated 2026-10-02. WIP preservation requested; all development workers completed and root pauses after checkpoint push. See [checkpoint handoff](CLOUD_WIP_HANDOFF.md). Product priorities and user decisions belong to the parent
coordinator; `/root` owns this cloud checkout, integration, commits and Draft PR10.
Accepted checkpoint: `4e1f29900080ad6004fd33f55580b9fe5ea75c37` (both CI workflows
5/5). Current work is on `wip/orx-ledger-cloud-handoff`; no merge or deployment.

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
