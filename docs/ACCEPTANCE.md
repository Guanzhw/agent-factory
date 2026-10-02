# Acceptance ledger

The target is complete factory/v0.3 functionality. This is a verified stage; production/scientific acceptance remains open. Tests exercise actual Agno/PostgreSQL/FastAPI behavior; model output alone is deterministic.

| Capability | Current evidence / limits |
|---|---|
| Selected native platform | Agno 3.1.0 fixed upstream revision, eight critical installed files matched; exact native HTTP/queue/auth regression passed |
| Material library | Six kinds, immutable versions/digests, separate-admin review, archive/withdrawal, inert import and current plan/ancestor guards; 19 focused tests plus actual browser acceptance |
| Callable factory / FR16 | Approved generic application discovery, exact material alternatives, immutable propose/revise/reject/accept, specific preflight, actual native adapter dispatch and configurable exact-plan review are implemented; conservative production admin-review default, live providers not configured or exercised |
| Snapshot/durability | One registered executor, native queue recovery after hard kill; old plan preserved across newer publication; no upstream fork/nested loop |
| Second application | Actual-input checksum through same factory/executor, tested; frontend prioritizes Auto-Research |
| Identity/access | Native managed roles/directory, same-token revoke/disable, current tool checks, owner-only plan/job/artifact; production identity provisioning pending |
| Lifecycle/HITL | Native input question, exact-version confirmation, continuation, paused/run cancellation, cleanup and artifact hashes passed actual PostgreSQL API tests |
| Idempotency/effects | Identical replay reuses task; changed payload 409; unknown receipt/effect refuses blind retry/release; original-key read-only receipt and real TCP ACK-loss/restart checks passed |
| Evidence | Actual synthetic subprocess metrics/evaluator/dataset/runtime/output provenance; scientific success explicitly unverified |
| Remote resources | Persistent reference/lease service and API; actual native metadata attach, synthetic lifecycle recovery tests; trusted Factory prepare/dispatch/receipt and product routing pass controlled two-app tests; real endpoints/providers unverified |
| OpenResearch | Exact-source CLI contract adapter and real subprocess fixture tests; exact-source 0.2.13 build and actual adapter preflight passed; one bounded actual OpenAlex discovery through the pinned adapter passed; registered discovery passes controlled native integration; real integrated research and ORX experiment execution remain unverified |
| Frontend | Real backend polling, preflight/jobs/questions/approval/cancel/artifact and manager UI; browser evidence recorded separately |
| Delegation | Independent native tickets, inherited current rights, depth/count/shared durable tool budget, group state/cascade, no child-plan reuse; 13 actual PostgreSQL tests including side-effect spies |
| Schedules | One public native poller, immutable-plan/owner/occurrence admission and guarded HTTP API; 7 original plus 9 guarded hard-process/restart/takeover tests; native unconditional lease-release race remains |
| Isolation/operations | Fixed demo child containment tested; twenty-user bounded native admission and clean-stop official PG17.11 restore passed; full hostile-code tenancy, egress, PITR/RPO/RTO, monitoring and target load acceptance pending |
| Live acceptance | Requires explicit approved provider/model budget, real integrated ORX output, production OS/identity and authorized remote endpoints |

The 32-core/64-GB and 54-core/192-GB single-server profiles are capacity targets, not measured benchmarks. The initial native concurrency cap is two. Current fact/inspection calls bypass the model queue.

The mapped actual-backend contract coverage and explicit remote handoff/replay gaps are recorded in [BACKEND_CONTRACTS.md](BACKEND_CONTRACTS.md). Controlled native cancellation tests prove query-schema compatibility and cancellation intent, not external process cleanup.

## Configurable plan-review stage

See [PLAN_POLICY.md](PLAN_POLICY.md) for current native-authority checks, exact-plan review bindings, expiry/revision withdrawal, delegated approval inheritance and real owner/admin browser evidence. Production defaults conservatively to administrator review; selecting a policy does not configure a provider or bypass exact material/connection/adapter preflight.

## Remote placement and scheduler recovery stage

See [remote execution placement](REMOTE_HANDOFF.md) for actual main-wired native API
contracts and browser evidence, and [scheduling](SCHEDULING.md) for guarded process
restart checks and the remaining native unconditional-release race. Controlled
ASGI, actual loopback HTTP and real external-host execution are distinct evidence
levels. Exact-source ORX build provenance does not certify a live research flow.

Material governance, durable event replay, active-compute authority loss, capacity and clean-stop restore are documented separately in MATERIAL_GOVERNANCE.md, EVENT_REPLAY.md and OPERATIONS.md. Production scientific/external-host acceptance is still distinct from these actual native synthetic-provider checks.

