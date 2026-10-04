# Verified source to controlled synthesis

This milestone extends the existing AutoResearch journey from an owner's completed,
verified literature task to an immutable source snapshot, an independently reviewed
plan, one native execution, and downloadable JSON/Markdown output. It builds on
accepted draft PR30 (`d4f5e6c0f64cc49e44561629ba6dc1e909661387`).

## Implemented boundary

1. The completed task shows its original provenance and limitations. The owner
   selects one to three supported source records and supplies a bounded question.
2. The server verifies original native completion, plan pins and artifact bytes,
   then stores an immutable owner-scoped snapshot. Client text is never evidence.
   Snapshot history and command receipts permit recovery after a lost response.
3. The snapshot seeds the existing application composer. Its question and exact
   snapshot reference are pinned into the proposal, binding manifest and plan.
   Existing application publication, independent temporary-plan approval and
   native task admission remain authoritative; there is no new execution API.
4. Static approved adapters resolve the plan snapshot at execution. Current source
   access, integrity and plan authority are rechecked before and after inference
   and at report effect boundaries. Cancellation or connection revocation after
   inference cannot publish a report; observed model usage is still settled.
5. The task shows structurally checked claims, source IDs, verbatim quote anchors
   and limitations. Existing verified artifact download serves JSON and Markdown.
   Historical output can remain readable when a source later changes; the separate
   `sourceCurrent` state reports that change rather than erasing history.

The feature is disabled by default. Enabling `FACTORY_SOURCE_SYNTHESIS_ENABLED=true`
requires explicit demo mode and `admin-review` temporary-plan policy. It registers
adapters, not published materials, applications, user connections or permissions.
Managers still use the existing separate publication review. Disabling the flag
preserves existing policy fingerprints. Remote handoff and delegation are rejected
for this bounded source-snapshot runtime.

## Recovery and failure handling

Snapshot POST receipts are validated against the original question, selection and
source fingerprint. Unknown acknowledgement locks the current form, first attempts
owner-scoped history reads, and preserves an opaque command pointer for refresh.
Without the original payload after reload, recovery performs reads only. Proposal
creation uses the original payload and request key for an explicit same-form retry;
owner proposal history provides original-plan recovery after refresh. These are
current-form guards, not a claim of a global lock across newly selected workflows.
Double clicks do not dispatch a second mutation. Malformed, missing, changed,
stale or cross-owner evidence fails closed. Unsupported source-context bounds are
rejected explicitly, never silently truncated or reclassified.

Original source application withdrawal does not erase already verified historical
research evidence. Current read authority, source integrity and the new synthesis
application/plan permissions are still required. Unknown report effects are not
replayed as if they had failed.

## Evidence and limits

Repository tests include `test_synthesis_sources.py`, `test_synthesis_runtime.py`,
`test_synthesis_configuration.py` and `test_synthesis_journey_postgres.py`;
frontend receipt/state coverage is in
`tests/synthesis-journey.test.ts` and `tests/source-plan.test.ts`. The browser runner
`scripts/accept_synthesis_journey_browser.py` exercises the actual mock HTTPS login,
PostgreSQL/native services and desktop/mobile UI. Exact-head acceptance results
belong to this milestone's draft PR and the task board. Local final browser
acceptance passed both desktop and mobile with one snapshot POST, one source task
and one synthesis task per viewport, original-receipt recovery, verified downloads,
cross-owner denial, no page/unexpected console errors and no horizontal overflow.
All temporary browser services and fixtures were cleaned.

All new scientific output uses the explicitly labelled controlled fixture model.
Source fixtures are synthetic or controlled transport fixtures; no new live public
retrieval or scientific-model compatibility is claimed. Citation structure and
artifact integrity do not verify scientific conclusions; domain review is required.
Production IdP, a real scientific provider, licensed full text, target-host isolation
and sustained target-capacity acceptance remain separate missing inputs/validation.

A complete baseline/candidate change-evaluation workflow remains code work: it
needs an explicit dataset, evaluator, approved change and persisted native review
contract. A pure comparison validator would not close that workflow. Schedule
management UI and scheduler replica safety also remain subsequent work. This
milestone adds no production recurring jobs, provisioning, merge or deployment.
