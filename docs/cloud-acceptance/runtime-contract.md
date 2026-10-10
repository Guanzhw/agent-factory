# Runtime boundary acceptance and integration handoff

## Scope and ownership

This is independent cloud-built test support under `cloud-validation/` and
`docs/cloud-acceptance/`. It deliberately makes no changes to the application,
its backend/frontend, root package manifests/lockfiles, or existing workflow.
It can be integrated alongside the separately developed Agno AgentOS 3.1.0 and
PostgreSQL implementation. Auto-Research remains the first application; the
runtime protocol is application-independent. Optional A2A is a separate
inter-agent interoperability boundary, not the remote execution transport.

The baseline branch is `main` at
`ba707a272c9d3fdfcbbe479f4278ee50bde3b703`. This proposal is additive to that older
scaffold. Its historical platform-selection text is not being rewritten here.
The selected engine for the integration handoff is Agno AgentOS 3.1.0 with
PostgreSQL; these tests neither import it nor assert native endpoint compatibility.

## Three independent lifecycles

1. A provisioned execution environment belongs to the deployment/compute owner
2. A durable session groups conversational/execution context
3. A run is a separately identified attempt inside a session

Attach/detach changes a client attachment to an existing session. It neither
creates a compute environment nor starts, cancels, or reclaims a run. Losing a
browser connection does not change accepted execution facts. The fixture models
a single attachment flag only; multi-client attachment semantics need application
integration tests. Worker lease expiry is a reconciliation condition, not evidence
that the old worker or its children stopped.

## Proposed adapter test interface

These are **test-boundary routes**, not the public application API specification.
An integration adapter may translate them to the actual backend. Identity must
come from an authenticated trusted context, never a request-body user ID.
`scope` is the exact tenant/user/task tuple in every run snapshot, event and
artifact; every lookup and mutation independently checks current permission.

| Route | Test semantics |
| --- | --- |
| `GET /v1/health` | Reports `factory-runtime-test/v1` and `fixture: true` |
| `POST /v1/sessions` | Empty body; durable context only |
| `POST /v1/sessions/{id}/attach` or `/detach` | Empty body; attachment only |
| `POST /v1/sessions/{id}/runs` | `input`, optional complete `reservation`, optional `parent_run_id` |
| `GET /v1/operations/{key}` | Current-authorized lookup of original command receipt |
| `GET /v1/runs/{id}/snapshot` | Authoritative scoped state and monotonic sequence |
| `GET /v1/runs/{id}/events?after=N` | Ordered scoped replay or `snapshot_required` |
| `GET /v1/runs/{id}/artifacts/report` | Synthetic content, scope, size, SHA-256 |
| `GET /v1/resources` | Current user's aggregate reservations across task scopes |
| `POST /v1/runs/{id}/cancel` | Request cancellation; no terminal or cleanup assertion |
| `POST /v1/runs/{id}/reply` | Typed answer or exact-bound approval response |
| `POST /v1/runs/{id}/step` | Synthetic effect counter for replay/revocation checks only |
| `POST /v1/runs/{id}/reclaim` | Requires terminal state, complete cleanup and reclaimed children |

All normal POSTs require `Idempotency-Key`, scoped to the trusted delegation.
The stored fingerprint includes method, path and canonical body. The same key
and same request return the stored receipt, not a second effect. Changed payload
or route returns `409 idempotency_conflict`. A receipt is the original command
result; query the snapshot for current run state. Replay still rechecks current
permission before looking up the receipt. An absent operation returns
`404 operation_unresolved`; it does not authorize creating a new key.

`ContractClient` intentionally supports only explicit IP loopback HTTP adapters,
disables environment proxies, refuses redirects and never retries automatically.
No external adapter execution command or automatic production endpoint discovery
is provided. Keep credentials out of CLI arguments and reports when adding a
future authenticated adapter.

## Fault and reconciliation rules

The fixture commits the run, reservation, and idempotency receipt before dropping
the connection, returning malformed JSON, or returning HTTP 503. These mutations
produce `UnknownAcknowledgement` in the client. A network timeout/disconnection
or ambiguous server error cannot prove non-acceptance. Keep the original key and
all known reservations until an authoritative result establishes what happened.
Do not reissue under a new key, count it as failed, or free capacity. A normal
HTTP rejection is separately represented by `ContractError`.

