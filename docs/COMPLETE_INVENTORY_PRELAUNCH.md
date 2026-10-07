# Complete inventory and prelaunch evidence

This stage follows PR49 `fdbc109a6ca59f10b9e985c18890cea6a958ea38`.
The target worker reported24204 sealed files and a PREPARED custody journal,
without guardian/child launch evidence, training configuration or evaluation.
Training had not started. `PROCESS_SUBMITTED` acknowledges allocation and does
not prove spawn; controller progress now carries that explicit meaning.
The observer's former16384-observation ceiling is a confirmed static
compatibility defect. The original swallowed exception was not recovered, so
this defect is **not asserted to be the sole cause of the target attempt**.

## Bounded full coverage

The existing complete profile remains `complete-venv-32768-v1`:
32768 files,65536 filesystem entries,1GiB/file,8GiB aggregate package bytes.
The observer retains one observation per exact path, verifies repeated identity,
type and stamp against the first observation, and rejects any change. Every
content hash and final unique-path descriptor reopen remains in place. No
inventory rows are sampled, truncated or omitted. Complete observation storage
is capped at65536+16: site files/directories plus fixed external document,
project, cache, venv config and stdlib roots. Legacy observation capacity remains
16384. No cross-call verification cache is introduced.

Separate byte/path bounds remain enforced: inventory and kernel8MiB each,
complete interpreter contract16MiB, generated runtime configuration1MiB,
contract directory/namespace counts and canonical path/depth checks. Runtime
configuration carries inventory pins, not its complete file list. File-count
admission does not promise arbitrary maximum-length names will fit the document
byte bounds. Inventory building now checks serialized document sizes before
returning bytes for writing; oversize data fails without truncation or output.

UV freshness checks perform repeated bounded inventory reads/hashes before
spawn, including a second before-effect check under custody. This can be costly
for large installed environments; the repair preserves those trust boundaries.
The regression runs serially with24204 small real inert files; its passing time
is not a throughput estimate for multi-gigabyte ML installations.

## Failure diagnostics and custody

Trusted driver failures carry only a fixed phase: binding-validation,
runtime-config-validation, environment-verification, config-staging, or
staged-program-verification. Provider-level failures also distinguish program
and device verification. The allocation retains `preDispatchFailure` with a
fixed code, original journal identity and `dispatchAttempted:false`. Only the
exact trusted exception type and an allowed phase are accepted; raw exception
messages, paths, input contents and credentials are never copied into this
metadata. Owner-scoped resource projection validates and retains the original
diagnostic; it is metadata, not launch, cancellation or release authority.

`dispatchAttempted:false` refers to this adapter's guardian/process spawn.
Preparation may already have reserved checkpoint storage or staged files.
Failure remains PREPARED/UNKNOWN with capacity held. It does not manufacture a
stop receipt or silently rerun allocation. Normal cancellation of the original
PREPARED journal produces the existing `never-dispatched` receipt; normal
reclaim releases capacity only after the original receipt checks. Missing or
uncertain dispatch acknowledgements retain existing UNKNOWN semantics.

No historical attempt gains these new diagnostics retroactively. Keep the
current target attempt's pins unchanged, retry0, and wait for its original
cancel/cleanup receipt. Do not use this patch to launch another GPU attempt before original release,
replace inflight files, remove custody or pretend PROCESS_SUBMITTED meant spawn.
Recovery is already authorized by the task. After positive original capacity
and GPU release, the recovery attempt must use a freshly built,
fully inventoried installation and newly sealed source/runtime/observer pins.
PR49's one-file path repair mode is deliberately pinned to that earlier repair;
it must not be repurposed or weakened to install this multi-file change.

## Validation scope

The new real-filesystem regression builds and captures all24204 files, checks
contract cardinality and the final file, runs the actual observer and driver,
and writes/verifies `run-config.json` through normal staging. Identical replay
returns the same proof. Mutation and deletion of the final file each reject
verification while preserving the existing configuration bytes. Source bundle
generation and output reservation are explicitly controlled fixtures; no ML,
GPU, external model, target DB or numerical result is claimed.

Additional tests exercise observation bounds and changed duplicate stamps,
exact/over-limit8MiB documents, fixed diagnostic redaction, durable PREPARED
custody, owner projection, no process dispatch/replay, and normal original
never-dispatched cancellation/reclaim. The same durable diagnostic case is
included in the disposable PostgreSQL CI lane.

## Bytecode and the stopped original attempt

A subsequent target report confirmed the original canonical exit2/retry0,
CANCELLED/never-dispatched journal and no Torch training/evaluation. Factory
RECLAIMED and GPU RELEASED receipts remain unconfirmed. Three new pyc files
changed the sealed namespace despite unchanged original file contents. Their
writer has not been established; original relative paths and timing are needed.

The guardian had a concrete no-bytecode gap: its Python used isolated `-I`
without `-B`; isolated mode ignores PYTHON* variables. Guardian dispatch now
explicitly uses `-I -B`, and its entrypoint rejects a missing no-bytecode flag
before importing local support modules. Payload/spec fingerprints are not
silently rewritten. Full namespace verification still rejects unlisted files;
no general pyc ignore rule or deletion workaround is added. The actual research
payload, preparation command and controller already enforce no-bytecode flags.
Development/synthetic helper commands outside this execution path do not prove
which process wrote the target files.

A real small guardian/child regression checks successful stop, explicit flags,
all support-file identities/hashes and the complete directory membership with
zero new pyc. A missing-B negative case rejects even when the ignored environment
variable is set. The training lease's never-dispatched receipt means its own
guardian cannot simply be blamed; preparation or external inspection may be
separate candidates, subject to actual evidence.

Use [the original-custody recovery runbook](ORIGINAL_RESEARCH_CUSTODY_RECOVERY.md)
for the finite read-only fields and existing normal receipt reconciliation.
Original capacity/GPU release must be proved before the already-authorized
recovery attempt. No target receipt has been fabricated or repaired by cloud.
