# Target admission and first-baseline boundary

This document describes admission requirements and remaining implementation
boundaries. It contains no target inventory or capacity measurements.

## Complete environment, without trimming

A complete environment must fit all bounds together. Package file count, tree
entry count, serialized metadata size and hard-link identity are separate gates.
A reported complete inventory that exceeds any gate remains inadmissible.

Current admission remains closed: 4,096 files, 8,192 entries per module tree,
1 MiB collected inventory JSON, 2 MiB canonical interpreter contract, and
single-link regular files. The aggregate byte bound alone is insufficient.
No package subtree, shared library, metadata file or startup file may be omitted
to fit these limits. The largest file, total namespace entries/directories and
actual canonical-contract bytes are still separate required measurements.

The uv0.11.7 profile accepts only its exact reviewed startup files. An additional
startup `.pth` requires its public source, owning package version, imported code
and environment dependencies to be reviewed. A familiar filename and hash are
not a semantic audit. Unlisted executable startup files remain rejected.

## Hard links and storage choices

A larger, versioned inventory profile could finitely bound the complete tree,
check each path's device/inode/link count/mode/owner/size/hash/timestamps, require
consistent pins for paths sharing an inode, and retain descriptors. That proves
observed consistency, not immutability throughout execution. Repeated hashes,
open descriptors, or a read-only bind of the existing cache do not stop a writer
through another hard-link alias. Changing shared-cache permissions is not an
acceptable isolation repair.

When free space cannot hold an additional complete copy, copying is not a safe
fallback. A strong runtime isolation route needs one of these actual capabilities:

- A supported independent CoW clone or read-only filesystem snapshot, with its
  namespace protected from replacement and measured/reserved CoW growth. Reflink
  support and space cannot be assumed from the operating-system name.
- An approved filesystem/kernel mechanism that prevents writes to every admitted
  inode, plus protection for its namespace. Capability, privilege, rollback and
  effects on shared cache users must be established before any change.
- Enough separate storage for a complete copy, with an enforced writer/reader
  authority boundary and explicit cache/checkpoint capacity reservations.

The kernel documents [fs-verity](https://docs.kernel.org/filesystems/fsverity.html)
as file integrity/write protection, with filesystem support and enablement
requirements; it does not establish this target's capability or authorize modifying
shared cache files. [FICLONE](https://man7.org/linux/man-pages/man2/FICLONE.2const.html)
is a filesystem-dependent CoW operation, not a synonym for hard linking.

No route is automatically selected or performed. A cooperative operator freeze
of all uv/cache writers can support an explicitly independent diagnostic, but
must not be represented as enforced runtime isolation or managed acceptance.
The coordinator does not weaken the existing hard-link gate to disguise this
resource constraint.

Before increasing bounds, measure the full canonical contract, namespace and
largest file. Budget each complete byte scan: observer, capture and guardian
checks may each read the entire tree. Post-gate checks also consume the managed
CPU/wall limits. Test finite memory, cancellation and scan deadlines on the
actual target; a scan timeout is an admission failure, not a scientific result.

## Genuine identities and bootstrap dependencies

Managed launch IDs are outputs of existing Factory lifecycle, not user inputs:
owner authority and immutable reviewed plan create the native task/run; the
existing research runtime creates its lease and original provider allocation;
`ResearchLocalDriver` derives the execution binding from that allocation and
`ResearchCheckpointStore.reserve` reserves the output in managed storage before
launch. Replacing any of these with hand-written IDs would defeat custody.

Safe token-byte preparation needs its own immutable preparation manifest and
original producer binding. Reusing the final training manifest creates a hash
cycle: that manifest includes the token-byte file hash while the file header
includes its producer manifest hash. The preparation artifact must precede the
final training manifest. A preparation-store primitive under development is not
a complete preparation runtime or executable bootstrap.

The target must identify an existing Factory/Agno control environment with a
reachable PostgreSQL store, or an existing configured remote receiver/runtime
channel. No credential, private path or fabricated plan/journal is requested.
Absent that control plane, managed baseline bootstrap remains unavailable.

The separately documented fixed eager-model diagnostic requires none of these
managed IDs and produces none. It uses the existing verified generator and SDPA
runtime, one synthetic B1/T2048 forward/backward, and finite supervision. A pass
only measures eager-model compatibility/memory; it cannot authorize training,
prove compiled optimizer fit, reserve a checkpoint, or produce `val_bpb`.
