# Original research custody recovery

## Latest reported state — 2026-10-07

A subsequent authorized read-only target check reported the original Factory
lease and provider allocation as `RECLAIMED`, `capacityHeld: false`,
`released: true`, `allStopped: true`, with GPU `RELEASED` / `never-dispatched`
proof. Original mapping, binding hash and database identity checks passed.
`cancelAck` and `releaseAck` remain `unknown`; neither was reset or replayed.
A later target read reports original terminal task/cancelled ticket and consistent
plan/native/mapping/ledger, but descendants remain NOT_CHECKED. Empty training
output and absent run-config/seal/train/eval receipts agree with never-dispatched.
The PR52 strict audit was not run because separate historical configuration pins
were not retained. These are target reports, not cloud execution evidence.

The strict full-configuration reconstruction prerequisite was overbroad for this
release question. The revised [handoff](PR50_RELEASED_CUSTODY_HANDOFF.md) supplies
an explicit minimal release mode using original persisted plan, binding, journal
identity and positive stop/compute/GPU receipts, plus an executable root-only queue
check. It does not require artifacts from stages that never occurred or relabel
current metadata as independently retained history. Full forensic validation
remains optional and is explicitly not claimed by the minimal mode.

Positive persisted release can coexist with unknown transport acknowledgements.
After these release and queue checks pass, no repeated release, ACK reset or old
service reconstruction is needed. Preserve the failed attempt and all artifacts;
continue with a separate installation and attempt under existing authorization.
Actual missing or mismatched stop/release proofs remain UNKNOWN, never fabricated.

## Earlier missing-receipt recovery procedure

The following procedure applies when release is genuinely missing or requires
the existing mutation/reconciliation path. It does not require replay after
already-persisted release has been independently validated.

This is a stop-only recovery runbook, not authorization to launch another
experiment. The reported observation is an original journal with `CANCELLED`,
`never-dispatched`, `stoppedProof: true` and `capacityHeld: false`, while the
corresponding Factory `RECLAIMED` and GPU `RELEASED` confirmations remain absent
or unknown. Those are different layers of evidence. This document does not
claim the target has been repaired or identify the cause of the missing release.

## Preserve the original attempt

Keep the original database, configuration, workspace, journal, environment
inventory, interpreter contract and receipts. Do not delete newly observed
bytecode files to make old namespace pins pass, regenerate the old contract,
reset `cancelAck` or `releaseAck`, or manually update allocation/lease states.
Do not submit another task or allocate another GPU lease until the original
capacity and GPU release have been positively confirmed.

Use the existing authorized database configuration locally. Do not print,
export or request its DSN, password, tokens or environment. No new credential,
role, database or executor is needed for this investigation. Do not start a new
application lifespan, queue or training process merely to inspect custody.

## Read-only evidence checklist

An operator with existing access should read the original records, not select a
replacement by most-recent timestamp. Collect a small private evidence record
with these fields. Keep identifiers local; a public summary can report equality
booleans and finite states instead of raw identifiers or paths.

| Layer | Required observations |
| --- | --- |
| Original task and mapping | Task/owner/plan/native-run/lease identities; `af_process_runs.effect_key`; mapping equality with the original request and lease; task terminal/cancel flags and original native ticket status. |
| Factory lease | `state`, `capacityHeld`, `cancelAck`, `releaseAck`, `cancellationReason` if present, `providerJobId`, process binding, `stopEvidence`, `gpuEvidence.state` and release-proof kind. Record missing separately from `unknown`. |
| Provider allocation | `state`, `released`, `allStopped`, `executionStatus`, `exitCode`, `stopKind`, `processPin`, `directoryIdentity`, `journalIdentity`; configuration fingerprint and binding-hash equality booleans against the original configured provider and lease. |
| Original journal | Journal ID, identity/spec hash equality booleans, original directory/file identity match, same-boot match, owner/task/request match, `state`, `cancelRequested`, `stoppedProof`, `capacityHeld`, guardian/child presence, and stop-receipt kind. Use the existing adapter validation, not just unvalidated JSON fields. |
| Diagnostics | Any existing finite `preDispatchFailure` phase/code, original journal identity match and `dispatchAttempted` value. Allocation acknowledgement is not process-spawn proof. Do not collect exception messages, arbitrary provider output or configuration bodies. |
| Environment change | For each of the three reported new `.pyc` files: relative path within the installation, whether it was absent from the sealed inventory, regular-file/symlink classification, and mtime-change/after-capture booleans. Keep absolute paths and exact timestamps private. Do not infer the writer or execution from mtime alone. |

