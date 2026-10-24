# Material assembly and execution bindings

The platform uses immutable published application configurations and bounded
material proposals with Agno 3.1 and PostgreSQL. The existing native executor and
persistent queue own task execution.

Authors define application versions with named modes, exact material references,
allowed alternatives, tool order, connection requirements and budget ceilings.
Active members directly publish and manage their own versions. Other members use
published versions or copy them into resources with new IDs. Account administrators
have no resource-management override. Publication state is separate from immutable
content; withdrawing a version ends its current availability while preserving history.

A member submits a goal. Deterministic discovery searches published application
metadata and defaults. The proposal records the exact application, material
closure, execution bindings, connection pins, capabilities, budgets and missing
preflight items. The member can revise, reject or accept it. Revision creates a new
proposal; acceptance persists a task plan. Members submit new plans directly.
Workflow input, native tool confirmation and external-operation recovery continue
to follow the selected component's own runtime contract.

## Exact runtime declarations

Materials carry inert `runtimeBinding` data: `adapterId`, `revision` and bounded
`config`. Installed Python factories are registered at startup. Member-created
CLI/MCP resources persist their declarations and join the same binding registry;
a worker can load a newly configured adapter by its exact identity.

Tool publication matches the selected adapter's tool name and capabilities.
A private tool with the same name as another tool does not replace that tool's
material contract. Application validation follows the published material closure,
its mode capability ceiling and exact tool order. No second tool-permission
registry or approval-policy revision is required.

Plan creation resolves exact material hashes, adapter revisions and configuration,
required capabilities and personal or team connection pins. Missing adapters or
connections produce specific preflight failures. Runtime consumption retains the
persisted manifest and checks current membership, resource state, connection pins
and limits before effects. Actual-service execution preserves the selected model.

The single executor holds a stable model dispatcher. Agno RunOutput supplies the
owner/session/run identity; the dispatcher resolves the persisted task and creates
a fresh registered Model for the response. Tool factories, scoped knowledge and
bounded environment limits come from the same manifest. Concurrent runs do not
change the shared executor's model selection.

## Resource connections and operational bounds

Members configure models, remote services, CLI/MCP tools and SSH through the core
resource interfaces. Owners manage configuration, credentials and personal/team
sharing. A shared resource can be bound by another member while credential
custody remains with the resource owner. Plans contain redacted connection pins;
invocation checks the calling member, current sharing and owner resource state
before obtaining the opaque handle.

Installed integrations can still provide `Settings.runtime_adapters` and
`Settings.trusted_connections`. Native workflows use `Settings.native_workflows`;
external operation implementations use `Settings.workflow_runtimes`. Material
content references these declarations rather than installing Python factories.
See [member publication](MEMBER_PUBLICATION.md),
[member resource endpoints](MEMBER_RESOURCE_ENDPOINTS.md) and
[personal tool lifecycle](PERSONAL_TOOL_CONNECTION_LIFECYCLE.md).

For the fixed synthetic local program, the environment enforces the minimum of
operator, plan and selected environment time/output limits, together with its
process memory/PID/CPU bounds. ORX discovery's hard CPU/memory/PID containment is
an independent deployment boundary; its adapter enforces its implemented
time/output limits. Child tasks inherit ancestor ceilings and share durable root
tool-call accounting. Cancellation and resource withdrawal retain task-owned
cleanup checks. Unknown outcomes keep their original operation identity and are
not blindly replayed.

## Historical data and verification

Stored approval/configuration rows and immutable seed bodies retain their old
values. Startup uses current runtime configuration rather than stored approval
modes. Historical review writes return HTTP 410; private history remains
owner-scoped. Retired plan/publication mode settings are rejected as new runtime
configuration.

Plans with explicit execution bindings retain their original pins. Historical
plans without a manifest remain readable and require a newly composed plan for
execution; the runtime does not reconstruct missing bindings. Remote receiver
mappings retain source identities and validate the mapped local bindings; see
[remote bindings](REMOTE_BINDINGS.md).

The status endpoint reports demo/production mode separately from live integration
verification: `liveEnabled` describes production mode, `liveIntegrationVerified`
is not implied by configuration, and admission uses per-plan preflight.
Capacity depends on the configured native worker bound, not the number of accounts.

Current commands and verification boundaries are in
[development checks](DEVELOPMENT_CHECKS.md). Historical milestone records remain
in [verification](VERIFICATION.md) and [acceptance](ACCEPTANCE.md); their old approval
flows do not describe the current member publication contract.
