# Actual backend contract acceptance

The delivery target is the complete factory/v0.3 scope. This record describes a verified stage and remaining work; synthetic research is not completion of live acceptance.

## Relationship to the independent cloud checks

Draft PR #8 at `28d9685b964595f8ccdc1bcfe9f7016f25a087b8` proposes development `/v1` boundary operations. It does not establish native AgentOS compatibility. Its reference runtime is not imported into the product or these backend tests, and that draft was not merged. The backend maps applicable invariants onto its existing `/api/factory` interface.

| Invariant | Actual backend boundary and evidence |
| --- | --- |
| Original-key recovery after committed ACK loss | `POST /instances`, then `GET /requests/{requestId}`. A temporary TCP proxy forwards the real submission and drops the response; the original task/native ticket is recovered with reads, with one native acceptance and unchanged task/event records. |
| Persistent receipt after process restart | The separate test API process is stopped and restarted against the same generated PostgreSQL database and identity key. Task/session/run correlations and its paused question survive. No second submit is made. Windows termination is forced; POSIX uses SIGTERM. This is not a running remote-compute crash test. |
| Concurrent keys and semantic conflicts | Three real TCP requests with one owner/key/plan produce one task. Changed-plan reuse returns 409 and leaves the original receipt intact. |
| Trusted scope and native ingress | Unauthenticated receipt read is 401; Bob reading Alice's key is 404. Direct public native executor submission remains 403. Missing receipts remain unresolved and do not authorize another key. |
| Artifact provenance | An actual native checksum run completes; downloaded bytes match recorded size and SHA-256, and Bob cannot download them. |
| Native cancellation schema | Four tests exercise installed Agno 3.1.0 JWT/managed SQL policy, sessions/runs and actual cancellation intent. `session_id` must be a Query parameter; the old form returns 400. Wrong session/owner and revoked permission produce no intent. Correct query still cannot bypass Factory ingress. No running process is claimed by these schema tests. |

The five TCP tests use an actual FastAPI/Agno process and class-scoped PostgreSQL database. Only model output and the controlled connection fault are synthetic. There is no reference server substitution, paid provider, external host, credentials in command arguments, or production test-control route. Fixtures stop only their own recorded process trees and remove only their generated loopback database.

## Read-only receipt contract

`GET /api/factory/requests/{requestId}` rechecks the current authenticated owner's native rights. It returns `requestId`, `taskId`, `planId`, nullable `runId`, `admission` and `outcomeSource=persisted_factory_intent`. It neither calls job detail/reconciliation nor submits, continues, cancels, emits events or releases capacity. It returns a persisted intent, not a new scientific/execution conclusion. UNKNOWN admission remains held.

The frontend issues one submission. After a disconnected, timed-out, malformed or server-error acknowledgement it looks up the same owner-bound key, verifies the exact plan/task mapping, and reads job detail. It never automatically issues another POST. A changed-plan receipt cannot hide the original error; a known 409 is preserved. The original UI request key remains stable for explicit retry. A full browser restart recovers visible jobs from the server; a general durable client command journal is still pending.

Actual Playwright acceptance dropped the response after native admission. The UI recovered with one POST and one receipt GET, produced one native_accepted event and one hashed synthetic artifact, and displayed completion with the synthetic evidence label.

## Additional implemented boundaries and remaining work

Trusted Factory-to-Factory preparation precedes native admission. The selected
receiver owns the whole tree; origin/receiver current authority, immutable material
manifests, unknown receipts, native cleanup and artifact hashes are enforced.
Ten actual two-app product tests include paginated receiver-owned history and
child/cursor scope; two actual loopback HTTP browser services verified the UI.
Remote deployment/TLS/credential/host-restart proof remains separate.

Material imports/publication/archive/withdrawal and distinct current-admin review
are integrated. Signed, bounded Factory replay detects late commit prefix changes.
Guarded schedule interruption/restart/takeover tests expose the upstream lease
release race. Twenty-user admission and clean-stop official PostgreSQL restore
are verified. Generic mutation receipts/durable journals, hostile-code tenancy,
sustained target-host load, production monitoring/recovery and actual ORX research
remain tracked full-scope work.

## Governed remote process acceptance

The next remote stage runs two actual native services in separate owned OS
processes with independent generated PostgreSQL databases and workspaces. Both
use administrator-reviewed, non-demo, non-synthetic plans and explicitly
controlled Models; this does not turn fixture output into live provider evidence.
Operator mappings bind exact source specs to receiver-local connections. Both
configuration revisions/hashes and identities are sealed in an immutable proof;
the original source manifest is retained unchanged.

Nine process cases verify legal/missing/wrong-owner/rotated mappings, independent
receiver review, both current role withdrawals, origin process outage/restart,
receiver-owned descendants/scoped cancellation, crash after native commit before
acknowledgement, pre-review cancellation and controlled registered ORX discovery.
The origin has zero native tickets. A root dispatch owns one receiver native
ticket; separately delegated children have their own native tickets. Restarts
retain original identities/receipts and UNKNOWN capacity rules. Artifact bytes
are checked against persisted SHA metadata.

`GET /api/factory/requests/{requestId}` remains the read-only original-key intent
lookup. Receiver job detail survives origin unavailability with execution and
delegation actions disabled; protected operations still fail current authority
checks. Local cleanup does not infer revocation or stop from a network failure.
The transport reads bounded identity-encoded bodies and drops private error
messages. Exact application import preserves source hashes but starts a local
draft with separate receiver publication review; no user import route exists.

Independent databases here share one loopback PostgreSQL server, not two physical
database hosts. Production TLS/host/identity provisioning, cross-host/replica
isolation and live ORX experiments remain separate acceptance work. See
REMOTE_BINDINGS.md and VERIFICATION.md.
