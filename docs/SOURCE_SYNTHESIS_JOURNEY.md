# Verified source to controlled synthesis

Historical milestone: the demo-mode configuration, synthetic login and runner
entrypoints below are retired. They are retained to explain the original
acceptance results, not as current startup instructions. Current application
registration and identity requirements are in
[application development](APPLICATION_DEVELOPMENT.md) and [security](SECURITY.md).

This milestone extends the existing AutoResearch journey from an owner's completed,
verified literature task to an immutable source snapshot, a member-submitted plan,
one native execution, and downloadable JSON/Markdown output. It builds on
accepted draft PR30 (`d4f5e6c0f64cc49e44561629ba6dc1e909661387`).

## Implemented boundary

1. The completed task shows its original provenance and limitations. The owner
   selects one to three supported source records and supplies a bounded question.
2. The server verifies original native completion, plan pins and artifact bytes,
   then stores an immutable owner-scoped snapshot. Client text is never evidence.
   Snapshot history and command receipts permit recovery after a lost response.
3. The snapshot seeds the existing application composer. Its question and exact
   snapshot reference are pinned into the proposal, binding manifest and plan.
   Members publish the synthesis application and submit their own ready plan
   through the existing native task admission API.
4. Installed adapters resolve the plan snapshot at execution. Current source
   access, integrity and plan authority are rechecked before and after inference
   and at report effect boundaries. Cancellation or connection revocation after
   inference cannot publish a report; observed model usage is still settled.
5. The task shows structurally checked claims, source IDs, verbatim quote anchors
   and limitations. Existing verified artifact download serves JSON and Markdown.
   Historical output can remain readable when a source later changes; the separate
   `sourceCurrent` state reports that change rather than erasing history.

The feature is disabled by default. Enabling `FACTORY_SOURCE_SYNTHESIS_ENABLED=true`
requires explicit demo mode; both plan and publication settings remain
`member-self-service`. It registers the installed synthesis adapters. Members
publish the required materials/application and bind their own connections.
The flag is part of runtime configuration. Remote handoff and delegation are
rejected for this bounded source-snapshot runtime.

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
research evidence. Current membership, source integrity, synthesis plan readiness
and available application/resources remain required. Unknown report effects are
not replayed as if they had failed.

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

Dataset-bound comparison needs its own dataset, evaluator, bounded change,
original native execution and result lineage. A source-synthesis report alone
does not establish those facts. Scheduling behavior and current limitations are
documented in [SCHEDULING.md](SCHEDULING.md).
