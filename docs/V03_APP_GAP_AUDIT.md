# v0.3 application workflow gap audit

Audit baseline: PR28 commit `3afdef7` (2026-10-04). This is a read-only
code/test audit, not a new test run, browser acceptance, production deployment,
or a revalidation of the unavailable private design documents. Test references
identify executable evidence in the repository; exact-head CI results remain
with the corresponding PR. Later implementation must update these findings
rather than silently treating this baseline as current acceptance.

Current continuation implements the first two audited slices: owner-visible
proposal history with read-only original-plan recovery, and exact-plan review
re-entry. SQLite, PostgreSQL/HTTP and frontend contract tests cover them; current
browser and exact-head CI evidence are recorded by the stage PR. The flow table
below retains the PR28 baseline to explain the selected changes. PR30 closes the
guided approved-template editor and material-to-task slice. The subsequent
[source-to-synthesis milestone](SOURCE_SYNTHESIS_JOURNEY.md) implements the bounded
owner source handoff and controlled synthesis journey; its own draft PR records
acceptance. Schedule and general scientific-evaluation workflows remain code work.

The continuation also adds explicit development mock login, deployment declaration
validation and an opt-in [aggregate process contract](AGGREGATE_PROCESS_CONTRACTS.md).
These do not select a production provider or certify a real delegated host.

## Flow-by-flow status

`Implemented` below means the stated bounded mechanism exists in code with
relevant tests. It does not mean the complete production workflow is accepted.

