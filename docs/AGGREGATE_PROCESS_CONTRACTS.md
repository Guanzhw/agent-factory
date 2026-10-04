# Explicit delegated aggregate process backend

This continuation adds an opt-in backend to the existing process provider,
native reservation, custody journal and receiver evidence. It does not provision
a machine, mount cgroups, enable ancestor controllers or modify host delegation.
The current development host has no writable delegated cgroup subtree; fake
filesystem tests are contract evidence, **not kernel enforcement acceptance**.

An operator constructs `DelegatedCgroupConfig` with an existing dedicated cgroup
v2 domain subtree, its original boot/device/inode pins, CPU quota/period,
memory/swap maxima and PID maximum, and explicitly passes it as
`ProcessResourceProvider(..., aggregate_config=config)`. Register that provider
through the existing governed remote-target/pool configuration. No model or
browser request accepts a cgroup path or changes these limits. The deployment
[validator](DEPLOYMENT_VALIDATION.md) checks the configuration independently;
its optional read-only probe cannot certify execution.

Admission requires the original delegated domain, enabled CPU/memory/PID
controllers and no internal tasks. The native reservation rounds CPU quota and
memory plus swap upward, retains the per-process lower bounds, and still passes
through the existing target and shared-pool ceilings. Missing facilities reject
new work without falling back to cooperative limits. New admission checks do not
prevent cleanup of existing custody.

The guardian persists each intent before its effect, creates a unique task group,
writes and reads back limits, then attaches its own unreaped, blocked child before
opening the executable gate. Cancellation retains the same group identity.
Original whole-group emptiness and positive removal proof are required before
capacity release. Lost create/attach/kill/remove acknowledgements never authorize
replay or adoption of another group. An unreadable guardian identity is UNKNOWN,
not evidence that it died. Recovery effects require positive original guardian
absence and the existing provider operation lock.

Static enforcement schema 2 declares aggregate CPU, memory and PID scopes;
`aggregateEvidence` carries only hashed custody pins and finite observations.
Neither a declaration nor an attachment proves ongoing readback. A witnessed
controls mismatch permanently fails execution; cleanup may still release its
capacity. After removal, `limitsReadbackVerified` is false because no live group
exists to read. The positive release proof is independent. Original cooperative
receipts remain compatible and do not acquire aggregate claims.

This remains a trusted fixed-program backend, not a hostile-code sandbox or
network/disk isolation. The bounded process profile still restricts each process
to at most 2 CPU seconds, 128 MiB address space, 64 KiB output/file size and
5 seconds wall time. It is not a general long-running scientific environment.
Actual delegated Linux execution, escaped process-group descendants, aggregate
pressure, receiver-host identity/TLS and target capacity need separately recorded
target-host acceptance. No such acceptance is claimed here.
