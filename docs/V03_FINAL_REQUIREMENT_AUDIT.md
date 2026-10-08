# v0.3 final requirement audit

## Subsequent evidence — 2026-10-07

The [first real local baseline acceptance](RESEARCH_BASELINE_ACCEPTANCE.md) supersedes this October 4 audit's broad
claim that a selected non-toy adapter and all actual experiment execution are
still missing: the pinned local baseline, independent evaluation and release
have now completed. This does not close production scientific-provider work,
real candidate comparison or the external acceptance rows. The original audit
below remains a dated source review, not a fresh audit of all later code.

Read-only source audit on 2026-10-04, starting from checked-out `e0f74ec` and
concurrent schedule-diagnostics work. This report adds no requirements and makes
no new runtime acceptance claim. Existing tests were inspected, not rerun by this
auditor. The unavailable private design packages cannot be certified from this
public repository. Exact-head CI and final diagnostic execution evidence remain
with the coordinator and independent runtime reviewer.

## Current finding and acceptance boundary

Owner-visible pre-occurrence schedule refusal diagnostics now have actual PostgreSQL
and desktop/mobile acceptance. A subsequent launcher audit identified a separate
delivery gap: source/synthesis/comparison workflows were previously assembled by
test constructors rather than an explicit runnable development profile. That profile
and governed bootstrap are now implemented and have actual PostgreSQL/native and
shipped-CLI HTTPS startup/restart acceptance. No further mandatory user flow was identified within the
explicitly agreed bounded development scope. This is a scoped conclusion, not a
claim that all production code or scientific integration is finished. In particular,
a selected production scientific provider adapter and a non-toy experiment adapter
are still code work dependent on external specifications; they must not be relabelled
as merely supplying credentials or running deployment tests.

Diagnostics evidence reported by the coordinator covers nine PostgreSQL cases: an
eight-case passing batch (25.266 seconds) plus the corrected read-only-role fixture
case (2.500 seconds); an earlier six-case batch passed in 16.449 seconds and is not
counted again. An executor-read-only role can read diagnostics (200) but cannot edit
schedules (403); removing read permission denies the diagnostic read (403). Tests
also cover pending-fence reads without repair, zero SQL writes and scoped cursors.

Actual mock-HTTPS desktop/mobile browser acceptance covers four controlled native
refusals, retained IDs across reload and Bob ownership denial (404), with zero task,
occurrence and native-run creations. Evidence is recorded at
`/workspace/scratch/schedule-diagnostics-20261004/browser-v3/evidence.json`. The
independent reviewer cleared the code, eight frontend tests and four screenshots.
This auditor did not rerun those tests. Final full-suite and exact-head CI acceptance are still pending; they are not
inferred from these targeted diagnostic or startup tests.

The coordinator reported the new profile's actual mock-login/CSRF native flow: source
→ immutable snapshot → controlled synthesis, plus controlled comparison, with three
native jobs, separate plan review, verified artifacts, Bob denial and restart without
redispatch. The corrected native case passed in 25.051 seconds. The separate bootstrap
replay/revoked-connection/native-Bob-role case passed in the initial two-case batch;
that batch also contained a native-flow authentication fixture failure and must not
be described as an entirely passing suite. Its failed native case was subsequently
revalidated by the passing corrected run.

This auditor read `profile-pg.log`, `profile-native-pg-v2.log` and
`launcher-smoke-evidence.json` under
`/workspace/scratch/development-handoff-20261005/`. The shipped CLI was exercised
first with controlled-workflows initialization and then against the same database
and workspace without initialization. Both starts report HTTPS health/HTML 200,
actual Chromium Alice mock login and exit code zero. All three approved application
IDs, versions and hashes match across restart. The coordinator additionally reports
auth-config 200 and complete fixture cleanup; those two facts are not explicit fields
in the inspected launcher JSON. No real provider or organization IdP was involved.

## User journeys checked against implementation

