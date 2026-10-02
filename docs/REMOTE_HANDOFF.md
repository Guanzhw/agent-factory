# Trusted Factory execution placement

The product API can select one operator-installed Factory connection reference.
One origin metadata reservation represents one receiver-owned native execution
tree. The origin never creates another AgentOS ticket for a placed task. Runtime
attachment, compute allocation and Factory placement remain different operations.

## Authority and configuration

`Settings.handoff_targets` accepts trusted `HandoffTarget` objects; each contains
a connection reference, fixed base URL, explicit origin-to-receiver identity map,
credential resolver and immutable configuration revision. `handoff_origins`
contains `TrustedOrigin` objects with the reverse binding and a current authority
callback. These are operator configuration, never user/model JSON. The callback
must consult the authoritative current origin policy, grants, exact plan and
cancellation mandate; a static success callback is unsuitable for production.
Current source authority is now implemented through `OriginAuthorityTransport`
and an authenticated origin route, verified over controlled actual TCP.
Production distributed identity issuance, TLS and credential provisioning remain
unaccepted; see [receiver binding proofs](REMOTE_BINDINGS.md). No target is configured by default or discovered by URL.

`GET /api/factory/execution-targets` shows only references mapped to the current
native principal. It returns no URL/credential and reports connectivity as
unverified. `POST /instances` accepts optional `executionTargetRef`. Selection is
bound to the original semantic request key; local/remote or target changes with
the same key conflict. The local read-only `/requests/{requestId}` receipt binds
owner, immutable plan and selected target without contacting the receiver.

The receiver validates the exact ready plan manifest, hash/fingerprint, bounded
registered tool/capability scope and budgets, exact published material semantics
and dependency closure. Prepared imports cannot be reused through local public
admission or scheduling. Both origin and receiver current authority are checked
before native binding and every registered protected tool. Receiver descendants
inherit that persisted root; the whole tree stays at the selected receiver.

## Admission, recovery and cleanup

Prepare persists the immutable receiver plan and binding proof without execution.
Receiver administrator review exposes that exact plan in PREPARING, with no task
or ticket; after approval, idempotent prepare reserves its original task.
Dispatch commits an UNKNOWN boundary before its single native submission attempt.
The origin persists `dispatchAttempted` even when a later receipt says PREPARED.
Lost delivery, lost reply and restart lead to owner-bound receipt/native-ticket
reads, never automatic resubmission. Sticky task/run identifiers reject changed
receipts. Uncertain outcomes retain capacity. A known stopped result requires the
actual native/effect/descendant facts, or serialized positive proof that dispatch
never began. Bare cancel acknowledgement does not establish cleanup.

Root cancellation persists origin intent before any network lookup, then uses
receiver native cancellation and existing experiment/descendant supervision.
Remote answer/approval uses the actual native requirement ID and version. Reads
remain available to a current read-only owner; execution actions require current
run authority. Neither an expired approval nor cancellation intent erases prior
evidence. Public descendants use `originTaskId~receiverChildId` and are validated
against the exact receiver tree. Artifact downloads check metadata and actual
bytes, size and SHA-256 before returning them to the owner.

The narrow authenticated receiver routes are under `/remote-handoffs`: prepare,
dispatch, receipt, detail, children, scoped answer/approval/cancel and artifacts.
They accept no raw native agent configuration, owner override, model credentials
or arbitrary command. Raw native executor/schedule ingress stays blocked.

## Evidence and limits

Adapter and product HTTP tests passed against two actual
Factory apps, separate generated PostgreSQL databases, native authentication,
queue/HITL and deterministic models. They cover concurrency, exact identities,
lost delivery/reply/cancel acknowledgement, current revocation, child-tree scope,
actual fixed experiment process cleanup and artifact corruption. Their ASGI
transport is controlled and explicitly synthetic.

Supported browser acceptance additionally uses two actual loopback HTTP servers
and separate PostgreSQL stores. It checks target selection, repeated clicks,
stale question rejection, scoped child inspection, whole-tree cancellation and
hashed evidence downloads, owner isolation and desktop/mobile layout. The model
and literature sources are still synthetic. Local HTTP proves this composed
product boundary; it does not prove external-host TLS, distributed credentials,
multi-host process restart, hostile-code isolation or real scientific results.
No host/cloud provisioning, access grant, paid model or deployment is performed.

## Cancellation delivery window

Persisted origin cancellation may be observed before the receiver cancel POST.
Only a trusted callback signal bound to the exact original owner/task/manifest,
after original target/configuration validation, carries cancellation semantics.
Receiver lifecycle and native tool hooks stop this existing work without false
failure provenance. Wrong signal bindings fail closed. Current revocation or
policy failure remains a failed application outcome. A read-only downgraded owner
can retain exact native facts while trusted cleanup completes, but cannot answer,
dispatch or cancel through execution-authorized user routes.