The main-wired lifecycle observer has twelve actual native tests, including pre-ACK and completed-child healthy-tree regressions. It reclaims only positively stopped groups and does not impersonate revoked users; cross-replica running signals remain unverified.


## Material-driven assembly: FR / AC / AT

These public acceptance identifiers describe this implemented FR16 stage. They
do not certify all factory/v0.3 requirements or live scientific acceptance.

| Requirement | Acceptance criterion | Test evidence | Boundary |
|---|---|---|---|
| FR16 / AC16.1 | A new approved application selects an exact six-kind material closure and executes without a core application-ID branch | AT16.1: `test_new_six_kind_configuration_is_discovered_without_application_branches`; `test_new_approved_application_natural_language_to_actual_native_artifact_without_core_branch` in `test_applications_composition.py` | Deterministic approved-metadata discovery; no unrestricted model-designed application |
| FR16 / AC16.2 | Propose, revise, reject and accept retain immutable evidence; identical accept returns one plan/ticket | AT16.2: `test_semantic_keys_reject_changed_intent_and_accept_recovery_creates_one_plan`; `test_postgres_concurrent_identical_accept_single_native_ticket_and_restart_receipt` | Actual PostgreSQL/native admission, including a one-slot pool; lost-ACK/reload browser proof recorded separately |
| FR16 / AC16.3 | Only a separate current administrator publishes a shared exact definition; withdrawal denies current execution without erasing history | AT16.3: `test_publication_binds_exact_version_and_requires_separate_current_native_admin`; `test_actual_factory_restart_withdrawn_seed_keeps_history_and_blocks_current_execution` | No model publication or new production role grants |
| FR16 / AC16.4 | Exact bindings choose actual model/tool/knowledge/environment factories and recheck native identity/current authority | AT16.4: `test_concurrent_native_runs_keep_models_knowledge_and_owner_context_separate`; `test_registered_tool_material_changes_actual_native_function`; `test_selected_environment_limits_actual_fixed_process_and_retains_unknown_outcome` in `test_execution_bindings.py` | Controlled Models; fixed reviewed process, not hostile-code tenancy |
| FR16 / AC16.5 | Owner connection handles never enter prompts/public metadata; revocation, expiry, rotation and changed pins deny use | AT16.5: `test_05_expiry_recheck_and_restart_preserve_owner_reference`; `test_06_changed_revision_scope_and_handle_identity_cannot_rebind_old_reference`; `test_08_task_scope_cannot_cross_owner_task_cancel_or_terminal` in `test_connections_postgres.py` | Trusted operator registrations only; no real provider credential configured |
| FR16 / AC16.6 | Missing adapters identify only actual missing items and never invoke a fallback | AT16.6: `test_preflight_identifies_only_missing_binding_and_never_constructs_adapters`; `test_actual_production_configuration_missing_exact_model_registration_is_specific_and_never_executes` | Production-shaped generated fixture, not production access or a live provider test |
| FR16 / AC16.7 | Narrow ORX discovery uses the governed native tool path and preserves effect/artifact provenance | AT16.7: `test_approved_material_application_and_native_task_execute_discovery` in `test_orx_factory_postgres.py`; eight callable contracts in `test_orx_tools.py` | Native success uses labeled controlled transport; callable cancel/revoke/timeout checks do not certify real ORX process isolation |
| FR16 / AC16.8 | New tool contracts require explicit operator revisions and preserve legacy hashes | AT16.8: ten `test_runtime_binding_governance.py` cases; explicit adopted legacy-plan native execution in `test_applications_composition.py` | No implicit production migration or widened approval |

The React acceptance uses real loopback HTTP, generated native users/roles and
PostgreSQL: model/environment revision, blocked connection preflight, repeated
submission, lost persisted acknowledgements, owner revoke, independent review,
malformed-response recovery and mobile fit. No external provider/model request or
production grant occurs. Full-suite counts are in VERIFICATION.md.

## Governed remote bindings: FR / AC / AT

This stage preserves the original manifest while binding exact receiver-local
connections and adapters. It does not certify production identity, cross-host
isolation or live science. Default startup installs no remote configuration.

