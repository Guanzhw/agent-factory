# AT10: bounded inference recovery for existing external work

The public AT10 requirement is that a temporary inference outage must not
implicitly terminate an independently approved, lawful deterministic experiment.
The accepted standalone checkpoint is `4e1f29900080ad6004fd33f55580b9fe5ea75c37`.
The current extension implements original-owner Linux ORX revision-2 recovery
across delegated and receiver-owned work. Its actual acceptance is tracked in
[CLOUD_TASK_BOARD.md](CLOUD_TASK_BOARD.md); implementation and unit coverage do
not establish every distributed fault combination. Providers, Windows and
mutable research workloads remain outside this evidence.

## Native lifecycle decision

Agno 3.1.0's public background continuation route sends a paused run through its
existing durable queue ticket. Continuing a failed run does not use that same
paused-ticket route. Factory therefore does **not** rewrite native failed rows,
requeue dead letters as an owner, create a replacement run, or run a second loop.

At the registered model response boundary, an exact `ModelProviderError` with
status 408, 500, 502, 503 or 504 can become a native external-execution requirement
named `factory_resume_inference`. It is explicitly Factory control metadata,
not provider output, an executable catalog tool or a claim of research success.
The provider transcript and original run identity remain native-owned. Both
streaming and non-streaming response paths retain native requirement semantics.

Before exposing the requirement, Factory persists the task/owner/plan/native-run,
acknowledged ORX run, original effect fingerprint, control ID, failure count and
absolute deadline in `af_inference_waits`. It rechecks current authorization,
plan/material/connection bindings, original source and actual kernel evidence.
An absent or UNKNOWN launch acknowledgement never qualifies. Revision 1 and non-Linux plans keep their existing fail-closed behavior.
Delegated work records its root native owner, ancestor chain and original child
plan/native/ORX/effect identities. Received work also records its original
receiver receipt and requires current source authority at each observation.

The original wait deadline is at most 30 seconds, bounded by the admitted
experiment environment; a second failure cannot renew it. At most two inference
waits are allowed for that task. This is an intentionally short fixed-toy profile,
not a general production outage/retry policy. The original evaluator's own
5–30-second execution limit and selected CPU/memory/PID/output limits are not
extended. The local reviewed long-running evaluator finishes within 20 seconds.

## Resume and stop rules

The Chinese UI distinguishes **恢复本次推理** from approving a new experiment.
The existing durable approval command pins the exact native requirement and
version. Only one dispatch CAS can continue it; duplicate decisions reconcile
the original receipt. A changed/stale requirement, fabricated tool result or
changed owner/run is rejected. The continuation uses the same run and queue
row. It supplies a fixed control acknowledgement, never arbitrary tool output,
source, command, credentials, budget or provider selection.

A successful provider invocation marks recovery. Every invocation still passes
the existing usage reservation and current-authority guard, including retries.
Unknown usage retains its entire hold; recovery neither refunds it nor assumes
that a failed provider request was free. Over-budget authoritative accounting
requires stop. Exhausted remaining headroom cannot admit another invocation.
There are no automatic network probes or model retries from the observer.

While waiting (and until the first recovered invocation), the existing lifecycle
observer reads the same immutable ORX binding, original upstream-owned SQLite
run and kernel process evidence. It never creates a project/container, launches,
wakes or replaces a run. A successful external result can be persisted while
inference remains paused. The observer has its existing bounded batch/rotation;
500 ms is a polling interval, not a production hard-latency guarantee.

Current authority/connection/material loss, cancellation, rejection of recovery,
source or identity drift, actual budget overrun, deadline expiry, protected tool
failure and nonqualifying native failures still trigger original scoped cleanup.
429 is deliberately excluded because it can mean quota exhaustion, as are
401/403, context errors, arbitrary exceptions and unknown error classifications.
The original `native-failure → cleanup` rule remains intact: qualifying temporary
failures are intercepted before they become native terminal failures.

Source corruption cannot be converted to a successful result. If the exact
original tree is positively stopped but source/result reconciliation fails,
`orx_cleanup_source_unverified` retains kernel evidence and the unresolved effect
keeps its capacity hold. This means no live process is silently retained, but an
operator must resolve the original UNKNOWN record before its slot is released.

## Delegation, receiver and completed-result boundaries

The pause owner may be a child or the parent whose inference failed after an
independently approved child launched. Observation never approves a child,
transfers ownership, replaces a native ticket or grants another launch. Active
children must retain inherited current authority. A completed child can supply
read-only evidence only after its original external run is terminal and positive
kernel `allStopped` evidence is present; native completion alone is insufficient.

Receiver observations validate the entire immutable tool/capability intersection,
original grant and current source account budget. Actual tool invocations still
perform their named authorization check. No source proof is cached across
observations. Source cancellation, revocation, unavailability or overrun denies
continued recovery; unresolved usage and grants remain held.

If Agno exposes an original launch confirmation after a hard restart, an already
acknowledged approval is not dispatched again. A separate `resume_approved`
command verifies the original approval and stopped DONE effect, then uses the
public native queue-only continuation path on that same ticket. It permits at
most one recovery intent per original approval. See the exact boundary and
current actual evidence in [AT10_TREE_ACCEPTANCE.md](AT10_TREE_ACCEPTANCE.md).

After a terminal result has been persisted, stale native tool transcripts may
still ask to run, wait or read logs. The completed revision-2 Linux path validates
current tool authority, original source/native/ORX/effect identity and kernel stop
evidence before returning that same result. It does not run preflight/CLI, create
or wake a namespace, or extend a deadline. Logs come from the original bounded
regular file; symlinks and nonregular files are rejected.

## Verification and reproduction

Use the existing isolated PostgreSQL fixture and approved Linux toolchain from
[Linux ORX](LINUX_ORX.md). No paid provider, external request or real credential is
needed. Test-only faults use a deterministic local model; the ORX executable,
commands, evaluator, run rows, process bounds and metrics are actual.

```sh
PYTHONPATH=platform:platform/tests .venv/bin/python -m unittest test_inference_wait -v
# Requires the explicitly configured isolated PostgreSQL and approved ORX tools:
FACTORY_ORX_LINUX_CONTAINER=1 PYTHONPATH=platform:platform/tests \
  .venv/bin/python -m unittest test_actual_inference_wait -v
```

The actual suite covers one launch, continued external work during the outage,
background completion, repeated recovery decisions, original-run continuation,
a separately owned Factory process killed while paused and restarted against
its existing database, user cancellation, declined recovery, connection
revocation, timeout, authoritative budget overrun and source drift. Optional
`FACTORY_AT10_EVIDENCE_DIR` writes only synthetic acceptance receipts. CI without
the pinned local runtime explicitly skips these actual-runtime cases; it does
not substitute their unit tests for live evidence. Final measured results are
recorded in the PR and verification ledger.

## Work remaining

Independently implementable follow-ups include extending the recovery protocol
to Windows, completing the delegated/receiver actual acceptance matrix,
production provider usage/retry conformance, richer recovery telemetry and governed mutable
workspace/version/evaluator contracts. They require code and acceptance work;
credentials alone cannot complete them.

User decisions still govern the real inference provider/model and spending
limits, production identity/session policy, the first non-toy research workload
and its data/source rules, and authorized production hosts/TLS/capacity tests.
This stage selects none of those suppliers or permissions and does not establish
complete project or production acceptance.
