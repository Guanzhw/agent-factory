# Factory, OpenResearch, and research workloads

Status: bounded implementation available in this branch; baseline `f869ab5`. This contract is authoritative for the additive boundary-correction APIs. Historical acceptance reports remain historical evidence, not claims about this change.

## Ownership

- **Factory platform** owns authenticated actors, immutable approved definitions/plans, scoped connections, resource and tool budgets, native Agno durable dispatch, task identities, audit, cancellation, and evidence-based resource release. It does not decide research hypotheses.
- **OpenResearch application** owns a user's projects, research sessions, instructions, project/session context, and result navigation. Factory's application catalog is the entry into the workspace, not a second application selector inside it. General material composition is a developer/administrator surface.
- **Agent harness** owns the actual model/tool decision loop and native context. The existing deterministic Agno session controller is not a second model loop.
- **Karpathy autoresearch** is one workload with training inputs and an independent evaluator. The current controlled eleven-literal candidate profile remains a bounded workload, not the definition of all OpenResearch.

## Supported boundary in this increment

1. Explicit v2 application contracts use generic budgets and app-owned configuration. Existing v1 immutable versions and plan hashes remain readable and executable through a named compatibility path. Existing web clients stay compatible.
2. Trusted runtime adapters own evidence projection and stop/held interpretation. Core authority and original task identity remain mandatory; an interrupt acknowledgement or missing effect never proves that every process stopped.
3. Personal remote-agent onboarding targets an **existing OpenCode serve HTTPS endpoint**, not cloud compute provisioning and not an OpenResearch server. A platform-installed provider enforces network/identity/capability policy. Users create their own configuration and scoped binding; administrators do not pre-register each user's endpoint.
4. Credentials are owner- and destination-scoped secret references resolved only by a trusted backend. A missing secret backend means onboarding is unavailable. No API, SQL row, prompt, diagnostic or audit field accepts plaintext credentials.
5. OpenResearch workspace project/session records are owner-scoped. Executable workload sessions must use the existing approved Factory task admission and original task/run identity. A project record or a verified agent connection does not on its own grant execution or prove general OpenResearch compatibility.
6. Deployment mode, execution kind, evidence kind and verification status are separate. A controlled development deployment can run a real provider; fixtures never prove real research completion.

## Acceptance matrix

| Capability | Baseline | Required evidence before claiming ready |
|---|---|---|
| Existing ORX/OpenCode session adapter and broker | Implemented, previously exercised narrowly | Preserve identity, unknown-ack and stop tests |
| Generic v2 application contract | Implemented; local unit/native loop passed, PostgreSQL CI required | Unit and real PostgreSQL plan/dispatch tests; v1 hash compatibility |
| Adapter-owned lifecycle/evidence | Implemented; controlled regressions passed | Existing cancellation/custody regressions plus adapter tests |
| Personal remote agent configuration/verification/binding/revoke | Implemented provider contract; controlled tests passed, live/vault gate remains | Controlled HTTP tests, cross-owner/SSRF/secret-redaction/revoke tests; real PostgreSQL persistence |
| User credential onboarding into a deployment's secure vault | Opt-in encrypted backend and secure form implemented; real master key/deployment absent | Explicitly authorized secret backend integration and verification |
| OpenResearch project/session product API | Owner mappings + controlled task sessions + actual native read/attach implemented; native attached-session admission unavailable | Owner isolation, idempotency, original task linkage and honest capability tests |
| General upstream ORX project creation, worktrees, playbooks and arbitrary harness/model selection | Not yet supported by this increment | Explicit adapter capability and integration evidence; no inferred readiness |
| Live resource → project/session → model decision → managed tool/result → next decision → cancel/restart | Not accepted | Authorized real endpoint/model/runtime and exact evidence for every step |
| Browser/UI acceptance | UI implemented with mounted component tests; visual/browser acceptance remains unavailable | User-owned UI branch integration; actual browser evidence |

Tests will be recorded by kind (unit, real PostgreSQL, controlled end-to-end, live external). Passing a checksum or synthetic workflow is never substituted for the live first-application chain. No new deployment exposure, credential grant, paid call, merge or production connection is authorized by this document. See [UI integration contract](OPENRESEARCH_UI_INTEGRATION.md) for exact routes and unsupported states.

## Upstream reference

OpenResearch is pinned separately to `f336b121525d99364e2dee4fe90b2784894a54e6` (0.2.13). Its project/session capabilities exceed the current controlled Factory workload profile. The legacy CLI-only description in `OPENRESEARCH.md` describes a historical narrow adapter; `AUTORESEARCH_SESSION.md` describes the current session path.
