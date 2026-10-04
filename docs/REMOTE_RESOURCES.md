# Remote resources

Current extension: [shared admission and identity milestone](RESOURCE_IDENTITY_INTEGRATION.md)
adds ComputePool weighted admission, LocalWorkspaceProvider actual filesystem
allocation and ResourceMaintenance stop-only cleanup. CPU/memory/disk/time are
admission budgets; remote machine provisioning and kernel enforcement remain open.
The older contract description below retains its original validation boundaries.

Agent Factory treats remote runtime attachment, compute allocation and optional A2A as three different axes. A remote runtime executes its sessions/tools remotely; attaching it does not provision a machine. A compute provider owns allocation and release. A2A is an interoperability interface and is not a scheduler, sandbox or compute allocator.

## Implemented contract

`PersistentResourceService(store, auth, targets)` uses the existing `af_resources` and `af_leases` PostgreSQL tables. Registry rows persist trusted connection references and scoped summaries, never endpoint URLs or credentials. Operator code supplies `RemoteTarget` objects. The service accepts connection-reference identifiers, verifies current native authorization and explicit owner grants, and resolves only configured operator targets. No request-body bearer token, arbitrary URL, shell command or user-created provider is accepted. Redirect following is disabled.

Production remote targets require an operator-supplied credential callback for the verified user identity, a compatible registered `factory-executor`, JWT authentication and native user isolation. The executor must resolve the same persisted immutable plan reference or an explicitly verified equivalent; attachment does not copy or silently replace a plan. Wrong-audience identity tokens, owner mapping and remote native authorization remain deployment acceptance work. The local module's authorization check is not a claim that an external host's policy has been verified.

Callable methods:

| Method | Meaning |
|---|---|
| `discover(owner)` | Return only configured references granted to the verified owner. |
| `attach(owner, connection_ref)` | Read selected Agno `/info` and `/config`; record version/capability observations. |
| `attach(owner, connection_ref, task_id, request_id)` | Reserve a persistent runtime lease; submit the immutable task envelope to the configured registered executor once. |
| `allocate(owner, connection_ref, task_id, request_id, limits)` | Allocate through a separate operator compute-provider adapter within CPU/memory/disk/time ceilings. Native runtime references reject allocation as unsupported. |
| `inspect(owner, lease_id)` | Read scoped persisted lease state and expiry; does not contact or manufacture upstream state. |
| `reconcile(owner, lease_id)` | Read remote snapshots and update confirmed state; never replay submission/cancel/release after unknown acknowledgement. |
| `cancel(owner, lease_id)` | Persist cancellation intent before sending; accepted reply is not confirmed stop. |
| `disconnect(owner, lease_id)` | Mark the connection disconnected. Does not cancel the job or release capacity. |
| `heartbeat(owner, lease_id)` | Update owner-scoped heartbeat without extending the fixed maximum deadline. |
| `reclaim(owner, lease_id)` | Release only a confirmed-terminal runtime attachment slot, or request compute-provider release and require a separate `released=true` snapshot. |

Connection-reference bindings include a one-way fingerprint of the operator target axis, URL, executor, expected version and configuration revision. Rebinding a reference rejects effects against an existing lease with HTTP 409 instead of redirecting cancellation to a different host. URLs stay operator-only. Credential callbacks and compute-provider changes must increment the operator configuration revision when their security or resource identity changes.

Remote lifecycle metadata records owner, local task/plan IDs, remote session/run or provider-job IDs, request ID, immutable request fingerprint, server version and observed boot epoch when supplied by an explicit fixture. PostgreSQL reservation/update operations use a global transaction advisory lock. Unknown/reclaiming/cancel-requested leases hold capacity across service restarts; explicit resource reclamation releases a slot. Lease expiry does not prove remote stop and never silently releases capacity.

Runtime acknowledgements use native `run_id`, `session_id`, `user_id`, `agent_id` and run status where returned. The unique local-task session identifier persists before transmission. For lost submit acknowledgements, reconciliation reads the session's persisted factory envelope and adopts exactly one owner/executor-matching run only when the resource fingerprint matches. A missing or ambiguous snapshot remains UNKNOWN. Native queue tickets cannot be assumed recoverable through an invented remote lookup endpoint.