Also establish whether the **original configured runtime/app service object is
still available**. If reconstruction is required, identify its original source
revision, immutable plan, registered target reference, original launch spec and
interpreter-contract bytes, limits, provider root identity, pool/GPU binding,
driver/observer policy fingerprints and existing database configuration source.
Report exact equality with stored pins. Do not silently reconstruct using a
freshly captured environment or a different provider configuration.

New bytecode can invalidate the sealed namespace for future admission. That
fact alone does not explain a cleanup failure: the original journal read,
process stop validation and the never-dispatched release branch do not run the
environment observer again. Distinguish a failure to reconstruct the original
service from a failure inside an already available cleanup service.

## Use the existing stop-only path

1. Through the verified original runtime, inspect the original lease/provider
   and validate the full identity chain above. Reading a journal directly is
   useful evidence but does not update Factory accounting.
2. The internal `ResearchProcessRuntimeService` inherits
   `ProcessRuntimeService.observe_lease(original_lease_id)`. This path reads,
   stops and reclaims original custody; it never submits or launches a job.
   It checks original task/run/plan/provider bindings. It may request normal
   cancellation when the original task, authority or fixed deadline requires
   it. Use this existing service only after its original configuration is
   verified; this runbook does not provide a new unauthenticated endpoint.
3. If a release acknowledgement was lost, first inspect the original provider.
   A committed provider release can be reconciled without repeating reclaim.
   The ordinary `resources.reconcile(owner, original_lease_id)` route requires
   current authorization; the internal runtime read path uses its existing
   original-custody checks. Do not weaken either check to force reconciliation.
4. If the provider still reports unreleased capacity and `releaseAck` is
   `unknown`, the existing runtime deliberately does not repeat that uncertain
   effect. Preserve the hold and identify the exact failed boundary: original
   service reconstruction, provider record load, journal/stop validation,
   provider release, persistence, or final resource projection. Recovery beyond
   inspection needs a reviewed operation on that same original custody; an ACK
   reset or a new request ID is not such an operation.

For a valid original never-dispatched receipt,
`ResearchLocalProvider._before_release` derives its release observation from
the original process pin, stop receipt and lease binding. It does not require a
new GPU probe: the validated receipt proves that this attempt never dispatched.
This is not a claim that the physical device is globally idle. For a dispatched
process, the distinct original-process/device-release checks still apply.

The journal's `capacityHeld: false` is not sufficient to bypass those provider
and resource transitions. Do not fabricate their receipts from journal fields.
Likewise, a provider acknowledgement alone is not final release confirmation.

## Completion and stopping conditions

Recovery is confirmed only when a fresh validated original-provider snapshot
has `released: true`, `state: RECLAIMED`, matching positive stop evidence and
GPU `RELEASED` proof, and normal resource reconciliation has persisted the same
original lease as `RECLAIMED` with `capacityHeld: false`. Re-read the original
mapping and identities to ensure no replacement task, lease or job was created.
Checkpoint/storage reservations, if any, have their own retention accounting;
compute release does not assert that all storage holds are gone.

If the original runtime cannot be reconstructed with matching configuration,
or any original identity/stop proof is unverifiable, report that precise
boundary and retain the hold. There is no safe generic shell command that can
replace missing original service configuration. Preserve the evidence and do
not start the next attempt. This is an evidence requirement for the authorized
recovery, not a request for new credentials or additional user approval.

## Code references

- [Original process inspection and never-dispatched stop proof](../platform/agent_factory/process_enforcement.py)
- [Provider identity checks, inspection and reclaim](../platform/agent_factory/process_provider.py)
- [Research GPU release branch](../platform/agent_factory/research_local_provider.py)
- [Original-custody observation and unknown-ACK handling](../platform/agent_factory/process_runtime.py)
- [Validated lease reconciliation](../platform/agent_factory/resources.py)
- [GPU release evidence contract](../platform/agent_factory/gpu_custody.py)
