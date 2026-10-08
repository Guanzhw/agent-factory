# Managed original OpenResearch attachment: connection probe

This is a one-turn text-only **connection verification** path, not a native
research workload. The native multi-step research/tool loop remains unavailable.
Nothing in these endpoints proves live OpenResearch, provider compatibility,
remote installation, or operating-system network/tool enforcement. No live
provider invocation is part of the portable/PG admission tests.

## Operator installation

An installed `Settings.managed_orx_profiles_factory(store, auth, resources)` runs
after the existing `ProcessRuntimeService` and persistent resource service are
ready. It returns a mapping of stable profile IDs to trusted configuration. This
hook is Python operator code, never an environment JSON decoder or user API.
Each profile includes:

- `ownerId`, `targetRef`, exact published `applicationRef`, and `mode`
- Original native adapter `nativeProfileId` and `sessionId`
- Exact original connection `connectionPin` (including revision, version, and
  fingerprint)
- `contractSha256`, the digest of the installed provider's detached `contract`
- Optional governed application `connectionRefs` and display-only `name`

The resource target must contain the actual `ManagedORXSessionProvider`, allow
this owner, and use the existing compute pool/process lease lifecycle. Its
contract pins original project/source identity, original session, original
connection and selected native options. The installed application must declare
`exact_input_schema(provider.contract)`, the managed inert pause model, and the
existing `bounded_process_run` tool/environment pinned to this same target.
Use an explicit authoritative provider usage registration with its bounded
request guard; do not use a synthetic zero-local model billing contract.
The existing application/material publication review remains separate from task
plan review. The factory hook does not approve either kind of review.

The operator must install and independently witness default-deny provider
access, broker-only capability, no native tools, original-session custody, and
bounded one-request enforcement. A native response asserting these properties
is not an installation witness. The provider revalidates original authorization
at effect boundaries. Cleanup uses the retained original process provider, not
a newly configured replacement target.

## User path and HTTP contract

All paths are below `/api/factory/openresearch`, owner-scoped by native auth.
Attach an actual native project first using the existing trusted connection.

1. `GET /projects/{projectId}/managed-profiles` lists matching current installed
   probes only. Original source identity, connection grant/pin, profile options,
   session, provider, application schema and pure composition/usage preflight
   are checked. Each item declares `kind: managed-connection-probe`, one model
   request, disabled native tools and `nativeResearchAvailable: false`.
2. `POST /projects/{projectId}/sessions/prepare-managed` accepts only
   `{requestId, profileId, goal}`. It creates a standard composition proposal and
   accepts its schema-validated `inputValues.managedAttachment` into an immutable
   Factory plan. It persists a `prepared` session, with no inference, resource
   allocation, task admission, plan-review request, or approval.
3. The returned session includes `plan`, `planId`, current `authorization`,
   original `nativeProfileId`, `upstreamSessionId`, and managed profile identity.
   The UI requests the existing `/api/factory/plan-reviews` workflow explicitly.
4. `POST /projects/{projectId}/sessions/{sessionId}/start` accepts `{requestId}`,
   rechecks original installed custody and current plan authorization, then uses
   the same `FactoryAPI.instantiate` implementation as `/api/factory/instances`.
   There is no parallel queue or alternative task engine. A native external
   execution pause still requires the existing explicit task continuation.
5. Session inspection points to the original Factory task, not an AutoResearch
   run. Its status is labeled `persisted_factory_observation`; open the original
   task to refresh native evidence. `/requests/{requestId}` and session reconcile
   recover existing original intent/task identities read-only.

A durable dispatch intent precedes native submission. Repeated starts, changed
request IDs, restart and unknown acknowledgment never authorize another submit.
Unknown intent without an original task receipt remains unresolved. Cancellation
uses existing Factory control commands and original-custody cleanup. Removing an
installed profile does not hide historical task/session inspection.

## Evidence and gates

- `test_managed_workspace.ManagedWorkspaceTests`: 4 portable cases for
  nonexecuting preparation, current profile isolation, immutable target binding,
  review recheck and unknown-ack recovery without redispatch.
- `test_managed_workspace_postgres.ManagedWorkspacePostgresTests`: 2 required
  real-PostgreSQL cases for published schema/composition, native auth, independent
  plan review, shared Factory admission, durable unknown task recovery, and
  user-supplied proof rejection. The class has no skip decorator; run only with
  `FACTORY_TEST_DATABASE_URL` pointing to a disposable fixture database.
- Existing controlled-workload workspace endpoints are unchanged.

These tests do not demonstrate a production supervisor or a successful remote
research/model run. Those remain explicit separate acceptance work.
