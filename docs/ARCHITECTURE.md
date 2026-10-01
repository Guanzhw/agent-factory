# Architecture

The engine is Agno AgentOS 3.1.0 with PostgreSQL. The original React UI consumes `/api/factory`; there is no commercial Control Plane code or second agent loop. See [the native envelope decision](decisions/0001-native-plan-envelope.md).

```mermaid
flowchart LR
  UI[Research / material UI] --> API[Scoped factory API]
  API --> AUTH[Native JWT / managed SQL policy]
  API --> C[Versioned material catalog]
  C --> P[Immutable plan + dependency closure]
  P --> B[User/task binding + fingerprint]
  B --> Q[Agno durable PostgreSQL queue]
  Q --> E[Registered factory executor]
  E --> T[Current authority + fixed tools]
  T --> A[Evidence / metrics / artifacts]
  API --> R[Remote reference / lease service]
  R --> RA[Agno runtime attachment]
  R --> RC[Separate compute provider]
  R --> AA[Optional A2A interface]
```

Factory metadata stores material versions, immutable plan snapshots, trusted owner/session/native-run bindings, admission fingerprints, application events, effect receipts and artifact bytes. Agno owns run/session state, queue claims, heartbeat/recovery, model/tool loop, native HITL and cancellation. Application status derives from native state plus explicit effect/domain evidence; it is not a replacement scheduler. Unknown receipts/effects retain capacity.

Native explicit-version and factory-resolved runs did not obtain durable tickets in the verified upstream revision. One static executor closes this gap through public callable instructions/tools and hooks. Serializable queue session state references the server-owned persisted plan. Snapshot integrity and owner/session/run identities are checked; later catalog publication cannot mutate a running plan. Ordinary pre-hook exceptions are insufficient. Agent pre-hooks use native InputCheckError; Function tool pre-hooks require StopAgentRun (AgentRunException), because they swallow InputCheckError. Actual native side-effect spies verify denial precedes compute and artifact writes. Every protected tool independently rechecks current native rights and task authority.

Admission serializes semantic fingerprints and shared task budgets transactionally. Plan construction shares its metadata transaction connection, avoiding nested pool acquisition while holding an advisory lock. A native receipt is bound to the pre-existing task. If a process dies after reservation or a response is missing, inspect/reconcile authoritative state; never automatically resubmit or free capacity after a timeout.

Questions and confirmations are distinct native requirements. UI actions carry actual requirement IDs plus a canonical version token. Stale, cross-owner, canceled or wrong-type decisions are rejected. Continuation sends native tool execution objects, preserving their IDs. A canceled ticket is not proof remote/experiment work stopped; bounded local tools settle cancellation only after owned compute cleanup.

The demo model replaces only provider responses. Literature sources are invented fixture records. Experiments execute one reviewed fixed Python program; user/model text cannot become executable code. The same executor runs checksum plans without core changes. Live models and ORX tool registration remain disabled pending budget, provenance and isolation acceptance.

Remote attachment does not allocate a machine. Resource references resolve through operator configuration and current owner grants, with target fingerprints, lease heartbeats, remote IDs and snapshot reconciliation. No native durable cursor/boot epoch is invented. A2A is a future interoperability adapter, not environment provisioning. The remote lease and trusted prepare/dispatch APIs are implemented. A selected receiver owns the entire task tree and one native ticket; the origin holds metadata only. Separate local native services and databases verify routing/cancellation/evidence. Production provider/TLS/identity/endpoint acceptance remains open.

Deploy one application process and its bounded native worker pool on the proposed single server. Initial limits: two workers, two held tasks per user, twelve held tasks globally, twenty queued tickets, eight tool calls, bounded experiment time/output. Paused/UNKNOWN work retains its reservation. There is no permanent heavy environment per user. Local fixed compute has hard Windows job bounds and cleanup; full tenant isolation, aggregate CPU/RAM/PID measurement and sustained fair throughput remain deployment work. Twenty-user concurrent admission/cancel/revoke/UNKNOWN tests and clean-stop restore have passed. Fact queries use the API/database directly.

Child tickets share persisted root and ancestor tool budgets, plus a four-descendant lifetime cap and depth two. Their immutable scope cannot become a standalone new root. A bounded trusted lifecycle observer performs existing-work cleanup without UI reads; it validates original native bindings and uses public native cancellation APIs. Pre-ACK children stay uncertain, and completed tickets are not re-authorized as active execution. Default running signals are single-process only; see LIFECYCLE.md. Group capacity is held until native terminal facts and known effect cleanup agree.

Scheduling composes Agno SchedulePoller with a guarded public executor interface, while AgentOS scheduler=False disables its unguarded executor. Native schedule ingress is blocked. The owner-scoped wrapper accepts only an immutable top-level plan reference and cron/timezone; occurrence receipts enter the same Store/native queue admission. Native polling and queue ownership remain upstream. See SCHEDULING.md for tested recovery and remaining lease/restart acceptance.

Material governance separates immutable content from publication state and review
receipts. The default requires a distinct current administrator. Catalog discovery,
admission, native tools and delegated ancestor guards require current approved
versions; the version remains available as historical evidence after withdrawal.
Factory event replay uses persisted task stream IDs, signed owner/task positions
and one SQL snapshot. Late lower-ID commits explicitly invalidate the prefix;
display history limits never erase application failure facts.