| Agreed journey | Actual implementation inspected | Executable evidence inspected / boundary |
| --- | --- | --- |
| Author six kinds of reusable material; publish through another current administrator; withdraw while preserving history | `material_governance.py`, `MaterialGovernance.tsx`; exact-version governance and inert descriptors rather than code installation | `test_material_governance.py`; current publication authority and immutable material closure are distinct from a live adapter |
| Clone/revise approved application templates; select exact materials and existing slots | `ApplicationTemplateEditor.tsx`, `applicationTemplateState.ts`, `MaterialPicker.tsx`, `applications.py`, `ApplicationGovernance.tsx` | `test_material_template_journey_postgres.py::test_copied_six_kind_template_publication_plan_review_native_artifact_and_withdrawal`; separate reviewer/pin regression. Unknown fields remain advanced-only; no arbitrary capability creation |
| Describe a goal, obtain/revise/reject a bounded proposal, accept its immutable plan | `composition.py::propose/revise/reject/accept`, `ApplicationComposer.tsx` | `test_applications_composition.py`, `test_application_closure_authority.py`; FR16 discovers among approved metadata, not autonomous installation/publication |
| Recover lost proposal or acceptance reply, clear browser storage, revisit denied/pending review | `composition_inbox.py`, `CompositionInbox.tsx`, `planReviewState.ts`, `PlanReviews.tsx` | `test_composition_inbox_postgres.py`, `tests/composition-inbox.test.ts`, `tests/plan-review-recovery.test.ts`; original-plan read recovery does not renew execution authority |
| Independently approve a plan, create one native task, answer/approve/reject/cancel, recover interruption | `factory_api.py` `/instances` and `/requests/{requestId}`, `native_bridge.py`, `control_commands.py`, `ControlRecovery.tsx`, `ApprovedRecovery.tsx` | `test_control_commands.py`, process/remote variants, `test_approved_recovery.py`, `test_actual_inference_tree.py`; UNKNOWN never grants a new submission key or effect replay |
| Delegate within ancestry and shared budgets; cancel the original tree | `delegation.py`, current native guards and lifecycle observer | Delegation/AT10/native receiver tests. Root-only bounded process/comparison profiles intentionally do not enable delegation |
| Retrieve/read/download literature with provenance, missing text and failure states | `pubmed_retrieval.py`, `literature_evidence.py`, `LiteratureEvidence.tsx`, owner artifact routes | Literature/PubMed projection and native PG tests. Actual public abstracts and controlled fixtures remain distinct; full-text access and scientific validity are not inferred |
| Select verified sources, fix question/source snapshot, review and execute controlled synthesis | `synthesis_sources.py`, `synthesis_api.py`, `synthesis_runtime.py`, `SynthesisJourney.tsx`, `SynthesisReport.tsx` | `test_synthesis_journey_postgres.py`: stale/missing/cross-owner source, original-plan restart, actual native report and revocation/cancel at model boundary. This is a controlled scientific-model fixture |
| Review finite candidate changes and evaluate baseline/candidate under one fixed contract | `comparison_contract.py`, `comparison_fixture.py`, `comparison_profile.py`, `comparison_workflow.py`, `ComparisonPanel.tsx` | `test_comparison_workflow_postgres.py`: successful original identity/artifacts, failed candidate inconclusive, cancellation, prelaunch and presave revocation, lost ACK and UNKNOWN. One paired process, not two invented orchestration chains; metrics do not establish scientific validity |
| Create/edit/pause/resume schedules and inspect original occurrences | `schedule_management.py`, `scheduling.py`, `scheduling_api.py`, `schedule_contract.py`, `SchedulesPanel.tsx` | `test_schedule_management_postgres.py`: committed ACK loss, revision CAS, stale claim, unknown admission and cancellation during pending edits; `test_schedule_contract.py` compares actual native clock/DST. Pre-occurrence refusal visibility now has nine actual PG cases and desktop/mobile refusal acceptance; final exact-head CI remains pending |
| Attach an existing receiver, preserve original task/runtime identities, inspect/cancel owned resource leases | `remote_handoff.py`, `remote_bindings.py`, `remote_authority.py`, `resources.py`, `process_runtime.py`, `ConnectionsPanel.tsx` | Governed remote process/HTTP/PG and shared-lease tests. Separate local processes do not certify separate physical hosts. Machine provisioning is not required to attach an existing receiver |
| Login/logout, switch roles, retain owner isolation and current revocation | `browser_auth.py`, `development_identity.py`, `oidc_identity.py`, `browserAuth.ts`, `App.tsx` | Browser OIDC and production-mode identity PG tests, development HTTPS browser scripts. The real organization IdP remains unselected/unaccepted |
| Inspect usage, ambiguous cost and storage custody; reclaim only verified resources | `usage_ledger.py`, `UsageLedger.tsx`, `storage_governance.py`, `StoragePanel.tsx`, process/aggregate custody | Usage and storage/runtime tests. Nominal reservation accounting is not an invoice; quarantined/unknown resources are not silently released |

