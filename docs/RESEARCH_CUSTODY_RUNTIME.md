# Research custody runtime integration handoff

Latest outcome, 2026-10-07: [first real local baseline acceptance](RESEARCH_BASELINE_ACCEPTANCE.md) records completed
local training, checkpoint, independent fixed evaluation and released custody.
The earlier stage's readiness/no-live-execution statements below are historical;
its fixtures do not become live evidence. Production, real candidate comparison
and broader target-host acceptance remain separate.

Status: implemented contract helpers and native lifecycle integration with a controlled test driver; **no live GPU driver or verified scientific result**. This document describes the current code, not completed hardware acceptance. The local combined acceptance run passed 19 PostgreSQL/native tests: ten research cases and nine existing process regressions. The research driver remains inert; no pass count establishes hardware execution.

## Implemented boundaries

`gpu_custody.py` defines frozen `GpuBinding(receiver_namespace, device_id)`. Both values are opaque 64-character hexadecimal identities. The serialized contract fixes policy to `exclusive-factory-lease`, with `quotaEnforced: false` and `deviceIsolationEnforced: false`. The identity key binds the receiver namespace and device together. It does not expose hardware identifiers.

`resources.py` uses the existing lease database and serialized admission transaction. Exclusivity concerns participating Factory allocations in that database, including configured aliases and owners. It does not establish cross-database exclusivity, exclude external GPU users, enforce VRAM quotas, or provide physical device isolation. An operator must configure a consistent identity for aliases of the same device.

A trusted provider implements `allocate_bound(lease, before_effect=...)`, `inspect`, `cancel`, and `reclaim`. Original task, owner, native run, plan, lease fingerprint and GPU binding are pinned. A provider invokes the fresh-authority callback immediately before dispatch, after any wait, and persists original custody before the effect. Reopening an allocation reads its original state; it must not launch a replacement job.

Research and ordinary processes share the reservation calculation. A declared
aggregate CPU quota is rounded up to whole reserved cores; aggregate memory plus
swap is rounded up to MiB and cannot reduce the single-process reservation.
Both target ceilings and pool capacity are checked before provider dispatch.
These admission checks do not independently enforce the declared kernel limits.

`gpuEvidence` is a strict schema-1 assertion bound by `evidence_fingerprint(lease)`. HELD and UNKNOWN retain the binding and cannot carry release proof. RELEASED requires a RECLAIMED snapshot, explicit release, matching original process binding and positive stop evidence, plus a bounded device-observation hash. The proof kind distinguishes `never-dispatched` from `original-process-stopped-and-device-released`. These hashes bind a trusted operator provider's assertion; they do not authenticate the issuer or independently prove physical GPU behavior. Shared process validation remains required alongside GPU validation.

Busy devices, lost allocation acknowledgements, disconnects, cancellation requests, timeouts and UNKNOWN observations do not free capacity. A terminal process outcome alone does not free GPU capacity. Lost release acknowledgement is reconciled through the original allocation; it is not permission to repeat dispatch. Release and successful execution remain separate facts.

## Native controller and immutable experiment selection

`ResearchProcessRuntimeService` in `research_runtime.py` extends the existing process lifecycle:

- `submit(owner, task_id)` is an internal trusted-controller operation. It requires the original persisted native external-execution pause and exact unresolved tool requirement. It uses the existing resource allocation transaction and original effect mapping.
- `inspect_task(owner, task_id)` observes the original allocation. A repeated submit returns the original lease, including reclaimed work, rather than creating another execution.
- `completion(task, requirement)` checks the original requirement version, successful process outcome, positive stop/reclaim and GPU release before producing the native custody result.
- Maintenance can observe/cancel/reclaim existing work; it cannot autonomously submit or resume a research experiment.

The existing approval action accepts or declines the completed custody receipt.
Both decisions continue the same native run with an explicit `accepted` boolean;
declining a receipt does not undo completed work or claim a scientific failure.
Stopping an unfinished experiment uses the existing cancellation action.

This integration adds no public HTTP launch endpoint, alternate queue, automatic scheduler, or retry loop. It does not grant model arguments authority to choose arbitrary commands, devices or targets.

`research_runtime_profile.py` registers governed materials. The comparison manifest is knowledge content, pinned by `comparisonManifestSha256`; the tool configuration contains only `targetRef`, `comparisonManifestSha256` and `variantSha256`. Runtime resolution verifies the selected manifest against that hash under the original plan and current authorization. `research_manifest.py` pins protocol, ordered dataset/shard identities, tokenizer, environment, device, evaluator, initial checkpoint and artifact bounds. Declared hashes are not proof that corresponding bytes were staged or executed.

The fixed training budget is 300 seconds. The manifest's distinct `totalWallSeconds` accounts for the separately bounded full job; provider wall limits must match it. Preparation, startup/compilation, warmup, training and evaluation must not be conflated. Existing short bounded-process limits are not silently widened by this contract.

## Independent evaluator custody

