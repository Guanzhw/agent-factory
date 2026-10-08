# Backend contract for the OpenResearch workspace UI

The independently authorized UI now follows this additive backend contract. Existing application, task, preset and connection endpoints remain compatible. Changes are confined to this development branch; no user-local files were edited.

## Product navigation

Factory catalog → OpenResearch workspace → projects → sessions/results. Do not show another Factory application selector inside OpenResearch. Developer material composition/publication remains a separate administrative surface.

Two project kinds must remain visibly distinct:

- `factory-workspace`: Factory-owned grouping metadata over existing controlled-workload tasks. Its name/description does not rewrite the workload's repository, model or instructions. `upstreamProjectId` is null and session `contextSource` is `approved-workload-preset`.
- `native-openresearch`: a mapping to an actual upstream project observed through an owner-scoped trusted ORX adapter. `upstreamProjectId` and `nativeProject.projectIdentityHash` identify the original project/path/version mapping. This hash is **not** a repository content hash or scientific provenance proof. Native metadata is not copied into a new upstream project.

An OpenCode serve connection is a platform agent/harness environment, not an ORX workspace. The separate ordinary OpenResearch provider uses native ORX project/session APIs; it is not a renamed direct OpenCode connection. Neither connection automatically authorizes inference. See [ordinary OpenResearch](PERSONAL_OPENRESEARCH.md) and [governed personal commands](PERSONAL_NATIVE_COMMANDS.md) for the normal personal-mode path.

## Additive endpoints

All routes are authenticated under `/api/factory/openresearch`; authority is rechecked against current native grants.

| Method/path | Meaning |
|---|---|
| GET `/requests/{requestId}` | Read-only exact original owner command recovery after an interrupted response |
| GET `/capabilities` | Exact support flags and available controlled workloads; render unsupported features as unavailable |
| GET/POST `/projects` | List/create owner-only Factory grouping metadata; POST takes `requestId`, `name`, optional `description`, optional exact `connectionRefs` |
| GET `/projects/{id}` | Read the owner mapping; no provider call or execution claim |
| GET `/native-projects?connectionRef=...` | Read actual upstream projects through the pinned native ORX adapter |
| POST `/projects/attach` | Attach existing native identity: `requestId`, `connectionRef`, `nativeProjectId`, `projectIdentityHash` from preview; rereads upstream and checks identity |
| POST `/projects/{id}/refresh` | Observe original native project with the same connection revision and identity pin |
| GET/POST `/projects/{id}/sessions` | List/admit controlled-workload task-backed sessions; POST takes `requestId`, `workloadPresetId`, `goal`, `executionContract=controlled-workload-v1` |
| GET `/projects/{id}/sessions/{id}` | Original Factory task-backed session projection |
| POST `.../{sessionId}/reconcile` | Observe the original admission request only; never resubmit unknown work |
| POST `.../{sessionId}/cancel` | `requestId`; delegates to existing original-task cancellation and custody rules |

Create/attach and session requests are idempotent by owner and request ID. Reusing an ID for changed intent returns 409. Never generate a replacement request ID automatically after an unknown response. Keep the original project/session and offer read-only reconciliation. Cancellation acknowledgment is not proof of stopped resources.

A selected connection must be the connection the controlled preset actually uses. Mismatches return `OPENRESEARCH_WORKLOAD_CONNECTION_MISMATCH`. The legacy controlled-workload route rejects native attached projects with `NATIVE_PROJECT_GOVERNED_SESSION_BINDING_REQUIRED`; it never dispatches a different preset's project. Ordinary native OpenResearch sessions use the separate `/personal-agent` command flow and actual ORX adapter. Explicitly installed managed profiles use the separately labelled one-turn probe preparation/start endpoints; they do not imply full managed research availability.

## Resource onboarding

See [PERSONAL_REMOTE_CONNECTIONS.md](PERSONAL_REMOTE_CONNECTIONS.md). Read available providers before showing a connect form. No provider/secret backend is installed by default. Entering an endpoint does not verify it. Configure → verify → bind is explicit; only immutable active scoped bindings are selectable for a plan. Show expired/changed/revoked states and preserve identity across recovery.

The legacy managed native ORX read/attach handle retains owner-exclusive server and source-path pins. The separate ordinary ORX provider is self-service after globally installed capability/vault configuration, with explicit service Bearer-token or Basic-proxy authentication. Read verification is separate from owner-granted session API scope; no compute is provisioned. Ordinary mode preserves remote model credentials/billing and labels usage and interrupt outcomes as unverified/advisory.

## Truthful evidence

Use `deploymentMode`, `executionKind`, `evidenceKind`, and `verificationStatus` separately. Preserve old fields for old clients, but do not interpret `demo`/development as synthetic evidence. Missing evidence is unverified, not success. A terminal status without positive stop proof must not imply capacity released.

## Upstream project creation blocker

The pinned upstream [create endpoint](https://github.com/alphaXiv/OpenResearch/blob/f336b121525d99364e2dee4fe90b2784894a54e6/src/commands/up.rs#L1411-L1522) unconditionally calls `local::starter::warm`, which makes a model call. `githubSyncEnabled` is an explicit request override; upstream otherwise has a configuration default. The adapter does not invoke create, `/open`, harness probes, warmup or GitHub synchronization during read/attach.

Before enabling project creation, the product must disclose its model warmup and any repository publication and obtain the corresponding user authorization. Managed/shared-budget creation must enforce the shared accounting contract; ordinary owner-funded creation must retain its explicit remote-cost guarantee boundary. Neither is enabled by a client bypass boolean. No supported upstream flag suppresses warmup in the pinned revision.

## Versioned developer composition

V1 application definitions have no `contractVersion` and retain historical hashes and research-shaped compatibility fields. V2 has `contractVersion: 2`, explicit `defaultMode`, neutral `budget.operationSeconds`, and application-owned `configSchema`/`config`; authority fields cannot be declared inside that config. A v2 plan carries `config.applicationConfig`, while the runtime envelope retains bounded `sample` and `toolOrder`. Budget contract markers and field sets are exact and cannot be mixed. Remote handoff v2 is explicitly unsupported until both origin and receiver support it.

The additive `checksum-neutral` demo application uses mode `execute`. It proves generic contract execution only; it never proves live OpenResearch acceptance.