`App.tsx` mounts the proposal, synthesis, comparison, resource and scheduling
surfaces; these are not merely unused helper modules. The cited PG test bodies
exercise existing native services rather than replace task execution with a
reference server. Their historical run results still require the relevant stage's
acceptance record; this audit has not independently executed them again.

## Remaining classification

| Class | Remaining requirement / boundary | Closure condition |
| --- | --- | --- |
| Implemented; exact-head acceptance pending | Safe owner-visible schedule refusals before an occurrence is persisted | Nine actual PG cases plus desktop/mobile controlled refusal acceptance and independent review completed as recorded above; final exact-head CI remains pending |
| Implemented; targeted runtime acceptance passed | Explicit runnable controlled-workflows profile and governed bootstrap for source, synthesis and comparison | Corrected native PG flow plus bootstrap/revocation case and shipped-CLI initial/restart HTTPS smoke passed as recorded above; exact application pins survive restart. The basic default remains unchanged; final full-suite/exact-head CI remains pending |
| Selected-provider CODE plus external input | Production scientific model/SDK, authoritative usage/retry/pricing/input contract and governed model binding | Obtain the selected provider specification and allowed use; implement and test that adapter. Existing Go coding authorization cannot supply scientific-use authorization |
| Selected-research CODE plus external input | Non-toy dataset/evaluator/workspace and allowed-change adapter | Obtain question, source/data licences, dataset and evaluator versions, baseline/metric/change scope and reviewer; verify real bytes and execute through existing governance/custody. The finite comparison fixture closes only its declared scope |
| External identity/deployment validation | Organization IdP/TLS, subject/owner/reviewer mapping, revocation and real receiver transport | Authorized real configuration and separate-host acceptance, with no synthetic-identity substitution |
| External Linux enforcement validation | Delegated cgroup controllers, original boot/inode custody, aggregate pressure, descendants and stop/release | Target-host execution evidence. Existing fake filesystem/contracts cannot prove kernel enforcement; the current read-only mount cannot provide this evidence |
| External operational inputs and measurements | Approximately 20 department users on 32-core/64-GB or 54-core/192-GB host, actual workload/disk limits, monitoring and backup/restore objectives | Choose workload and RPO/RTO/PITR/retention/monitoring requirements, then measure/deploy/rehearse. Current bounded load and snapshot tooling are not target-capacity certification |

## Deliberately excluded from an automatic closure backlog

- Machine/cloud provisioning is optional; existing receiver attachment is already
  implemented and does not depend on it.
- Multi-poller conditional native lease release is a known topology limitation.
  Supported deployment has one active scheduler process; no cluster was promised.
- Per-schedule no-overlap, cumulative daily/monthly spending, deletion, catalog
  quotas and retention extensions require an explicit product policy selection.
  Existing owner/global active limits and per-plan usage budgets remain enforced.
- Arbitrary code generation/execution, autonomous installer/publication,
  hostile-code tenancy and network/disk isolation are not inferred from bounded
  approved-material composition or fixed-program process execution.
- A new universal command journal is not required just because an older document
  calls it pending. Current proposal, review, control, schedule and source flows
  have domain-specific durable identity and owner recovery. Any uncovered concrete
  mutation-loss scenario must be demonstrated before introducing another journal.

## Documentation reconciliation

`V03_APP_GAP_AUDIT.md` explicitly retains the PR28 baseline table. Its old proposal,
guided editing, review-reentry, synthesis and scheduling UI gaps are closed by later
code and tests; they are not current blockers. `MATERIAL_ASSEMBLY.md` and portions
of `BACKEND_CONTRACTS.md` also describe earlier adapter/stage limits. Conversely,
`ACCEPTANCE.md` correctly keeps production scientific-provider integration as code
work rather than implying that a credential alone completes it.

The closure map is useful only when read with these scope boundaries: “development
workflow complete” must not become “all production code complete” or “scientifically
validated.” Schedule-diagnostics actual tests and independent review are now recorded above;
final full-suite and exact-head CI remain pending. With the runnable-profile targeted
evidence recorded, no remaining selected bounded-development CODE blocker was found.
This conclusion is conditional on final checks passing and retains both
input-dependent production/research CODE rows above.
