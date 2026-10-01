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

## Required next boundaries

- Factory-to-Factory execution must be chosen before native admission, with separate databases, trusted target identity and immutable prepared material/scope bindings. Current native-only attachment does not accomplish this.
- Both current origin mandate and current remote rights must gate effects. The entire delegated tree needs one execution owner and explicit owner/host reservation accounting. Moving individual descendants is not supported.
- Remote cancel must use the Factory's descendant/experiment cleanup path, not interpret native cancellation intent as process termination. UNKNOWN, expiry and disconnect retain capacity.
- Generic mutation receipts, durable client command journals, contiguous event replay/cursor recovery, guarded scheduler crash/stale-lease recovery, material governance, hostile-code isolation, measured capacity and restore acceptance remain tracked work.
- Actual ORX research/experiment output and remote execution require separate source/build/endpoint evidence. Controlled tests do not establish live research.
