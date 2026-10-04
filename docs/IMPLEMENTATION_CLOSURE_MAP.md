# Implementation closure map

This map separates remaining code in the accepted scope from evidence that needs
real operating inputs or a deployment. It is not a new feature backlog. The
original PR28 table in `V03_APP_GAP_AUDIT.md` remains a historical audit; subsequent
draft PRs close proposal recovery, guided material editing, controlled source
synthesis, schedule management and the controlled comparison journey.

| Area | Implemented boundary | Remaining code or decision | External acceptance |
|---|---|---|---|
| Factory spine | Versioned materials, independent publication, composition, immutable plan approval, bindings, native lifecycle, receipts/HITL/cancel, usage and storage governance | No new replacement orchestrator is required | Production operational review and deployment |
| User application flow | Proposal inbox/re-entry, guided material workflow, source selection/snapshot to controlled synthesis, schedule editor/history and controlled paired comparison | Controlled browser/native acceptance passed; exact-head CI and final acceptance are recorded in the corresponding draft PR | Usability with actual department users |
| Scheduling | One native poller, current dispatch authority, timezone/DST preview, coalesced missed ticks, owner/global active quotas, original occurrence recovery and pause/resume; bounded owner-visible pre-occurrence diagnostics now implemented | Diagnostic API/UI/native/browser tests are integrated; final exact-head acceptance belongs to the checkpoint draft PR. Empty history still is not a complete refusal log | Operating timezone and schedule policy on deployed system |
| Runnable development instance | Explicit mock-login launcher and opt-in persistent synthetic source/synthesis/comparison profile | Actual combined native flows and shipped CLI HTTPS initialization/restart/mock-login passed; final exact-head acceptance belongs to the checkpoint PR | Dedicated operator-provided development PostgreSQL/workspace; production configuration remains separate |
| Schedule policy extensions | Existing active-task/storage and immutable-plan usage limits are enforced | No-overlap, cumulative periodic spending caps, schedule deletion/retention/catalog quotas require a selected policy; do not treat these as silently required features | Approved organization policy if these options are selected |
| Research workflow | Verified source provenance/citations and bounded synthetic paired metrics with real native process receipts | General non-toy experiment support requires selected dataset/evaluator/change-scope contracts and a reviewed adapter; finite fixture is complete only within its declared scope | Real scientific provider/source access, domain review, actual experiments and result validity |
| Remote runtime/resources | Governed attach, original receiver/runtime custody, shared resource pools, recovery and cancellation | No general machine/cloud provisioner is claimed or required by current attach scope | Separate physical host deployment, connectivity, credentials and receiver acceptance |
| Isolation | Cooperative process limits; separate optional delegated-cgroup implementation | Hostile-code sandbox/network isolation are not claimed; multi-poller/atomic conditional lease release remains a distinct topology limitation | Actual kernel delegation, pressure, descendant and custody tests on target hosts |
| Identity and access | Owner partitions, fresh native permissions, OIDC interfaces and development mock-login journey | No additional credential discovery or provider automation required | Actual IdP/TLS configuration, owner/reviewer mappings and revocation acceptance |
| Capacity/storage/operations | Bounded workers, admission, usage ledger, quarantine, bounded load tooling and database snapshot tooling | No unlimited expansion or invented production defaults | About 20-user mixed load on 32-core/64-GB or 54-core/192-GB target; real disk thresholds, backup/restore/RPO/PITR and monitoring |

Close the implemented development workflow deliberately after the final PR
evidence is accepted. Do not equate it with production or scientific readiness.
Before further implementation, select an outstanding code item or supply the
user-owned operational/scientific inputs for an external acceptance row. Optional
policy/topology extensions should not become an endless implied scope.