After fixture restart, the same operation key returns the accepted receipt and
its run remains visible. This tests the integration invariant, **not distributed
exactly-once execution**. Production must atomically persist its intent, bound
request fingerprint, reservation and effect correlation in PostgreSQL, and
reconcile with any external worker/resource owner. Transactions cannot make an
external effect atomic. Unresolvable outcomes remain unknown or need a person.

Events have a run-local positive sequence. A projection ignores duplicates and
older snapshots, rejects all cross-scope frames, and requires a snapshot on a
gap. Expired or future cursors request a fresh snapshot. This projection is test
support, not the application's event/cache implementation. Real UI tests must
also cover login/logout, task switches, stale subscriptions and cache erasure.

## Questions, approvals, and revocation

Questions and approvals have distinct persisted interaction IDs and kinds. A
question answer such as “continue” is not an approval. Wrong kind, stale ID,
expired request or changed binding is rejected; retries are deduplicated.
Accepting or denying the fixture's approval records a decision and does not run
a tool. The synthetic `step` counter does not implement a production tool policy.

The fixture uses a binding string to represent a production bound approval. The
real adapter must derive that binding from canonical action, exact target,
parameters, connection/identity, material plan version, policy prerequisites and
expiry. A reply must not grant manager permissions. Revocation blocks new
protected actions, data reads and replay of old receipts, without rewriting an
already-submitted external operation as cancelled. Revocation of data-derived
context, caches, credentials and model egress still needs real integration tests.

## Reservations and reclamation

Fixture run grants use positive integral `slots`, `cpu_millis` and `memory_mib`.
All accepted runs count toward host and user limits; different sessions/tasks
cannot reset a user's budget. Descendants additionally share the root budget,
maximum depth and lifetime descendant count. These small fixture limits exist
only to make boundary tests deterministic, not to size a deployment.

Cancelling, waiting, lease expiry or reaching an execution terminal state does
not release the reservation. Reclaim requires verified zero remaining runtime,
tool, browser, MCP and experiment processes, clean temporary data, and reclaimed
direct children (recursively enforcing descendant cleanup). The synthetic
process counts and cleanup flag are controlled test evidence, **not OS proof**.
Production must prove process-tree termination, home/cache/workspace/credential
cleanup, release of temporary grants and absence of orphan external jobs before
reuse. Preserved audit/artifacts must remain permission-scoped after reclamation.

Execution state, business verification and cleanup state are separate axes.
Process completion does not imply successful research. The fixture supports a
completed run whose business result is failed and whose resources remain held.

## Integration checklist and evidence levels

1. Keep this fixture as a reference test target; never import it into production
2. Add a separate development adapter mapping the proposed test operations onto
   the actual backend without changing existing application endpoint contracts
3. Replace synthetic identities with two approved test identities plus an explicit
   same-user different-task delegation, and test current authorization on every
   real route, artifact download, event and operation lookup
4. Drive equivalent fault scenarios using a controlled transport proxy/test seam;
   never expose `/_test/control` on a production listener
5. Replace clean SQLite reopen with actual PostgreSQL/worker crash, lease fencing,
   network partition and backup/restore evidence; verify exact backend commit,
   schema and Agno version in the report
6. Supply trusted process and external-job inventory, cleanup evidence and
   measured resource limits. Test safe waits, reservation of child capacity and
   deadlock avoidance using the real scheduler
7. Add the standalone Python command to CI only as an explicit integration change;
   existing Node CI alone does not execute these tests

| Area | Current independent evidence | Still required |
| --- | --- | --- |
| FR-01/02/04 | Synthetic scope, delegation and revocation HTTP tests | Real authentication, object rules and context revocation |
| FR-06/08/09 | Typed waits, unknown ACK, restart, replay, snapshot and outcome tests | Native persistence, crash recovery, UI and external effects |
| FR-07/13 | Reservation arithmetic, nested limits and cleanup-gate tests | Actual isolation, scheduling fairness, measurement and full process cleanup |
| FR-10/12/15/16 | Correlated commands and parent-child lineage in fixture | Real audit, assembly preflight, dynamic proposal and admin review/publish |
| FR-03/05/11/14 | No acceptance claimed by this suite | Connections, real tools/definitions and application integration |

Dynamic intent-driven assembly and administrator review before shared publication
remain in the complete product scope. This independent component does not settle
temporary-plan policy or implement catalog/definition/UI behavior. No fixture
success should mark those acceptance items, or live Auto-Research, as complete.
