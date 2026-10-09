# Factory, OpenResearch, and research workloads

Status: reviewable implementation in this branch, based on `f869ab5`. This is the authoritative product boundary; implementation, controlled integration evidence, and live acceptance are separate. Historical acceptance reports remain historical evidence.

## Ownership

- **Factory platform** owns authenticated actors, immutable approved definitions/plans, owner connections, native Agno task/command dispatch, audit, platform budgets, and managed resource custody. It does not invent research decisions.
- **OpenResearch application** keeps its actual upstream projects, sessions, transcripts, harness/model configuration and native tool loop. Factory stores owner/connection/native-ID mappings and observations, not replacement projects or another research inference loop. Its UI is entered from the Factory catalog without a second application selector.
- **OpenCode runtime** can also be connected directly as a platform capability. Direct OpenCode sessions are not labelled OpenResearch projects or first-application acceptance.
- **Karpathy autoresearch** is one workload with training inputs and an independent evaluator. Its controlled eleven-literal candidate profile remains a workload, not the definition of every research application.

## Explicit connection modes

### Ordinary personal mode (personal-resource default)

The user owns an existing remote service and its model credentials/billing. Factory verifies scoped service access, admits the exact command through its existing plan/review/native-task path, and preserves original upstream identities. Native tools and inference stay at the remote service. Reported usage is advisory; command acceptance and observed assistant output are not hard budget enforcement, provider billing proof, independent scientific validation, or verified process termination. Interrupt remains best effort and stopped state stays unverified.

This is a separate trusted execution contract, `personal-external-v1`. It cannot be selected as a bypass flag on a managed plan. It receives no shared Factory model credential and allocates no managed remote lease. A local command task succeeding means command acceptance/observation, not that the remote process stopped. Existing configured temporary-plan review policy remains in force; personal mode does not silently auto-approve it.

Supported ordinary providers are `opencode-personal-session-v1` and `openresearch-personal-session-v1`. The latter uses real pinned ORX project/session/message/interrupt APIs and preserves the native OpenResearch tool loop. Existing project/session attachment performs native reads only. Unknown POST acknowledgements never automatically replay; ORX unknown acknowledgements cannot be recovered from similar transcript text. Known-ack ORX transcript correlation is explicitly inferred, not exact turn-table proof.

### Managed mode (optional stronger guarantees)

Shared Factory credentials/budgets and managed capacity require the existing broker, shared ledger and positive original-process stop evidence. An independently installed supervisor/control reader must prove task/session ownership, broker-only egress and original cleanup scope. A remote health response or signed usage self-report is not such proof.

The implemented managed attachment profile is currently an advanced single-turn, text-only connection probe, with one provider request and native tools disabled. It preserves the original project/session and yields a bounded native response artifact. It is not the complete managed research application. Managed multi-step research still needs the existing governed MCP tools to be wired through an installed supervisor, with source/workload attestation and shared accounting; no new reasoning loop is proposed.

## Common contracts

1. V2 applications use neutral budgets and app-owned configuration. V1 immutable definitions/hashes and plans remain on their explicit compatibility path. Remote Factory handoff v2 remains unsupported rather than falling back to broader v1 ceilings.
2. Trusted adapters own evidence and stop interpretation. Core identity/authority/idempotency remain mandatory. Nothing in ordinary mode changes managed positive-stop release rules.
3. Users configure their own endpoint records. Administrators install provider implementations, global network policy and publish shared capabilities, not each user's personal endpoint.
4. The secure vault is opt-in: an external master key or organizational vault is required. Stored service credentials are ciphertext; owner/provider/destination/revision are bound cryptographically. Remote configuration, plans and prompts carry opaque references only. Known authentication echoes are rejected before remote metadata/transcripts are persisted.
5. Configuration, verification, binding, rotation/revocation, and exact request recovery are distinct. A new verification or credential revision does not silently retarget an approved plan. Explicit renewal/rebind preserves original native IDs and historical command pins, rejects wider scope, and stays blocked when a pending/UNKNOWN turn cannot safely be reconciled.
6. Deployment mode, execution kind, evidence kind and verification status are separate. Development can call a real provider; fixture results still do not prove live research.

## Acceptance matrix

| Capability | Implemented contract | Evidence/remaining gate |
|---|---|---|
| Generic v2 application contract | Neutral limits/config; exact v1 compatibility | Unit/native loop and required real-PG tests |
| Adapter-owned lifecycle/evidence | Original identity, no replay, positive managed stop | Existing custody/cancel regressions and required PG cases |
| Secure owner remote onboarding | Configure → verify → scoped bind → status/revoke; opt-in encrypted vault | Synthetic credential/probe tests and real-PG concurrency/wiring; real vault deployment not performed |
| Ordinary direct OpenCode sessions | Original native project/session, multi-turn tools/results, interrupt/recovery | Controlled HTTP/native-task fixtures; not ORX application proof |
| Ordinary OpenResearch application | Actual upstream project/session attach, native tool-loop transcripts, further turns, interrupt/recovery | Controlled ORX-shaped wire + required native queue/PG first-app fixture; live compatibility unverified |
| Explicit same-session renewal | Fresh verified pin + same native identity + explicit CAS/history; no pending-turn bypass | Controlled expiry/rotation, races, history, and UI tests; deployment validation required |
| Managed native attachment | One-turn text-only probe using shared broker/ledger/custody | Controlled protocol/resource/accounting tests; real supervisor/kernel enforcement unverified |
| Managed multi-step research | Existing governed tool bridge is the intended extension | Not complete; do not substitute the probe or checksum |
| Ordinary new ORX project creation | Separate creation connection/immutable plan, versioned preview, per-request owner consent, native dispatch and original project/session handoff; GitHub sync explicitly false | Controlled unit/API/UI and required real-PG/native-queue cases; UNKNOWN is never replayed or settled by candidate resemblance; live acceptance unverified |
| UI | Catalog → application workspace; resource setup; plans/tasks/results; ordinary/managed distinction | Mounted component/navigation/recovery tests; browser visual acceptance unavailable here |
| Live resource → native research decisions/tools/results → continue/cancel/restart | Not accepted | Requires exact authorized real endpoint, credential handoff, execution/cost scope and collected evidence |

No merge, deployment exposure, real credential grant, remote execution or paid model call has been performed by this implementation. Tests distinguish unit, real PostgreSQL, controlled wire/native runtime, and live external evidence. Passing checksum or synthetic workflows never substitutes for the live first-app chain.

See [UI/API integration](OPENRESEARCH_UI_INTEGRATION.md), [personal remote connections](PERSONAL_REMOTE_CONNECTIONS.md), [ordinary native OpenResearch](PERSONAL_OPENRESEARCH.md), and [managed attachment requirements](NATIVE_ORX_ATTACHMENT.md).

Ordinary creation's disclosure, recognized wire spelling, consent and recovery
boundaries are detailed in [native project creation](PERSONAL_OPENRESEARCH_PROJECT_CREATION.md).

OpenResearch's native contract is pinned to `f336b121525d99364e2dee4fe90b2784894a54e6` (0.2.13). `OPENRESEARCH.md` documents the legacy CLI adapter; `AUTORESEARCH_SESSION.md` describes the controlled research-session workload path. Neither alone defines the full product.