| User flow | Baseline implementation and test evidence | Remaining classification |
|---|---|---|
| Manager authors reusable materials | Six kinds, immutable bodies/dependencies, provenance/licence validation and inert import in `platform/agent_factory/material_governance.py`; `web/MaterialGovernance.tsx`. `test_material_governance.py` covers six-kind import, credential/schema rejection and immutable closure. | Implemented. Real selected research material onboarding and review remain external validation. |
| A different manager publishes or rejects | Exact-version separate-current-admin review, withdrawal/archive and historical preservation; same module/UI. Tests include `test_default_requires_separate_current_native_admin_and_exact_digest`, `test_archive_and_withdraw_preserve_versions_hashes_and_history`. | Implemented; production reviewer identities and operating policy remain external inputs. No new approval subsystem is needed. |
| Manager defines an application from materials | `applications.py` validates modes, exact material choices, dependency closure, capability/tool/budget boundaries; `ApplicationGovernance.tsx` supports copy, revise, draft, publication request and separate decision. `test_applications_composition.py`, `test_application_snapshots.py`, `test_application_closure_authority.py`. | Implemented governance. Code/usability gap: definition editing is a JSON textarea even when cloning an approved template; a constrained slot/config form can reuse the current backend. |
| User describes a goal and chooses an approved application | `composition.py::_application/_candidate` discovers from approved metadata and creates bounded proposals; `ApplicationComposer.tsx` exposes application, mode, material slots, own connections and preflight. `test_new_six_kind_configuration_is_discovered_without_application_branches` and actual native new-application test. | Implemented FR16 bounded discovery; not unrestricted autonomous creation/install/publication. |
| User revises/rejects/accepts a proposal | Immutable proposal lineage, semantic request keys and one accepted plan; `composition.py`; `test_semantic_keys_reject_changed_intent_and_accept_recovery_creates_one_plan`, concurrent PG acceptance/restart test. | Implemented writes. **Code gap: no owner proposal list or history recovery entry point**, detailed below. |
| User returns after a lost reply/reload/device change | `commandKeys.ts` retains owner/operation/payload-hash request keys; composer retains one sessionStorage proposal ID and follows bounded revision links. | Partial. Known-ID recovery works, but losing the sole pointer or the first creation reply leaves durable proposals undiscoverable. Accepted plan recovery currently calls accept again and requires the original semantic key. |
| User requests temporary-plan approval | `plan_policy.py`, `PlanReviews.tsx`; exact-plan digest, expiry, changed policy/current role and denial checks. `test_plan_policy.py` includes current policy, owner isolation, expiry, native continuation and actual approved execution. | Implemented mandate. **Code gap: PlanReviewGate's review/request pointers are only useRef; reload loses pending/denied/expired review context despite an existing owner list API.** |
| User creates one native task | `factory_api.py`, `native_bridge.py`, `execution_bindings.py` preserve owner/plan/request/native identity and current guards. Composition/native admission tests and `tests/api.test.ts` cover original-key ambiguous create recovery. | Implemented. Cross-device creation-intent discovery beyond existing task/request lookup can be evaluated after proposal recovery; do not replay an unknown create. |
| User answers, approves, rejects or cancels | `control_commands.py`, `ControlRecovery.tsx`, `controlCommandStorage.ts`, task detail in `App.tsx`. `test_control_commands.py`, process and remote variants, `tests/control-commands.test.ts`. | Implemented durable decisions and separate continuation/stop confirmation. Existing recovery must be reused, not replaced by a second command journal. |
| User recovers approved or interrupted native work | `ApprovedRecovery.tsx`, native/control validation, lifecycle observer; `test_approved_recovery.py`, `test_inference_control_validation.py`, AT10/recovery tests. | Implemented for bounded existing contracts. A stopped/unknown effect remains distinct from success and must never be automatically replayed. |
| User delegates, cancels a tree and checks shared limits | `delegation.py`, lifecycle observer and task detail; delegation, AT10, remote/control tests. | Implemented bounded ancestry and shared root budgets. The root-only process application deliberately forbids delegation; this is not evidence of remote child process support. |
| User sees and downloads literature evidence | `pubmed_retrieval.py`, `pubmed_profile.py`, `literature_evidence.py`, `LiteratureEvidence.tsx`, verified artifact download. Literature/PubMed unit and PG tests; `tests/literature-evidence.test.ts`, `tests/artifact-download.test.ts`. | Implemented source provenance, missing text, failure/empty states and hash checks. Real public abstract retrieval is documented; production question/full-text permission and scientific validity remain separate. |
| User turns retrieved evidence into a synthesis | `literature_synthesis.py` pins source context, validates citations/quotes and limitations; `literature_synthesis_profile.py` registers a controlled scientific model and saved reports. Synthesis unit/native PG tests. | **Code gap:** source snapshot is installed through operator profile construction, not a user-facing “use this verified result” transition. Real scientific model/provider contract and domain review also remain external/adapter work. A controlled source-selection/review flow can be built independently without claiming real synthesis. |
| User proposes and evaluates a research/code change | `orx_experiment_tools.py` exposes bounded success/evaluator-failure/long-running scenarios with pinned archives; ORX and AT10 tests. | **Code gap:** no general candidate-change proposal/diff, baseline/candidate contract or persisted comparison review. The existing toy cannot be renamed into this feature. Choose a public synthetic fixture for implementation; real dataset/evaluator/metric acceptance still needs inputs. |
| User selects an existing remote Factory | `remote_handoff.py`, `remote_bindings.py`, `remote_authority.py`, `remote_execution.py` plus PR28 process evidence; independent-service real HTTP/PG tests. | Implemented exact source/receiver mapping, one native dispatch, restart/unknown/revoke/cancel and root process evidence. Cross-host TLS, actual IdP/owner mapping and target host acceptance remain external validation. **Machine provisioning is not a prerequisite for attaching an already running receiver.** |
| User sees process/pool custody | `process_runtime.py`, `process_provider.py`, `resources.py`, `remote_process_evidence.py`; `ConnectionsPanel.tsx`, `RemoteProcessEvidence.tsx`. Local/remote native PG and safe projection tests. | Implemented cooperative bounded processes with retained evidence and separate execution outcome/release. Aggregate isolation backend remains code work; capability detection correctly rejects unavailable enforcement. Not a general scheduler or hostile-code sandbox. |
| User signs in and switches/ends session | `browser_auth.py`, OIDC modules, `browserAuth.ts`, `App.tsx`; browser auth, native identity and browser evidence referenced by PR26. | Implemented controlled HTTPS/identity/session/CSRF flows. Real production IdP, deployed TLS and account onboarding remain external acceptance. |
| User checks usage and cost | `usage_ledger.py`, Go accounting, `UsageLedger.tsx`; native/remote usage tests and UI validation. | Implemented commitments/holds/settlement and nominal-vs-invoice disclosure. Go development authorization does not authorize scientific use or establish actual invoice cost. |
| User schedules repeat approved work | `scheduling.py`, `scheduling_api.py`, native occurrence/recovery tests; registered in `main.py`. | Backend implemented with one native poller. **Code gap: no corresponding schedule management UI/API helper in web.** Scheduler replica safety is a separate backend limit, not solved by a UI. |
| Operator recovers storage and measures capacity | `storage_governance.py`, `StoragePanel.tsx`, snapshot/recovery/pressure scripts and tests. | Implemented bounded quarantine/restore/reclaim and tested restore mechanisms. Production retention/RPO/PITR/monitoring and sustained 20-user mixed workloads on the actual 32/64 or 54/192 host remain code/configuration/measurement work. |

