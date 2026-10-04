# Shared compute admission and production identity integration

This milestone follows PR24 exact `d7221e451e7f61c3b9d711788bf17486d6cb5f82`.
It implements previously missing shared resource admission, actual local workspace
allocation, stop-only maintenance and an opt-in external access-token identity
entry. It does not provision remote machines, identities, OAuth grants or secrets.

## Resource contract

`ComputePool(pool_id, cpu, memory_mb, disk_mb, max_leases=20,
max_owner_leases=2)` is an immutable operator admission policy. Attach it to a
compute `RemoteTarget.capacity_pool`. All aliases of one physical provider
namespace must use the same pool. On one server, configure a shared pool for
targets consuming the same capacity, with headroom for PostgreSQL and the OS.
Pool values are operator limits, not detected or measured physical capacity.

The existing PostgreSQL transaction/advisory lock now atomically sums CPU,
memory, disk and slots across owners and references. Every lease other than
RECLAIMED consumes its original reservation, including expired, terminal,
cancel-requested and UNKNOWN records. Owner slot ceilings prevent one owner from
using every slot; this is bounded admission, not a FIFO/fair-share scheduler.
One task cannot obtain another live allocation in the same pool by changing its
request ID or alias. Old unpooled target behavior remains available explicitly.

Lease records pin pool identity/configuration, provider namespace and target
identity. Conflicting aliases and changed historical pool definitions fail
closed. Shrinking or removing a pool does not erase old reservations. Cleanup
can still use the original provider binding when only capacity policy changes;
replacing the provider/root fails closed until its original custody is reconciled.
For external adapters without a namespace property, consistent pool assignment
and configuration revisions remain an operator responsibility.

`LocalWorkspaceProvider(store, root)` implements the existing ResourceProvider
interface using the additive `af_compute_allocations` journal. The root must be
an existing task-owned POSIX directory; `store.engine` must use the Factory's
database. Construct the provider and its RemoteTarget in trusted operator startup
code, before constructing PersistentResourceService. Manage any separately
constructed database engine with that operator application's lifespan.

The provider creates real directories/markers, persists intent before effects,
pins root/directory identities and serializes operations using a flock on the
root directory inode. SQL/FS work runs off the event loop. Only the fixed
workspace-only backend is admitted; no user commands or arbitrary backends run.
Only the provider's marker and empty workspace can be removed. Foreign files,
symlinks, hardlinks or identity changes retain capacity for investigation.

Guarded allocation rechecks current owner/task authority, cancellation/deadline
and target/pool/namespace bindings after waiting for its filesystem lock. A
canceled waiting caller cannot later create a workspace. Effects already started
can remain uncertain; they are not undone or reissued automatically. A denied
post-reservation admission can conservatively retain a hold even if no workspace
was created. Absence alone never proves a prior effect was safely released.

Cancellation acknowledgement does not free a pool reservation. Reclaim requires
confirmed terminal custody, recorded release proof and an identity-bound read.
The provider only allocates **workspace availability**: CPU, memory, disk and
seconds are **admission budgets, not kernel-enforced quotas**. It does not attach
a process to that workspace, provision a VM/container, or certify hostile-code
containment. Existing remote runtime attachment remains a separate axis.

## Operator maintenance

`POST /api/factory/resources/maintenance` is guarded by current `agent_os:admin`.
It is a stop-only scan of existing compute custody for revoked owners, requested
task cancellation, terminal tasks or fixed deadline expiry. Ordinary revoked
owners remain unable to cancel/reclaim through their normal API. Maintenance
cannot allocate, restore roles, redirect a provider or retry uncertain effects.

Each call scans at most20 rows. Send `{ "after": "<nextCursor>" }` to continue;
reset the cursor for a later sweep. This avoids a stable active prefix starving
later expired leases. The API is explicit operator reconciliation, not a second
scheduler or an automatically deployed cleanup daemon. Authentication-store
unavailability is not treated as revocation. Only positive matching release
evidence changes a lease to RECLAIMED.

## External identity entry

`Settings.oidc_identity=OIDCIdentityConfig(...)` enables a production-mode bearer
bridge. It is incompatible with demo mode and is operator-only, not loaded from
request JSON or discovered from untrusted endpoints. Configure a fixed HTTPS
issuer, expected audience, public JWKS and `(issuer, subject) → existing owner`
map. The existing internal JWT signing key remains separately configured.

The verifier implements a deliberately narrow [RFC9068 access-token profile](https://www.rfc-editor.org/rfc/rfc9068.html#section-4):
RS256, explicit access-token `typ`, bounded required claims, signed expiry and
not-before checks, and fixed public RSA keys. ID tokens, HS256/none, ambiguous
JSON/headers, unknown keys and token-supplied key URLs are rejected. Key rotation
uses an operator-replaced trusted key set; there is no remote JWKS fetch. The
[PyJWT cryptography extra](https://pyjwt.readthedocs.io/en/stable/installation.html)
is locked with the existing dependency set.

Authenticated requests require the actual ASGI HTTPS scheme; arbitrary forwarded
headers are not trusted. TLS termination/trusted proxy setup remains deployment
work. No browser cookie is promoted and no login/session/logout or OAuth callback
flow is implemented. WebSocket entry is denied by this profile.

The verified subject maps only to an existing, enabled SQL user. The bridge
creates a short-lived in-process native token; external roles/scopes never grant
permissions. Current native SQL authorization still applies at API admission and
execution. No user is automatically created. SQL identity outages return a fixed
503; invalid or unavailable subjects return a sanitized401. Native internal
queue calls retain their separate trusted token path. External token expiry is
not a claim that already admitted work or UNKNOWN resource custody has stopped.

## Acceptance and remaining work

Serialized, disposable PostgreSQL tests passed:

- Three pool tests (23.007s): two services/engines, four competing requests,
  shared weighted admission, UNKNOWN/restart and owner API isolation.
- Administrator maintenance API (6.680s): revoked-owner denial, original-lease
  stop/reclaim, positive release and unchanged user grants.
- Three actual filesystem/provider/native-task tests (14.904s): persistence,
  cancellation/release, root rebinding, unknown replies and foreign-file safety.
- Four production-mode synthetic identity tests (12.837s): SQL mapping/revocation,
  owner metadata isolation and RSA → governed immutable plan → native queue →
  checksum artifact/receipt/two SETTLED attempts. This uses synthetic keys/users
  and an explicitly registered local fixture model, not an external IdP/model.

Default Python:945 total=627 passed+318 skipped (48.001s). Frontend78, Ruff and
Pyright passed. npm production audit and49 locked Python dependency audit found
no known vulnerabilities. A final identity-filtered allocation-journal query was
verified with12 focused tests and a fresh4.921s actual PG/filesystem case. Independent review and54 focused offline checks passed; fixes
included PG lock quoting, effect serialization, namespace aliases and scan cursor.
Exact-head CI and any later final observations are recorded on the stage draft PR.

Still required: selected issuer/public keys/audience/subject map and real TLS/IdP
acceptance; browser authorization-code/PKCE and session/logout integration;
operator host pool budgets/root locations/cleanup cadence; real remote machine
provisioning and kernel quota/fencing adapters; deployment monitoring and target
capacity measurements. Neither the task's small host nor these fixtures certify
32-core/64GB or54-core/192GB capacity. No production permissions, accounts,
credentials, network/security settings, purchases, merge or deployment changed.