The compute `ResourceProvider` contract has separate allocate/inspect/cancel/reclaim operations. Each inspected response must bind lease ID, owner and fingerprint. It is an adapter contract with a state-only synthetic provider test; no real provider or environment provisioning is implemented here.

API wrappers should pass a server-verified owner, never a user-supplied owner ID. `discover`, `inspect`, `disconnect` and `heartbeat` are synchronous; other callable methods above are asynchronous. Request IDs are nonempty strings up to 200 characters and remain bound to immutable work. Allocation limits contain exactly `cpu`, `memoryMb`, `diskMb` and `seconds`, each a positive integer within operator ceilings. HTTP 400 rejects malformed request IDs/limits; 404 hides unknown or ungranted references and leases; 409 rejects incompatible metadata, target rebinding, idempotency conflicts, duplicate runtime attachment, unsupported allocation and unconfirmed reclaim; 429 indicates held capacity. Native authorization errors propagate. Errors after transmission preserve an UNKNOWN lease with capacity held, so callers must inspect/reconcile that same lease rather than retry with a new request ID.

## Selected runtime provenance and gaps

The HTTP adapter pins Agno 3.1.0 by default and checks the operator's expected version. It uses public `/info`, `/config`, `/agents/{id}/runs`, `/agents/{id}/runs/{run_id}`, cancellation, and scoped session/run snapshot routes. Tests use installed Agno 3.1.0 for actual metadata-only attachment. The selected source revision is [ab1d6007](https://github.com/agno-agi/agno/tree/ab1d6007f09163c3adadbe06f998dc481b77a09a), with [metadata implementation](https://github.com/agno-agi/agno/blob/ab1d6007f09163c3adadbe06f998dc481b77a09a/libs/agno/agno/os/router.py) and [metadata schema](https://github.com/agno-agi/agno/blob/ab1d6007f09163c3adadbe06f998dc481b77a09a/libs/agno/agno/os/schema.py). Native `/info` reports `agno_version`, `os_id`, `auth_mode` and `user_isolation`; it does **not** report a boot epoch. Ordinary targets therefore expose `bootEpoch=null`, `bootEpochVerified=false` and no restart fencing promise. Synthetic transport tests provide a clearly labeled fixture epoch and demonstrate the rejection/UNKNOWN behavior after epoch change.

Agno has resume/event machinery, but this adapter has not verified cross-host durable replay. It reports `eventReplay=not_verified`, uses snapshot reconciliation, and does not invent a durable event cursor. Native filesystem/artifact transfer and remote OS provisioning are not implemented. The recorded artifact is the observed result snapshot, persisted with SHA-256, configured connection origin, remote run/session IDs, epoch availability and synthetic-fixture marker. It is not automatically validated research evidence.

## Validation boundary

`platform/tests/test_resources_contract.py` checks actual installed Agno metadata routes through local ASGI HTTP transport without executing a model. Twelve contract tests passed locally with no model execution. Lifecycle tests use `httpx.MockTransport` and a disk SQLite fixture with the resource/lease column contract. They cover scoped references, fingerprint conflicts, operator reference rebinding, strict version/production-identity rejection, fixed-deadline expiry, restart persistence, lost submit/cancel replies, no replay, preserved capacity, epoch mismatch, disconnect versus cancellation, accepted versus confirmed cancel, snapshot artifact hash/origin, heartbeat ownership/revocation, separate compute allocation, and acknowledged versus confirmed release. This does not certify PostgreSQL contention, external-host TLS/authentication, native remote execution, or actual compute/OS isolation.

Production gaps include worker/child process fencing, cgroup or Windows Job resource enforcement on remote hosts, CPU/memory/disk quota evidence, lease expiry cleanup, remote secret resolution, verified remote owner token mapping, shared-plan availability, durable event continuity and recovery after remote restarts. A native CANCELLED snapshot confirms that run's native status; it does not prove external experiments/child resources are stopped. Separate compute leases require their own provider confirmation.

The host profiles of 32 cores / 64 GB and 54 cores / 192 GB are planning targets, not measured throughput or capacity tests. The service counts configured lease slots; it is not a fleet scheduler and does not allocate a permanent heavy runtime for each user. No external remote host, cloud resource, paid model or real compute allocation was used by these tests.