## Recommended milestone: proposal inbox and original plan recovery

Concrete failure trigger: the server commits `composition.propose`, but its
response is lost before `ApplicationComposer.rememberProposal` stores the ID.
The user refreshes, starts another task, clears session storage, or opens another
device. The proposal and its immutable candidate remain in `af_composition_*`,
but the available API only reads a supplied proposal ID. The browser has no
owner list from which to find it. A command key is a hash-to-UUID pointer, not a
saved goal/configuration or a list of committed results.

A second trigger occurs after acceptance: `inspect` exposes `planId`, but the
composer's recovery control calls `acceptProposal` again. Backend `accept`
returns the original plan for the original command key; a new key against an
already accepted proposal returns conflict. Losing browser storage therefore
cannot be solved by asking the user to accept the plan again.

Bounded implementation:

1. Owner-scoped stable cursor list of persisted proposals, including pending,
   revised, rejected and accepted states; explicitly mark paging rather than
   claiming a complete live snapshot. Do not expose another owner's existence.
2. Read a selected original proposal and, when accepted, its exact stored plan
   through read authority. Do not write, accept, dispatch, renew review or restore
   withdrawn material merely to display historical records.
3. A Chinese “我的装配提案” entry restores a selected proposal/plan. The user sees
   revised lineage, accepted/read-only history and current execution eligibility
   separately. Existing policy/binding checks still gate all subsequent work.
4. Preserve original owner/application/material/binding/plan hashes and link any
   creation recovery to the original request. Do not generate new request IDs to
   bypass an uncertain or already committed operation.

Suggested ownership: root owns routes/shared contracts and integration;
`composition_inbox.py` plus its tests owns read-only query/projection; a separate
UI worker owns the inbox component/state/API integration agreed with root. Reuse
`CompositionService.inspect`, existing immutable plan storage and the current
composer/review gates rather than introducing another execution service.

Acceptance: lost first reply is discoverable after restart without a new POST;
accepted original plan remains readable after storage loss and material
withdrawal; execution after withdrawal is still denied; strict owner/cursor
isolation; bounded pages have no duplicates within a fixed listing boundary;
selecting old history does not silently accept, dispatch or switch identity;
mobile/desktop browser proof with independent author/reviewer/user identities.

## Other concrete independent slices

1. **Plan review re-entry**: recover exact-plan pending/denied/expired review state
   using existing `api.planReviews(false)`, not a new review subsystem. Preserve
   the distinction between an expired decision and permission to request a new
   review. Small frontend slice; best adjacent to the proposal inbox.
2. **Approved-template application editor**: use known material slots, available
   exact versions, configured bounds and connection requirements to build a
   draft form; preserve advanced JSON and the existing independent publication
   gate. This improves manager usability without inventing departmental work.
3. **Verified-source handoff to a controlled synthesis draft**: select existing
   owner-scoped evidence, show source/hash/full-text limitations, create an
   immutable source snapshot and review it before a separate task. Reuse the
   current knowledge/synthesis contracts. This is a code workflow, while a live
   scientific provider and semantic acceptance remain separate inputs.
4. **Schedule visibility/management**: expose the already available owner-scoped
   backend list, enable/pause and occurrence history with exact-plan provenance.
   Keep single-poller deployment and existing current-authorization rechecks.

Candidate-change comparison is valuable but larger than these slices: first
specify immutable baseline/candidate inputs, approved patch scope, evaluator and
metric provenance, failure/unknown outcomes and separate human acceptance. It
must not start as an unrestricted shell/editor or as an unsupported scientific
claim.

## Evidence and scope cautions

- The checked-in reconciliation/acceptance documents mix historical milestones
  and current amendments. Code above supersedes stale statements that all remote
  compute or browser identity remain unimplemented.
- Real public retrieval, controlled-model synthesis, live Go coding development,
  process enforcement, aggregate isolation, remote attachment and machine
  provisioning are distinct claims. Completion of one does not establish another.
- This audit ran no heavy tests, model calls, network retrieval, production
  identity operation or deployment. It changed only this audit document.