| Requirement | Acceptance criterion | Actual evidence | Boundary |
|---|---|---|---|
| Remote / AC-R1 | Legal exact owner mapping produces an immutable two-configuration proof and one receiver root ticket, with zero origin native tickets | AT-R1: `test_01_real_tcp_governed_mapping_review_single_admission_and_artifact_integrity` in `test_governed_remote_process_postgres.py` | Two OS processes, independent generated PG databases/workspaces on one loopback PG server; controlled provider |
| Remote / AC-R2 | Missing, wrong-owner, rotated and withdrawn bindings deny execution while retaining proof history | AT-R2: process cases02/03; nine `test_remote_bindings_postgres.py` cases | Exact tool material permission ceiling; explicit operator mapping only |
| Remote / AC-R3 | Complete source application versions retain their hashes and require separate receiver publication and plan approval | AT-R3: nine `test_application_snapshots.py` cases and process case01 | Trusted in-process import; no source approval or access grant copied |
| Remote / AC-R4 | Both current role withdrawals deny protected work and stop paused receiver work without a successful checksum/artifact | AT-R4: `test_04_both_current_role_revocations_stop_paused_native_work_without_checksum` | Current native managed Auth; generated fixture principals |
| Remote / AC-R5 | Origin outage denies continuation, preserves readable paused facts/capacity and recovers the original receipt after restart | AT-R5: `test_05_real_origin_process_outage_fails_closed_and_restart_reads_original_receipt` | Actual stopped/restarted origin process; unreachability is not revocation or stop proof |
| Remote / AC-R6 | Receiver children inherit narrowed exact materials/bindings; scoped cancellation preserves unrelated work | AT-R6: `test_06_descendants_inherit_mapping_narrow_scope_and_cancel_only_owned_tree` | One native ticket per child; children stay on the selected receiver |
| Remote / AC-R7 | Receiver crash after committed native dispatch reconciles one original ticket; pre-review cancel proves no dispatch | AT-R7: process cases07/08 | Actual owned worker PID hard exit/restart, same database/keys; no blind retry |
| Remote / AC-R8 | Extended ORX contract preserves legacy hashes, current authority and evidence provenance | AT-R8: four `test_remote_contracts.py` cases; process case09 | Actual native DONE effect and artifact; discovery transport explicitly controlled, no integrated ORX CLI experiment claim |
| Remote / AC-R9 | Authenticated origin checks use actual current guards; transport errors cannot leak private details or read unbounded bodies | AT-R9: fourteen `test_remote_authority.py` and eight `test_remote_target_transport.py` cases | Bounded HTTP, no ambient proxy/redirect, non-loopback HTTP rejected; production host authorization still pending |

The frontend shows the exact PREPARING receiver-review state and redacted binding
proof, resumes only the original plan/target/request key and hides native controls
until a verified receiver task exists. Exact parent-application child modes are
projected from current immutable scope. Supported browser evidence and complete
test counts are recorded in VERIFICATION.md.

## Actual Linux ORX / usage ledger: accepted bounded evidence

The earlier local WIP handoff is superseded by the cloud evidence recorded in
[VERIFICATION.md](VERIFICATION.md), [LINUX_ORX.md](LINUX_ORX.md) and
[Linux ORX evidence](evidence/linux-orx-2026-10-02.json). The pinned Linux binary
was independently reproduced; 10 actual local adapter and 6 actual native Factory
cases have separate focused evidence. Actual Factory hard interruption/restart,
original-run recovery and the seven-phase Chromium workflow were also exercised.
The usage-ledger implementation and dual-process accounting have native
PostgreSQL evidence. These are bounded local toy experiments and synthetic
provider usage, not live research or production tenancy acceptance.

At exact commit `2b738ac5377115be122e3b512992a9b2a6471860`, both push and PR CI
passed all five jobs. Each PostgreSQL run executed 387 tests, with 352 passes and
35 explicit opt-in skips. The 35 are exactly:

| Category | Count | Missing CI opt-in / boundary |
|---|---:|---|
| Actual Linux local ORX adapter | 10 | Pinned binary/source and task-owned Docker containment |
| Actual Linux ORX native Factory | 6 | Same toolchain/container plus actual PG integration opt-in |
| Actual Windows local ORX adapter | 10 | Pinned Windows binary/source and Windows containment |
| Actual Windows ORX native Factory | 6 | Windows containment, pinned toolchain and native PG opt-in |
| Exact-binary ORX preflight | 2 | Explicit binary and digest |
| Official clean PostgreSQL dump/restore | 1 | Opt-in `FACTORY_PG_BIN` tools |

A skip is neither a failure nor evidence of runtime success. The 16 Linux actual
cases have separate evidence; they do not certify the 16 Windows cases. In
particular, the historical Windows native connection-revocation acceptance was
not passed and remains unverified on Windows. Cross-platform static/unit CI does
not replace that runtime acceptance. The clean-stop dump/restore case has separate
local evidence; it is not live-write recovery acceptance.

[The original cloud handoff](CLOUD_HANDOFF.md) is preserved as a superseded
historical checkpoint. Durable control-command receipts/recovery are described in
[CONTROL_COMMANDS.md](CONTROL_COMMANDS.md), with native/remote fault tests, actual
service exits, four Chromium restart/identity cases and actual Linux ORX
approval/cancel receipt recovery. Final CI for this milestone is tracked in the
draft PR; the exact-head counts above describe the earlier completed checkpoint. Disk admission/retention/monitoring, fair-load acceptance,
live-write restore and remote actual ORX remain separate pending work.