`research_evaluation.py` validates an evaluation contract and bounded exact JSON output. It requires training and evaluation to have the same owner but distinct original task, native run, lease and provider-job identities. It rejects malformed/duplicate/non-finite output and binds the output to the complete evaluation-contract hash. Training stdout alone cannot establish an independent score.

`ResearchEvaluationService` resolves both executions from existing original effect mappings, current immutable plans and completed/reclaimed custody. The evaluator target is selected by an operator registry keyed by the evaluator descriptor hash; its target fingerprint is pinned. The evaluator uses a different target and provider from training. The service checks custody/authorization before and after reading the original evaluator's bounded completed output.

The trusted checkpoint reader returns metadata and a streaming byte identity, not deserialized tensors or a full checkpoint buffer. The service caps verification at **2 GiB**, even if a manifest permits a larger checkpoint. It checks exact hash/length and artifact ownership plus producer provenance: `nativeRunId`, `planId`, `planFingerprint`, `leaseId`, `providerJobId` and `variantSha256`. Artifact metadata's `jobId` identifies the producer task. An injected reader is operator configuration, never a request/model callback.

Successful service verification establishes `evaluatorCustodyVerified: true`, while retaining `executionVerified: false` and `scientificConclusionVerified: false`. The runtime custody receipt similarly retains `gpuExecutionVerified: false`. This milestone neither proves that the evaluator implementation computes the intended scientific metric nor validates live GPU execution.

## Required real local adapter contract

The next adapter must supply the following evidence without weakening the existing lifecycle:

1. **Approved fixed execution and limits.** Bind the reviewed training/evaluator commands and dependencies to the original plan. Admit device and CPU/memory/storage/time budgets before work. Honor total wall time independently of the 300-second training budget; do not claim quotas that the backend cannot enforce.
2. **Verified staging.** Check actual source/variant bytes, frozen preparation/evaluation source, data shards, tokenizer and environment/kernel identities against the manifest. Keep candidate-writable source separate from trusted evaluation inputs. A hash-shaped model assertion is insufficient.
3. **Durable dispatch and stop custody.** Persist original effect identity before launch, perform fresh authority checks immediately before the effect, retain UNKNOWN after ambiguous failure, and recover without re-dispatch. Produce original process stop and device-release observations; device-idle guesses alone are not original custody proof.
4. **Checkpoint producer provenance.** Publish bounded artifacts from the original training run with the producer fields listed above and verified byte hashes/lengths. Checkpoint parsing/execution safety is separate from streaming hash verification. The contract service does not load model tensors.
5. **Independent trusted evaluation.** Use fixed reviewed evaluator source/environment and frozen evaluation data; validate the checkpoint and produce bounded exact result JSON bound to the evaluation contract. Candidate stdout, mutable candidate evaluation code and synthetic metrics must not substitute for this result.
6. **Real-target acceptance.** Demonstrate owner isolation, busy admission, lost ACK, cancellation, timeout, restart, UNKNOWN retention and positive release under the existing native task. Only then assess a same-device frozen baseline/candidate experiment. No actual training is authorized by this document.

## Controlled evidence and remaining scope

`platform/tests/research_driver_fixture.py` is deliberately inert. It persists simulated original custody in the existing allocation table and can inject lost acknowledgements and UNKNOWN stop states. Its legacy process-enforcement-shaped snapshots exist solely to exercise shared validators on synthetic targets; it starts no process, touches no GPU and demonstrates no kernel enforcement. Unit or native integration success with it must retain controlled-fixture labeling.

The research cases exercise original-run continuation after acknowledgement loss, service-object reconstruction, cancellation/timeout/revocation, UNKNOWN retention, positive release, and actual PostgreSQL checkpoint tamper detection. The over-60-second check backdates persisted native timestamps; it is not an elapsed training run. Capacity probes and ordinary maintenance routing use explicitly documented guards/spies; they do not prove another owner's native GPU execution or simultaneous ordinary process execution.

No accepted-candidate pointer mutation, automatic keep/rollback action, git mutation or autonomous experiment loop is implemented here. Advisory assessment remains separate from an approved promotion decision. A future candidate pipeline requires separate review of execution, evaluation, promotion and recovery boundaries.

## Public source and licensing boundary

The selected source is [karpathy/autoresearch](https://github.com/karpathy/autoresearch/tree/228791fb499afffb54b46200aca536f79142f117). Preserve its source provenance and outstanding notice review separately from dataset licensing.

The original [NVIDIA Nemotron-ClimbMix dataset](https://huggingface.co/datasets/nvidia/Nemotron-ClimbMix) metadata identifies **CC-BY-NC-4.0**. A shuffled mirror's MIT tag does not replace the original dataset's terms. Review applicable notices, attribution and permitted use before acquiring/staging data; do not rebundle that dataset as MIT project content. This handoff includes no dataset bytes, machine diagnostics, local configuration, credentials, host identities or user information. Real execution remains subject to authorization and readiness acceptance.
